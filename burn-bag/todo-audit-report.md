# TODO Audit Report
- Timestamp (UTC): 2026-02-22 20:37:29Z
- Repo: /app
- Platform: Linux-6.8.0-x86_64-with-glibc2.39
- Mode: FULL
- Strict: True

## Summary

- **PASS**: TODO completeness
- **PASS**: Referenced file/path checks
- **PASS**: Baseline required files
- **PASS**: Docs/README link & diagram asset integrity
- **PASS**: Canonical command discovery
- **PASS**: Docker checks
- **PASS**: Local CI command
- **FAIL**: RG0 start
- **PASS**: RG0 stop
- **PASS**: RG0 orphan container check
- **PASS**: RG1 smoke
- **PASS**: RG2 workflow calls canonical CI command
- **PASS**: CI secret dependence scan
- **PASS**: Line-by-line verifiability

## Details

### PASS: TODO completeness

All 111 checkbox items are checked.

### PASS: Referenced file/path checks

All referenced backtick paths/globs appear to exist.

### PASS: Baseline required files

All expected baseline files exist.

### PASS: Docs/README link & diagram asset integrity

No broken relative links/images detected in README/docs.

### PASS: Canonical command discovery

start_cmd=make local-up
stop_cmd=make local-down
ci_cmd=make ci-fast
migrate_cmd=make migrate
seed_cmd=(none)
rg1_cmd=(none)
compose_file=/app/infra/docker-compose.yml
health_url=http://localhost:8000/health

### PASS: Docker checks

Skipped in local mode.

### PASS: Local CI command

Local CI command passed: make ci-fast
Log: /app/burn-bag/audit-logs/20260222T203512Z-ci.log

### FAIL: RG0 start

Start command failed. Log: /app/burn-bag/audit-logs/20260222T203512Z-rg0-up.log

### PASS: RG0 stop

Stop command succeeded. Log: /app/burn-bag/audit-logs/20260222T203512Z-rg0-down.log

### PASS: RG0 orphan container check

No 'Up' containers detected in compose ps. Log: /app/burn-bag/audit-logs/20260222T203512Z-docker-compose-ps.log

### PASS: RG1 smoke

Skipped RG1 smoke for local mode (focus on RG0 + unit tests).

### PASS: RG2 workflow calls canonical CI command

Workflow /app/.github/workflows/ci.yml appears to call canonical CI command(s): make ci

### PASS: CI secret dependence scan

No obvious secret key references found in CI workflow.

### PASS: Line-by-line verifiability

All checked TODO items have some evidence signal (paths/commands or RG coverage).
