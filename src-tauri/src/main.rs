#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod saved_reveal;
mod update_gate;

use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{ShellExt, process::CommandChild};
use thiserror::Error;

#[cfg(target_os = "windows")]
use std::{os::windows::process::CommandExt, process::Command};

const SIDECAR_NAME: &str = "olga-companion-sidecar";
const SIDECAR_PORT: &str = "8865";
const FRONTEND_PORT: &str = "5273";
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Debug, Error)]
enum StartupError {
    #[error("could not resolve an application path")]
    AppPath(#[from] tauri::Error),
    #[error("could not prepare the application data directory")]
    AppData(#[from] std::io::Error),
    #[error("could not start the OLGA Companion sidecar")]
    Sidecar(#[from] tauri_plugin_shell::Error),
    #[error("sidecar lifecycle state is unavailable")]
    LifecycleState,
    #[error(
        "port {0} is unavailable (already in use, or reserved by Windows), so OLGA Companion did not start rather than attach to another program's sidecar; \
         close the other OLGA Companion (or end its olga-companion-sidecar.exe in Task Manager) and launch again"
    )]
    PortInUse(String),
}

/// How long a just-quit instance may still hold the port (an update relaunch, or a quick
/// close and reopen) before the port is declared taken.
const PORT_GRACE: Duration = Duration::from_secs(3);
const PORT_POLL: Duration = Duration::from_millis(250);

/// The webview talks to a fixed loopback port. If something already listens there, a
/// freshly spawned sidecar would fail to bind while the window silently used the other
/// program's state, so refuse to start instead.
fn ensure_port_free(port: &str) -> Result<(), StartupError> {
    let deadline = Instant::now() + PORT_GRACE;
    loop {
        match TcpListener::bind(format!("127.0.0.1:{port}")) {
            Ok(listener) => {
                drop(listener);
                return Ok(());
            }
            // Access denied is what Windows reports for an exclusive owner or an
            // excluded (reserved) port range: the sidecar could not bind either.
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::AddrInUse | std::io::ErrorKind::PermissionDenied
                ) =>
            {
                if Instant::now() >= deadline {
                    return Err(StartupError::PortInUse(port.to_owned()));
                }
                std::thread::sleep(PORT_POLL);
            }
            // Not provably occupied: let the sidecar report its own bind failure.
            Err(_) => return Ok(()),
        }
    }
}

fn clear_startup_failure(app: &tauri::App) {
    if let Ok(directory) = app.path().app_local_data_dir() {
        let _ = std::fs::remove_file(directory.join("startup-error.log"));
    }
}

/// A windowless app has no console, so keep the reason where support can find it.
fn record_startup_failure(app: &tauri::App, error: &StartupError) {
    if let Ok(directory) = app.path().app_local_data_dir() {
        let _ = std::fs::create_dir_all(&directory);
        let _ = std::fs::write(
            directory.join("startup-error.log"),
            format!("{error}\n\ndetail: {error:?}\n"),
        );
    }
}

fn spawn_sidecar(app: &tauri::App) -> Result<CommandChild, StartupError> {
    ensure_port_free(SIDECAR_PORT)?;
    let app_data = app.path().app_local_data_dir()?;
    std::fs::create_dir_all(&app_data)?;
    let toolkit = app
        .path()
        .resource_dir()?
        .join("resources")
        .join("olga-toolkit");
    let (_events, child) = app
        .shell()
        .sidecar(SIDECAR_NAME)?
        .args([
            "--host",
            "127.0.0.1",
            "--port",
            SIDECAR_PORT,
            "--frontend-port",
            FRONTEND_PORT,
        ])
        .env("OLGA_APP_DATA_DIR", &app_data)
        .env("OLGA_TOOLKIT_DIR", &toolkit)
        .current_dir(app_data)
        .spawn()?;
    Ok(child)
}

type SidecarSlot = Arc<Mutex<Option<CommandChild>>>;

