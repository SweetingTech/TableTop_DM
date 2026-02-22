param(
  [ValidateSet('docker','local')]
  [string]$Mode = 'docker',
  [switch]$InstallDeps
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

if (-not (Get-Command bash -ErrorAction SilentlyContinue)) {
  Write-Error "bash is required to run setup scripts on Windows (install Git Bash or WSL)."
}

if ($Mode -eq 'docker') {
  bash scripts/setup.sh --mode docker
  exit $LASTEXITCODE
}

if ($InstallDeps) {
  bash scripts/setup.sh --mode local --install-deps
} else {
  bash scripts/setup.sh --mode local
}
