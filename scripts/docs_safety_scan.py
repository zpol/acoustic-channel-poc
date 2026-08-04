#!/usr/bin/env python3
"""Warn when public documentation contains private operational details.

Scans Markdown, YAML, and Python help/docstrings under docs/, configs/,
README.md, and output/samples/README.md.

Does not modify raw experiment WAV captures. Skips private experiment
dump trees under experiments/ (those may retain lab metadata locally).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

# RFC1918 + common lab leftovers
RFC1918 = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b"
)
HOME_PATH = re.compile(r"/home/[A-Za-z0-9._-]+")
SSH_USER_AT = re.compile(r"\b[A-Za-z][A-Za-z0-9._-]{0,31}@(?:192\.168\.|10\.|172\.)")

# Configurable hostname denylist (lab machines)
DEFAULT_HOSTNAME_DENYLIST = (
    "t11",
    "nkn@",
)

SCAN_GLOBS = (
    "README.md",
    "docs/**/*.md",
    "configs/**/*",
    "output/samples/README.md",
    "src/**/*.py",
    "scripts/*.py",
    ".github/**/*.yml",
    ".github/**/*.yaml",
)

# Self-scan would false-positive on the denylist literals
SKIP_FILES = {
    "scripts/docs_safety_scan.py",
    "tests/test_publication_pass.py",
    "configs/local-lab.env",
}

SKIP_PARTS = (
    "experiments/",
    "__pycache__",
    ".venv/",
    "node_modules/",
    "configs/local-lab.env",
)


def _iter_files(root: Path) -> Iterable[Path]:
    for pattern in SCAN_GLOBS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel = path.as_posix()
            if any(s in rel for s in SKIP_PARTS):
                continue
            if rel in SKIP_FILES or path.name in {Path(s).name for s in SKIP_FILES}:
                if path.name == "docs_safety_scan.py":
                    continue
            yield path


def scan_file(path: Path, hostnames: Tuple[str, ...] = DEFAULT_HOSTNAME_DENYLIST) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"{path}: unreadable ({exc})"]
    findings: List[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        if RFC1918.search(line):
            findings.append(f"{path}:{i}: RFC1918 address: {line.strip()[:120]}")
        if HOME_PATH.search(line):
            findings.append(f"{path}:{i}: home-directory path: {line.strip()[:120]}")
        if SSH_USER_AT.search(line):
            findings.append(f"{path}:{i}: SSH user@private-IP: {line.strip()[:120]}")
        low = line.lower()
        for host in hostnames:
            if host.lower() in low:
                # Allow documentation that explains redaction of the hostname
                if "redact" in low or "placeholder" in low or "example" in low:
                    continue
                findings.append(f"{path}:{i}: denylist hostname/user '{host}': {line.strip()[:120]}")
    return findings


def scan_repository(root: Path, hostnames: Tuple[str, ...] = DEFAULT_HOSTNAME_DENYLIST) -> List[str]:
    out: List[str] = []
    for path in sorted(set(_iter_files(root))):
        out.extend(scan_file(path, hostnames=hostnames))
    return out


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("."))
    args = p.parse_args(argv)
    findings = scan_repository(args.root.resolve())
    if findings:
        print("Documentation safety scan FAILED:")
        for f in findings:
            print(f"  {f}")
        return 1
    print("Documentation safety scan OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
