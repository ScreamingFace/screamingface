mod commands;
mod runtime_process;
mod state;
mod updates;
mod windows;

use std::sync::Mutex;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let builder = tauri::Builder::default();

  #[cfg(not(target_os = "macos"))]
  let builder = builder.plugin(tauri_plugin_decorum::init());

  builder
    .plugin(tauri_plugin_updater::Builder::new().build())
    .plugin(tauri_plugin_process::init())
    .invoke_handler(tauri::generate_handler![
      commands::update_theme,
      commands::check_for_updates,
      commands::get_update_window_state,
      commands::update_window_response,
    ])
    .setup(|app| {
      app.manage(Mutex::new(state::AppState::default()));
      app.manage(runtime_process::RuntimeProcess::default());
      app.manage(state::PendingUpdate {
        update: Mutex::new(None),
        window_state: Mutex::new(None),
      });
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      runtime_process::start(app.handle())?;
      windows::setup_main_window(app.handle())?;
      updates::start_periodic_update_checks(app.handle());
      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|app, event| {
      if matches!(event, tauri::RunEvent::Exit) {
        runtime_process::stop(app);
      }
    });
}
