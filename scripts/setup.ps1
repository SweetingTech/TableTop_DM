param(
  [ValidateSet('docker','local')]
  [string]$Mode = 'docker',
  [switch]$InstallDeps
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

if ($Mode -eq 'docker') {
  if (Get-Command bash -ErrorAction SilentlyContinue) {
    bash scripts/setup.sh --mode docker
  } else {
    pwsh -ExecutionPolicy Bypass -File ./setup.ps1
  }
} else {
  if (Get-Command bash -ErrorAction SilentlyContinue) {
    if ($InstallDeps) { bash scripts/setup.sh --mode local --install-deps } else { bash scripts/setup.sh --mode local }
  } else {
    Write-Error "bash is required to run local setup checks"
  }
}
