param(
  [ValidateSet('docker','local')]
  [string]$Mode = 'docker',
  [switch]$ResetDb
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
    if ($ResetDb) {
      & $bash 'scripts/start.sh' '--mode' 'docker' '--reset-db'
    } else {
      & $bash 'scripts/start.sh' '--mode' 'docker'
    }
  } else {
    if ($ResetDb) {
      throw "-ResetDb is only supported with -Mode docker. Use Docker mode for destructive local dependency resets."
    }
    & $bash 'scripts/start.sh' '--mode' 'local'
  }
  $exitCode = $LASTEXITCODE
} finally {
  $ErrorActionPreference = $previousErrorActionPreference
}

if ($exitCode -ne 0) {
  throw "scripts/start.sh failed with exit code $exitCode"
}
