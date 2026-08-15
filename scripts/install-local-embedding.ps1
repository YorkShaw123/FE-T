# Install the Forestar ONNX runtime and export the official BAAI model.
param(
    [string]$ModelDir = "$env:USERPROFILE\.forestar-editor\models\bge-small-zh-v1.5",
    [switch]$Force,
    [switch]$KeepBuildEnvironment
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimePython = Join-Path $Root ".venv\Scripts\python.exe"
$BuildVenv = Join-Path $Root ".embedding-build-venv"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"

function Invoke-Native {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Native command failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path $RuntimePython)) {
    throw "Project virtual environment not found: $RuntimePython"
}

Write-Host "[1/5] Installing the ONNX CPU runtime ..."
Invoke-Native { & $RuntimePython -m pip install -r (Join-Path $Root "requirements-local-embedding.txt") }

Write-Host "[2/5] Creating an isolated model export environment ..."
if (-not (Test-Path $BuildPython)) {
    Invoke-Native { & $RuntimePython -m venv $BuildVenv }
}
Invoke-Native { & $BuildPython -m pip install -r (Join-Path $Root "requirements-local-embedding-export.txt") }

Write-Host "[3/5] Downloading official BAAI weights and exporting ONNX ..."
$ExportArgs = @((Join-Path $Root "scripts\export_local_embedding_model.py"), $ModelDir)
if ($Force) { $ExportArgs += "--force" }
Invoke-Native { & $BuildPython @ExportArgs }

Write-Host "[4/5] Verifying the model with the production runtime ..."
Invoke-Native { & $RuntimePython (Join-Path $Root "scripts\verify_local_embedding.py") --model-dir $ModelDir }

Write-Host "[5/5] Cleaning the temporary export environment ..."
if (-not $KeepBuildEnvironment) {
    Remove-Item -LiteralPath $BuildVenv -Recurse -Force
    Write-Host "Temporary PyTorch/Transformers export environment removed."
} else {
    Write-Host "Export environment retained: $BuildVenv"
}

Write-Host "Done. Re-index existing corpora to enable semantic_score."
