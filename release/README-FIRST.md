# TableTop DM v1.0.0 - README FIRST

## Prerequisites

- Windows 10/11 or a compatible Linux/macOS shell.
- Docker Desktop for the recommended local stack.
- Python 3.11+ if running from source.

No hosted AI API key is required for the demo campaign. Local LM Studio/Ollama
providers can be configured later from Control Plane -> AI Settings.

## First Run On Windows

1. Extract the release zip.
2. Open PowerShell in the extracted folder.
3. Run:
   ```powershell
   .\scripts\verify_boot.ps1 -Mode docker
   .\scripts\start.ps1 -Mode docker
   ```
4. Open `http://localhost:8000/`.

To stop:

```powershell
.\scripts\stop.ps1 -Mode docker
```

## First Run From Source

```powershell
copy .env.example .env
.\scripts\start.ps1 -Mode docker
```

## Troubleshooting

- `GET /readyz?verbose=1` explains dependency failures for Postgres, Redis,
  Qdrant, and migrations.
- If Docker is unhealthy, restart Docker Desktop and run `.\scripts\stop.ps1
  -Mode docker` before starting again.
- If a disposable local Docker database reports an already-applied migration
  checksum mismatch, rebuild the local dependency volumes with
  `.\scripts\start.ps1 -Mode docker -ResetDb`. This deletes local Postgres,
  Redis, and Qdrant Docker volume data.
- For local LLM use, configure provider/model/base URL in Control Plane -> AI
  Settings. RAG requires a reachable embedding model for local providers.

## Release Verification

The release gate expects:

```powershell
python -m compileall -q app.py services shared tests infra
pytest tests\services tests\contracts tests\integration -q
pytest tests\e2e -rs -q
.\scripts\verify_boot.ps1 -Mode docker
```
