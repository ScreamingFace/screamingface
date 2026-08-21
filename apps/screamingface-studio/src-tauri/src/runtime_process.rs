use std::{
  env,
  io::{BufRead, BufReader, Error, ErrorKind},
  path::PathBuf,
  process::{Child, Command, Stdio},
  sync::{mpsc, Mutex},
  thread,
  time::{Duration, Instant},
};
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
}

enum StartupEvent {
  Ready,
  Error(String),
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
      if line.starts_with(READY_PREFIX) {
        let _ = stdout_sender.send(StartupEvent::Ready);
      }
      log::info!(target: "screamingface_runtime", "{line}");
    }
  });
  thread::spawn(move || {
    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
      if let Some(cause) = line.strip_prefix(ERROR_PREFIX) {
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
      Ok(StartupEvent::Ready) => {
        app.state::<RuntimeProcess>()
          .child
          .lock()
          .map_err(|_| Error::other("runtime process lock is poisoned"))?
          .replace(child);
        monitor(app.clone());
        log::info!("ScreamingFace runtime is ready at http://127.0.0.1:9108");
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

#[cfg(target_os = "windows")]
fn venv_executable() -> &'static str {
  ".venv/Scripts/screamingface-runtime.exe"
}

#[cfg(not(target_os = "windows"))]
fn venv_executable() -> &'static str {
  ".venv/bin/screamingface-runtime"
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
