#!/usr/bin/env python3
"""Prepare conference demo assets (simulation + stage rehearsal)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    out = ROOT / "output" / "conference"
    out.mkdir(parents=True, exist_ok=True)
    cmds = [
        [sys.executable, "-m", "src.hardware_profile", "--redacted", "--no-probe"],
        [
            sys.executable,
            "-m",
            "src.signal_analysis",
            "compare-modulations",
            "--message",
            "DEMO-LAB-2027",
            "--frequency-zero",
            "18500",
            "--frequency-one",
            "19500",
            "--symbol-duration",
            "0.20",
            "--out-dir",
            str(out / "modulation-comparison"),
        ],
        [
            sys.executable,
            "-m",
            "src.stage_demo",
            "--simulate",
            "--message",
            "DEMO-LAB-2027",
            "--modulation",
            "cpfsk",
        ],
        [
            sys.executable,
            "-m",
            "src.calibration",
            "--dry-run",
            "--physical",
            "--start-frequency",
            "2000",
            "--end-frequency",
            "10000",
            "--step",
            "500",
            "--out-dir",
            str(out / "calibration-audible-sim"),
        ],
    ]
    for cmd in cmds:
        print("RUN", " ".join(cmd))
        subprocess.run(cmd, cwd=ROOT, check=False)
    (out / "README.md").write_text(
        "# Conference assets\n\n"
        "Generated locally. Prefer PHYSICAL_RX captures from `experiments/` "
        "for stage replay.\n"
    )
    print("Prepared", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
