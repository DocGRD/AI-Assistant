<#
Zero-Cost AI Operating System for Obsidian — Windows installer (PowerShell).

  ./install/install.ps1 [-Python python] [-Optional]

  -Python    Python interpreter to build the venv with (default: python)
  -Optional  also install optional feature deps (pypdf, faster-whisper)

Idempotent: safe to re-run. Never overwrites an existing settings.json.
Windows is the development / occasional-use machine (CPU embeddings); the
GPU + systemd service path is Linux — see install/install.sh and Docs/DEPLOYMENT.md.
#>
param(
    [string]$Python = "python",
    [switch]$Optional
)
$ErrorActionPreference = "Stop"

# Repo root = parent of this script's dir.
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
Write-Host "==> Repo: $Root"

# Python check
try { $pv = & $Python --version 2>&1 } catch { throw "'$Python' not found. Install Python 3.12+ from python.org and re-run." }
Write-Host "==> Python: $pv"

# 1) venv
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "==> Creating .venv"
    & $Python -m venv .venv
}

# 2) dependencies (use `python -m pip` — the .exe shims embed an absolute path and break after a move)
Write-Host "==> Installing requirements"
& $venvPy -m pip install --upgrade pip | Out-Null
& $venvPy -m pip install -r requirements.txt

# 2b) optional feature deps
if ($Optional) {
    Write-Host "==> Installing optional feature deps (pypdf, faster-whisper)"
    & $venvPy -m pip install pypdf faster-whisper
}

# 3) settings.json (never overwrite an existing one)
$cfg = Join-Path $Root "assistant_core\config\settings.json"
$ex  = Join-Path $Root "assistant_core\config\settings.example.json"
if (-not (Test-Path $cfg)) {
    Copy-Item $ex $cfg
    Write-Host "==> Created settings.json from the example — EDIT IT (vault_path + at least one provider key)."
} else {
    Write-Host "==> settings.json already exists — left untouched."
}

Write-Host ""
Write-Host "==> Done."
Write-Host "    Next: edit assistant_core\config\settings.json, then run:"
Write-Host "      .venv\Scripts\python.exe -m assistant_core --terminal"
Write-Host "    Headless mode runs automatically when launched without a console."
