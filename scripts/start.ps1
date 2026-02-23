param(
  [ValidateSet('docker','local')]
  [string]$Mode = 'docker'
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

$bash = Get-Command bash -ErrorAction SilentlyContinue
if (-not $bash) {
  Write-Error "The 'bash' command was not found. Install Git Bash, WSL, or another Bash environment."
  exit 1
}

if ($Mode -eq 'docker') {
  & $bash.Path 'scripts/start.sh' '--mode' 'docker'
} else {
  & $bash.Path 'scripts/start.sh' '--mode' 'local'
}
