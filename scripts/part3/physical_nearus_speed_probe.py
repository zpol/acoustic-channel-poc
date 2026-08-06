#!/usr/bin/env python3
"""Near-US PHYSICAL_RX speed cliff probe (15/16 kHz)."""
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


def main() -> int:
    remote = os.environ["ACOUSTIC_REMOTE_TX"]
    rdir = os.environ["ACOUSTIC_REMOTE_DIR"]
    outdev = int(os.environ.get("ACOUSTIC_REMOTE_OUTPUT_DEVICE", "0"))
    in_dev = 0
    out_dir = Path("output/part3/physical")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fast → slower insurance. HELLO keeps airtime manageable.
    cases = [
        # tsym, fec, reps, amp, msg
        (0.12, "none", 1, 0.30, "HELLO"),
        (0.15, "none", 1, 0.30, "HELLO"),
        (0.15, "hamming74", 1, 0.30, "HELLO"),
        (0.20, "none", 1, 0.30, "HELLO"),
        (0.20, "hamming74", 1, 0.30, "HELLO"),
        (0.25, "hamming74", 1, 0.30, "HELLO"),  # recovery-like but R=1
        (0.25, "hamming74", 2, 0.30, "HELLO"),  # known-good baseline
    ]
    results = []
    for tsym, fec, reps, amp, msg in cases:
        f0, f1 = 15000.0, 16000.0
        cfg = ModulationConfig(
            sample_rate=48000,
            symbol_duration=tsym,
            frequency_zero=f0,
            frequency_one=f1,
            amplitude=amp,
        )
        air = estimate_duration(
            msg, tsym, repeats=reps, inter_frame_silence=0.25, fec=fec
        )
        listen = air + 8.0
        print(
            f"\n--- NEAR-US T={tsym} fec={fec} R={reps} air≈{air:.1f}s "
            f"listen={listen:.1f}s ---",
            flush=True,
        )
        n = int(listen * 48000)
        rec = sd.rec(n, samplerate=48000, channels=1, dtype="float32", device=in_dev)
        time.sleep(1.2)
        remote_cmd = (
            f"cd {shlex.quote(rdir)} && . .venv/bin/activate && "
            f"PYTHONPATH=. python -m src.transmitter --message {shlex.quote(msg)} "
            f"--modulation cpfsk --fec {fec} --symbol-duration {tsym} "
            f"--frequency-zero {f0} --frequency-one {f1} "
            f"--amplitude {amp} --repeats {reps} --inter-frame-silence 0.25 "
            f"--output-device {outdev} --near-ultrasonic"
        )
        p = subprocess.Popen(
            ["ssh", remote, remote_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        sd.wait()
        out, err = p.communicate(timeout=300)
        ok_tx = "Transmission finished" in (out or "")
        print(f"ssh={p.returncode} finished={ok_tx}", flush=True)
        if p.returncode != 0:
            print("ERR", (err or out or "")[-400:], flush=True)
        audio = rec[:, 0].astype(np.float64)
        peak = float(np.max(np.abs(audio)))
        path = out_dir / f"nearus_speed_T{int(tsym*1000)}_{fec}_R{reps}.wav"
        wavfile.write(str(path), 48000, audio.astype(np.float32))
        bits = encode_message(msg, fec=fec)
        stats, _, result = decode_from_samples(
            audio,
            cfg,
            min_energy=1e-6,
            min_ratio=1.08,
            expected_bits=bits,
            fec=fec,
            sync_mode="correlation",
            apply_bandpass=False,
            frequency_search_hz=150.0,
            frequency_search_step_hz=25.0,
            symbol_duration_search_percent=3.0,
            symbol_duration_search_steps=5,
            timing_steps=16,
        )
        print(
            f"peak={peak:.3f} success={result.success} msg={stats.recovered_message!r} "
            f"err={result.error}",
            flush=True,
        )
        results.append(
            (tsym, fec, reps, bool(result.success), stats.recovered_message, result.error, air, peak)
        )

    print("\nSUMMARY NEAR-US SPEED", flush=True)
    for tsym, fec, reps, ok, recov, err, air, peak in results:
        flag = "OK" if ok else "FAIL"
        print(
            f"{flag} T={tsym:.2f}s fec={fec:9s} R={reps} air≈{air:.1f}s "
            f"peak={peak:.3f} -> {recov!r} {err or ''}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
