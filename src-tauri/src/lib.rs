use std::net::TcpStream;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Flask 后端监听地址与端口（与 app.py 保持一致）
const SERVER_HOST: &str = "127.0.0.1";
const SERVER_PORT: u16 = 5000;
/// 等待后端启动的超时时间
const STARTUP_TIMEOUT: Duration = Duration::from_secs(60);

/// 持有 Sidecar 子进程句柄，用于应用退出时清理
struct SidecarHandle(Mutex<Option<CommandChild>>);

/// 轮询等待后端端口就绪
fn wait_for_server(timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if TcpStream::connect((SERVER_HOST, SERVER_PORT)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // 1) 以 Sidecar 方式启动 Python（Flask）后端
            let sidecar_command = app
                .shell()
                .sidecar("forestar-server")
                .expect("未找到 Sidecar 二进制 forestar-server，请先执行后端打包");
            let (mut rx, child) = sidecar_command
                .spawn()
                .expect("启动 Flask Sidecar 失败");

            // 监听 Sidecar 输出，便于排查问题（写进标准错误流）
            tauri::async_runtime::spawn(async move {
                use tauri_plugin_shell::process::CommandEvent;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            eprintln!("[sidecar stdout] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[sidecar stderr] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Error(err) => {
                            eprintln!("[sidecar error] {}", err);
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[sidecar terminated] code={:?}", payload.code);
                        }
                        _ => {}
                    }
                }
            });

            app.manage(SidecarHandle(Mutex::new(Some(child))));

            // 2) 等待后端端口就绪后，把主窗口导航到 Web 界面
            let window = app
                .get_webview_window("main")
                .expect("找不到主窗口 main");
            std::thread::spawn(move || {
                if wait_for_server(STARTUP_TIMEOUT) {
                    let _ = window.eval(&format!(
                        "window.location.replace('http://{}:{}/')",
                        SERVER_HOST, SERVER_PORT
                    ));
                } else {
                    // 后端启动超时：在等待页中给出明确提示
                    let _ = window.eval(
                        r#"document.body.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;background:#11161e;color:#8b93a7;text-align:center;padding:24px;box-sizing:border-box;"><h2 style="color:#e6e9f0;">后端启动超时</h2><p style="line-height:1.8;">无法连接本地服务（127.0.0.1:5000）。<br/>可能原因：端口被占用、杀毒软件拦截，或上次运行的进程未退出。<br/>请关闭本应用后重试。</p></div>'"#
                    );
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Tauri 应用构建失败")
        .run(|app, event| {
            // 应用退出时清理 Sidecar 进程，避免残留 Flask 服务器
            if let RunEvent::Exit = event {
                if let Some(handle) = app.try_state::<SidecarHandle>() {
                    if let Some(child) = handle.0.lock().unwrap().take() {
                        #[cfg(windows)]
                        {
                            // PyInstaller onefile 打包的 sidecar 会派生 Python 子进程，
                            // 仅 kill 主进程会留下孤儿进程继续占用端口；
                            // 因此先按进程树整树清理，再 kill 兜底。
                            let _ = std::process::Command::new("taskkill")
                                .args(["/PID", &child.pid().to_string(), "/T", "/F"])
                                .output();
                        }
                        let _ = child.kill();
                    }
                }
            }
        });
}
