#!/usr/bin/env python3
"""PHYSICAL_RX speed probe against remote TX (ACOUSTIC_REMOTE_* env)."""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

from src.modulation import ModulationConfig
from src.protocol import encode_message, estimate_duration
from src.receiver import decode_from_samples


def carriers(tsym: float) -> tuple[float, float]:
    if tsym <= 0.07:
        return 3000.0, 8000.0
    return 3500.0, 7500.0


def main() -> int:
    remote = os.environ["ACOUSTIC_REMOTE_TX"]
    rdir = os.environ["ACOUSTIC_REMOTE_DIR"]
    outdev = int(os.environ.get("ACOUSTIC_REMOTE_OUTPUT_DEVICE", "0"))
    payload = "DEMO_DEMO_334"
    in_dev = 0
    out_dir = Path("output/part3/physical")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Speeds to validate (outdev fixed from env)
    cases = [
        (0.20, 0.40, 2, "HELLO"),
        (0.12, 0.40, 2, "HELLO"),
        (0.07, 0.40, 1, "DEMO_DEMO_334"),
        (0.07, 0.40, 2, "DEMO_DEMO_334"),
    ]
    results = []
    for tsym, amp, reps, msg in cases:
        f0, f1 = carriers(tsym)
        cfg = ModulationConfig(
            sample_rate=48000,
            symbol_duration=tsym,
            frequency_zero=f0,
            frequency_one=f1,
            amplitude=amp,
        )
        air = estimate_duration(
            msg, tsym, repeats=reps, inter_frame_silence=0.25, fec="none"
        )
        listen = air + 6.0
        sr = 48000
        print(
            f"\n--- out={outdev} T={tsym} amp={amp} R={reps} msg={msg!r} "
            f"listen={listen:.1f}s ---",
            flush=True,
        )
        n = int(listen * sr)
        rec = sd.rec(n, samplerate=sr, channels=1, dtype="float32", device=in_dev)
        time.sleep(1.0)
        remote_cmd = (
            f"cd {shlex.quote(rdir)} && . .venv/bin/activate && "
            f"PYTHONPATH=. python -m src.transmitter --message {shlex.quote(msg)} "
            f"--modulation cpfsk --fec none --symbol-duration {tsym} "
            f"--frequency-zero {f0} --frequency-one {f1} "
            f"--amplitude {amp} --repeats {reps} --inter-frame-silence 0.25 "
            f"--output-device {outdev}"
        )
        p = subprocess.Popen(
            ["ssh", remote, remote_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        sd.wait()
        out, err = p.communicate(timeout=180)
        print(
            "ssh",
            p.returncode,
            "finished=",
            ("Transmission finished" in (out or "")),
            flush=True,
        )
        if p.returncode != 0:
            print("ERR", (err or out or "")[-400:], flush=True)
        audio = rec[:, 0].astype(np.float64)
        peak = float(np.max(np.abs(audio)))
        safe = msg.replace("!", "")
        path = out_dir / f"speed_out{outdev}_T{int(tsym * 1000)}_R{reps}_{safe}.wav"
        wavfile.write(str(path), sr, audio.astype(np.float32))
        bits = encode_message(msg, fec="none")
        # Faster decode for probe: skip heavy freq search on first pass
        stats, _, result = decode_from_samples(
            audio,
            cfg,
            min_energy=1e-6,
            min_ratio=1.08,
            expected_bits=bits,
            fec="none",
            sync_mode="correlation",
            apply_bandpass=False,
            frequency_search_hz=0.0,
            symbol_duration_search_percent=2.5,
            symbol_duration_search_steps=5,
            timing_steps=16,
        )
        print(
            f"peak={peak:.3f} success={result.success} msg={stats.recovered_message!r} "
            f"err={result.error} wav={path.name}",
            flush=True,
        )
        results.append(
            {
                "outdev": outdev,
                "tsym": tsym,
                "reps": reps,
                "payload": msg,
                "success": bool(result.success),
                "recovered": stats.recovered_message,
                "error": result.error,
                "peak": peak,
                "wav": str(path),
            }
        )

    print("\nSUMMARY", flush=True)
    for r in results:
        flag = "OK" if r["success"] else "FAIL"
        print(
            f"{flag} T={r['tsym']} R={r['reps']} {r['payload']!r} "
            f"-> {r['recovered']!r} peak={r['peak']:.3f}",
            flush=True,
        )
    return 0 if any(r["success"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
