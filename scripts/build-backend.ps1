# 打包 Flask 后端为单文件可执行程序，并复制为 Tauri externalBin 所需的命名格式
# 用法: powershell -ExecutionPolicy Bypass -File scripts\build-backend.ps1
param(
    [string]$Target = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "[1/2] PyInstaller 打包后端 ..."
python -m PyInstaller forestar-server.spec --clean --noconfirm

$distExe = Join-Path $Root "dist\forestar-server.exe"
if (-not (Test-Path $distExe)) {
    throw "打包失败：未找到 $distExe"
}

$binDir = Join-Path $Root "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$targetExe = Join-Path $binDir "forestar-server-$Target.exe"
Copy-Item $distExe $targetExe -Force

Write-Host "[2/2] 后端已就绪: $targetExe"
