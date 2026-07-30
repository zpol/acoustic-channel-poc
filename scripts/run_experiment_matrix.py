#!/usr/bin/env python3
"""Run a simulated (or physical) experiment matrix and write benchmark plots."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.modulation import ModulationConfig, add_channel_impairments, modulate
from src.protocol import encode_message
from src.provenance import Provenance
from src.receiver import decode_from_samples


DEFAULT_MATRIX = {
    "payloads": ["HELLO", "DEMO-2027"],
    "modulations": ["bfsk", "cpfsk"],
    "fec_modes": ["none", "hamming74"],
    "symbol_durations": [0.20, 0.15, 0.12],
    "distances_cm": [20, 50, 100],
    "trials_per_condition": 10,
}


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def atten_for_distance(cm: float) -> float:
    # Crude free-field-ish roll-off for simulation only
    return float(np.clip(30.0 / max(cm, 1.0), 0.05, 1.0))


def run_matrix(cfg: Dict[str, Any], out_dir: Path, seed: int = 0) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[dict] = []
    rng = np.random.default_rng(seed)
    trial_id = 0
    for payload in cfg["payloads"]:
        for mod in cfg["modulations"]:
            for fec in cfg["fec_modes"]:
                for tsym in cfg["symbol_durations"]:
                    for dist in cfg["distances_cm"]:
                        for t in range(cfg["trials_per_condition"]):
                            trial_id += 1
                            mcfg = ModulationConfig(
                                symbol_duration=float(tsym),
                                frequency_zero=3500.0,
                                frequency_one=7500.0,
                                amplitude=0.2,
                            )
                            bits = encode_message(payload, fec=fec)
                            tx = modulate(bits, mcfg, modulation=mod, repeats=1)
                            rx = add_channel_impairments(
                                tx,
                                noise_level=0.003 + 0.00002 * dist,
                                attenuation=atten_for_distance(dist),
                                timing_offset_samples=int(rng.integers(0, 400)),
                                rng=rng,
                            )
                            stats, _, result = decode_from_samples(
                                rx,
                                mcfg,
                                min_energy=1e-6,
                                min_ratio=1.2,
                                expected_bits=bits,
                                fec=fec,
                                sync_mode="correlation",
                            )
                            ok = bool(result.success and stats.recovered_message == payload)
                            rows.append(
                                {
                                    "trial_id": trial_id,
                                    "payload": payload,
                                    "modulation": mod,
                                    "fec": fec,
                                    "symbol_duration": tsym,
                                    "distance_cm": dist,
                                    "success": int(ok),
                                    "ber": stats.bit_error_rate,
                                    "crc_fail": int(not ok and (result.error or "").startswith("CRC")),
                                    "sync_fail": int(not ok and "Preamble" in (result.error or "")),
                                    "fec_corrected": result.fec_corrected_bits,
                                    "snr_db": stats.snr_estimate_db,
                                    "clipping": int(stats.clipping),
                                    "confidence": stats.mean_confidence,
                                    "provenance": Provenance.SIMULATED_RX.value,
                                }
                            )

    # Write all-trials.csv
    fieldnames = list(rows[0].keys()) if rows else []
    with (out_dir / "all-trials.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # Condition summary
    conditions: Dict[tuple, List[dict]] = {}
    for r in rows:
        key = (r["modulation"], r["fec"], r["symbol_duration"], r["distance_cm"], r["payload"])
        conditions.setdefault(key, []).append(r)
    summaries = []
    for key, group in conditions.items():
        n = len(group)
        ok = sum(r["success"] for r in group)
        lo, hi = wilson_ci(ok, n)
        bers = [r["ber"] for r in group if r["ber"] is not None]
        summaries.append(
            {
                "modulation": key[0],
                "fec": key[1],
                "symbol_duration": key[2],
                "distance_cm": key[3],
                "payload": key[4],
                "n": n,
                "successes": ok,
                "success_rate": ok / n,
                "ci_low": lo,
                "ci_high": hi,
                "mean_ber": float(np.mean(bers)) if bers else None,
                "sync_failures": sum(r["sync_fail"] for r in group),
                "crc_failures": sum(r["crc_fail"] for r in group),
                "mean_snr_db": float(np.nanmean([r["snr_db"] for r in group if r["snr_db"] is not None])),
            }
        )
    with (out_dir / "condition-summary.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summaries[0].keys()))
        w.writeheader()
        w.writerows(summaries)
    (out_dir / "condition-summary.json").write_text(json.dumps(summaries, indent=2))

    # Plots
    def _agg(field: str, value_key: str = "success_rate"):
        vals: Dict[Any, List[float]] = {}
        for s in summaries:
            vals.setdefault(s[field], []).append(s[value_key])
        xs = sorted(vals.keys(), key=lambda x: (str(type(x)), x))
        ys = [float(np.mean(vals[x])) for x in xs]
        return xs, ys

    fig, ax = plt.subplots()
    xs, ys = _agg("distance_cm")
    ax.plot(xs, ys, marker="o")
    ax.set_ylim(0, 1.05)
    ax.set_title("Success by distance (SIMULATED_RX)")
    ax.set_xlabel("distance_cm")
    ax.set_ylabel("mean success_rate")
    fig.tight_layout()
    fig.savefig(out_dir / "success-by-distance.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots()
    xs, ys = _agg("symbol_duration")
    ax.plot(xs, ys, marker="o")
    ax.set_ylim(0, 1.05)
    ax.set_title("Success by symbol duration (SIMULATED_RX)")
    fig.tight_layout()
    fig.savefig(out_dir / "success-by-symbol-duration.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots()
    for mod in cfg["modulations"]:
        xs, ys = [], []
        for s in summaries:
            if s["modulation"] == mod:
                xs.append(s["distance_cm"])
                ys.append(s["mean_ber"] or 0)
        if xs:
            ax.scatter(xs, ys, label=mod, alpha=0.6)
    ax.set_title("BER by mode (SIMULATED_RX)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "ber-by-mode.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots()
    ax.scatter(
        [s["mean_snr_db"] for s in summaries],
        [s["success_rate"] for s in summaries],
        alpha=0.6,
    )
    ax.set_title("SNR vs success (SIMULATED_RX)")
    ax.set_xlabel("mean estimated detector SNR dB")
    ax.set_ylabel("success_rate")
    fig.tight_layout()
    fig.savefig(out_dir / "snr-vs-success.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots()
    for mod in cfg["modulations"]:
        rate = np.mean([s["success_rate"] for s in summaries if s["modulation"] == mod])
        ax.bar(mod, rate)
    ax.set_ylim(0, 1.05)
    ax.set_title("BFSK vs CPFSK (SIMULATED_RX)")
    fig.tight_layout()
    fig.savefig(out_dir / "bfsk-vs-cpfsk.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots()
    for fec in cfg["fec_modes"]:
        rate = np.mean([s["success_rate"] for s in summaries if s["fec"] == fec])
        ax.bar(fec, rate)
    ax.set_ylim(0, 1.05)
    ax.set_title("FEC comparison (SIMULATED_RX)")
    fig.tight_layout()
    fig.savefig(out_dir / "fec-comparison.png", dpi=120)
    plt.close(fig)

    overall = sum(r["success"] for r in rows) / max(1, len(rows))
    report = [
        "# Benchmark matrix report\n\n",
        f"Provenance: **{Provenance.SIMULATED_RX.value}**\n\n",
        f"Trials: {len(rows)}\n\n",
        f"Overall success rate: {100 * overall:.1f}%\n\n",
        "Failed trials are retained in `all-trials.csv`.\n",
    ]
    (out_dir / "report.md").write_text("".join(report))
    print(f"Wrote {out_dir} overall_success={overall:.3f}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config-json", type=Path, default=None)
    p.add_argument("--out-dir", type=Path, default=Path("output/benchmark"))
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    cfg = DEFAULT_MATRIX
    if args.config_json and args.config_json.exists():
        cfg = json.loads(args.config_json.read_text())
    run_matrix(cfg, args.out_dir, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
