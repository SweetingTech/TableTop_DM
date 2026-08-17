param(
  [ValidateSet('fast','unit','contracts','integration','e2e','all')]
  [string]$Suite = 'fast'
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Push-Location $root
try {
  & uv run python scripts/test.py $Suite
  if ($LASTEXITCODE -ne 0) { throw "Test suite failed with exit code $LASTEXITCODE" }
} finally {
  Pop-Location
}
