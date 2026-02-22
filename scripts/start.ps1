$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not (Test-Path ".env")) {
  if (Test-Path ".env.example") {
    Copy-Item ".env.example" ".env"
    Write-Host "[start] Created .env from .env.example"
  } else {
    throw "[start] .env is missing and .env.example was not found."
  }
}

Write-Host "[start] Starting infrastructure services"
docker compose -f infra/docker-compose.yml up -d postgres redis qdrant

Write-Host "[start] Running migrations"
bash infra/scripts/migrate.sh

Write-Host "[start] Seeding demo campaign"
bash infra/scripts/seed_demo.sh

Write-Host "[start] Installing Python dependencies"
python -m pip install -r requirements-dev.txt | Out-Null
python -c "import tomllib, pathlib, subprocess; data=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); deps=data.get('project', {}).get('dependencies', []); subprocess.check_call(['python','-m','pip','install',*deps]) if deps else None"

if ($env:RUN_FOREGROUND -eq "1") {
  Write-Host "[start] Running app in foreground at http://localhost:5000"
  python app.py
  exit $LASTEXITCODE
}

if (-not (Test-Path ".run")) { New-Item -ItemType Directory -Path ".run" | Out-Null }

$proc = Start-Process -FilePath "python" -ArgumentList "app.py" -PassThru -RedirectStandardOutput ".run/app.log" -RedirectStandardError ".run/app.log"
$proc.Id | Out-File ".run/app.pid" -Encoding ascii
Write-Host "[start] Stack is up. Dashboard: http://localhost:5000"
Write-Host "[start] Use scripts/stop.ps1 to stop all services."
