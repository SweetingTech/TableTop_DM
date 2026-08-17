param(
  [switch]$Reset,
  [switch]$NoBuild,
  [int]$Timeout = 180
)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'manage.py'), 'start', '--timeout', "$Timeout")
if ($Reset) { $arguments += '--reset' }
if ($NoBuild) { $arguments += '--no-build' }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "TableTop DM start failed with exit code $LASTEXITCODE" }