fn take_sidecar(slot: &Mutex<Option<CommandChild>>) -> Option<CommandChild> {
    match slot.lock() {
        Ok(mut guard) => guard.take(),
        Err(poisoned) => poisoned.into_inner().take(),
    }
}

/// The Windows updater hands over to the installer and calls `process::exit(0)`, which
/// never delivers `RunEvent::Exit`. Without this the old sidecar keeps its port and locks
/// its own executable while the installer tries to replace it, so the update UI stops it
/// explicitly before installing. The backend must first confirm that no run is starting,
/// running or of unknown status, and the stop is only reported as done once the port is
/// really free again.
// Tauri injects `State` by value; a command cannot take it by reference. `async` runs this
// blocking body (HTTP waits, port polling) off the thread that pumps window messages: as a
// plain sync command a stalled backend froze the window for the whole wait.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command(async)]
fn stop_sidecar(slot: tauri::State<'_, SidecarSlot>) -> Result<(), serde_json::Value> {
    stop_if_idle(SIDECAR_PORT, update_gate::GATE_TIMEOUT, || {
        if let Some(child) = take_sidecar(&slot) {
            terminate_sidecar(child);
        }
    })
}

/// Reveal one file the native save route just wrote. The argument is an id from that
/// response. A path is refused, and this command adds no shell or opener permission.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
fn reveal_saved_report(app: tauri::AppHandle, reveal_id: String) -> Result<(), &'static str> {
    let app_data = app
        .path()
        .app_local_data_dir()
        .map_err(|_| "reveal_unavailable")?;
    let path = saved_reveal::path_for_reveal(&app_data, &reveal_id).ok_or("reveal_refused")?;
    saved_reveal::reveal_in_explorer(&path)
}

fn stop_if_idle(
    port: &str,
    timeout: Duration,
    stop: impl FnOnce(),
) -> Result<(), serde_json::Value> {
    let prepare_id = update_gate::new_prepare_id();
    update_gate::authorize_stop(port, timeout, &prepare_id)?;
    stop();
    ensure_port_free(port).map_err(|_| {
        // The backend is still up and will not be stopped by this attempt: let it launch
        // runs again instead of staying closed for an update that is not happening.
        update_gate::release_prepare(port, &prepare_id, timeout);
        update_gate::refusal(
            "stop_failed",
            "The local backend did not stop, so the update was not installed. Close OLGA Companion from the Task Manager (olga-companion-sidecar.exe) and open it again.",
        )
    })
}

