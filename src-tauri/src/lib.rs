use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Flask 后端监听地址（与 app.py 保持一致）
const SERVER_HOST: &str = "127.0.0.1";
/// 等待后端启动的超时时间
const STARTUP_TIMEOUT: Duration = Duration::from_secs(60);

/// 持有 Sidecar 子进程句柄与后端端口，用于应用退出时优雅关闭
struct SidecarHandle {
    child: Mutex<Option<CommandChild>>,
    port: u16,
}

/// 探测一个当前空闲的本地端口，作为 Flask 后端监听端口。
/// 桌面版使用随机空闲端口，避免与本机测试服务或其他程序冲突。
fn pick_free_port() -> u16 {
    let listener = TcpListener::bind((SERVER_HOST, 0)).expect("无法绑定本地空闲端口");
    listener.local_addr().expect("读取本地端口失败").port()
}

/// 轮询等待后端端口就绪
fn wait_for_server(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if TcpStream::connect((SERVER_HOST, port)).is_ok() {
            return true;
        }
        // Flask 就绪后尽快切换首屏；100ms 轮询仍很轻量，并减少额外等待。
        std::thread::sleep(Duration::from_millis(100));
    }
    false
}

/// 探测后端端口是否仍在监听（后端已退出则返回 false）
fn port_listening(port: u16) -> bool {
    TcpStream::connect((SERVER_HOST, port)).is_ok()
}

/// 向后端发送优雅退出请求（POST /api/system/shutdown）。
/// 后端收到后会在短暂延迟内自行退出；请求失败（后端已退出或不可达）时静默忽略。
fn request_shutdown(port: u16) {
    let Ok(mut stream) = TcpStream::connect((SERVER_HOST, port)) else {
        return;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(300)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(300)));
    let request = format!(
        "POST /api/system/shutdown HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n",
        SERVER_HOST, port
    );
    let _ = stream.write_all(request.as_bytes());
    let mut buf = [0u8; 128];
    let _ = stream.read(&mut buf);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // 1) 探测空闲端口，并通过环境变量 FLORA_PORT 传给后端
            //    （app.py 读取该变量；所有模式都只绑定回环地址）
            let server_port = pick_free_port();
            let sidecar_command = app
                .shell()
                .sidecar("flora-server")
                .expect("未找到 Sidecar 二进制 flora-server，请先执行后端打包")
                .env("FLORA_PORT", server_port.to_string());
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

            app.manage(SidecarHandle {
                child: Mutex::new(Some(child)),
                port: server_port,
            });

            // 2) 等待后端端口就绪后，把主窗口导航到 Web 界面
            let window = app
                .get_webview_window("main")
                .expect("找不到主窗口 main");
            // 显式使用 canonical 512px PNG 作为运行时窗口图标。
            // Windows 会根据任务栏缩放自行降采样，避免窗口继承低分辨率资源后被放大。
            window.set_icon(tauri::include_image!("./icons/icon.png"))?;
            std::thread::spawn(move || {
                if wait_for_server(server_port, STARTUP_TIMEOUT) {
                    let _ = window.eval(&format!(
                        "window.location.replace('http://{}:{}/')",
                        SERVER_HOST, server_port
                    ));
                } else {
                    // 后端启动超时：在等待页中给出明确提示
                    let js = r#"document.body.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;background:#11161e;color:#8b93a7;text-align:center;padding:24px;box-sizing:border-box;"><h2 style="color:#e6e9f0;">后端启动超时</h2><p style="line-height:1.8;">无法连接本地服务（127.0.0.1:5000）。<br/>可能原因：端口被占用、杀毒软件拦截，或上次运行的进程未退出。<br/>请关闭本应用后重试。</p></div>'"#
                        .replace("127.0.0.1:5000", &format!("{}:{}", SERVER_HOST, server_port));
                    let _ = window.eval(&js);
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Tauri 应用构建失败")
        .run(|app, event| {
            // 应用退出时优雅关闭 Sidecar：先请求后端自行退出，等待其真正
            // 退出后再强杀兜底，避免强杀进程树导致黑窗口闪现或进程残留。
            if let RunEvent::Exit = event {
                if let Some(handle) = app.try_state::<SidecarHandle>() {
                    let port = handle.port;
                    let child = handle.child.lock().unwrap().take();
                    // 1) 请求后端优雅退出（后端收到后约 0.3 秒内自行退出）
                    request_shutdown(port);
                    // 2) 等待后端自行退出（最多约 1.5 秒）
                    for _ in 0..15 {
                        if !port_listening(port) {
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(100));
                    }
                    let still_running = port_listening(port);
                    // 3) 仅在后端确实仍存活时强杀兜底（PyInstaller onefile 会派生 Python
                    //    子进程，仅 kill 主进程会留下孤儿进程继续占用端口，
                    //    因此先按进程树整树清理，再 kill 兜底）。正常退出路径
                    //    不再启动 taskkill，避免关闭应用后闪出控制台窗口。
                    if let Some(child) = child {
                        if still_running {
                            #[cfg(windows)]
                            {
                                use std::os::windows::process::CommandExt;

                                const CREATE_NO_WINDOW: u32 = 0x0800_0000;
                                let _ = std::process::Command::new("taskkill")
                                    .args(["/PID", &child.pid().to_string(), "/T", "/F"])
                                    .creation_flags(CREATE_NO_WINDOW)
                                    .output();
                            }
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}
