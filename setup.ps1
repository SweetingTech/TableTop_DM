$ErrorActionPreference = 'Stop'

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'docker CLI is required but was not found in PATH.'
}

$Bash = if (Get-Command bash -ErrorAction SilentlyContinue) { 'bash' } elseif (Get-Command wsl -ErrorAction SilentlyContinue) { 'wsl bash' } else { throw 'bash is required but was not found. Install Git for Windows or WSL.' }

Write-Host '[1/5] Starting infrastructure...'
& $Bash "$RootDir/infra/scripts/phase1_up.sh"

Write-Host '[2/5] Running dependency health checks...'
& $Bash "$RootDir/infra/scripts/phase1_healthcheck.sh"

Write-Host '[3/5] Applying schema migrations...'
& $Bash "$RootDir/infra/scripts/migrate.sh"

Write-Host '[4/5] Seeding demo campaign data...'
& $Bash "$RootDir/infra/scripts/seed_demo.sh"

Write-Host '[5/5] Verifying schemas and RLS...'
& $Bash "$RootDir/infra/scripts/phase2_verify_schema.sh"

Write-Host 'Setup complete: Phases 1-4 infrastructure, migrations, and demo seed are ready.'
