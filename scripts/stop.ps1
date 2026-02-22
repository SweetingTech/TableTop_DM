param(
  [ValidateSet('docker','local')]
  [string]$Mode = 'docker'
)
$ErrorActionPreference = 'Continue'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

if ($Mode -eq 'docker') {
  bash scripts/stop.sh --mode docker
} else {
  bash scripts/stop.sh --mode local
}
