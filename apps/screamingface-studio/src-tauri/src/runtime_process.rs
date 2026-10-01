use std::{
  env,
  io::{BufRead, BufReader, Error, ErrorKind},
  path::PathBuf,
  process::{Child, Command, Stdio},
  sync::{mpsc, Mutex},
  thread,
  time::{Duration, Instant},
};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

const READY_PREFIX: &str = "SCREAMINGFACE_RUNTIME_READY ";
const ERROR_PREFIX: &str = "SCREAMINGFACE_RUNTIME_ERROR ";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(90);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Default)]
pub struct RuntimeProcess {
  child: Mutex<Option<Child>>,
  services: Mutex<Option<RuntimeServices>>,
}

/// The service addresses the runtime publishes in its readiness record. Only the Engine is
/// read today; the webview gets it through the `runtime_services` command.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RuntimeServices {
  pub engine: String,
}

#[derive(Deserialize)]
struct ReadyRecord {
  services: RuntimeServices,
}

enum StartupEvent {
  Ready(RuntimeServices),
  Error(String),
}

/// Parses `... SCREAMINGFACE_RUNTIME_READY {"services":{...}}`. The runtime prefixes the marker
/// with a timestamp and a `[supervisor]` tag, so the marker is searched for, not anchored.
fn parse_ready_line(line: &str) -> Option<RuntimeServices> {
  let (_, record) = line.split_once(READY_PREFIX)?;
  serde_json::from_str::<ReadyRecord>(record.trim())
    .ok()
    .map(|record| record.services)
}

/// The Engine address of a runtime that is up, or `None` while it starts or after it exited.
pub fn services(app: &AppHandle) -> Option<RuntimeServices> {
  app
    .try_state::<RuntimeProcess>()?
    .services
    .lock()
    .ok()?
    .clone()
}

fn clear_services(state: &RuntimeProcess) {
  if let Ok(mut services) = state.services.lock() {
    services.take();
  }
}

pub fn start(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
  let executable = executable_path(app)?;
  if !executable.is_file() {
    return Err(Error::new(
      ErrorKind::NotFound,
      format!(
        "ScreamingFace runtime executable not found at {}. Run runtime/build-sidecar.sh first.",
        executable.display()
      ),
    )
    .into());
  }

  let data_dir = app.path().app_data_dir()?.join("runtime");
  std::fs::create_dir_all(&data_dir)?;
  let mut command = Command::new(&executable);
  command
    .arg("--data-dir")
    .arg(&data_dir)
    .arg("up")
    .arg("--foreground")
    .stdout(Stdio::piped())
    .stderr(Stdio::piped());
  #[cfg(unix)]
  command.process_group(0);
  let mut child = command
    .spawn()
    .map_err(|error| {
      Error::new(
        error.kind(),
        format!("failed to start {}: {error}", executable.display()),
      )
    })?;

  let stdout = child
    .stdout
    .take()
    .ok_or_else(|| Error::other("runtime stdout was not piped"))?;
  let stderr = child
    .stderr
    .take()
    .ok_or_else(|| Error::other("runtime stderr was not piped"))?;
  let (sender, receiver) = mpsc::channel();
  let stdout_sender = sender.clone();

  thread::spawn(move || {
    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
      if line.contains(READY_PREFIX) {
        match parse_ready_line(&line) {
          Some(services) => {
            let _ = stdout_sender.send(StartupEvent::Ready(services));
          }
          None => {
            let _ = stdout_sender.send(StartupEvent::Error(
              "runtime readiness record is malformed".to_owned(),
            ));
          }
        }
      }
      log::info!(target: "screamingface_runtime", "{line}");
    }
  });
  thread::spawn(move || {
    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
      if let Some((_, cause)) = line.split_once(ERROR_PREFIX) {
        let _ = sender.send(StartupEvent::Error(cause.to_owned()));
        log::error!(target: "screamingface_runtime", "{line}");
      } else {
        log::warn!(target: "screamingface_runtime", "{line}");
      }
    }
  });

  let deadline = Instant::now() + STARTUP_TIMEOUT;
  loop {
    match receiver.recv_timeout(Duration::from_millis(100)) {
      Ok(StartupEvent::Ready(services)) => {
        let state = app.state::<RuntimeProcess>();
        state
          .child
          .lock()
          .map_err(|_| Error::other("runtime process lock is poisoned"))?
          .replace(child);
        log::info!("ScreamingFace runtime is ready; Engine at {}", services.engine);
        state
          .services
          .lock()
          .map_err(|_| Error::other("runtime services lock is poisoned"))?
          .replace(services);
        monitor(app.clone());
        return Ok(());
      }
      Ok(StartupEvent::Error(cause)) => return startup_failure(child, cause),
      Err(mpsc::RecvTimeoutError::Disconnected) => {
        return startup_failure(child, "runtime output closed during startup".to_owned())
      }
      Err(mpsc::RecvTimeoutError::Timeout) => {}
    }

    if let Some(status) = child.try_wait()? {
      return Err(Error::other(format!(
        "ScreamingFace runtime exited before readiness with {status}"
      ))
      .into());
    }
    if Instant::now() >= deadline {
      return startup_failure(child, "runtime readiness timed out".to_owned());
    }
  }
}

