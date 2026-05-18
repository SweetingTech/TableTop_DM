param(
  [ValidateSet('docker','local')]
  [string]$Mode = 'docker',
  [string]$BaseUrl = 'http://localhost:8000'
)

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

function Assert-HttpOk {
  param(
    [string]$Path,
    [int]$TimeoutSec = 15
  )
  $url = "$BaseUrl$Path"
  try {
    $response = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec $TimeoutSec
  } catch {
    throw "[verify_boot] $url failed: $($_.Exception.Message)"
  }
  if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
    throw "[verify_boot] $url returned HTTP $($response.StatusCode)"
  }
  Write-Host "[verify_boot] OK $url"
  return $response
}

try {
  & .\scripts\stop.ps1 -Mode $Mode
  & .\scripts\start.ps1 -Mode $Mode

  Assert-HttpOk -Path '/health' | Out-Null
  $ready = Assert-HttpOk -Path '/readyz?verbose=1' -TimeoutSec 30
  $readyJson = $ready.Content | ConvertFrom-Json
  if (-not $readyJson.ready) {
    throw "[verify_boot] /readyz returned but ready=false: $($ready.Content)"
  }

  Assert-HttpOk -Path '/' | Out-Null
  Assert-HttpOk -Path '/game' | Out-Null
  Assert-HttpOk -Path '/control' | Out-Null
  Assert-HttpOk -Path '/help' | Out-Null

  Write-Host "[verify_boot] Boot verification passed."
} finally {
  & .\scripts\stop.ps1 -Mode $Mode
}
