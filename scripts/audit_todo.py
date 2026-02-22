#!/usr/bin/env python3
"""
audit_todo.py
Repo auditor that treats todo.md/TODO.md as a contract and verifies:
- All checkboxes are checked
- Referenced files/paths exist
- Canonical commands exist and succeed (ci, up/down, migrate, seed, rg1)
- Docker compose config is valid (+ optional build)
- README and docs links/images are not broken
- Writes a report to burn-bag/todo-audit-report.md

Design goals:
- Deterministic and CI-friendly
- Minimal assumptions, configurable via env vars/flags
- Fail loudly on structural breakage
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict


CHECKBOX_RE = re.compile(r"^\s*-\s*\[(?P<mark>[ xX])\]\s+(?P<body>.+?)\s*$")
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


@dataclass
class TodoItem:
    line_no: int
    checked: bool
    text: str
    section_path: Tuple[str, ...]


@dataclass
class AuditFinding:
    name: str
    status: str  # PASS / FAIL / WARN
    details: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def which(cmd: str) -> Optional[str]:
    from shutil import which as _which

    return _which(cmd)


def run_cmd(
    cmd: List[str],
    cwd: Path,
    timeout_s: int = 900,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str]:
    """Run command and return (exit_code, combined_output)."""
    p = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout_s,
    )
    return p.returncode, p.stdout


def parse_todo(todo_path: Path) -> List[TodoItem]:
    items: List[TodoItem] = []
    current_sections: List[str] = []

    for idx, line in enumerate(read_text(todo_path).splitlines(), start=1):
        h = HEADING_RE.match(line)
        if h:
            level = len(h.group("hashes"))
            title = h.group("title").strip()
            # Trim to level-1 and append this heading
            current_sections = current_sections[: level - 1]
            current_sections.append(title)
            continue

        m = CHECKBOX_RE.match(line)
        if m:
            mark = m.group("mark").strip().lower()
            checked = mark == "x"
            body = m.group("body").strip()
            items.append(TodoItem(idx, checked, body, tuple(current_sections)))

    return items


def extract_code_spans(text: str) -> List[str]:
    return [s.strip() for s in CODE_SPAN_RE.findall(text)]


def looks_like_path(token: str) -> bool:
    # Heuristic: contains a path separator, wildcard, extension, or starts with dot or known dir
    if any(
        ch in token
        for ch in [
            "/",
            "\\",
            "*",
            "?",
            ".github",
            "docs/",
            "infra/",
            "services/",
            "scripts/",
        ]
    ):
        return True
    if token.endswith(
        (".md", ".yml", ".yaml", ".json", ".sql", ".sh", ".ps1", "Dockerfile")
    ):
        return True
    return False


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def find_make_targets(makefile: Path) -> set:
    targets = set()
    if not makefile.exists():
        return targets
    # Extremely simple Makefile target parser
    for line in read_text(makefile).splitlines():
        if line.startswith("\t") or line.strip().startswith("#"):
            continue
        # match "target: ..."
        if ":" in line:
            left = line.split(":", 1)[0].strip()
            if left and " " not in left and left != ".PHONY":
                targets.add(left)
    return targets


def resolve_compose_file(root: Path, override: Optional[str]) -> Optional[Path]:
    if override:
        p = (
            (root / override).resolve()
            if not Path(override).is_absolute()
            else Path(override)
        )
        return p if p.exists() else None

    env_cf = os.environ.get("COMPOSE_FILE")
    if env_cf:
        p = (
            (root / env_cf).resolve()
            if not Path(env_cf).is_absolute()
            else Path(env_cf)
        )
        if p.exists():
            return p

    # Common defaults
    for cand in [
        root / "infra" / "docker-compose.yml",
        root / "infra" / "docker-compose.yaml",
        root / "docker-compose.yml",
        root / "docker-compose.yaml",
    ]:
        if cand.exists():
            return cand

    return None


def resolve_health_url(override: Optional[str]) -> str:
    if override:
        return override
    return os.environ.get("VTT_HEALTH_URL", "http://localhost:8000/health")


def http_get(url: str, timeout_s: int = 5) -> Tuple[bool, str]:
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            code = resp.getcode()
            body = resp.read(512).decode("utf-8", errors="replace")
            return 200 <= code < 300, f"HTTP {code}: {body[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def fmt_cmd(cmd: Optional[List[str]]) -> str:
    return " ".join(cmd) if cmd else "(none)"


def pick_command(
    root: Path,
    make_targets: set,
    prefer_make: bool,
    target: str,
    script_fallback: Optional[Path],
) -> Optional[List[str]]:
    """
    Returns a command list to execute a canonical operation.
    target = make target (e.g., "ci", "up", "down", "seed", "migrate", "rg1")
    """
    if prefer_make and target in make_targets and which("make"):
        return ["make", target]

    if script_fallback and script_fallback.exists():
        # Windows: run ps1 via pwsh/powershell if needed
        if script_fallback.suffix.lower() == ".ps1":
            pwsh = which("pwsh") or which("powershell")
            if not pwsh:
                return None
            return [pwsh, "-ExecutionPolicy", "Bypass", "-File", str(script_fallback)]
        return [str(script_fallback)]

    return None


def scan_markdown_links(md_path: Path, root: Path) -> List[AuditFinding]:
    findings: List[AuditFinding] = []
    text = read_text(md_path)

    # Images
    for link in MD_IMAGE_RE.findall(text):
        link = link.strip()
        if not link or is_url(link) or link.startswith("data:"):
            continue
        # Remove anchors/query
        link = link.split("#", 1)[0].split("?", 1)[0]
        p = (md_path.parent / link).resolve()
        if not p.exists():
            findings.append(
                AuditFinding(
                    name=f"Docs image exists: {md_path.relative_to(root)} -> {link}",
                    status="FAIL",
                    details=f"Missing file: {p}",
                )
            )

    # Links
    for link in MD_LINK_RE.findall(text):
        link = link.strip()
        if not link or is_url(link) or link.startswith("mailto:"):
            continue
        link_no_anchor = link.split("#", 1)[0].split("?", 1)[0]
        if not link_no_anchor:
            continue
        # Treat as relative file path unless it looks like a route
        if "/" in link_no_anchor or "." in Path(link_no_anchor).name:
            p = (md_path.parent / link_no_anchor).resolve()
            if not p.exists():
                findings.append(
                    AuditFinding(
                        name=f"Docs link exists: {md_path.relative_to(root)} -> {link}",
                        status="FAIL",
                        details=f"Missing file: {p}",
                    )
                )

    return findings


def main() -> int:
    root = repo_root()

    ap = argparse.ArgumentParser(
        description="Audit todo.md/TODO.md completion and repo readiness."
    )
    ap.add_argument(
        "--todo",
        default="TODO.md",
        help="Path to todo.md/TODO.md relative to repo root.",
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="Run full audit (docker compose config/build, RG0, RG1, CI command).",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Fail on unverifiable TODO lines (WARN becomes FAIL).",
    )
    ap.add_argument(
        "--compose-file", default=None, help="Override docker compose file path."
    )
    ap.add_argument("--health-url", default=None, help="Override health URL for RG0.")
    ap.add_argument(
        "--report",
        default="burn-bag/todo-audit-report.md",
        help="Report path (relative to repo root).",
    )
    ap.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip docker compose build in full mode.",
    )
    ap.add_argument(
        "--skip-rg1", action="store_true", help="Skip RG1 smoke in full mode."
    )
    args = ap.parse_args()

    todo_path = (root / args.todo).resolve()
    if not todo_path.exists():
        fallback_name = "TODO.md" if Path(args.todo).name == "todo.md" else "todo.md"
        fallback = (root / fallback_name).resolve()
        if fallback.exists():
            todo_path = fallback
        else:
            print(f"FAIL: TODO file not found: {todo_path}", file=sys.stderr)
            return 2

    # Prepare report output path
    report_path = (root / args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    findings: List[AuditFinding] = []
    items = parse_todo(todo_path)

    # 1) Check unchecked items
    unchecked = [it for it in items if not it.checked]
    if unchecked:
        details = "\n".join(
            [
                f"- L{it.line_no}: {it.text} ({' > '.join(it.section_path)})"
                for it in unchecked[:50]
            ]
        )
        findings.append(
            AuditFinding(
                name="TODO completeness",
                status="FAIL",
                details=f"Found {len(unchecked)} unchecked items.\n{details}",
            )
        )
    else:
        findings.append(
            AuditFinding(
                name="TODO completeness",
                status="PASS",
                details=f"All {len(items)} checkbox items are checked.",
            )
        )

    # 2) Extract referenced paths from backticks and verify they exist
    referenced_paths_fail = []

    for it in items:
        spans = extract_code_spans(it.text)
        for token in spans:
            if not looks_like_path(token):
                continue

            # Command-like spans should not be treated as paths (make up, ./scripts/start.*)
            if token.startswith("make "):
                continue
            if token.startswith("./") and "*" in token:
                # glob pattern
                globs = list(root.glob(token[2:]))
                if not globs:
                    referenced_paths_fail.append((it, token, "glob matched nothing"))
                continue

            # Standard file/glob
            if "*" in token or "?" in token:
                globs = list(root.glob(token))
                if not globs:
                    referenced_paths_fail.append((it, token, "glob matched nothing"))
                continue

            p = (
                (root / token).resolve()
                if not Path(token).is_absolute()
                else Path(token)
            )
            if not p.exists():
                referenced_paths_fail.append((it, token, f"missing: {p}"))

    if referenced_paths_fail:
        details = "\n".join(
            [
                f"- L{it.line_no}: `{tok}` -> {why}"
                for it, tok, why in referenced_paths_fail[:100]
            ]
        )
        findings.append(
            AuditFinding(
                name="Referenced file/path checks",
                status="FAIL",
                details=f"Missing {len(referenced_paths_fail)} referenced paths.\n{details}",
            )
        )
    else:
        findings.append(
            AuditFinding(
                name="Referenced file/path checks",
                status="PASS",
                details="All referenced backtick paths/globs appear to exist.",
            )
        )

    # 3) Baseline required files (these are implied by your TODO)
    must_exist = [
        "README.md",
        ".env.example",
        ".github/workflows/ci.yml",
    ]
    if not (root / "TODO.md").exists() and not (root / "todo.md").exists():
        must_exist.append("TODO.md")
    # Optional: accept ci.yaml
    if (
        not (root / ".github/workflows/ci.yml").exists()
        and (root / ".github/workflows/ci.yaml").exists()
    ):
        must_exist.remove(".github/workflows/ci.yml")
        must_exist.append(".github/workflows/ci.yaml")

    docs_expected = [
        "docs/SPEC_MASTER.md",
        "docs/DATA_MODEL.md",
        "docs/STATE_DB_SCHEMA.md",
        "docs/LEDGER_SCHEMA.md",
        "docs/EVENT_ENVELOPE.md",
        "docs/INTERVENTION_CONTRACT.md",
        "docs/DOMAIN_TAGS.md",
        "docs/SECURITY_VISIBILITY.md",
        "docs/CONTENT_RATING.md",
        "docs/REPLAY_DEBUG.md",
    ]
    must_exist.extend(docs_expected)

    scripts_expected = [
        "scripts/start.sh",
        "scripts/stop.sh",
        "scripts/test.sh",
        "scripts/start.ps1",
        "scripts/stop.ps1",
    ]
    must_exist.extend(scripts_expected)

    missing_baseline = [p for p in must_exist if not (root / p).exists()]
    if missing_baseline:
        findings.append(
            AuditFinding(
                name="Baseline required files",
                status="FAIL",
                details="Missing required files:\n"
                + "\n".join([f"- {p}" for p in missing_baseline]),
            )
        )
    else:
        findings.append(
            AuditFinding(
                name="Baseline required files",
                status="PASS",
                details="All expected baseline files exist.",
            )
        )

    # 4) README and docs link/image integrity checks
    md_files = [root / "README.md"]
    docs_dir = root / "docs"
    if docs_dir.exists():
        md_files.extend(list(docs_dir.glob("**/*.md")))

    md_link_findings: List[AuditFinding] = []
    for md in md_files:
        md_link_findings.extend(scan_markdown_links(md, root))

    if md_link_findings:
        # Aggregate as FAIL if any missing assets
        details = "\n".join(
            [f"- {f.name}: {f.details}" for f in md_link_findings[:200]]
        )
        findings.append(
            AuditFinding(
                name="Docs/README link & diagram asset integrity",
                status="FAIL",
                details=f"Found {len(md_link_findings)} broken links/images.\n{details}",
            )
        )
    else:
        findings.append(
            AuditFinding(
                name="Docs/README link & diagram asset integrity",
                status="PASS",
                details="No broken relative links/images detected in README/docs.",
            )
        )

    # 5) Determine canonical commands
    makefile = root / "Makefile"
    targets = find_make_targets(makefile)
    prefer_make = makefile.exists() and which("make") is not None

    compose_file = resolve_compose_file(root, args.compose_file)
    health_url = resolve_health_url(args.health_url)

    start_cmd = pick_command(
        root,
        targets,
        prefer_make,
        "up",
        root / "scripts/start.sh"
        if (root / "scripts/start.sh").exists()
        else (root / "scripts/start.ps1"),
    )
    stop_cmd = pick_command(
        root,
        targets,
        prefer_make,
        "down",
        root / "scripts/stop.sh"
        if (root / "scripts/stop.sh").exists()
        else (root / "scripts/stop.ps1"),
    )
    migrate_cmd = pick_command(root, targets, prefer_make, "migrate", None)
    seed_cmd = pick_command(root, targets, prefer_make, "seed", None)
    ci_cmd = pick_command(
        root,
        targets,
        prefer_make,
        "ci",
        root / "scripts/test.sh" if (root / "scripts/test.sh").exists() else None,
    )
    rg1_cmd = pick_command(
        root,
        targets,
        prefer_make,
        "rg1",
        (root / "scripts/rg1.sh")
        if (root / "scripts/rg1.sh").exists()
        else (
            (root / "scripts/smoke_rg1.sh")
            if (root / "scripts/smoke_rg1.sh").exists()
            else None
        ),
    )

    # Command existence checks
    cmd_missing = []
    for name, cmd in [("start", start_cmd), ("stop", stop_cmd), ("ci", ci_cmd)]:
        if cmd is None:
            cmd_missing.append(name)
    if cmd_missing:
        findings.append(
            AuditFinding(
                name="Canonical command discovery",
                status="FAIL",
                details=f"Could not determine canonical command(s): {', '.join(cmd_missing)}. "
                f"Expected Makefile targets or scripts to exist.",
            )
        )
    else:
        findings.append(
            AuditFinding(
                name="Canonical command discovery",
                status="PASS",
                details=(
                    f"start_cmd={fmt_cmd(start_cmd)}\n"
                    f"stop_cmd={fmt_cmd(stop_cmd)}\n"
                    f"ci_cmd={fmt_cmd(ci_cmd)}\n"
                    f"migrate_cmd={fmt_cmd(migrate_cmd)}\n"
                    f"seed_cmd={fmt_cmd(seed_cmd)}\n"
                    f"rg1_cmd={fmt_cmd(rg1_cmd)}\n"
                    f"compose_file={compose_file if compose_file else '(none found)'}\n"
                    f"health_url={health_url}"
                ),
            )
        )

    # If full mode, do heavy checks
    cmd_logs_dir = root / "burn-bag" / "audit-logs"
    cmd_logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    def log_run(
        name: str, cmd: List[str], timeout_s: int = 1800
    ) -> Tuple[int, str, Path]:
        log_path = cmd_logs_dir / f"{timestamp}-{name}.log"
        rc, out = run_cmd(cmd, cwd=root, timeout_s=timeout_s)
        log_path.write_text(out, encoding="utf-8", errors="replace")
        return rc, out, log_path

    if args.full:
        # Docker compose validation/build
        if compose_file and which("docker"):
            # config
            rc, out, lp = log_run(
                "docker-compose-config",
                ["docker", "compose", "-f", str(compose_file), "config"],
                timeout_s=600,
            )
            if rc != 0:
                findings.append(
                    AuditFinding(
                        name="Docker compose config",
                        status="FAIL",
                        details=f"`docker compose config` failed. Log: {lp}",
                    )
                )
            else:
                findings.append(
                    AuditFinding(
                        name="Docker compose config",
                        status="PASS",
                        details=f"Compose config valid. Log: {lp}",
                    )
                )

            if not args.skip_build:
                rc, out, lp = log_run(
                    "docker-compose-build",
                    ["docker", "compose", "-f", str(compose_file), "build"],
                    timeout_s=3600,
                )
                if rc != 0:
                    findings.append(
                        AuditFinding(
                            name="Docker compose build",
                            status="FAIL",
                            details=f"`docker compose build` failed. Log: {lp}",
                        )
                    )
                else:
                    findings.append(
                        AuditFinding(
                            name="Docker compose build",
                            status="PASS",
                            details=f"Compose services build OK. Log: {lp}",
                        )
                    )
        else:
            findings.append(
                AuditFinding(
                    name="Docker checks",
                    status="WARN",
                    details="Docker or compose file not found. Skipping docker validation/build.",
                )
            )

        # Run CI command locally (equivalent)
        if ci_cmd:
            rc, out, lp = log_run("ci", ci_cmd, timeout_s=3600)
            if rc != 0:
                findings.append(
                    AuditFinding(
                        name="Local CI command",
                        status="FAIL",
                        details=f"CI command failed: {' '.join(ci_cmd)}\nLog: {lp}",
                    )
                )
            else:
                findings.append(
                    AuditFinding(
                        name="Local CI command",
                        status="PASS",
                        details=f"CI command passed: {' '.join(ci_cmd)}\nLog: {lp}",
                    )
                )

        # RG0: up -> health -> down
        if start_cmd and stop_cmd:
            rc, out, lp = log_run("rg0-up", start_cmd, timeout_s=1800)
            if rc != 0:
                findings.append(
                    AuditFinding(
                        name="RG0 start",
                        status="FAIL",
                        details=f"Start command failed. Log: {lp}",
                    )
                )
            else:
                # Poll health a bit
                ok = False
                last_msg = ""
                for _ in range(30):
                    ok, last_msg = http_get(health_url, timeout_s=3)
                    if ok:
                        break
                    import time

                    time.sleep(2)

                if not ok:
                    findings.append(
                        AuditFinding(
                            name="RG0 health",
                            status="FAIL",
                            details=f"Health check failed for {health_url}. Last: {last_msg}",
                        )
                    )
                else:
                    findings.append(
                        AuditFinding(
                            name="RG0 health",
                            status="PASS",
                            details=f"Health OK at {health_url}. {last_msg}",
                        )
                    )

            rc, out, lp = log_run("rg0-down", stop_cmd, timeout_s=900)
            if rc != 0:
                findings.append(
                    AuditFinding(
                        name="RG0 stop",
                        status="FAIL",
                        details=f"Stop command failed. Log: {lp}",
                    )
                )
            else:
                findings.append(
                    AuditFinding(
                        name="RG0 stop",
                        status="PASS",
                        details=f"Stop command succeeded. Log: {lp}",
                    )
                )

            # Optional: confirm compose ps shows nothing running
            if compose_file and which("docker"):
                rc, out, lp = log_run(
                    "docker-compose-ps",
                    ["docker", "compose", "-f", str(compose_file), "ps"],
                    timeout_s=60,
                )
                # If ps output still lists running containers, warn/fail
                if "Up" in out:
                    findings.append(
                        AuditFinding(
                            name="RG0 orphan container check",
                            status="WARN",
                            details=f"Compose still reports containers as Up. Inspect: {lp}",
                        )
                    )
                else:
                    findings.append(
                        AuditFinding(
                            name="RG0 orphan container check",
                            status="PASS",
                            details=f"No 'Up' containers detected in compose ps. Log: {lp}",
                        )
                    )

        # RG1 smoke
        if not args.skip_rg1:
            if rg1_cmd is None:
                findings.append(
                    AuditFinding(
                        name="RG1 smoke",
                        status="FAIL" if args.strict else "WARN",
                        details="No RG1 runner found (expected `make rg1` target or scripts/rg1.sh or scripts/smoke_rg1.sh).",
                    )
                )
            else:
                # Bring stack up again for rg1
                if start_cmd:
                    log_run("rg1-up", start_cmd, timeout_s=1800)
                if migrate_cmd:
                    log_run("rg1-migrate", migrate_cmd, timeout_s=900)
                if seed_cmd:
                    log_run("rg1-seed", seed_cmd, timeout_s=900)

                rc, out, lp = log_run("rg1", rg1_cmd, timeout_s=1800)
                if rc != 0:
                    findings.append(
                        AuditFinding(
                            name="RG1 smoke",
                            status="FAIL",
                            details=f"RG1 command failed: {' '.join(rg1_cmd)}\nLog: {lp}",
                        )
                    )
                else:
                    findings.append(
                        AuditFinding(
                            name="RG1 smoke",
                            status="PASS",
                            details=f"RG1 passed: {' '.join(rg1_cmd)}\nLog: {lp}",
                        )
                    )

                if stop_cmd:
                    log_run("rg1-down", stop_cmd, timeout_s=900)

        # RG2 local equivalent: workflow file must call canonical scripts/commands
        wf = root / ".github" / "workflows"
        wf_file = (
            (wf / "ci.yml")
            if (wf / "ci.yml").exists()
            else ((wf / "ci.yaml") if (wf / "ci.yaml").exists() else None)
        )
        if wf_file and wf_file.exists():
            y = read_text(wf_file)
            # Basic checks
            must_mention = []
            if prefer_make and "ci" in targets:
                must_mention.append("make ci")
            else:
                must_mention.append("scripts/test.sh")

            missing = [m for m in must_mention if m not in y]
            if missing:
                findings.append(
                    AuditFinding(
                        name="RG2 workflow calls canonical CI command",
                        status="FAIL" if args.strict else "WARN",
                        details=f"Workflow {wf_file} does not appear to call: {', '.join(missing)}",
                    )
                )
            else:
                findings.append(
                    AuditFinding(
                        name="RG2 workflow calls canonical CI command",
                        status="PASS",
                        details=f"Workflow {wf_file} appears to call canonical CI command(s): {', '.join(must_mention)}",
                    )
                )

            # Check for obvious secret dependence
            bad_markers = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
            found_bad = [m for m in bad_markers if m in y]
            if found_bad:
                findings.append(
                    AuditFinding(
                        name="CI secret dependence scan",
                        status="WARN",
                        details=f"Workflow references possible secret keys: {', '.join(found_bad)}. "
                        f"CI should pass without secrets using MockLLM.",
                    )
                )
            else:
                findings.append(
                    AuditFinding(
                        name="CI secret dependence scan",
                        status="PASS",
                        details="No obvious secret key references found in CI workflow.",
                    )
                )
        else:
            findings.append(
                AuditFinding(
                    name="RG2 workflow presence",
                    status="FAIL" if args.strict else "WARN",
                    details="No CI workflow file found under .github/workflows/ci.yml(ci.yaml).",
                )
            )

    # 6) Identify unverifiable TODO lines (line-by-line honesty)
    # Rule: if a checked line has no backtick references and is not inside RG headings, we cannot directly verify it.
    unverifiable = []
    for it in items:
        spans = extract_code_spans(it.text)
        in_rg = any(
            "RG0" in s or "RG1" in s or "RG2" in s or "Reality Gates" in s
            for s in it.section_path
        )
        if it.checked and not spans and not in_rg:
            unverifiable.append(it)

    if unverifiable:
        # In strict mode, fail. Otherwise warn.
        status = "FAIL" if args.strict else "WARN"
        details = "\n".join(
            [
                f"- L{it.line_no}: {it.text} ({' > '.join(it.section_path)})"
                for it in unverifiable[:60]
            ]
        )
        findings.append(
            AuditFinding(
                name="Line-by-line verifiability",
                status=status,
                details=(
                    f"{len(unverifiable)} checked TODO items have no machine-verifiable evidence "
                    f"(no paths/commands in backticks and not under RG sections).\n"
                    f"Recommendation: add evidence tags or a mapping file tying each item to a test/gate.\n"
                    f"{details}"
                ),
            )
        )
    else:
        findings.append(
            AuditFinding(
                name="Line-by-line verifiability",
                status="PASS",
                details="All checked TODO items have some evidence signal (paths/commands or RG coverage).",
            )
        )

    # Write report
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    report_lines = []
    report_lines.append("# TODO Audit Report\n")
    report_lines.append(f"- Timestamp (UTC): {now}\n")
    report_lines.append(f"- Repo: {root}\n")
    report_lines.append(f"- Platform: {platform.platform()}\n")
    report_lines.append(f"- Mode: {'FULL' if args.full else 'QUICK'}\n")
    report_lines.append(f"- Strict: {args.strict}\n\n")

    # Summary table
    report_lines.append("## Summary\n\n")
    for f in findings:
        report_lines.append(f"- **{f.status}**: {f.name}\n")

    report_lines.append("\n## Details\n\n")
    for f in findings:
        report_lines.append(f"### {f.status}: {f.name}\n\n")
        report_lines.append(f"{f.details}\n\n")

    report_path.write_text("".join(report_lines), encoding="utf-8", errors="replace")

    # Decide exit code
    has_fail = any(f.status == "FAIL" for f in findings)
    print(f"Wrote report: {report_path}")
    if has_fail:
        print("AUDIT FAIL: see report for details.", file=sys.stderr)
        return 1
    print("AUDIT PASS (or WARN): see report for details.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
