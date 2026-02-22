param(
  [ValidateSet('docker','local')]
  [string]$Mode = 'docker'
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

if ($Mode -eq 'docker') {
  bash scripts/start.sh --mode docker
} else {
  bash scripts/start.sh --mode local
}
