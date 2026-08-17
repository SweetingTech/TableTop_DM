param([switch]$Volumes)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'manage.py'), 'stop')
if ($Volumes) { $arguments += '--volumes' }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "TableTop DM stop failed with exit code $LASTEXITCODE" }
