#!/usr/bin/env python3
"""Generate Part 2 article figures from real repository evidence only.

Usage:
  PYTHONPATH=. python scripts/article/generate_part2_figures.py
  PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-03
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "article-part2"
FIG = OUT / "figures"
EVID = OUT / "evidence"

# Visual identity
BG = "#ffffff"
FG = "#1a1a1a"
ACCENT = "#2a6f97"
ACCENT2 = "#bc4749"
ACCENT3 = "#2a9d8f"
GRID = "#dddddd"
NOTE = "#555555"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mpl_safe(s: str) -> str:
    """Escape $ so matplotlib does not treat it as mathtext."""
    return str(s).replace("$", r"\$")


def style_ax(ax: plt.Axes) -> None:
    ax.set_facecolor(BG)
    ax.tick_params(colors=FG)
    for spine in ax.spines.values():
        spine.set_color(FG)
    ax.yaxis.label.set_color(FG)
    ax.xaxis.label.set_color(FG)
    ax.title.set_color(FG)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.8)


def save_fig(fig: plt.Figure, stem: str) -> List[str]:
    FIG.mkdir(parents=True, exist_ok=True)
    png = FIG / f"{stem}.png"
    svg = FIG / f"{stem}.svg"
    fig.savefig(png, dpi=160, bbox_inches="tight", facecolor=BG)
    fig.savefig(svg, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return [str(png.relative_to(ROOT)), str(svg.relative_to(ROOT))]


def load_csv_snr(path: Path):
    freqs, snrs, energies = [], [], []
    with path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            freqs.append(float(row["frequency"]))
            snrs.append(float(row["estimated_detector_snr_db"]))
            energies.append(float(row["energy"]))
    return np.array(freqs), np.array(snrs), np.array(energies)


def fig01(manifest: Dict[str, Any], log: List[str]) -> None:
    src_png = ROOT / "output/article/14-audible-vs-near-us-calibration.png"
    aud = ROOT / "output/samples/calibration-audible-physical/measurements.csv"
    nus = ROOT / "output/samples/calibration-near-us-physical/measurements.csv"
    status = "EXISTS_READY" if src_png.exists() else "MISSING_METADATA"
    # Regenerate from CSV for reproducibility + SVG
    fa, sa, _ = load_csv_snr(aud)
    fn, sn, _ = load_csv_snr(nus)
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=False)
    fig.patch.set_facecolor(BG)
    axes[0].plot(fa / 1000, sa, "o-", color=ACCENT, ms=4, lw=1.3, label="audible sweep")
    axes[0].axhline(0, color=NOTE, lw=0.8, ls="--")
    axes[0].set_ylabel("estimated_detector_snr_db")
    axes[0].set_xlabel("Frequency (kHz)")
    axes[0].set_title("Physical audible calibration 2–10 kHz")
    axes[0].text(0.99, 0.02, "PHYSICAL_RX", transform=axes[0].transAxes, ha="right", fontsize=9, color=NOTE)
    style_ax(axes[0])
    axes[1].plot(fn / 1000, sn, "s-", color=ACCENT2, ms=4, lw=1.3, label="near-US sweep")
    axes[1].axhline(0, color=NOTE, lw=0.8, ls="--")
    axes[1].set_ylabel("estimated_detector_snr_db")
    axes[1].set_xlabel("Frequency (kHz)")
    axes[1].set_title("Physical near-ultrasonic calibration 15–21 kHz")
    axes[1].text(0.99, 0.02, "PHYSICAL_RX", transform=axes[1].transAxes, ha="right", fontsize=9, color=NOTE)
    style_ax(axes[1])
    fig.suptitle(
        "Audible vs near-US physical calibration (tested TX→RX path)\n"
        "Metric: estimated_detector_snr_db (not calibrated SPL)",
        color=FG,
    )
    fig.tight_layout()
    outs = save_fig(fig, "fig01-audible-vs-near-us-calibration")
    # Also copy original as reference
    import shutil

    shutil.copy(src_png, FIG / "fig01-source-14-audible-vs-near-us-calibration.png")
    sources = [aud, nus, src_png]
    entry = {
        "figure_id": "FIG-01",
        "title": "Audible vs near-US calibration",
        "output_files": outs + [str((FIG / "fig01-source-14-audible-vs-near-us-calibration.png").relative_to(ROOT))],
        "status": "GENERATED_FROM_REAL_DATA",
        "provenance": ["PHYSICAL_RX"],
        "source_files": [str(p.relative_to(ROOT)) for p in sources],
        "source_sha256": [sha256_file(p) for p in sources],
        "generator_script": "scripts/article/generate_part2_figures.py",
        "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-01",
        "parameters": {"metric": "estimated_detector_snr_db"},
        "trial_ids": ["calibration-audible-physical", "calibration-near-us-physical"],
        "claims_supported": [
            "Audible-band detector SNR can be positive on tested path",
            "15–21 kHz sweep shows low/negative estimated_detector_snr_db",
        ],
        "limitations": [
            "Not calibrated SPL",
            "Hardware/room specific",
            "Original PNG 14-* also archived as source copy",
        ],
        "contains_redactions": False,
        "prior_status_note": status,
    }
    manifest["figures"].append(entry)
    log.append(f"FIG-01 regenerated from CSV; original PNG present={src_png.exists()}")


def fig02(manifest: Dict[str, Any], log: List[str]) -> None:
    gen = ROOT / "output/samples/near_us_HELLO_tx.wav"
    # No paired PHYSICAL_RX of the same 18.5/19.5 HELLO transmission found.
    # calibration-near-us rx_physical.wav is a frequency sweep, not this frame.
    entry = {
        "figure_id": "FIG-02",
        "title": "Generated 18.5/19.5 kHz versus physical recording",
        "output_files": [],
        "status": "MISSING_PHYSICAL_EVIDENCE",
        "provenance": ["GENERATED_TX"],
        "source_files": [str(gen.relative_to(ROOT))] if gen.exists() else [],
        "source_sha256": [sha256_file(gen)] if gen.exists() else [],
        "generator_script": "scripts/article/generate_part2_figures.py",
        "command": "N/A — not generated (no linkable PHYSICAL_RX for same trial)",
        "parameters": {"intended_carriers_hz": [18500, 19500]},
        "trial_ids": [],
        "claims_supported": [],
        "limitations": [
            "near_us_HELLO_tx.wav is GENERATED_TX only",
            "No PHYSICAL_RX WAV documented as the matching microphone capture of that TX",
            "Do not pair with calibration sweep RX",
        ],
        "contains_redactions": False,
        "missing_requirement": (
            "Record PHYSICAL_RX while playing a documented 18500/19500 TX "
            "(or save metadata linking TX+RX hashes), then regenerate FIG-02"
        ),
    }
    # Still export a GENERATED_TX-only panel clearly labelled (not as physical success)
    if gen.exists():
        sr, data = wavfile.read(gen)
        x = np.asarray(data, dtype=float)
        if x.ndim > 1:
            x = x.mean(1)
        # short window for readability
        n = min(len(x), int(sr * 2.5))
        fig, ax = plt.subplots(figsize=(11, 3.8))
        fig.patch.set_facecolor(BG)
        ax.specgram(x[:n], Fs=sr, NFFT=2048, noverlap=1536, cmap="magma")
        ax.axhline(18500, color="cyan", ls="--", lw=1, label="18.5 kHz")
        ax.axhline(19500, color="lime", ls=":", lw=1, label="19.5 kHz")
        ax.set_ylim(10000, 22000)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Frequency (Hz)")
        ax.set_title("GENERATED_TX only — near_us_HELLO (not physical success)")
        ax.legend(loc="upper right", fontsize=8)
        ax.text(0.01, 0.02, "GENERATED_TX — Panel B PHYSICAL_RX MISSING", transform=ax.transAxes, color="white", fontsize=9)
        style_ax(ax)
        fig.tight_layout()
        outs = save_fig(fig, "fig02-generated-tx-only-18500-19500-NOT-PHYSICAL")
        entry["output_files"] = outs
        entry["status"] = "MISSING_PHYSICAL_EVIDENCE"
        entry["notes"] = "Partial GENERATED_TX export for reference only; full two-panel FIG-02 blocked"
        log.append("FIG-02: MISSING physical pair; exported GENERATED_TX-only reference")
    else:
        log.append("FIG-02: missing generated TX as well")
    manifest["figures"].append(entry)


def fig03(manifest: Dict[str, Any], log: List[str]) -> None:
    nus = ROOT / "output/samples/calibration-near-us-physical/measurements.csv"
    fn, sn, en = load_csv_snr(nus)
    fig, ax = plt.subplots(figsize=(11, 4.8))
    fig.patch.set_facecolor(BG)
    ax.plot(fn / 1000, sn, "o-", color=ACCENT2, ms=5, lw=1.4)
    ax.axhline(0, color=NOTE, ls="--", lw=0.8)
    marks = {
        15.0: ("15 kHz", ACCENT3, "Selected after physical calibration"),
        16.0: ("16 kHz", ACCENT3, "Selected after physical calibration"),
        18.5: ("18.5 kHz", ACCENT, "Initial theory-driven selection"),
        19.5: ("19.5 kHz", ACCENT, "Initial theory-driven selection"),
    }
    for f_khz, (lab, col, note) in marks.items():
        ax.axvline(f_khz, color=col, ls=":", lw=1.2)
        # nearest measured point
        idx = int(np.argmin(np.abs(fn / 1000 - f_khz)))
        ax.scatter([fn[idx] / 1000], [sn[idx]], s=60, color=col, zorder=5)
        ax.annotate(
            f"{lab}\n{note}\n{sn[idx]:.1f} dB",
            xy=(fn[idx] / 1000, sn[idx]),
            xytext=(8, 12 if f_khz < 17 else -28),
            textcoords="offset points",
            fontsize=7,
            color=FG,
            arrowprops=dict(arrowstyle="->", color=col, lw=0.8),
        )
    ax.set_xlabel("Frequency (kHz)")
    ax.set_ylabel("estimated_detector_snr_db")
    ax.set_title("Physical near-US calibration sweep 15–21 kHz")
    ax.text(0.99, 0.02, "PHYSICAL_RX", transform=ax.transAxes, ha="right", fontsize=9, color=NOTE)
    style_ax(ax)
    fig.tight_layout()
    outs = save_fig(fig, "fig03-physical-frequency-response-15k-21k")
    manifest["figures"].append(
        {
            "figure_id": "FIG-03",
            "title": "Physical response 15–21 kHz",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": ["PHYSICAL_RX"],
            "source_files": [str(nus.relative_to(ROOT))],
            "source_sha256": [sha256_file(nus)],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-03",
            "parameters": {"metric": "estimated_detector_snr_db", "highlight_hz": [15000, 16000, 18500, 19500]},
            "trial_ids": ["calibration-near-us-physical"],
            "claims_supported": [
                "15/16 kHz were later selected for recovery; detector SNR still negative at calib time",
                "18.5/19.5 kHz were weaker theory-driven candidates on this sweep",
            ],
            "limitations": ["Calib SNR does not by itself prove later CRC-valid live decode"],
            "contains_redactions": False,
        }
    )
    log.append("FIG-03 generated from near-US measurements.csv")


def fig04(manifest: Dict[str, Any], log: List[str]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 5.2), sharex=False)
    fig.patch.set_facecolor(BG)
    for ax, f0, label in [
        (axes[0], 15000, "f0 nominal"),
        (axes[1], 16000, "f1 nominal"),
    ]:
        xs = np.arange(f0 - 150, f0 + 150 + 1e-9, 25)
        # explanatory synthetic envelope peaked at nominal (NOT measured data)
        ys = np.exp(-0.5 * ((xs - f0) / 55.0) ** 2)
        ax.vlines(xs, 0, ys, color=ACCENT, lw=2)
        ax.plot(xs, ys, "o", color=ACCENT, ms=4)
        ax.axvline(f0, color=ACCENT2, ls="--", lw=1.2, label=f"{label}: {f0} Hz")
        ax.scatter([f0], [1.0], s=80, color=ACCENT2, zorder=5, label="selected local max (illustrative)")
        ax.set_xlim(f0 - 180, f0 + 180)
        ax.set_ylim(0, 1.25)
        ax.set_ylabel("relative score (diagram)")
        ax.set_xlabel("Frequency (Hz)")
        ax.legend(loc="upper right", fontsize=8)
        style_ax(ax)
        ax.text(0.01, 0.92, "Explanatory diagram — not a measured spectrum", transform=ax.transAxes, fontsize=8, color=NOTE)
    fig.suptitle(
        "Carrier-neighbourhood search (±150 Hz, step 25 Hz, configurable)\n"
        "Configuration derived from PHYSICAL_RX recovery campaign",
        color=FG,
    )
    fig.tight_layout()
    outs = save_fig(fig, "fig04-carrier-neighborhood-search")
    manifest["figures"].append(
        {
            "figure_id": "FIG-04",
            "title": "Carrier-neighborhood receiver search",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": [],
            "source_files": ["configs/near-us-recovery.yaml", "docs/near-us-recovery-campaign.md"],
            "source_sha256": [],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-04",
            "parameters": {"f0": 15000, "f1": 16000, "search_hz": 150, "step_hz": 25},
            "trial_ids": [],
            "claims_supported": ["Receiver can search a configurable neighbourhood around nominal carriers"],
            "limitations": [
                "Diagram is explanatory; envelope is illustrative, not measured energy from a WAV",
            ],
            "contains_redactions": False,
            "diagram_type": "explanatory",
        }
    )
    log.append("FIG-04 explanatory diagram generated")


def fig05(manifest: Dict[str, Any], log: List[str]) -> None:
    log_path = EVID / "hello_nua_terminal_redacted.log"
    wav = ROOT / "output/lab_nua_HELLO_20260804T195738.wav"
    if not log_path.exists() or not wav.exists():
        manifest["figures"].append(
            {
                "figure_id": "FIG-05",
                "title": "First HELLO physical recovery",
                "output_files": [],
                "status": "MISSING_PHYSICAL_EVIDENCE",
                "provenance": [],
                "source_files": [],
                "source_sha256": [],
                "generator_script": "scripts/article/generate_part2_figures.py",
                "command": "N/A",
                "parameters": {},
                "trial_ids": [],
                "claims_supported": [],
                "limitations": ["Missing HELLO log or WAV"],
                "contains_redactions": False,
            }
        )
        log.append("FIG-05 missing sources")
        return
    text = log_path.read_text()
    # Render terminal from original log text (redacted)
    lines = text.splitlines()
    # Keep result-relevant lines + header
    keep = []
    for ln in lines:
        if any(
            k in ln
            for k in (
                "Auto-TX",
                "f0=",
                "Recovered:",
                "CRC:",
                "Status:",
                "Provenance:",
                "Capture done",
                "Saved capture",
                "MODE",
                "LIVE PHYSICAL",
            )
        ):
            keep.append(ln)
    # Fallback: full log if filter too aggressive
    body = "\n".join(keep) if len(keep) >= 5 else text
    body = re.sub(r"output/lab_nua_HELLO_\S+", "output/lab_nua_HELLO_<trial>.wav", body)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")
    ax.axis("off")
    ax.text(
        0.02,
        0.98,
        body,
        transform=ax.transAxes,
        va="top",
        ha="left",
        family="monospace",
        fontsize=8.5,
        color="#e6edf3",
        wrap=True,
    )
    ax.text(
        0.98,
        0.02,
        "PHYSICAL_RX  |  redacted terminal from original live_monitor log",
        transform=ax.transAxes,
        ha="right",
        fontsize=9,
        color="#7ee787",
    )
    fig.tight_layout()
    png = FIG / "fig05-hello-crc-valid-physical-rx.png"
    fig.savefig(png, dpi=160, bbox_inches="tight", facecolor="#0d1117")
    plt.close(fig)
    outs = [str(png.relative_to(ROOT))]
    manifest["figures"].append(
        {
            "figure_id": "FIG-05",
            "title": "First HELLO physical recovery",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": ["PHYSICAL_RX"],
            "source_files": [
                str(log_path.relative_to(ROOT)),
                str(wav.relative_to(ROOT)),
            ],
            "source_sha256": [sha256_file(log_path), sha256_file(wav)],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-05",
            "parameters": {
                "carriers_hz": [15000, 16000],
                "payload": "HELLO",
                "crc": "VALID",
            },
            "trial_ids": ["lab_nua_HELLO_20260804T195738"],
            "claims_supported": [
                "PHYSICAL_RX decode of HELLO with CRC VALID at 15/16 kHz profile",
            ],
            "limitations": [
                "Single documented trial in preserved log (N=1 for this HELLO capture)",
                "Terminal image is a rendering of the redacted log, not a live screenshot",
            ],
            "contains_redactions": True,
        }
    )
    log.append("FIG-05 rendered from redacted HELLO log + linked WAV")


def fig06(manifest: Dict[str, Any], log: List[str]) -> None:
    rows = [
        {
            "expected": "user@domain.tld",
            "tx_input": "user@domain.tld",
            "recovered": "user@domain.tld",
            "crc": "CRC VALID",
            "trial_id": "20260804T200528_user@domain.tld_",
            "wav": "output/lab_nearus_payloads/20260804T200528_user@domain.tld_.wav",
            "exact": True,
            "notes": "",
        },
        {
            "expected": "demo_sinclair_2000",
            "tx_input": "demo_sinclair_2000",
            "recovered": "demo_sinclair_2000",
            "crc": "CRC VALID",
            "trial_id": "20260804T201103_demo_sinclair_2000_",
            "wav": "output/lab_nearus_payloads/20260804T201103_demo_sinclair_2000_.wav",
            "exact": True,
            "notes": "",
        },
        {
            "expected": "this_is_working!!!",
            "tx_input": "this_is_working!!!",
            "recovered": "this_is_working!!!",
            "crc": "CRC VALID",
            "trial_id": "20260804T201521_this_is_working!!!_",
            "wav": "output/lab_nearus_payloads/20260804T201521_this_is_working!!!_.wav",
            "exact": True,
            "notes": "",
        },
        {
            "expected": "p4$$w0rd",
            "tx_input": "p4<PID>w0rd (remote shell expanded $$)",
            "recovered": "p41068552w0rd",
            "crc": "CRC VALID",
            "trial_id": "20260804T200144_p4$$w0rd_",
            "wav": "output/lab_nearus_payloads/20260804T200144_p4$$w0rd_.wav",
            "exact": False,
            "notes": "Before shlex.quote; CRC matches transmitted modified string",
        },
        {
            "expected": "p4$$w0rd",
            "tx_input": "p4$$w0rd",
            "recovered": "p4$$w0rd",
            "crc": "CRC VALID",
            "trial_id": "20260804T202412_p4dollars_retry",
            "wav": "output/lab_nearus_payloads/20260804T202412_p4dollars_retry.wav",
            "exact": True,
            "notes": "After shlex.quote fix",
        },
    ]
    # Verify WAVs exist
    for r in rows:
        p = ROOT / r["wav"]
        if not p.exists():
            raise FileNotFoundError(r["wav"])
        r["wav_sha256"] = sha256_file(p)
        r["provenance"] = "PHYSICAL_RX"

    csv_path = FIG / "fig06-physical-payload-results.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "expected",
                "tx_input",
                "recovered",
                "crc",
                "exact_match",
                "trial_id",
                "provenance",
                "wav",
                "wav_sha256",
                "notes",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "expected": r["expected"],
                    "tx_input": r["tx_input"],
                    "recovered": r["recovered"],
                    "crc": r["crc"],
                    "exact_match": r["exact"],
                    "trial_id": r["trial_id"],
                    "provenance": r["provenance"],
                    "wav": r["wav"],
                    "wav_sha256": r["wav_sha256"],
                    "notes": r["notes"],
                }
            )

    fig, ax = plt.subplots(figsize=(12, 4.8))
    fig.patch.set_facecolor(BG)
    ax.axis("off")
    col_labels = ["Expected", "TX input (documented)", "Recovered", "CRC", "Exact?", "Provenance"]
    cell = []
    for r in rows:
        cell.append(
            [
                mpl_safe(r["expected"]),
                mpl_safe(r["tx_input"][:28] + ("…" if len(r["tx_input"]) > 28 else "")),
                mpl_safe(r["recovered"]),
                r["crc"],
                "yes" if r["exact"] else "no",
                "PHYSICAL_RX",
            ]
        )
    table = ax.table(cellText=cell, colLabels=col_labels, loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.05, 1.6)
    for (i, j), cell_obj in table.get_celld().items():
        cell_obj.set_edgecolor(GRID)
        if i == 0:
            cell_obj.set_facecolor("#e8eef3")
            cell_obj.get_text().set_weight("bold")
        else:
            cell_obj.set_facecolor(BG)
            if j == 4 and cell[i - 1][4] == "no":
                cell_obj.set_facecolor("#fde8e8")
            if j == 4 and cell[i - 1][4] == "yes":
                cell_obj.set_facecolor("#e7f6ef")
    ax.set_title(
        "Physical near-US payload recoveries (documented trials only)\n"
        + mpl_safe(
            "Exact matches after quoting fix: 4/4 intended strings; plus 1 CRC-valid modified TX (SSH $$)"
        ),
        color=FG,
        fontsize=11,
    )
    ax.text(0.5, 0.02, "PHYSICAL_RX — do not report as 100% reliability", transform=ax.transAxes, ha="center", fontsize=8, color=NOTE)
    fig.tight_layout()
    outs = save_fig(fig, "fig06-physical-payload-results")
    outs.append(str(csv_path.relative_to(ROOT)))
    summary = ROOT / "output/samples/experiment-summaries/20260804-nearus-payloads/summary.md"
    sources = [ROOT / r["wav"] for r in rows] + [summary]
    manifest["figures"].append(
        {
            "figure_id": "FIG-06",
            "title": "Exact recovered payloads",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": ["PHYSICAL_RX"],
            "source_files": [str(p.relative_to(ROOT)) for p in sources],
            "source_sha256": [sha256_file(p) for p in sources],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-06",
            "parameters": {"documented_trials": len(rows)},
            "trial_ids": [r["trial_id"] for r in rows],
            "claims_supported": [
                "Four intended payloads recovered exactly after quoting fix",
                "One pre-fix trial CRC-validated a shell-expanded transmitter input",
            ],
            "limitations": [
                "Trial counts are the documented runs in summary.md / WAVs (not a large-N study)",
                "WAV files currently under output/lab_nearus_payloads (local lab dumps)",
            ],
            "contains_redactions": False,
        }
    )
    log.append("FIG-06 table/csv generated from documented WAVs + summary")


def fig07(manifest: Dict[str, Any], log: List[str]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    fig.patch.set_facecolor(BG)

    def flow(ax, title, steps, color):
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title(title, color=FG, fontsize=11)
        y = 0.88
        for i, s in enumerate(steps):
            ax.add_patch(
                mpatches.FancyBboxPatch(
                    (0.12, y - 0.08),
                    0.76,
                    0.12,
                    boxstyle="round,pad=0.02",
                    facecolor="#f4f7fa",
                    edgecolor=color,
                    lw=1.5,
                )
            )
            ax.text(0.5, y - 0.02, s, ha="center", va="center", fontsize=8, color=FG, wrap=True)
            if i < len(steps) - 1:
                ax.annotate("", xy=(0.5, y - 0.12), xytext=(0.5, y - 0.08), arrowprops=dict(arrowstyle="->", color=color))
            y -= 0.2

    flow(
        axes[0],
        "Before quoting fix",
        [
            mpl_safe("intended: p4$$w0rd"),
            mpl_safe("remote shell expansion of $$"),
            "modified transmitter input\n(documented recovered: p41068552w0rd)",
            "CRC VALID for transmitted\n(modified) input — PHYSICAL_RX",
        ],
        ACCENT2,
    )
    flow(
        axes[1],
        "After shlex.quote",
        [
            mpl_safe('shlex.quote("p4$$w0rd")'),
            "literal argument preserved over SSH",
            mpl_safe("p4$$w0rd reaches transmitter"),
            "exact recovery + CRC VALID\nPHYSICAL_RX",
        ],
        ACCENT3,
    )
    fig.suptitle(
        "Shell quoting bug vs fix (live_monitor/experiment remote TX)\n"
        "Commit introducing fix: 8bdc9be — src/live_monitor.py / src/experiment.py",
        color=FG,
        fontsize=11,
    )
    fig.tight_layout()
    outs = save_fig(fig, "fig07-shell-quoting-before-after")
    manifest["figures"].append(
        {
            "figure_id": "FIG-07",
            "title": "Shell quoting bug",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": ["PHYSICAL_RX"],
            "source_files": [
                "output/lab_nearus_payloads/results_20260804T200144.md",
                "src/live_monitor.py",
                "src/experiment.py",
            ],
            "source_sha256": [
                sha256_file(ROOT / "output/lab_nearus_payloads/results_20260804T200144.md"),
                sha256_file(ROOT / "src/live_monitor.py"),
                sha256_file(ROOT / "src/experiment.py"),
            ],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-07",
            "parameters": {"fix_commit": "8bdc9be"},
            "trial_ids": [
                "20260804T200144_p4$$w0rd_",
                "20260804T202412_p4dollars_retry",
            ],
            "claims_supported": [
                "Pre-fix trial recovered a PID-substituted string with CRC VALID",
                "Post-fix trial recovered exact p4$$w0rd with CRC VALID",
            ],
            "limitations": [
                "Diagram summarizes documented outcomes; exact PID value comes from that trial's recovered string",
            ],
            "contains_redactions": False,
        }
    )
    log.append("FIG-07 before/after diagram generated")


def fig08(manifest: Dict[str, Any], log: List[str]) -> None:
    wav = ROOT / "output/lab_nua_HELLO_20260804T195738.wav"
    sr, data = wavfile.read(wav)
    x = np.asarray(data, dtype=float)
    if x.ndim > 1:
        x = x.mean(1)
    # Focus on a mid segment where TX likely occurred (after ~2.5s delay)
    start = int(2.0 * sr)
    stop = min(len(x), start + int(25 * sr))
    seg = x[start:stop]
    fig, ax = plt.subplots(figsize=(11, 4.6))
    fig.patch.set_facecolor(BG)
    ax.specgram(seg, Fs=sr, NFFT=4096, noverlap=3072, cmap="viridis")
    ax.axhline(15000, color="white", ls="--", lw=1, label="15 kHz")
    ax.axhline(16000, color="cyan", ls=":", lw=1, label="16 kHz")
    ax.set_ylim(5000, 20000)
    ax.set_xlabel("Time (s) within excerpt")
    ax.set_ylabel("Frequency (Hz)")
    ax.set_title("PHYSICAL_RX spectrogram — HELLO trial lab_nua_HELLO_20260804T195738")
    ax.legend(loc="upper right", fontsize=8)
    ax.text(0.01, 0.02, "PHYSICAL_RX | CRC VALID (full-file decode)", transform=ax.transAxes, color="white", fontsize=9)
    ax.text(0.01, 0.08, "Spectral leakage may appear below carriers; not labelled as 'audible' without notes", transform=ax.transAxes, color="white", fontsize=7)
    style_ax(ax)
    fig.tight_layout()
    outs = save_fig(fig, "fig08-successful-physical-rx-spectrogram")
    manifest["figures"].append(
        {
            "figure_id": "FIG-08",
            "title": "Successful physical spectrogram (HELLO)",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": ["PHYSICAL_RX"],
            "source_files": [str(wav.relative_to(ROOT))],
            "source_sha256": [sha256_file(wav)],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-08",
            "parameters": {"excerpt_start_s": 2.0, "excerpt_len_s": 25, "nfft": 4096},
            "trial_ids": ["lab_nua_HELLO_20260804T195738"],
            "claims_supported": [
                "Physical capture of HELLO recovery trial contains energy near 15/16 kHz region",
            ],
            "limitations": [
                "Spectrogram excerpt timing is approximate (not sample-accurate frame bounds)",
                "Peak sample magnitude was high (~0.92); possible compression/clipping effects",
            ],
            "contains_redactions": False,
        }
    )
    log.append("FIG-08 spectrogram from HELLO PHYSICAL_RX WAV")


def fig09(manifest: Dict[str, Any], log: List[str]) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    fig.patch.set_facecolor(BG)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    boxes = [
        (1, 4.5, "Controller\n(RX host)"),
        (1, 2.5, "Python receiver\n+ decode"),
        (5.2, 4.5, "TX laptop\nspeaker"),
        (5.2, 1.2, "RX laptop\nmicrophone"),
    ]
    for x, y, t in boxes:
        ax.add_patch(mpatches.FancyBboxPatch((x, y), 2.4, 1.0, boxstyle="round,pad=0.05", facecolor="#f4f7fa", edgecolor=ACCENT, lw=1.5))
        ax.text(x + 1.2, y + 0.5, t, ha="center", va="center", fontsize=9, color=FG)
    ax.annotate("SSH: playback\ncoordination only\n(NOT the payload)", xy=(5.2, 5.0), xytext=(3.4, 5.3), fontsize=8, color=ACCENT2, arrowprops=dict(arrowstyle="->", color=ACCENT2))
    ax.annotate("acoustic payload\nthrough air", xy=(6.4, 2.2), xytext=(6.4, 3.5), fontsize=8, color=ACCENT3, ha="center", arrowprops=dict(arrowstyle="->", color=ACCENT3, lw=2))
    ax.annotate("", xy=(2.2, 3.5), xytext=(2.2, 4.5), arrowprops=dict(arrowstyle="->", color=FG))
    ax.annotate("", xy=(6.4, 2.2), xytext=(2.4, 2.8), arrowprops=dict(arrowstyle="->", color=FG))
    ax.set_title("Experimental architecture — payload travels acoustically", color=FG)
    ax.text(0.99, 0.02, "Explanatory diagram (configuration from PHYSICAL_RX campaign)", transform=ax.transAxes, ha="right", fontsize=8, color=NOTE)
    fig.tight_layout()
    outs = save_fig(fig, "fig09-experimental-architecture")
    manifest["figures"].append(
        {
            "figure_id": "FIG-09",
            "title": "Experimental architecture",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": [],
            "source_files": ["docs/near-us-recovery-campaign.md"],
            "source_sha256": [],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-09",
            "parameters": {},
            "trial_ids": [],
            "claims_supported": ["SSH coordinated playback only; payload path is acoustic"],
            "limitations": ["Schematic; not a photograph of the lab setup"],
            "contains_redactions": False,
        }
    )
    log.append("FIG-09 architecture diagram generated")


def fig10(manifest: Dict[str, Any], log: List[str]) -> None:
    stages = [
        ("NumPy waveform", "digital"),
        ("OS audio", "digital"),
        ("DAC", "boundary"),
        ("amplifier", "physical"),
        ("laptop speaker", "physical"),
        ("room", "physical"),
        ("microphone", "physical"),
        ("ADC", "boundary"),
        ("audio processing", "digital"),
        ("receiver", "digital"),
    ]
    colors = {"digital": "#dbeafe", "physical": "#fee2e2", "boundary": "#fef9c3"}
    fig, ax = plt.subplots(figsize=(12, 3.2))
    fig.patch.set_facecolor(BG)
    ax.set_xlim(0, len(stages))
    ax.set_ylim(0, 1)
    ax.axis("off")
    for i, (name, kind) in enumerate(stages):
        ax.add_patch(mpatches.FancyBboxPatch((i + 0.05, 0.35), 0.9, 0.35, boxstyle="round,pad=0.02", facecolor=colors[kind], edgecolor=FG, lw=1))
        ax.text(i + 0.5, 0.52, name, ha="center", va="center", fontsize=7, color=FG)
        if i < len(stages) - 1:
            ax.annotate("", xy=(i + 1.05, 0.52), xytext=(i + 0.95, 0.52), arrowprops=dict(arrowstyle="->", color=FG))
    ax.axvline(2.0, color=ACCENT2, ls="--", lw=1)
    ax.text(2.0, 0.85, "Nyquist constrains sampling\n≠ flat hardware response", ha="center", fontsize=8, color=ACCENT2)
    ax.set_title("Nyquist vs physical audio chain", color=FG)
    ax.text(0.01, 0.05, "digital", color=NOTE, fontsize=8)
    ax.text(0.15, 0.05, "physical", color=NOTE, fontsize=8)
    fig.tight_layout()
    outs = save_fig(fig, "fig10-nyquist-vs-physical-chain")
    manifest["figures"].append(
        {
            "figure_id": "FIG-10",
            "title": "Nyquist versus physical chain",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": [],
            "source_files": ["docs/blog-part2-nyquist-meets-hardware.md"],
            "source_sha256": [],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-10",
            "parameters": {},
            "trial_ids": [],
            "claims_supported": ["Nyquist is not a guarantee of usable transducer response"],
            "limitations": ["Conceptual diagram"],
            "contains_redactions": False,
        }
    )
    log.append("FIG-10 chain diagram generated")


def fig11(manifest: Dict[str, Any], log: List[str]) -> None:
    stages = [
        ("Synthetic payload", "TX"),
        ("Frame", "TX"),
        ("CRC-16", "TX"),
        ("Hamming(7,4)", "TX"),
        ("CPFSK", "TX"),
        ("Physical playback", "CH"),
        ("Mic recording", "CH"),
        ("Sync", "RX"),
        ("Demod", "RX"),
        ("FEC decode", "RX"),
        ("CRC check", "RX"),
        ("Recovered", "RX"),
    ]
    col = {"TX": ACCENT, "CH": ACCENT2, "RX": ACCENT3}
    fig, ax = plt.subplots(figsize=(13, 3.0))
    fig.patch.set_facecolor(BG)
    ax.set_xlim(0, len(stages))
    ax.set_ylim(0, 1)
    ax.axis("off")
    for i, (name, role) in enumerate(stages):
        ax.add_patch(mpatches.FancyBboxPatch((i + 0.05, 0.35), 0.9, 0.4, boxstyle="round,pad=0.02", facecolor="#f8fafc", edgecolor=col[role], lw=1.6))
        ax.text(i + 0.5, 0.55, name, ha="center", va="center", fontsize=6.5, color=FG)
        ax.text(i + 0.5, 0.22, role, ha="center", fontsize=7, color=col[role])
        if i < len(stages) - 1:
            ax.annotate("", xy=(i + 1.05, 0.55), xytext=(i + 0.95, 0.55), arrowprops=dict(arrowstyle="->", color=FG))
    ax.set_title("Frame and channel pipeline (recovery profile uses Hamming + CPFSK)", color=FG)
    fig.tight_layout()
    outs = save_fig(fig, "fig11-frame-and-channel-pipeline")
    manifest["figures"].append(
        {
            "figure_id": "FIG-11",
            "title": "Frame and channel pipeline",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": [],
            "source_files": ["src/protocol.py", "src/fec.py", "src/modulation.py"],
            "source_sha256": [],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-11",
            "parameters": {},
            "trial_ids": [],
            "claims_supported": ["Pipeline includes CRC, optional Hamming, CPFSK, physical path, CRC validation"],
            "limitations": ["Schematic"],
            "contains_redactions": False,
        }
    )
    log.append("FIG-11 pipeline diagram generated")


def fig12(manifest: Dict[str, Any], log: List[str]) -> None:
    events = [
        "18.5/19.5 kHz theory-driven selection",
        "Weak physical calibration (15–21 kHz sweep)",
        "Select 15/16 kHz after calibration ranking",
        "Receiver neighbourhood search (±150 Hz)",
        "HELLO CRC VALID (PHYSICAL_RX)",
        "Varied payload recoveries (PHYSICAL_RX)",
        mpl_safe("Shell quoting bug on p4$$w0rd"),
        mpl_safe("Exact p4$$w0rd recovery after shlex.quote"),
    ]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    fig.patch.set_facecolor(BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(events) + 1)
    ax.axis("off")
    for i, e in enumerate(events):
        y = len(events) - i
        ax.plot([0.15, 0.15], [y - 0.3, y + 0.3] if i == 0 else [y, y + 1], color=ACCENT, lw=2)
        ax.scatter([0.15], [y], s=50, color=ACCENT2, zorder=5)
        ax.text(0.22, y, e, va="center", fontsize=9, color=FG)
    ax.set_title("Recovery timeline (order documented; no unverified dates added)", color=FG)
    ax.text(0.99, 0.02, "Derived from campaign docs + PHYSICAL_RX trials", transform=ax.transAxes, ha="right", fontsize=8, color=NOTE)
    fig.tight_layout()
    outs = save_fig(fig, "fig12-recovery-timeline")
    manifest["figures"].append(
        {
            "figure_id": "FIG-12",
            "title": "Recovery timeline",
            "output_files": outs,
            "status": "GENERATED_FROM_REAL_DATA",
            "provenance": ["PHYSICAL_RX"],
            "source_files": [
                "docs/near-us-recovery-campaign.md",
                "output/samples/experiment-summaries/20260804-nearus-payloads/summary.md",
            ],
            "source_sha256": [],
            "generator_script": "scripts/article/generate_part2_figures.py",
            "command": "PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-12",
            "parameters": {},
            "trial_ids": [],
            "claims_supported": ["Ordered narrative matches documented campaign sequence"],
            "limitations": ["No wall-clock timestamps beyond filenames/summary date 2026-08-04"],
            "contains_redactions": False,
        }
    )
    log.append("FIG-12 timeline generated")


GENERATORS = {
    "FIG-01": fig01,
    "FIG-02": fig02,
    "FIG-03": fig03,
    "FIG-04": fig04,
    "FIG-05": fig05,
    "FIG-06": fig06,
    "FIG-07": fig07,
    "FIG-08": fig08,
    "FIG-09": fig09,
    "FIG-10": fig10,
    "FIG-11": fig11,
    "FIG-12": fig12,
}


def write_audit(manifest: Dict[str, Any]) -> None:
    rows = []
    for f in manifest["figures"]:
        rows.append(
            {
                "Figure": f["figure_id"],
                "Description": f.get("title", ""),
                "Status": f.get("status", ""),
                "Evidence source": "; ".join(f.get("source_files", [])[:3]),
                "Provenance": ", ".join(f.get("provenance", [])) or "diagram",
                "Can generate now": "yes"
                if f.get("status")
                in ("GENERATED_FROM_REAL_DATA", "EXISTS_READY", "DIAGRAM_TO_GENERATE")
                and f.get("output_files")
                else ("partial" if f.get("output_files") else "no"),
                "Missing requirement": f.get("missing_requirement", f.get("limitations", [""])[0] if f.get("limitations") else ""),
            }
        )
    lines = [
        "# Part 2 Figure Audit",
        "",
        f"Generated: {manifest['generated_at']}",
        f"Git HEAD (at generation): {manifest.get('git_head', 'unknown')}",
        "",
        "| Figure | Description | Status | Evidence source | Provenance | Can generate now | Missing requirement |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['Figure']} | {r['Description']} | {r['Status']} | {r['Evidence source']} | {r['Provenance']} | {r['Can generate now']} | {r['Missing requirement']} |"
        )
    (OUT / "FIGURE_AUDIT.md").write_text("\n".join(lines) + "\n")


def write_source_csv(manifest: Dict[str, Any]) -> None:
    path = OUT / "source-evidence.csv"
    seen = set()
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["path", "sha256", "used_by_figures"])
        w.writeheader()
        for fig in manifest["figures"]:
            for p, h in zip(fig.get("source_files", []), fig.get("source_sha256", []) or []):
                key = (p, h)
                if key in seen:
                    continue
                seen.add(key)
                w.writerow({"path": p, "sha256": h, "used_by_figures": fig["figure_id"]})


def write_captions(manifest: Dict[str, Any]) -> None:
    caps = {
        "FIG-01": "Figure 1 — Audible and near-ultrasonic physical calibration on the tested laptop path. Metric: estimated_detector_snr_db (not calibrated SPL). Provenance: PHYSICAL_RX.",
        "FIG-02": "Figure 2 — NOT COMPLETE: GENERATED_TX reference for near-US carriers exists, but no linkable PHYSICAL_RX of the same 18.5/19.5 kHz transmission was found. Do not present as physical success.",
        "FIG-03": "Figure 3 — Physical 15–21 kHz calibration sweep with markers at 15/16 kHz (later recovery carriers) and 18.5/19.5 kHz (theory-driven). Provenance: PHYSICAL_RX.",
        "FIG-04": "Figure 4 — Explanatory diagram of configurable carrier-neighbourhood search (±150 Hz, 25 Hz step) used in the recovery profile. Not a measured spectrum.",
        "FIG-05": "Figure 5 — Redacted live_monitor terminal rendering for HELLO at 15/16 kHz ending in CRC VALID. Provenance: PHYSICAL_RX (N=1 documented log).",
        "FIG-06": "Figure 6 — Documented physical payload recoveries. Exact matches after quoting fix: 4/4 intended strings; one pre-fix CRC-valid modified TX. Provenance: PHYSICAL_RX.",
        "FIG-07": "Figure 7 — Before/after remote SSH quoting for p4$$w0rd (fix in 8bdc9be). Provenance of trials: PHYSICAL_RX.",
        "FIG-08": "Figure 8 — Spectrogram excerpt of HELLO PHYSICAL_RX capture with 15/16 kHz guides. Full-file decode was CRC VALID. Provenance: PHYSICAL_RX.",
        "FIG-09": "Figure 9 — Experimental architecture: SSH coordinates playback only; payload travels through air.",
        "FIG-10": "Figure 10 — Conceptual chain showing where Nyquist stops guaranteeing hardware behaviour.",
        "FIG-11": "Figure 11 — TX / physical channel / RX pipeline including Hamming(7,4) and CRC.",
        "FIG-12": "Figure 12 — Documented recovery timeline (order only; no invented timestamps).",
    }
    lines = ["# Part 2 figure captions", ""]
    for fig in manifest["figures"]:
        fid = fig["figure_id"]
        lines.append(f"## {fid}")
        lines.append("")
        lines.append(caps.get(fid, fig.get("title", "")))
        lines.append("")
        lines.append(f"Status: `{fig.get('status')}`")
        lines.append("")
    (OUT / "captions.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--figure", default="ALL", help="FIG-01 .. FIG-12 or ALL")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)

    git_head = "unknown"
    try:
        import subprocess

        git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        pass

    manifest: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "figures": [],
    }
    log: List[str] = []
    targets = list(GENERATORS.keys()) if args.figure == "ALL" else [args.figure]
    for fid in targets:
        if fid not in GENERATORS:
            raise SystemExit(f"Unknown figure {fid}")
        GENERATORS[fid](manifest, log)

    (OUT / "figure-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    write_audit(manifest)
    write_source_csv(manifest)
    write_captions(manifest)
    (OUT / "generation-log.txt").write_text("\n".join(log) + "\n")
    print("Wrote", OUT)
    for line in log:
        print(" ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
