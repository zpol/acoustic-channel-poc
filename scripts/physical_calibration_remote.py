#!/usr/bin/env python3
"""Physical frequency calibration with optional remote TX + local RX.

Saves packages under output/calibration-audible-physical and
output/calibration-near-us-physical with provenance PHYSICAL_RX.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.calibration import (
    build_sweep_waveform,
    estimate_noise_from_gaps,
    measure_response,
    recommend_frequencies,
)
from src.carrier_recommend import FreqPoint, recommend_carrier_pairs, recommendations_as_dict
from src.provenance import Provenance
from src.synchronization import estimate_latency, generate_sync_pilot
from src.visualizer import save_frequency_response


def git_commit() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def play_remote(host: str, remote_dir: str, wav_local: Path, device: int) -> None:
    remote_wav = "/tmp/acoustic_cal_tx.wav"
    remote_py = "/tmp/acoustic_cal_play.py"
    play_script = (
        "import sounddevice as sd\n"
        "from scipy.io import wavfile\n"
        "import numpy as np\n"
        f"sr, data = wavfile.read({remote_wav!r})\n"
        "x = np.asarray(data, dtype=np.float32)\n"
        "if x.ndim > 1: x = x.mean(1)\n"
        f"sd.play(x, sr, device={device})\n"
        "sd.wait()\n"
    )
    subprocess.run(["scp", "-q", str(wav_local), f"{host}:{remote_wav}"], check=True)
    subprocess.run(
        ["ssh", host, f"cat > {remote_py} <<'PY'\n{play_script}PY"],
        check=True,
    )
    subprocess.run(
        ["ssh", host, f"cd {remote_dir} && . .venv/bin/activate && python {remote_py}"],
        check=True,
    )


def play_local(wav: np.ndarray, sr: int, device: int | None) -> None:
    import sounddevice as sd

    sd.play(wav.astype(np.float32), sr, device=device)
    sd.wait()


def run_cal(
    out_dir: Path,
    f_start: float,
    f_stop: float,
    step: float,
    amplitude: float,
    near_us: bool,
    input_device: int,
    output_device: int | None,
    remote_tx: str | None,
    remote_dir: str,
    remote_output_device: int,
    sample_rate: int = 48000,
    tone_duration: float = 0.30,
    gap: float = 0.12,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    frequencies = list(np.arange(f_start, f_stop + step * 0.5, step))
    pilot = generate_sync_pilot(sample_rate, duration=0.05, amplitude=amplitude)
    sweep, segments = build_sweep_waveform(
        frequencies, sample_rate, tone_duration, gap, amplitude
    )
    ambient_n = int(0.5 * sample_rate)
    pad = int(0.15 * sample_rate)
    tx = np.concatenate([np.zeros(ambient_n), pilot, np.zeros(pad), sweep])
    offset = ambient_n + len(pilot) + pad
    segments = [(s + offset, e + offset, f) for s, e, f in segments]

    tx_path = out_dir / "tx_reference.wav"
    wavfile.write(str(tx_path), sample_rate, tx.astype(np.float32))

    # Pre-stage remote WAV before arming the recorder (avoids SCP delay in latency).
    remote_py = "/tmp/acoustic_cal_play.py"
    if remote_tx:
        remote_wav = "/tmp/acoustic_cal_tx.wav"
        play_script = (
            "import sounddevice as sd\n"
            "from scipy.io import wavfile\n"
            "import numpy as np\n"
            f"sr, data = wavfile.read('{remote_wav}')\n"
            "x = np.asarray(data, dtype=np.float32)\n"
            "if x.ndim > 1:\n"
            "    x = x.mean(1)\n"
            f"sd.play(x, sr, device={remote_output_device})\n"
            "sd.wait()\n"
        )
        subprocess.run(["scp", "-q", str(tx_path), f"{remote_tx}:{remote_wav}"], check=True)
        subprocess.run(
            ["ssh", remote_tx, f"cat > {remote_py} <<'PY'\n{play_script}PY"],
            check=True,
        )

    import sounddevice as sd

    pad_end = int(0.8 * sample_rate)
    n_rec = len(tx) + pad_end
    print(f"Recording {n_rec / sample_rate:.1f}s on device {input_device}…", flush=True)
    rec = sd.rec(
        n_rec,
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=input_device,
    )
    time.sleep(0.25)
    print("Playing sweep…", flush=True)
    if remote_tx:
        subprocess.run(
            [
                "ssh",
                remote_tx,
                f"cd {remote_dir} && . .venv/bin/activate && python {remote_py}",
            ],
            check=True,
        )
    else:
        play_local(tx, sample_rate, output_device)
    time.sleep(0.35)
    sd.wait()
    rx = np.asarray(rec, dtype=np.float64).reshape(-1)
    wavfile.write(str(out_dir / "rx_physical.wav"), sample_rate, rx.astype(np.float32))
    print(
        f"RX peak={float(np.max(np.abs(rx))):.3f} rms={float(np.sqrt(np.mean(rx**2))):.4f}",
        flush=True,
    )

    lat = estimate_latency(pilot, rx, sample_rate, max_latency_s=2.5)
    print(
        f"Latency detected={lat.detected} s={lat.latency_seconds:.4f} "
        f"conf={lat.confidence:.3f}",
        flush=True,
    )
    aligned = rx
    if lat.detected and lat.latency_samples > 0:
        aligned = rx[lat.latency_samples :]
    else:
        print("WARNING: pilot not confidently detected — raw alignment kept", flush=True)

    mid = frequencies[len(frequencies) // 2]
    # Noise from pre-pilot ambient window on aligned recording when possible
    amb = aligned[: min(len(aligned), ambient_n)]
    from src.modulation import goertzel as _gz

    ambient_noise = float(np.median([_gz(amb, f, sample_rate) for f in frequencies[::3]])) if len(amb) > 100 else 0.0
    gap_noise = estimate_noise_from_gaps(aligned, segments, sample_rate, probe_freq=mid)
    noise = max(ambient_noise, gap_noise, 1e-12)
    points = measure_response(aligned, segments, sample_rate, noise)
    # Also print relative energy ranking for honesty when absolute SNR is harsh
    ranked = sorted(points, key=lambda p: p.energy, reverse=True)
    print("Top energies:", flush=True)
    for p in ranked[:6]:
        print(
            f"  {p.frequency:.0f} Hz  E={p.energy:.3e}  "
            f"estimated_detector_snr_db={p.estimated_detector_snr_db:.1f}",
            flush=True,
        )
    freq_points = [
        FreqPoint(p.frequency, p.estimated_detector_snr_db, p.energy) for p in points
    ]
    recs = recommend_carrier_pairs(
        freq_points, sample_rate=sample_rate, min_separation_hz=1000.0, min_snr_db=3.0
    )
    if not recs:
        # Fall back: rank by energy, but keep true detector SNR in the report fields
        by_e = sorted(points, key=lambda p: p.energy, reverse=True)
        soft_points = []
        for p in points:
            rel = 10.0 * np.log10((p.energy + 1e-20) / (by_e[-1].energy + 1e-20))
            soft_points.append(FreqPoint(p.frequency, rel, p.energy))
        soft_recs = recommend_carrier_pairs(
            soft_points,
            sample_rate=sample_rate,
            min_separation_hz=1000.0,
            min_snr_db=0.0,
        )
        # Remap labels onto true measured SNRs
        true = {p.frequency: p.estimated_detector_snr_db for p in points}
        from src.carrier_recommend import CarrierRecommendation

        recs = []
        for r in soft_recs:
            snr = min(true.get(r.frequency_zero, -99), true.get(r.frequency_one, -99))
            recs.append(
                CarrierRecommendation(
                    label=r.label,
                    frequency_zero=r.frequency_zero,
                    frequency_one=r.frequency_one,
                    estimated_snr_db=snr,
                    recommended_symbol_duration=max(0.15, r.recommended_symbol_duration),
                    notes=r.notes + " (ranked by energy; SNR is measured detector SNR)",
                )
            )
    fallback = recommend_frequencies(points, min_separation=1000.0, min_snr_db=0.0)

    with (out_dir / "measurements.csv").open("w", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "frequency",
                "energy",
                "noise_floor",
                "estimated_detector_snr_db",
                "adjacent_energy",
                "harmonic_energy",
                "clipping",
            ],
        )
        w.writeheader()
        for p in points:
            w.writerow(
                {
                    "frequency": p.frequency,
                    "energy": p.energy,
                    "noise_floor": p.noise_floor,
                    "estimated_detector_snr_db": p.estimated_detector_snr_db,
                    "adjacent_energy": p.adjacent_energy,
                    "harmonic_energy": p.harmonic_energy,
                    "clipping": p.clipping,
                }
            )

    pair = None
    if recs:
        pair = (recs[0].frequency_zero, recs[0].frequency_one)
        for r in recs:
            print(
                f"{r.label}: f0={r.frequency_zero:.0f} f1={r.frequency_one:.0f} "
                f"SNR≈{r.estimated_snr_db:.1f}dB Tsym={r.recommended_symbol_duration:.3f}",
                flush=True,
            )
    elif fallback:
        pair = fallback

    save_frequency_response(
        [p.frequency for p in points],
        [p.energy for p in points],
        noise,
        out_dir / "response.png",
        recommended=pair,
    )

    # SNR curve
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.plot(
        [p.frequency for p in points],
        [p.estimated_detector_snr_db for p in points],
        marker="o",
        ms=3,
    )
    ax.set_xlabel("Hz")
    ax.set_ylabel("estimated_detector_snr_db")
    ax.set_title(f"Physical response [{Provenance.PHYSICAL_RX.value}]")
    ax.axhline(6, color="orange", ls="--", label="6 dB guide")
    if near_us:
        ax.axvline(17000, color="red", ls=":", label="17 kHz warn")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "noise_floor.png", dpi=120)
    plt.close(fig)

    ambient_rms = float(np.sqrt(np.mean(rx[:ambient_n] ** 2)))
    meta = {
        "provenance": Provenance.PHYSICAL_RX.value,
        "git_commit": git_commit(),
        "f_start": f_start,
        "f_stop": f_stop,
        "step": step,
        "amplitude": amplitude,
        "near_ultrasonic": near_us,
        "sample_rate": sample_rate,
        "input_device": input_device,
        "output_device": output_device,
        "remote_tx": remote_tx,
        "latency": {
            "detected": lat.detected,
            "seconds": lat.latency_seconds,
            "confidence": lat.confidence,
            "correlation_peak": lat.correlation_peak,
        },
        "ambient_rms": ambient_rms,
        "recommendations": recommendations_as_dict(recs),
        "snr_note": "estimated_detector_snr_db is not calibrated SPL",
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    report = [
        f"# Physical calibration\n\n",
        f"Provenance: **{Provenance.PHYSICAL_RX.value}**\n\n",
        f"Range: {f_start:.0f}–{f_stop:.0f} Hz step {step}\n\n",
        f"Amplitude: {amplitude}\n\n",
        f"Latency detected={lat.detected} ({lat.latency_seconds:.4f}s)\n\n",
        f"Ambient RMS: {ambient_rms:.6f}\n\n",
        "## Recommendations\n\n",
    ]
    for r in recs:
        report.append(
            f"- **{r.label}**: {r.frequency_zero:.0f}/{r.frequency_one:.0f} Hz, "
            f"SNR≈{r.estimated_snr_db:.1f} dB, Tsym={r.recommended_symbol_duration:.3f}s\n"
        )
    if not recs:
        report.append("- No pair met SNR/separation constraints; inspect CSV.\n")
    (out_dir / "report.md").write_text("".join(report))
    print(f"Saved {out_dir}", flush=True)
    return meta


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--band", choices=("audible", "near-us", "both"), default="both")
    p.add_argument("--input-device", type=int, default=0)
    p.add_argument("--output-device", type=int, default=0)
    p.add_argument("--remote-tx", default="demo-user@tx-host")
    p.add_argument("--remote-dir", default="/path/to/repository")
    p.add_argument("--remote-output-device", type=int, default=1)
    p.add_argument("--local-tx", action="store_true", help="Play on this host instead of SSH")
    args = p.parse_args()

    remote = None if args.local_tx else args.remote_tx
    if remote:
        subprocess.run(
            [
                "ssh",
                remote,
                "pactl set-default-sink "
                "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink; "
                "pactl set-sink-mute @DEFAULT_SINK@ 0; "
                "pactl set-sink-volume @DEFAULT_SINK@ 85%",
            ],
            check=False,
        )

    # Mic prep local
    subprocess.run(
        ["amixer", "-c", "0", "set", "Capture", "40%", "unmute"],
        capture_output=True,
    )
    subprocess.run(
        ["amixer", "-c", "0", "cset", "name=Input Source", "Rear Mic"],
        capture_output=True,
    )

    if args.band in ("audible", "both"):
        print("=== AUDIBLE PHYSICAL CAL 2–10 kHz ===", flush=True)
        run_cal(
            ROOT / "output" / "calibration-audible-physical",
            2000,
            10000,
            250,
            0.15,
            False,
            args.input_device,
            args.output_device,
            remote,
            args.remote_dir,
            args.remote_output_device,
        )
    if args.band in ("near-us", "both"):
        print("=== NEAR-US PHYSICAL CAL 15–21 kHz ===", flush=True)
        run_cal(
            ROOT / "output" / "calibration-near-us-physical",
            15000,
            21000,
            250,
            0.10,
            True,
            args.input_device,
            args.output_device,
            remote,
            args.remote_dir,
            args.remote_output_device,
            tone_duration=0.35,
            gap=0.15,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