pub fn stop(app: &AppHandle) {
  let Some(state) = app.try_state::<RuntimeProcess>() else {
    return;
  };
  clear_services(&state);
  let Ok(mut guard) = state.child.lock() else {
    log::error!("runtime process lock is poisoned during shutdown");
    return;
  };
  let Some(mut child) = guard.take() else {
    return;
  };

  request_shutdown(&mut child);
  let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
  while Instant::now() < deadline {
    match child.try_wait() {
      Ok(Some(status)) => {
        log::info!("ScreamingFace runtime exited with {status}");
        return;
      }
      Ok(None) => thread::sleep(Duration::from_millis(50)),
      Err(error) => {
        log::error!("failed while waiting for the runtime to stop: {error}");
        break;
      }
    }
  }
  log::warn!("ScreamingFace runtime did not stop gracefully; killing it");
  let _ = child.kill();
  let _ = child.wait();
}

fn startup_failure(
  mut child: Child,
  cause: String,
) -> Result<(), Box<dyn std::error::Error>> {
  request_shutdown(&mut child);
  let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
  while Instant::now() < deadline {
    match child.try_wait() {
      Ok(Some(_)) => break,
      Ok(None) => thread::sleep(Duration::from_millis(50)),
      Err(_) => break,
    }
  }
  if child.try_wait().ok().flatten().is_none() {
    let _ = child.kill();
    let _ = child.wait();
  }
  Err(Error::other(format!("ScreamingFace runtime failed to start: {cause}")).into())
}

fn monitor(app: AppHandle) {
  thread::spawn(move || loop {
    thread::sleep(Duration::from_secs(1));
    let state = app.state::<RuntimeProcess>();
    let Ok(mut guard) = state.child.lock() else {
      log::error!("runtime process lock is poisoned while monitoring");
      return;
    };
    let Some(child) = guard.as_mut() else {
      return;
    };
    match child.try_wait() {
      Ok(Some(status)) => {
        log::error!("ScreamingFace runtime exited unexpectedly with {status}");
        guard.take();
        clear_services(&state);
        return;
      }
      Ok(None) => {}
      Err(error) => {
        log::error!("failed to inspect the ScreamingFace runtime: {error}");
        return;
      }
    }
  });
}

fn executable_path(_app: &AppHandle) -> Result<PathBuf, Box<dyn std::error::Error>> {
  if let Some(path) = env::var_os("SCREAMINGFACE_RUNTIME_EXECUTABLE") {
    return Ok(PathBuf::from(path));
  }

  #[cfg(debug_assertions)]
  {
    let runtime = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../runtime");
    let frozen = runtime
      .join("dist")
      .join("screamingface-runtime")
      .join(executable_name());
    if frozen.is_file() {
      return Ok(frozen);
    }
    return Ok(runtime.join(venv_executable()));
  }

  #[cfg(not(debug_assertions))]
  Ok(
    _app
      .path()
      .resource_dir()?
      .join("screamingface-runtime")
      .join(executable_name()),
  )
}

#[cfg(target_os = "windows")]
fn executable_name() -> &'static str {
  "screamingface-runtime.exe"
}

#[cfg(not(target_os = "windows"))]
fn executable_name() -> &'static str {
  "screamingface-runtime"
}

#[cfg(all(debug_assertions, target_os = "windows"))]
fn venv_executable() -> &'static str {
  ".venv/Scripts/screamingface.exe"
}

#[cfg(all(debug_assertions, not(target_os = "windows")))]
fn venv_executable() -> &'static str {
  ".venv/bin/screamingface"
}

#[cfg(unix)]
fn request_shutdown(child: &mut Child) {
  // SAFETY: the child was placed in a new process group whose id is its PID. Signalling that
  // group reaches the PyInstaller bootloader, Python runtime, and Scoreboard child together.
  unsafe {
    libc::kill(-(child.id() as libc::pid_t), libc::SIGTERM);
  }
}

#[cfg(not(unix))]
fn request_shutdown(child: &mut Child) {
  let _ = child.kill();
}

#[cfg(test)]
mod tests {
  use super::*;

  #[test]
  fn parses_the_engine_address_from_a_timestamped_ready_line() {
    let line = "2026-09-29T13:58:36.290749+00:00 [supervisor] SCREAMINGFACE_RUNTIME_READY \
      {\"services\":{\"engine\":\"http://127.0.0.1:9108\",\"gateway\":\"http://127.0.0.1:9105\",\
      \"scoreboard\":\"http://127.0.0.1:9106\"}}";
    assert_eq!(
      parse_ready_line(line),
      Some(RuntimeServices {
        engine: "http://127.0.0.1:9108".to_owned()
      })
    );
  }

  #[test]
  fn ignores_a_line_without_the_ready_marker() {
    assert_eq!(parse_ready_line("[supervisor] starting engine"), None);
  }

  #[test]
  fn ignores_malformed_ready_json() {
    assert_eq!(parse_ready_line("SCREAMINGFACE_RUNTIME_READY {not json"), None);
  }

  #[test]
  fn ignores_a_ready_record_without_an_engine() {
    assert_eq!(
      parse_ready_line("SCREAMINGFACE_RUNTIME_READY {\"services\":{\"gateway\":\"x\"}}"),
      None
    );
  }
}
