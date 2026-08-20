# 打包 Flask 后端为单文件可执行程序，并复制为 Tauri externalBin 所需的命名格式
# 用法: powershell -ExecutionPolicy Bypass -File scripts\build-backend.ps1
param(
    [string]$Target = "x86_64-pc-windows-msvc",
    [switch]$BundleLocalEmbedding
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "[1/2] PyInstaller 打包后端 ..."
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }
$previousBundleSetting = $env:FLORA_BUNDLE_ONNX
$workDir = Join-Path $Root (".pyinstaller-work-" + [guid]::NewGuid().ToString("N"))
try {
    $env:FLORA_BUNDLE_ONNX = if ($BundleLocalEmbedding) { "1" } else { "0" }
    # 每次使用独立临时工作目录，避免杀毒软件或旧进程短暂占用上次的 TOC/PKG
    # 文件时错误复用旧产物。dist 仍保持稳定路径，供后续复制。
    & $pythonExe -m PyInstaller flora-server.spec --workpath $workDir --clean --noconfirm
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 打包失败（退出码 $LASTEXITCODE），已停止构建，禁止继续复用旧产物"
    }
} finally {
    $env:FLORA_BUNDLE_ONNX = $previousBundleSetting
    if (Test-Path -LiteralPath $workDir) {
        Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$distExe = Join-Path $Root "dist\flora-server.exe"
if (-not (Test-Path $distExe)) {
    throw "打包失败：未找到 $distExe"
}

$binDir = Join-Path $Root "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$targetExe = Join-Path $binDir "flora-server-$Target.exe"
Copy-Item $distExe $targetExe -Force

Write-Host "[2/2] 后端已就绪: $targetExe"