fn terminate_sidecar(child: CommandChild) {
    #[cfg(target_os = "windows")]
    {
        // PyInstaller onefile launches a worker beneath its bootstrap process.
        // Killing only the bootstrap leaves the API worker listening on 8865.
        let pid = child.pid().to_string();
        let _ = Command::new("taskkill")
            .args(["/PID", &pid, "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }
    let _ = child.kill();
}

fn main() -> tauri::Result<()> {
    let child_slot: SidecarSlot = Arc::new(Mutex::new(None::<CommandChild>));
    let setup_slot = Arc::clone(&child_slot);
    let app = tauri::Builder::default()
        .manage(Arc::clone(&child_slot))
        .invoke_handler(tauri::generate_handler![stop_sidecar, reveal_saved_report])
        .plugin(tauri_plugin_shell::init())
        // The updater downloads and verifies from Rust, not the WebView, so the
        // window CSP does not gate the release endpoint. Applying an update is
        // still an explicit operator action in the UI, never automatic.
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .setup(move |app| {
            let child =
                spawn_sidecar(app).inspect_err(|error| record_startup_failure(app, error))?;
            clear_startup_failure(app);
            let mut slot = setup_slot
                .lock()
                .map_err(|_| StartupError::LifecycleState)?;
            *slot = Some(child);
            drop(slot);
            Ok(())
        })
        .build(tauri::generate_context!())?;

    app.run(move |_handle, event| {
        if matches!(event, RunEvent::Exit) {
            if let Some(child) = take_sidecar(&child_slot) {
                terminate_sidecar(child);
            }
        }
    });
    Ok(())
}

#[cfg(test)]
#[allow(clippy::expect_used, clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn a_taken_port_is_refused_after_the_grace_period() {
        let Ok(listener) = TcpListener::bind("127.0.0.1:0") else {
            return;
        };
        let Ok(address) = listener.local_addr() else {
            return;
        };
        let started = Instant::now();

        let result = ensure_port_free(&address.port().to_string());

        assert!(matches!(result, Err(StartupError::PortInUse(_))));
        assert!(started.elapsed() >= PORT_GRACE);
    }

    #[test]
    fn stopping_twice_is_harmless_because_the_slot_is_emptied_once() {
        let slot: Mutex<Option<CommandChild>> = Mutex::new(None);

        assert!(take_sidecar(&slot).is_none());
        assert!(take_sidecar(&slot).is_none());
    }

    #[test]
    fn a_refused_stop_never_reaches_the_kill() {
        // Nothing here can answer as a backend with an active run, so use a silent one.
        let Ok(listener) = TcpListener::bind("127.0.0.1:0") else {
            return;
        };
        let Ok(address) = listener.local_addr() else {
            return;
        };
        let mut killed = false;

        let result = stop_if_idle(
            &address.port().to_string(),
            Duration::from_millis(300),
            || killed = true,
        );

        assert!(!killed);
        assert_eq!(result.unwrap_err()["code"], "unconfirmed");
        drop(listener);
    }

    #[test]
    fn a_stop_that_leaves_the_port_taken_is_reported_as_failed_and_reopens_launching() {
        use std::io::{Read, Write};
        let Ok(listener) = TcpListener::bind("127.0.0.1:0") else {
            return;
        };
        let Ok(address) = listener.local_addr() else {
            return;
        };
        let port = address.port().to_string();
        let seen: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
        let log = Arc::clone(&seen);
        // An idle backend that, unlike a real one, stays bound after the "stop".
        let server = std::thread::spawn(move || {
            for body in [
                r#"{"token":"t"}"#,
                r#"{"safe":true,"confirmed":true,"blocking":[],"starting":0}"#,
                r#"{"token":"t"}"#,
                r#"{"released":true}"#,
            ] {
                let Ok((mut stream, _)) = listener.accept() else {
                    return;
                };
                let mut buffer = [0_u8; 2048];
                let count = stream.read(&mut buffer).unwrap_or(0);
                if let Ok(mut guard) = log.lock() {
                    guard.push(String::from_utf8_lossy(&buffer[..count]).into_owned());
                }
                let _ = stream.write_all(
                    format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                        body.len()
                    )
                    .as_bytes(),
                );
            }
            std::thread::sleep(PORT_GRACE + Duration::from_secs(1));
        });
        let mut stopped = false;

        let result = stop_if_idle(&port, Duration::from_secs(2), || stopped = true);

        assert!(stopped);
        assert_eq!(result.unwrap_err()["code"], "stop_failed");
        let requests = seen.lock().expect("requests").clone();
        let prepare_id = requests[1]
            .lines()
            .find_map(|line| line.strip_prefix("X-Update-Prepare-Id: "))
            .map(str::to_owned)
            .expect("prepare carries an attempt id");
        assert!(requests[3].starts_with("POST /api/update/release"));
        assert!(requests[3].contains(&format!("X-Update-Prepare-Id: {prepare_id}")));
        let _ = server.join();
    }

    #[test]
    fn a_free_port_is_accepted_immediately() {
        let Ok(listener) = TcpListener::bind("127.0.0.1:0") else {
            return;
        };
        let Ok(address) = listener.local_addr() else {
            return;
        };
        drop(listener);

        assert!(ensure_port_free(&address.port().to_string()).is_ok());
    }
}
