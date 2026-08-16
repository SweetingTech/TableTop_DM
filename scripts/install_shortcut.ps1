# Create a "Tabletop DM" shortcut on the user's desktop pointing at
# launch_app.ps1. Idempotent — re-running just refreshes the existing file.
# Skip pwsh prompts to keep the install clean.

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$launcher = Join-Path $root 'scripts\launch_app.ps1'

if (-not (Test-Path $launcher)) {
    Write-Error "Launcher script missing at $launcher. Pull latest and try again."
    exit 1
}

# Resolve the real Desktop. Use a CSIDL call because some folks have OneDrive
# redirecting Desktop and $env:USERPROFILE\Desktop doesn't exist.
$desktop = [Environment]::GetFolderPath('Desktop')
if ([string]::IsNullOrWhiteSpace($desktop) -or -not (Test-Path $desktop)) {
    Write-Error "Couldn't resolve the Desktop folder."
    exit 1
}
$shortcutPath = Join-Path $desktop 'Tabletop DM.lnk'

# Use powershell.exe (Windows PowerShell 5.1) so the script can run via the
# default execution policy bypass we set on the command line. This avoids
# making the user fiddle with Set-ExecutionPolicy.
$ps = (Get-Command powershell.exe).Source

$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($shortcutPath)
$lnk.TargetPath        = $ps
$lnk.Arguments         = "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`""
$lnk.WorkingDirectory  = $root
# imageres.dll has a stack of nicer icons than shell32. Index 109 is a controller.
$lnk.IconLocation      = "$env:SystemRoot\System32\imageres.dll,109"
$lnk.Description       = 'Start Tabletop DM and open the dashboard'
$lnk.WindowStyle       = 1   # normal window so the user can see startup output
$lnk.Save()

Write-Host ''
Write-Host "Created shortcut: $shortcutPath" -ForegroundColor Green
Write-Host "Target:           $ps" -ForegroundColor DarkGray
Write-Host "Launcher:         $launcher" -ForegroundColor DarkGray
Write-Host ''
Write-Host 'Double-click the desktop icon any time. First boot is ~30s; subsequent boots are faster.' -ForegroundColor Cyan
