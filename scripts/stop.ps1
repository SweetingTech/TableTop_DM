$ErrorActionPreference = "Continue"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (Test-Path ".run/app.pid") {
  $pidValue = Get-Content ".run/app.pid" -Raw
  $pidValue = $pidValue.Trim()
  if ($pidValue) {
    Write-Host "[stop] Stopping app process $pidValue"
    Stop-Process -Id ([int]$pidValue) -Force -ErrorAction SilentlyContinue
  }
  Remove-Item ".run/app.pid" -ErrorAction SilentlyContinue
}

Write-Host "[stop] Stopping infrastructure services"
docker compose -f infra/docker-compose.yml down --remove-orphans
Write-Host "[stop] Done"
