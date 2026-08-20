# Windows 构建

## 前置条件

- Python 3.10+
- Node.js 18+
- Rust MSVC 工具链
- 已安装项目 Python 依赖和 npm 依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -r requirements-local-embedding.txt
npm install
```

## 一键构建

```powershell
npm run build:all
```

流程依次执行：

1. 用 PyInstaller 将 Flask 后端打包为单文件 Sidecar，并包含 ONNX Runtime。
2. 将后端复制为 Tauri `externalBin` 要求的 target triple 文件名。
3. 构建 Tauri 2 桌面程序和 NSIS 安装包。
4. 将直接运行版的两个 EXE 复制到项目根目录。

## 分步命令

```powershell
# package.json 当前脚本会包含本地 Embedding 运行时
npm run build:backend

# 手动构建不含 ONNX Runtime 的轻量后端
powershell -ExecutionPolicy Bypass -File scripts\build-backend.ps1

# 构建桌面端和安装包
npm run tauri:build
```

本地模型权重始终单独放在用户 models 目录，不打入 `flora-server.exe`。

## 产物

| 产物 | 路径 |
|---|---|
| PyInstaller 原始后端 | `dist\flora-server.exe` |
| Tauri Sidecar | `src-tauri\binaries\flora-server-x86_64-pc-windows-msvc.exe` |
| 直接运行版 | 根目录 `Flora Editor.exe` + `flora-server.exe` |
| NSIS 安装包 | `src-tauri\target\release\bundle\nsis\` |

两个直接运行版 EXE 必须位于同一目录。Tauri 主程序负责窗口、随机端口和生命周期，Sidecar 负责 Flask、业务逻辑和本地数据访问。

## 打包约束

- `flora-server.spec` 使用 PyInstaller onefile，关闭 UPX 以降低杀毒软件误报。
- `src-tauri/tauri.conf.json` 的 `externalBin` 指向 `binaries/flora-server`。
- NSIS 使用 `currentUser` 安装模式和简体中文。
- `useLocalToolsDir: true` 将 Tauri 构建工具缓存放在项目 target 目录。
- 构建产物、模型、用户数据库和私人语料都由 `.gitignore` 排除。
