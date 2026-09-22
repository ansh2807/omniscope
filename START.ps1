<#
  START.ps1 - launcher for machines where .bat files are blocked.

  Run it with:
      powershell -ExecutionPolicy Bypass -File .\START.ps1

  It does exactly what START.bat does, and additionally clears Mark-of-the-Web
  from the project folder first, so it works on a freshly downloaded copy.
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "  ============================================================"
Write-Host "    CREATOR INTELLIGENCE ENGINE"
Write-Host "  ============================================================"
Write-Host ""

# ---------- 0. clear Mark-of-the-Web on ourselves -------------------------
try {
    Get-ChildItem -Path $PSScriptRoot -Recurse -File -ErrorAction SilentlyContinue |
        Unblock-File -ErrorAction SilentlyContinue
    Write-Host "  [0/5] Cleared the downloaded-file flag from this folder."
} catch {
    Write-Host "  [0/5] Could not clear the downloaded-file flag (continuing anyway)."
}

# ---------- 1. locate Python ----------------------------------------------
$py = $null
foreach ($cand in @("py", "python", "python3")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) {
        $args = if ($cand -eq "py") { @("-3") } else { @() }
        try {
            $v = & $cmd.Source @args "--version" 2>&1
            if ($v -match "Python 3") { $py = $cmd.Source; $pyArgs = $args; break }
        } catch { }
    }
}
if (-not $py) {
    Write-Host ""
    Write-Host "  [X] Python was not found on this computer." -ForegroundColor Red
    Write-Host "      Install Python 3.10+ from https://www.python.org/downloads/"
    Write-Host "      and tick 'Add python.exe to PATH' during setup."
    Write-Host ""
    Read-Host "  Press Enter to close"
    exit 1
}
Write-Host "  [1/5] $(& $py @pyArgs '--version' 2>&1) found."

# ---------- 2. virtual environment -----------------------------------------
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Write-Host "  [2/5] Creating virtual environment (one time, ~15 seconds)..."
    & $py @pyArgs -m venv .venv
} else {
    Write-Host "  [2/5] Virtual environment ready."
}

# ---------- 3. dependencies -------------------------------------------------
$stamp = Join-Path $PSScriptRoot ".venv\.installed"
if (-not (Test-Path $stamp)) {
    Write-Host "  [3/5] Installing dependencies (one time, ~60 seconds)..."
    & $vpy -m pip install --upgrade pip --quiet
    & $vpy -m pip install -r requirements-dev.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [X] Dependency installation failed." -ForegroundColor Red
        Read-Host "  Press Enter to close"
        exit 1
    }
    "ok" | Out-File -FilePath $stamp -Encoding ascii
} else {
    Write-Host "  [3/5] Dependencies ready."
}

# ---------- 4. browser tier --------------------------------------------------
# Playwright's Python package and its Chromium binary are separate downloads.
# The old PowerShell launcher installed only the package, then incorrectly reported
# setup complete; live Instagram/YouTube collection failed on a fresh machine.
$browserStamp = Join-Path $PSScriptRoot ".venv\.browser"
if ($env:CI_SKIP_BROWSER -eq "1") {
    Write-Host "  [4/5] Browser install skipped by CI_SKIP_BROWSER."
} elseif (-not (Test-Path $browserStamp)) {
    Write-Host "  [4/5] Installing the browser engine (one time, about 150 MB)..."
    & $vpy -m playwright install chromium
    if ($LASTEXITCODE -eq 0) {
        "ok" | Out-File -FilePath $browserStamp -Encoding ascii
        Write-Host "        Browser engine installed."
    } else {
        Write-Host "  [!] Browser download failed; reports will run with limited social data." -ForegroundColor Yellow
        Write-Host "      Re-run START.ps1 or ENABLE-BROWSER.bat to retry."
    }
} else {
    Write-Host "  [4/5] Browser engine ready."
}

# ---------- 5. config + key --------------------------------------------------
$apiKey = (& $vpy "tools\bootstrap.py" | Select-Object -Last 1).Trim()
if (-not $apiKey) {
    Write-Host "  [X] Setup failed." -ForegroundColor Red
    Read-Host "  Press Enter to close"
    exit 1
}
Write-Host "  [5/5] Configuration ready."

# ---------- pick a free port --------------------------------------------------
$port = 8000
foreach ($p in @(8000, 8001, 8002, 8003, 8010)) {
    $busy = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if (-not $busy) { $port = $p; break }
}

Write-Host ""
Write-Host "  ------------------------------------------------------------"
Write-Host "    Opening  http://localhost:$port"
Write-Host "    Your API key:  $apiKey"
Write-Host "    (saved in .env - you will be signed in automatically)"
Write-Host ""
Write-Host "    Leave this window open. Press Ctrl+C here to stop."
Write-Host "  ------------------------------------------------------------"
Write-Host ""

Start-Job -ScriptBlock {
    param($u) Start-Sleep -Seconds 4; Start-Process $u
} -ArgumentList "http://localhost:$port/?key=$apiKey" | Out-Null

& $vpy -m uvicorn app.main:app --host 127.0.0.1 --port $port

Write-Host ""
Write-Host "  Server stopped."
Read-Host "  Press Enter to close"
