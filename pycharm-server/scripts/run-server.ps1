# Run NutriW server on Windows (PowerShell)
$ErrorActionPreference = "Stop"
$serverRoot = Split-Path -Parent $PSScriptRoot
Set-Location $serverRoot

$venvPath = Join-Path $serverRoot "venv"
$pythonExe = Join-Path $venvPath "Scripts\\python.exe"
$cfgPath = Join-Path $venvPath "pyvenv.cfg"
$requirementsPath = Join-Path $serverRoot "requirements.txt"
$needsRecreate = $false

if (Test-Path -LiteralPath $cfgPath) {
    $cfg = Get-Content -LiteralPath $cfgPath -Raw
    if ($cfg -notmatch [regex]::Escape($venvPath)) {
        $needsRecreate = $true
    }
}

if ($needsRecreate -and (Test-Path -LiteralPath $venvPath)) {
    Write-Host "Detected stale venv path. Recreating environment..."
    Remove-Item -LiteralPath $venvPath -Recurse -Force
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    python -m venv $venvPath
}

& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r $requirementsPath
& $pythonExe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
