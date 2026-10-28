"""Run repeatable checks and save a sanitized evidence summary."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--postgres", action="store_true", help="Require TEST_DATABASE_URL and real PG")
args = parser.parse_args()
if args.postgres and not os.getenv("TEST_DATABASE_URL"):
    raise SystemExit("TEST_DATABASE_URL is required; no PostgreSQL result will be claimed")
(root / "artifacts").mkdir(exist_ok=True)
(root / "evidence").mkdir(exist_ok=True)
for generated in [root / "artifacts/tests.xml", root / "artifacts/audit.json"]:
    generated.unlink(missing_ok=True)
commands = [
    [sys.executable, "-m", "ruff", "check", "."],
    [sys.executable, "-m", "ruff", "format", "--check", "."],
    [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--junitxml=artifacts/tests.xml",
        *([] if args.postgres else ["-m", "not postgres"]),
    ],
    [
        sys.executable,
        "-m",
        "pip_audit",
        "-r",
        "requirements.txt",
        "--progress-spinner",
        "off",
        "--no-deps",
        "--disable-pip",
        "--format",
        "json",
        "--output",
        "artifacts/audit.json",
    ],
]
outcomes = []
for command in commands:
    run = subprocess.run(command, cwd=root, capture_output=True, text=True)
    # Logs stay private: pytest failures may contain connection parameters.
    (root / "artifacts" / f"check-{len(outcomes)}.log").write_text(
        run.stdout + run.stderr, encoding="utf-8"
    )
    outcomes.append(
        {
            "check": ["lint", "format", "pytest", "dependency-audit"][len(outcomes)],
            "exit_code": run.returncode,
        }
    )
suite = (
    ET.parse(root / "artifacts/tests.xml").getroot()
    if (root / "artifacts/tests.xml").exists()
    else ET.Element("testsuites")
)
cases = suite.findall(".//testcase")
test_counts = {
    "total": len(cases),
    "failed": len(suite.findall(".//failure")),
    "errors": len(suite.findall(".//error")),
    "skipped": len(suite.findall(".//skipped")),
}
source = hashlib.sha256()
for folder in ["gateway", "tests", "migrations", "scripts"]:
    for file in sorted((root / folder).rglob("*.py")):
        source.update(file.relative_to(root).as_posix().encode())
        source.update(file.read_bytes().replace(b"\r\n", b"\n"))
for name in [
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "alembic.ini",
    "Dockerfile",
    "compose.yaml",
    ".github/workflows/ci.yml",
]:
    source.update(name.encode())
    source.update((root / name).read_bytes().replace(b"\r\n", b"\n"))
audit_path = root / "artifacts/audit.json"
audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None
vulnerabilities = (
    sum(len(d["vulns"]) for d in audit.get("dependencies", [])) if audit is not None else None
)
success = (
    all(outcome["exit_code"] == 0 for outcome in outcomes)
    and bool(cases)
    and test_counts["skipped"] == 0
)
summary = {
    "schema_version": 1,
    "generated_at": datetime.now(UTC).isoformat(),
    "status": "passed" if success else "failed",
    "python": sys.version.split()[0],
    "test_scope": "portable-and-postgresql" if args.postgres else "portable-sqlite-only",
    "tests": test_counts,
    "checks": outcomes,
    "dependency_vulnerabilities": vulnerabilities,
    "source_sha256": source.hexdigest(),
    "data": "synthetic-only",
}
(root / "evidence/results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2))
raise SystemExit(0 if success else 1)
