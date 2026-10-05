use crate::state::{AppState, PendingUpdate, UpdateWindowState, UpdateWindowType};
use crate::windows::show_update_window;
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Manager, Theme};

#[cfg(target_os = "macos")]
use {
  crate::windows::{MACOS_TRAFFIC_LIGHTS_INSET_X, MACOS_TRAFFIC_LIGHTS_INSET_Y},
  tauri_plugin_decorum::WebviewWindowExt,
};

/// The local runtime's service addresses, or `null` while it is starting or after it exited.
#[tauri::command]
pub fn runtime_services(app: AppHandle) -> Option<crate::runtime_process::RuntimeServices> {
  crate::runtime_process::services(&app)
}

#[tauri::command]
pub fn update_theme(app: AppHandle, theme: Option<String>) {
  let native_theme = match theme.as_deref() {
    None => None,
    Some("dark") => Some(Theme::Dark),
    Some("light") => Some(Theme::Light),
    Some(theme) => {
      log::error!("Ignoring unsupported native window theme: {theme}");
      return;
    }
  };

  for (_, window) in app.webview_windows() {
    if let Err(error) = window.set_theme(native_theme) {
      log::error!("Failed to update native window theme: {error}");
    }
  }

  #[cfg(target_os = "macos")]
  if let Some(window) = app.get_webview_window("main") {
    let _ = window.set_traffic_lights_inset(
      MACOS_TRAFFIC_LIGHTS_INSET_X,
      MACOS_TRAFFIC_LIGHTS_INSET_Y,
    );
  }
}

#[tauri::command]
pub async fn check_for_updates(app: AppHandle) {
  crate::updates::check_for_updates(&app, true).await;
}

#[tauri::command]
pub fn get_update_window_state(app: AppHandle) -> UpdateWindowState {
  app
    .state::<PendingUpdate>()
    .window_state
    .lock()
    .unwrap()
    .clone()
    .unwrap_or(UpdateWindowState {
      update_window_type: UpdateWindowType::Checking,
      version: String::new(),
      current_version: app.package_info().version.to_string(),
      release_notes: String::new(),
      error: String::new(),
      progress: 0,
    })
}

#[tauri::command]
pub async fn update_window_response(app: AppHandle, install_update: bool) -> Result<(), String> {
  let update = app.state::<PendingUpdate>().update.lock().unwrap().clone();

  let Some(update) = update else {
    return Ok(());
  };

  if !install_update {
    app.state::<Mutex<AppState>>().lock().unwrap().dismissed_update_version = update.version;
    return Ok(());
  }

  let version = Arc::new(update.version.clone());
  let current_version = Arc::new(update.current_version.clone());
  let progress_app = app.clone();
  let mut downloaded = 0_u64;
  let mut last_progress = 0_usize;

  let result = update
    .download_and_install(
      {
        let version = Arc::clone(&version);
        let current_version = Arc::clone(&current_version);
        move |chunk_size, content_length| {
          downloaded += chunk_size as u64;
          let progress = content_length
            .filter(|length| *length > 0)
            .map(|length| ((downloaded as f64 / length as f64) * 100.0) as usize)
            .unwrap_or(0)
            .min(100);
          if progress > last_progress {
            show_update_window(
              &progress_app,
              UpdateWindowType::Downloading,
              version.to_string(),
              current_version.to_string(),
              String::new(),
              String::new(),
              progress,
            );
            last_progress = progress;
          }
        }
      },
      || {},
    )
    .await;

  match result {
    Ok(()) => {
      app.restart();
    }
    Err(error) => {
      let message = format!("Could not install the update.\n\n{error}");
      show_update_window(
        &app,
        UpdateWindowType::Failed,
        version.to_string(),
        current_version.to_string(),
        String::new(),
        message.clone(),
        0,
      );
      Err(message)
    }
  }
}
