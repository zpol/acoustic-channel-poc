#!/usr/bin/env python3
"""Generate Part 3 publication figures from capacity campaign CSVs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "part3"
FIG = OUT / "figures"

BG = "#ffffff"
FG = "#1a1a1a"
C1 = "#2a6f97"
C2 = "#bc4749"
C3 = "#2a9d8f"
GRID = "#dddddd"


def load_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open() as fh:
        return list(csv.DictReader(fh))


def fnum(row: Dict[str, Any], key: str) -> float:
    return float(row[key])


def save(fig: plt.Figure, stem: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{stem}.png", dpi=160, bbox_inches="tight", facecolor=BG)
    fig.savefig(FIG / f"{stem}.svg", bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def style(ax: plt.Axes) -> None:
    ax.set_facecolor(BG)
    ax.grid(True, color=GRID, lw=0.6)
    ax.tick_params(colors=FG)
    for s in ax.spines.values():
        s.set_color(FG)


def fig_tsym(summary: List[Dict[str, Any]]) -> None:
    rows = [r for r in summary if r["campaign"] == "tsym"]
    # Prefer one noise level for clarity: use most common
    if not rows:
        return
    noises = sorted({fnum(r, "noise_level") for r in rows})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    fig.patch.set_facecolor(BG)
    for i, noise in enumerate(noises):
        sub = [r for r in rows if abs(fnum(r, "noise_level") - noise) < 1e-12]
        sub = sorted(sub, key=lambda r: fnum(r, "symbol_duration"))
        xs = [fnum(r, "symbol_duration") * 1000 for r in sub]
        axes[0].plot(xs, [fnum(r, "fer") for r in sub], "o-", color=C1 if i == 0 else C2, label=f"noise={noise}")
        axes[1].plot(
            xs,
            [fnum(r, "payload_goodput_bps") for r in sub],
            "s-",
            color=C1 if i == 0 else C2,
            label=f"noise={noise}",
        )
    axes[0].set_xlabel("Symbol duration (ms)")
    axes[0].set_ylabel("FER")
    axes[0].set_title("Frame error vs Tsym")
    axes[1].set_xlabel("Symbol duration (ms)")
    axes[1].set_ylabel("Payload goodput (bit/s)")
    axes[1].set_title("Goodput vs Tsym (successes account for airtime)")
    for ax in axes:
        style(ax)
        ax.legend(fontsize=8)
        ax.text(0.99, 0.02, "SIMULATED_RX", transform=ax.transAxes, ha="right", fontsize=8, color="#555")
    fig.suptitle("Part 3 — Symbol duration trade-off (mild impairment)", color=FG)
    fig.tight_layout()
    save(fig, "fig-tsym-fer-goodput")


def fig_cliff(summary: List[Dict[str, Any]]) -> None:
    rows = [r for r in summary if r["campaign"] == "cliff"]
    if not rows:
        return
    noises = sorted({fnum(r, "noise_level") for r in rows})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    fig.patch.set_facecolor(BG)
    for i, noise in enumerate(noises):
        sub = sorted(
            [r for r in rows if abs(fnum(r, "noise_level") - noise) < 1e-12],
            key=lambda r: fnum(r, "symbol_duration"),
        )
        xs = [fnum(r, "symbol_duration") * 1000 for r in sub]
        axes[0].plot(xs, [fnum(r, "fer") for r in sub], "o-", color=C1 if i == 0 else C2, label=f"noise={noise}")
        axes[1].plot(
            xs,
            [fnum(r, "payload_goodput_bps") for r in sub],
            "s-",
            color=C1 if i == 0 else C2,
            label=f"noise={noise}",
        )
    axes[0].set_xlabel("Symbol duration (ms)")
    axes[0].set_ylabel("FER")
    axes[0].set_title("FER cliff under harsh sim noise")
    axes[1].set_xlabel("Symbol duration (ms)")
    axes[1].set_ylabel("Payload goodput (bit/s)")
    axes[1].set_title("Goodput peak vs cliff (SIMULATED_RX)")
    for ax in axes:
        style(ax)
        ax.legend(fontsize=8)
        ax.text(0.99, 0.02, "SIMULATED_RX", transform=ax.transAxes, ha="right", fontsize=8, color="#555")
    fig.suptitle("Part 3 — Capacity cliff (harsh impairment model)", color=FG)
    fig.tight_layout()
    save(fig, "fig-cliff-fer-goodput")


def fig_spacing(summary: List[Dict[str, Any]]) -> None:
    rows = sorted(
        [r for r in summary if r["campaign"] == "spacing"],
        key=lambda r: fnum(r, "spacing_hz"),
    )
    if not rows:
        return
    xs = [fnum(r, "spacing_hz") for r in rows]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))
    fig.patch.set_facecolor(BG)
    axes[0].plot(xs, [fnum(r, "fer") for r in rows], "o-", color=C1)
    axes[1].plot(xs, [fnum(r, "payload_goodput_bps") for r in rows], "s-", color=C3)
    axes[0].set_xlabel("Carrier spacing (Hz)")
    axes[0].set_ylabel("FER")
    axes[1].set_xlabel("Carrier spacing (Hz)")
    axes[1].set_ylabel("Payload goodput (bit/s)")
    for ax, title in zip(axes, ["FER vs spacing", "Goodput vs spacing"]):
        ax.set_title(title)
        style(ax)
        ax.text(0.99, 0.02, "SIMULATED_RX", transform=ax.transAxes, ha="right", fontsize=8, color="#555")
    fig.suptitle("Part 3 — Carrier spacing (Tsym=70 ms, CPFSK)", color=FG)
    fig.tight_layout()
    save(fig, "fig-spacing-fer-goodput")


def fig_modulation(summary: List[Dict[str, Any]]) -> None:
    rows = [r for r in summary if r["campaign"] == "modulation"]
    if not rows:
        return
    mods = sorted({r["modulation"] for r in rows})
    tsyms = sorted({fnum(r, "symbol_duration") for r in rows})
    x = np.arange(len(tsyms))
    width = 0.35
    fig, ax = plt.subplots(figsize=(10, 4.2))
    fig.patch.set_facecolor(BG)
    for i, mod in enumerate(mods):
        ys = []
        for t in tsyms:
            match = [r for r in rows if r["modulation"] == mod and abs(fnum(r, "symbol_duration") - t) < 1e-12]
            ys.append(fnum(match[0], "payload_goodput_bps") if match else 0.0)
        ax.bar(x + (i - 0.5) * width, ys, width, label=mod, color=C1 if i == 0 else C2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t*1000:.0f} ms" for t in tsyms])
    ax.set_ylabel("Payload goodput (bit/s)")
    ax.set_title("BFSK vs CPFSK goodput (SIMULATED_RX)")
    ax.legend()
    style(ax)
    fig.tight_layout()
    save(fig, "fig-modulation-goodput")


def fig_redundancy(summary: List[Dict[str, Any]]) -> None:
    rows = [r for r in summary if r["campaign"] == "redundancy"]
    if not rows:
        return
    labels = [r["condition_id"].replace("redundancy_", "") for r in rows]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    fig.patch.set_facecolor(BG)
    axes[0].bar(range(len(rows)), [fnum(r, "fer") for r in rows], color=C2)
    axes[1].bar(range(len(rows)), [fnum(r, "payload_goodput_bps") for r in rows], color=C3)
    for ax, ylabel, title in zip(
        axes,
        ["FER", "Payload goodput (bit/s)"],
        ["FER under stressed noise", "Goodput under stressed noise"],
    ):
        ax.set_xticks(range(len(rows)))
        ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        style(ax)
        ax.text(0.99, 0.02, "SIMULATED_RX", transform=ax.transAxes, ha="right", fontsize=8, color="#555")
    fig.suptitle("Part 3 — FEC vs repeats (stressed channel)", color=FG)
    fig.tight_layout()
    save(fig, "fig-redundancy-fer-goodput")


def fig_overhead(path: Path) -> None:
    rows = [r for r in load_csv(path) if r["label"] == "short_text" and r["fec"] == "none" and r["repeats"] == "1"]
    if not rows:
        return
    rows = sorted(rows, key=lambda r: float(r["symbol_duration"]))
    fig, ax = plt.subplots(figsize=(9, 4.0))
    fig.patch.set_facecolor(BG)
    xs = [float(r["symbol_duration"]) * 1000 for r in rows]
    ax.plot(xs, [float(r["raw_symbol_rate_bps"]) for r in rows], "o--", color=C1, label="raw symbol rate (1/Tsym)")
    ax.plot(xs, [float(r["ideal_goodput_bps_if_success"]) for r in rows], "s-", color=C3, label="ideal payload goodput if CRC OK")
    ax.set_xlabel("Symbol duration (ms)")
    ax.set_ylabel("bit/s")
    ax.set_title("Protocol overhead: raw rate vs payload goodput (HELLO, FEC none, R=1)")
    ax.legend(fontsize=8)
    style(ax)
    ax.text(0.99, 0.02, "Analytic (no channel)", transform=ax.transAxes, ha="right", fontsize=8, color="#555")
    fig.tight_layout()
    save(fig, "fig-overhead-raw-vs-goodput")


def fig_pipeline() -> None:
    stages = [
        "Payload",
        "Frame+CRC",
        "Optional FEC",
        "CPFSK/BFSK",
        "Airtime\n(+repeats)",
        "Mic / sim",
        "Sync+demod",
        "CRC decision",
        "Goodput",
    ]
    fig, ax = plt.subplots(figsize=(12, 2.8))
    fig.patch.set_facecolor(BG)
    ax.set_xlim(0, len(stages))
    ax.set_ylim(0, 1)
    ax.axis("off")
    for i, name in enumerate(stages):
        ax.add_patch(
            plt.matplotlib.patches.FancyBboxPatch(
                (i + 0.08, 0.35),
                0.84,
                0.35,
                boxstyle="round,pad=0.02",
                facecolor="#f4f7fa",
                edgecolor=C1,
                lw=1.4,
            )
        )
        ax.text(i + 0.5, 0.52, name, ha="center", va="center", fontsize=8, color=FG)
        if i < len(stages) - 1:
            ax.annotate("", xy=(i + 1.05, 0.52), xytext=(i + 0.92, 0.52), arrowprops=dict(arrowstyle="->", color=FG))
    ax.set_title("Part 3 measurement pipeline (goodput accounts for failures + airtime)", color=FG)
    fig.tight_layout()
    save(fig, "fig-capacity-pipeline")


def main() -> int:
    summary = load_csv(OUT / "condition_summary.csv")
    fig_tsym(summary)
    fig_cliff(summary)
    fig_spacing(summary)
    fig_modulation(summary)
    fig_redundancy(summary)
    fig_overhead(OUT / "overhead_analysis.csv")
    fig_pipeline()
    captions = {
        "fig-tsym-fer-goodput": "FER and payload goodput vs symbol duration under mild simulated impairment (SIMULATED_RX).",
        "fig-cliff-fer-goodput": "Harsh-impairment cliff: FER rises and goodput collapses at short Tsym (SIMULATED_RX).",
        "fig-spacing-fer-goodput": "Carrier spacing sweep at 70 ms CPFSK (SIMULATED_RX).",
        "fig-modulation-goodput": "BFSK vs CPFSK goodput comparison (SIMULATED_RX).",
        "fig-redundancy-fer-goodput": "FEC vs frame repeats under stressed noise (SIMULATED_RX).",
        "fig-overhead-raw-vs-goodput": "Analytic overhead: 1/Tsym vs payload goodput for HELLO.",
        "fig-capacity-pipeline": "Measurement pipeline for Part 3 capacity metrics.",
    }
    (OUT / "captions.md").write_text(
        "# Part 3 figure captions\n\n"
        + "\n".join(f"## {k}\n\n{v}\n" for k, v in captions.items())
        + "\nProvenance: SIMULATED_RX unless marked Analytic.\n"
    )
    print("Wrote figures to", FIG)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
