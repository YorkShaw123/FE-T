# 一键构建桌面应用：
#   1) PyInstaller 打包 Flask 后端
#   2) Tauri 构建桌面应用与安装包
#   3) 把「直接运行版」主程序 + 后端 sidecar 复制到项目根目录，方便用户直接使用
# 用法: powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "===== 步骤1/3: 打包后端 ====="
& (Join-Path $PSScriptRoot "build-backend.ps1") -BundleLocalEmbedding

Write-Host "===== 步骤2/3: 构建 Tauri 桌面应用 ====="
npm run tauri build

Write-Host "===== 步骤3/3: 复制直接运行版到项目根目录 ====="
$appExe = Join-Path $Root "src-tauri\target\release\forestar-editor.exe"
$serverExe = Join-Path $Root "src-tauri\binaries\forestar-server-x86_64-pc-windows-msvc.exe"
$destApp = Join-Path $Root "Forestar Editor.exe"
# 注意：Tauri 运行时按「exe 同目录 + 无 target triple 后缀」查找 sidecar，
# 因此根目录必须命名为 forestar-server.exe
$destServer = Join-Path $Root "forestar-server.exe"

if (-not (Test-Path $appExe)) { throw "未找到 $appExe，请确认 Tauri 构建成功" }
if (-not (Test-Path $serverExe)) { throw "未找到 $serverExe，请确认后端打包成功" }

Copy-Item $appExe $destApp -Force
Copy-Item $serverExe $destServer -Force

Write-Host ""
Write-Host "构建完成！"
Write-Host "  安装包: src-tauri\target\release\bundle\nsis\"
Write-Host "  直接运行版（已复制到项目根目录，两个文件需放在一起）:"
Write-Host "    $destApp"
Write-Host "    $destServer"
