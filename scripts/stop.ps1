param(
  [ValidateSet('docker','local')]
  [string]$Mode = 'docker'
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

# Prefer Git Bash for Windows paths over WSL bash
$GitBashPath = "$env:ProgramFiles\Git\bin\bash.exe"
$bash = if (Test-Path $GitBashPath) {
    $GitBashPath
} elseif (Get-Command bash -ErrorAction SilentlyContinue) {
    (Get-Command bash).Path
} else {
    Write-Error "The 'bash' command was not found. Install Git Bash, WSL, or another Bash environment."
    exit 1
}

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
  if ($Mode -eq 'docker') {
    & $bash 'scripts/stop.sh' '--mode' 'docker'
  } else {
    & $bash 'scripts/stop.sh' '--mode' 'local'
  }
  $exitCode = $LASTEXITCODE
} finally {
  $ErrorActionPreference = $previousErrorActionPreference
}

if ($exitCode -ne 0) {
  throw "scripts/stop.sh failed with exit code $exitCode"
}
