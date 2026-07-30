#!/usr/bin/env python3
"""Two-process live reliability benchmark (speaker + microphone)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from src.modulation import ModulationConfig
from src.protocol import encode_message, estimate_duration
from src.receiver import decode_from_samples

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = [
    "DEMO-LAB-2027",
    "HELLO",
    "OK",
    "TEST-01",
    "ABC123",
    "PING",
]
# Live benchmark defaults that matched the successful ~67% run
SYMBOL = 0.12
REPEATS = 2
AMP = 0.28
INPUT_DEV = "0"
OUTPUT_DEV = "0"
FREQ_ZERO = "3500"
FREQ_ONE = "7500"


def main() -> int:
    results = []
    for msg in MESSAGES:
        dur = (
            estimate_duration(
                msg, SYMBOL, repeats=REPEATS, inter_frame_silence=0.4
            )
            + 4.0
        )
        safe = msg.replace("-", "_")
        raw_path = ROOT / "output" / f"tp_{safe}.wav"
        rx_cmd = [
            sys.executable,
            "-m",
            "src.receiver",
            "--input-device",
            INPUT_DEV,
            "--duration",
            f"{dur:.2f}",
            "--symbol-duration",
            str(SYMBOL),
            "--frequency-zero",
            FREQ_ZERO,
            "--frequency-one",
            FREQ_ONE,
            "--min-ratio",
            "1.15",
            "--amplitude",
            str(AMP),
            "--save-raw-wav",
            str(raw_path),
        ]
        tx_cmd = [
            sys.executable,
            "-m",
            "src.transmitter",
            "--message",
            msg,
            "--output-device",
            OUTPUT_DEV,
            "--symbol-duration",
            str(SYMBOL),
            "--frequency-zero",
            FREQ_ZERO,
            "--frequency-one",
            FREQ_ONE,
            "--amplitude",
            str(AMP),
            "--repeats",
            str(REPEATS),
            "--inter-frame-silence",
            "0.4",
        ]
        print(f"\n>>> {msg!r}  record {dur:.1f}s", flush=True)
        rx = subprocess.Popen(
            rx_cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(2.5)
        tx = subprocess.run(tx_cmd, cwd=ROOT, capture_output=True, text=True)
        if tx.returncode != 0:
            print(f"  TX failed: {tx.stderr or tx.stdout}", flush=True)
        try:
            rx.communicate(timeout=dur + 45)
        except subprocess.TimeoutExpired:
            rx.kill()
            rx.communicate()

        cfg = ModulationConfig(
            symbol_duration=SYMBOL,
            frequency_zero=float(FREQ_ZERO),
            frequency_one=float(FREQ_ONE),
            amplitude=AMP,
        )
        ok = False
        recovered = None
        ber = None
        err = "no wav"
        if raw_path.exists():
            _sr, raw = wavfile.read(str(raw_path))
            x = np.asarray(raw, dtype=np.float64)
            if x.ndim > 1:
                x = x.mean(axis=1)
            exp = encode_message(msg)
            st, _, r = decode_from_samples(
                x,
                cfg,
                min_energy=1e-6,
                min_ratio=1.15,
                expected_bits=exp,
            )
            ok = bool(r.success and st.recovered_message == msg)
            recovered = st.recovered_message
            ber = st.bit_error_rate
            err = None if ok else r.error
            print(
                f"  peak={float(np.max(np.abs(x))):.3f} "
                f"clip={st.clipping} off={st.timing_offset_samples} "
                f"snr={st.snr_estimate_db}",
                flush=True,
            )
        mark = "OK" if ok else "FAIL"
        ber_s = f"{ber:.3f}" if ber is not None else "—"
        print(
            f"  [{mark}] {msg!r} → {recovered!r}  BER={ber_s}  {err or ''}",
            flush=True,
        )
        results.append((msg, ok, recovered, ber, err))

    n = len(results)
    n_ok = sum(1 for r in results if r[1])
    bers = [r[3] for r in results if r[3] is not None]
    mean_ber = float(np.mean(bers)) if bers else float("nan")
    pct = 100.0 * n_ok / n if n else 0.0
    print("\n==== SUMMARY ====", flush=True)
    print(f"frames OK: {n_ok}/{n} ({pct:.1f}%)", flush=True)
    print(f"mean BER: {mean_ber:.4f}", flush=True)
    print(f"payload delivery: {pct:.1f}%", flush=True)
    for msg, ok, recovered, ber, err in results:
        status = "YES" if ok else "NO "
        print(
            f"  {status}  {msg:15}  ber={ber}  {recovered or err}",
            flush=True,
        )
    return 0 if n_ok == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
