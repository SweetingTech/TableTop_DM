$ErrorActionPreference = 'Stop'

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'docker CLI is required but was not found in PATH.'
}

# Prefer Git Bash for Windows paths over WSL bash
$GitBashPath = "$env:ProgramFiles\Git\bin\bash.exe"
$Bash = if (Test-Path $GitBashPath) {
    $GitBashPath
} elseif (Get-Command bash -ErrorAction SilentlyContinue) {
    'bash'
} else {
    throw 'bash is required but was not found. Install Git for Windows or WSL.'
}

function Run-BashScript([string]$ScriptPath) {
    # Convert backslashes for bash compatibility
    $UnixPath = $ScriptPath -replace '\\', '/'
    & $Bash $UnixPath
    if ($LASTEXITCODE -ne 0) {
        throw "Script $ScriptPath failed with exit code $LASTEXITCODE"
    }
}

Write-Host '[1/5] Starting infrastructure...'
Run-BashScript "$RootDir/infra/scripts/phase1_up.sh"

Write-Host '[2/5] Running dependency health checks...'
Run-BashScript "$RootDir/infra/scripts/phase1_healthcheck.sh"

Write-Host '[3/5] Applying schema migrations...'
Run-BashScript "$RootDir/infra/scripts/migrate.sh"

Write-Host '[4/5] Seeding demo campaign data...'
Run-BashScript "$RootDir/infra/scripts/seed_demo.sh"

Write-Host '[5/5] Verifying schemas and RLS...'
Run-BashScript "$RootDir/infra/scripts/phase2_verify_schema.sh"

Write-Host 'Setup complete: Phases 1-4 infrastructure, migrations, and demo seed are ready.'
