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

    $homeMatch = [regex]::Match($cfg, '(?m)^home\s*=\s*(.+)$')
    if ($homeMatch.Success) {
        $homePath = $homeMatch.Groups[1].Value.Trim()
        if (-not (Test-Path -LiteralPath $homePath)) {
            $needsRecreate = $true
        }
    }
}

if ((-not $needsRecreate) -and (Test-Path -LiteralPath $pythonExe)) {
    try {
        & $pythonExe --version *> $null
    } catch {
        $needsRecreate = $true
    }
}

if ($needsRecreate -and (Test-Path -LiteralPath $venvPath)) {
    Write-Host "Detected stale or broken venv. Recreating environment..."
    Remove-Item -LiteralPath $venvPath -Recurse -Force
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv $venvPath
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv $venvPath
    } else {
        throw "Python was not found. Install Python and try again."
    }
}

& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r $requirementsPath
& $pythonExe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
