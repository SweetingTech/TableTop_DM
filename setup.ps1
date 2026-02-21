$ErrorActionPreference = 'Stop'

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'docker CLI is required but was not found in PATH.'
}

Write-Host '[1/3] Starting infrastructure...'
& "$RootDir/infra/scripts/phase1_up.sh"

Write-Host '[2/3] Running dependency health checks...'
& "$RootDir/infra/scripts/phase1_healthcheck.sh"

Write-Host '[3/3] Verifying Phase 2 schemas and RLS...'
& "$RootDir/infra/scripts/phase2_verify_schema.sh"

Write-Host 'Setup complete: Phase 1 and Phase 2 infrastructure are up and verified.'
