# Tabletop DM launcher.
# Starts the docker-compose deps + the Flask host process, waits for /readyz,
# then opens the dashboard in the default browser. Run from a desktop shortcut.

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

# Window title so the user knows what this is.
$Host.UI.RawUI.WindowTitle = 'Tabletop DM — starting…'

Write-Host ''
Write-Host '==============================' -ForegroundColor Cyan
Write-Host '  Tabletop DM' -ForegroundColor Cyan
Write-Host '==============================' -ForegroundColor Cyan
Write-Host ''

# If the server is already up just open the browser.
$alreadyUp = $false
try {
    $r = Invoke-WebRequest -Uri 'http://localhost:8000/readyz' -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $alreadyUp = $true }
} catch { }

if ($alreadyUp) {
    Write-Host 'Server is already running at http://localhost:8000' -ForegroundColor Green
} else {
    Write-Host 'Starting server (docker compose + Flask). First boot can take ~30s.' -ForegroundColor Yellow
    Write-Host ''
    & "$PSScriptRoot\start.ps1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Startup script returned a non-zero exit code.' -ForegroundColor Red
        Read-Host 'Press Enter to close'
        exit 1
    }
}

# Poll /readyz for up to 60 seconds before opening the browser.
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri 'http://localhost:8000/readyz' -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200 -and $r.Content -match '"status":\s*"ready"') {
            $ready = $true
            break
        }
    } catch {
        # not up yet
    }
    Start-Sleep -Seconds 1
}

if (-not $ready) {
    Write-Host ''
    Write-Host 'Server did not report ready within 60s. Check burn-bag/local-run/app.log.' -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

Write-Host ''
Write-Host 'Server is up. Opening browser…' -ForegroundColor Green
Start-Process 'http://localhost:8000/'

$Host.UI.RawUI.WindowTitle = 'Tabletop DM — running'
Write-Host ''
Write-Host 'Leave this window open while you play. To stop the server, run:' -ForegroundColor Cyan
Write-Host '    .\scripts\stop.ps1' -ForegroundColor Cyan
Write-Host ''
Read-Host 'Press Enter to keep this window in the background (or close it manually)'
