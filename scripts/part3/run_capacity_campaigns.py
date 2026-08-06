#!/usr/bin/env python3
"""Part 3 capacity campaigns (SIMULATED_RX by default).

Measures trade-offs among Tsym, carrier spacing, modulation, FEC, repeats,
and reports raw rate / goodput / FER / BER — not Shannon capacity.

Usage:
  PYTHONPATH=. python scripts/part3/run_capacity_campaigns.py
  PYTHONPATH=. python scripts/part3/run_capacity_campaigns.py --campaign tsym
  PYTHONPATH=. python scripts/part3/run_capacity_campaigns.py --quick
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.capacity_metrics import (
    airtime_s,
    eval_zlib_compression,
    fer,
    frame_overhead,
    payload_goodput_bps,
    raw_symbol_rate_bps,
    summarize_ber,
)
from src.modulation import ModulationConfig, add_channel_impairments, modulate
from src.protocol import encode_message
from src.provenance import Provenance
from src.receiver import decode_from_samples


OUT = ROOT / "output" / "part3"


@dataclass
class TrialRow:
    campaign: str
    condition_id: str
    trial: int
    payload: str
    modulation: str
    fec: str
    repeats: int
    inter_frame_silence: float
    symbol_duration: float
    frequency_zero: float
    frequency_one: float
    spacing_hz: float
    noise_level: float
    attenuation: float
    success: int
    ber: Optional[float]
    snr_db: Optional[float]
    airtime_s: float
    coded_bits: int
    payload_bytes: int
    sync_fail: int
    crc_fail: int
    decode_cpu_ms: float
    provenance: str


def wilson_ci(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def run_one(
    *,
    campaign: str,
    condition_id: str,
    trial: int,
    payload: str,
    modulation: str,
    fec: str,
    repeats: int,
    inter_frame_silence: float,
    tsym: float,
    f0: float,
    f1: float,
    noise_level: float,
    attenuation: float,
    rng: np.random.Generator,
    timing_offset: Optional[int] = None,
) -> TrialRow:
    cfg = ModulationConfig(
        sample_rate=48000,
        symbol_duration=float(tsym),
        frequency_zero=float(f0),
        frequency_one=float(f1),
        amplitude=0.25,
    )
    bits = encode_message(payload, fec=fec)
    tx = modulate(
        bits,
        cfg,
        modulation=modulation,
        repeats=repeats,
        inter_frame_silence=inter_frame_silence,
    )
    if timing_offset is None:
        timing_offset = int(rng.integers(0, max(1, int(0.002 * cfg.sample_rate))))
    rx = add_channel_impairments(
        tx,
        noise_level=noise_level,
        attenuation=attenuation,
        timing_offset_samples=timing_offset,
        rng=rng,
    )
    t0 = time.perf_counter()
    stats, _, result = decode_from_samples(
        rx,
        cfg,
        min_energy=1e-6,
        min_ratio=1.15,
        expected_bits=bits,
        fec=fec,
        sync_mode="correlation",
        apply_bandpass=False,
        symbol_duration_search_percent=2.5,
        symbol_duration_search_steps=5,
    )
    cpu_ms = (time.perf_counter() - t0) * 1000.0
    ok = bool(result.success and stats.recovered_message == payload)
    err = result.error or ""
    air = airtime_s(
        payload,
        tsym,
        fec=fec,
        repeats=repeats,
        inter_frame_silence=inter_frame_silence,
    )
    return TrialRow(
        campaign=campaign,
        condition_id=condition_id,
        trial=trial,
        payload=payload,
        modulation=modulation,
        fec=fec,
        repeats=repeats,
        inter_frame_silence=inter_frame_silence,
        symbol_duration=tsym,
        frequency_zero=f0,
        frequency_one=f1,
        spacing_hz=abs(f1 - f0),
        noise_level=noise_level,
        attenuation=attenuation,
        success=int(ok),
        ber=stats.bit_error_rate,
        snr_db=stats.snr_estimate_db,
        airtime_s=air,
        coded_bits=len(bits),
        payload_bytes=len(payload.encode("utf-8")),
        sync_fail=int(not ok and ("reamble" in err.lower() or "sync" in err.lower())),
        crc_fail=int(not ok and "CRC" in err),
        decode_cpu_ms=cpu_ms,
        provenance=Provenance.SIMULATED_RX.value,
    )


def summarize(rows: Sequence[TrialRow]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[TrialRow]] = {}
    for r in rows:
        groups.setdefault(r.condition_id, []).append(r)
    out: List[Dict[str, Any]] = []
    for cid, rs in sorted(groups.items()):
        n = len(rs)
        succ = sum(r.success for r in rs)
        air = sum(r.airtime_s for r in rs)
        pb = rs[0].payload_bytes
        lo, hi = wilson_ci(succ, n)
        out.append(
            {
                "condition_id": cid,
                "campaign": rs[0].campaign,
                "n": n,
                "successes": succ,
                "fer": fer(succ, n),
                "frame_success_rate": succ / n if n else 0.0,
                "wilson_lo": lo,
                "wilson_hi": hi,
                "mean_ber": summarize_ber([r.ber for r in rs]),
                "sync_fail": sum(r.sync_fail for r in rs),
                "crc_fail": sum(r.crc_fail for r in rs),
                "payload_goodput_bps": payload_goodput_bps(pb, succ, air),
                "raw_symbol_rate_bps": raw_symbol_rate_bps(rs[0].symbol_duration),
                "mean_airtime_s": air / n if n else 0.0,
                "mean_decode_cpu_ms": float(np.mean([r.decode_cpu_ms for r in rs])),
                "modulation": rs[0].modulation,
                "fec": rs[0].fec,
                "repeats": rs[0].repeats,
                "symbol_duration": rs[0].symbol_duration,
                "frequency_zero": rs[0].frequency_zero,
                "frequency_one": rs[0].frequency_one,
                "spacing_hz": rs[0].spacing_hz,
                "noise_level": rs[0].noise_level,
                "attenuation": rs[0].attenuation,
                "payload": rs[0].payload,
                "provenance": rs[0].provenance,
            }
        )
    return out


def campaign_cliff(rng: np.random.Generator, trials: int, quick: bool) -> List[TrialRow]:
    """Find the Tsym cliff under harsher simulated impairments.

    Hypothesis: goodput peaks at intermediate Tsym once FER rises at short symbols.
    Tuned so mild AWGN+attenuation can break short symbols (validated probe).
    """
    rows: List[TrialRow] = []
    tsyms = [0.12, 0.08, 0.07, 0.05, 0.04, 0.03, 0.02] if not quick else [0.07, 0.04, 0.02]
    # SNR-ish grid where short Tsym fails while longer may survive
    impairments = [
        (0.05, 0.10),
        (0.10, 0.10),
        (0.20, 0.20),
    ]
    if quick:
        impairments = [(0.10, 0.10)]
    for tsym in tsyms:
        for noise, att in impairments:
            cid = f"cliff_T{tsym:.3f}_N{noise:.2f}_A{att:.2f}"
            for t in range(trials):
                rows.append(
                    run_one(
                        campaign="cliff",
                        condition_id=cid,
                        trial=t,
                        payload="HELLO",
                        modulation="cpfsk",
                        fec="none",
                        repeats=1,
                        inter_frame_silence=0.0,
                        tsym=tsym,
                        f0=3000.0,
                        f1=8000.0,
                        noise_level=noise,
                        attenuation=att,
                        rng=rng,
                    )
                )
    return rows


def campaign_tsym(rng: np.random.Generator, trials: int, quick: bool) -> List[TrialRow]:
    """Hypothesis: shorter Tsym raises raw rate until FER collapses goodput."""
    rows: List[TrialRow] = []
    tsyms = [0.20, 0.12, 0.08, 0.07, 0.05, 0.04, 0.03] if not quick else [0.12, 0.07, 0.04]
    noises = [0.002, 0.008] if not quick else [0.005]
    payload = "HELLO"
    for tsym in tsyms:
        for noise in noises:
            cid = f"tsym_T{tsym:.3f}_N{noise:.3f}_cpfsk_none_r1"
            for t in range(trials):
                rows.append(
                    run_one(
                        campaign="tsym",
                        condition_id=cid,
                        trial=t,
                        payload=payload,
                        modulation="cpfsk",
                        fec="none",
                        repeats=1,
                        inter_frame_silence=0.0,
                        tsym=tsym,
                        f0=3000.0,
                        f1=8000.0,
                        noise_level=noise,
                        attenuation=0.6,
                        rng=rng,
                    )
                )
    return rows


def campaign_spacing(rng: np.random.Generator, trials: int, quick: bool) -> List[TrialRow]:
    """Hypothesis: wider spacing improves discrimination until mic response hurts."""
    rows: List[TrialRow] = []
    # Keep geometric mean ~sqrt(f0*f1) near audible demo band
    pairs = [
        (4000, 5000),
        (3500, 5500),
        (3000, 6000),
        (3000, 8000),
        (2500, 9000),
        (2000, 10000),
    ]
    if quick:
        pairs = [(4000, 5000), (3000, 8000), (2000, 10000)]
    for f0, f1 in pairs:
        cid = f"spacing_{int(f0)}_{int(f1)}_T0.07"
        for t in range(trials):
            rows.append(
                run_one(
                    campaign="spacing",
                    condition_id=cid,
                    trial=t,
                    payload="HELLO",
                    modulation="cpfsk",
                    fec="none",
                    repeats=1,
                    inter_frame_silence=0.0,
                    tsym=0.07,
                    f0=f0,
                    f1=f1,
                    noise_level=0.005,
                    attenuation=0.55,
                    rng=rng,
                )
            )
    return rows


def campaign_modulation(rng: np.random.Generator, trials: int, quick: bool) -> List[TrialRow]:
    rows: List[TrialRow] = []
    mods = ["bfsk", "cpfsk"]
    tsyms = [0.12, 0.07, 0.04] if not quick else [0.07]
    for mod in mods:
        for tsym in tsyms:
            cid = f"mod_{mod}_T{tsym:.3f}"
            for t in range(trials):
                rows.append(
                    run_one(
                        campaign="modulation",
                        condition_id=cid,
                        trial=t,
                        payload="HELLO",
                        modulation=mod,
                        fec="none",
                        repeats=1,
                        inter_frame_silence=0.0,
                        tsym=tsym,
                        f0=3000.0,
                        f1=8000.0,
                        noise_level=0.006,
                        attenuation=0.55,
                        rng=rng,
                    )
                )
    return rows


def campaign_redundancy(rng: np.random.Generator, trials: int, quick: bool) -> List[TrialRow]:
    """Compare FEC vs repeats vs neither at a stressed operating point."""
    rows: List[TrialRow] = []
    configs = [
        ("none", 1, 0.0),
        ("hamming74", 1, 0.0),
        ("none", 2, 0.25),
        ("hamming74", 2, 0.25),
    ]
    tsym = 0.05 if not quick else 0.05
    noise = 0.012  # stressed
    for fec, reps, silence in configs:
        cid = f"redundancy_{fec}_r{reps}_s{silence:.2f}"
        for t in range(trials):
            rows.append(
                run_one(
                    campaign="redundancy",
                    condition_id=cid,
                    trial=t,
                    payload="HELLO",
                    modulation="cpfsk",
                    fec=fec,
                    repeats=reps,
                    inter_frame_silence=silence,
                    tsym=tsym,
                    f0=3000.0,
                    f1=8000.0,
                    noise_level=noise,
                    attenuation=0.45,
                    rng=rng,
                )
            )
    return rows


def campaign_overhead_analytic() -> List[Dict[str, Any]]:
    payloads = {
        "short_text": "HELLO",
        "email_like": "user@domain.tld",
        "json_like": '{"k":1,"v":2}',
        "repetitive": "AAAAAAAABBBBBBBB",
        "maxish": "X" * 32,
    }
    rows = []
    for label, payload in payloads.items():
        for fec in ("none", "hamming74"):
            oh = frame_overhead(payload, fec=fec)
            for tsym in (0.25, 0.12, 0.07, 0.04):
                for reps, silence in ((1, 0.0), (2, 0.25)):
                    air = airtime_s(
                        payload,
                        tsym,
                        fec=fec,
                        repeats=reps,
                        inter_frame_silence=silence,
                    )
                    rows.append(
                        {
                            "label": label,
                            "payload": payload,
                            "fec": fec,
                            "symbol_duration": tsym,
                            "repeats": reps,
                            "inter_frame_silence": silence,
                            "payload_bytes": oh.payload_bytes,
                            "coded_bits": oh.coded_bits,
                            "overhead_fraction": oh.overhead_fraction,
                            "coding_expansion": oh.coding_expansion,
                            "airtime_s_if_success": air,
                            "ideal_goodput_bps_if_success": (8 * oh.payload_bytes) / air,
                            "raw_symbol_rate_bps": raw_symbol_rate_bps(tsym),
                        }
                    )
    return rows


def campaign_compression() -> List[Dict[str, Any]]:
    samples = {
        "short_text": b"HELLO",
        "json": b'{"user":"demo","host":"lab","ok":true}',
        "random": bytes(range(32)),
        "repetitive": b"A" * 32,
        "email": b"user@domain.tld",
    }
    return [asdict(eval_zlib_compression(k, v)) for k, v in samples.items()]


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def pick_best_candidate(summaries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Maximize goodput subject to FER <= 0.2 among simulated conditions."""
    eligible = [s for s in summaries if s["fer"] <= 0.2 and s["n"] >= 3]
    if not eligible:
        eligible = list(summaries)
    best = max(eligible, key=lambda s: s["payload_goodput_bps"])
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--campaign",
        default="all",
        choices=["all", "tsym", "spacing", "modulation", "redundancy", "cliff", "overhead", "compression"],
    )
    ap.add_argument("--trials", type=int, default=12)
    ap.add_argument("--quick", action="store_true", help="Fewer conditions for smoke runs")
    ap.add_argument("--seed", type=int, default=20260806)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    trials = 5 if args.quick else args.trials

    started = datetime.now(timezone.utc).isoformat()
    all_trials: List[TrialRow] = []
    analytic: Dict[str, Any] = {}

    if args.campaign in ("all", "tsym"):
        all_trials.extend(campaign_tsym(rng, trials, args.quick))
    if args.campaign in ("all", "cliff"):
        all_trials.extend(campaign_cliff(rng, trials, args.quick))
    if args.campaign in ("all", "spacing"):
        all_trials.extend(campaign_spacing(rng, trials, args.quick))
    if args.campaign in ("all", "modulation"):
        all_trials.extend(campaign_modulation(rng, trials, args.quick))
    if args.campaign in ("all", "redundancy"):
        all_trials.extend(campaign_redundancy(rng, trials, args.quick))
    if args.campaign in ("all", "overhead"):
        analytic["overhead"] = campaign_overhead_analytic()
        write_csv(out / "overhead_analysis.csv", analytic["overhead"])
    if args.campaign in ("all", "compression"):
        analytic["compression"] = campaign_compression()
        write_csv(out / "compression_eval.csv", analytic["compression"])

    trial_dicts = [asdict(r) for r in all_trials]
    if trial_dicts:
        write_csv(out / "all_trials.csv", trial_dicts)
        summaries = summarize(all_trials)
        write_csv(out / "condition_summary.csv", summaries)
        best = pick_best_candidate(summaries)
        (out / "best_candidate_sim.json").write_text(json.dumps(best, indent=2) + "\n")
    else:
        summaries = []
        best = {}

    # Always write overhead/compression if all
    if args.campaign == "all":
        if "overhead" not in analytic:
            analytic["overhead"] = campaign_overhead_analytic()
            write_csv(out / "overhead_analysis.csv", analytic["overhead"])
        if "compression" not in analytic:
            analytic["compression"] = campaign_compression()
            write_csv(out / "compression_eval.csv", analytic["compression"])

    manifest = {
        "generated_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "quick": args.quick,
        "trials_per_condition": trials,
        "provenance": Provenance.SIMULATED_RX.value,
        "n_trials": len(all_trials),
        "n_conditions": len(summaries),
        "best_candidate_sim": best,
        "note": (
            "SIMULATED_RX only. Do not present as PHYSICAL_RX capacity. "
            "Physical validation requires a separate campaign with stated N."
        ),
    }
    (out / "campaign_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"n_trials": len(all_trials), "best": best}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
