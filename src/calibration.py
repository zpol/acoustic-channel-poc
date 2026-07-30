"""Speaker/microphone frequency calibration utility.

Plays a frequency sweep, records the response, estimates SNR per tone,
and recommends two BFSK frequencies with good separation.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from scipy.io import wavfile

from src.modulation import (
    DEFAULT_SAMPLE_RATE,
    HIGH_FREQ_WARNING_HZ,
    generate_tone,
    goertzel,
)
from src.carrier_recommend import FreqPoint, recommend_carrier_pairs, recommendations_as_dict
from src.provenance import Provenance
from src.synchronization import (
    align_recording,
    estimate_latency,
    generate_sync_pilot,
)
from src.visualizer import save_frequency_response

console = Console()


@dataclass(frozen=True)
class CalibrationPoint:
    frequency: float
    energy: float
    noise_floor: float
    snr_db: float
    adjacent_energy: float = 0.0
    estimated_detector_snr_db: float = 0.0
    clipping: bool = False
    harmonic_energy: float = 0.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.calibration",
        description=(
            "Calibrate speaker/mic frequency response for BFSK/CPFSK. "
            "Default sweep is audible 2–10 kHz. Near-ultrasonic requires "
            "--near-ultrasonic. Use --physical for packaged evidence."
        ),
    )
    parser.add_argument("--input-device", type=int, default=None)
    parser.add_argument("--output-device", type=int, default=None)
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument(
        "--near-ultrasonic",
        action="store_true",
        help="Use 16–22 kHz sweep (experimental; requires confirmation)",
    )
    parser.add_argument("--physical", action="store_true", help="Save full calibration package")
    parser.add_argument("--f-start", type=float, default=None)
    parser.add_argument("--f-stop", type=float, default=None)
    parser.add_argument("--start-frequency", type=float, default=None, dest="start_frequency")
    parser.add_argument("--end-frequency", type=float, default=None, dest="end_frequency")
    parser.add_argument(
        "--step",
        type=float,
        default=None,
        help="Frequency step in Hz (default 500 audible / 250 ultrasonic)",
    )
    parser.add_argument(
        "--tone-duration",
        type=float,
        default=0.35,
        help="Seconds per test tone",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=0.15,
        help="Silence between tones (seconds)",
    )
    parser.add_argument(
        "--amplitude",
        type=float,
        default=0.12,
        help="Playback amplitude (keep low)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate sweep + synthetic response plot without audio I/O",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        default=Path("output/calibration_response.png"),
        help="Path for frequency-response PNG",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("output/calibration"),
        help="Package directory when --physical is set",
    )
    parser.add_argument(
        "--min-separation",
        type=float,
        default=1000.0,
        help="Minimum Hz between recommended BFSK tones",
    )
    return parser


def default_range(near_ultrasonic: bool) -> Tuple[float, float, float]:
    if near_ultrasonic:
        return 16_000.0, 22_000.0, 250.0
    return 2_000.0, 10_000.0, 500.0


def build_sweep_waveform(
    frequencies: Sequence[float],
    sample_rate: int,
    tone_duration: float,
    gap: float,
    amplitude: float,
) -> Tuple[np.ndarray, List[Tuple[int, int, float]]]:
    """Return waveform and list of (start_sample, end_sample, frequency)."""
    chunks: List[np.ndarray] = []
    segments: List[Tuple[int, int, float]] = []
    cursor = 0
    gap_n = int(round(gap * sample_rate))
    for freq in frequencies:
        tone, _ = generate_tone(
            frequency=freq,
            duration=tone_duration,
            sample_rate=sample_rate,
            amplitude=amplitude,
        )
        start = cursor
        chunks.append(tone)
        cursor += len(tone)
        segments.append((start, cursor, freq))
        if gap_n > 0:
            chunks.append(np.zeros(gap_n, dtype=np.float64))
            cursor += gap_n
    waveform = np.concatenate(chunks) if chunks else np.zeros(0)
    return waveform, segments


def measure_response(
    recording: np.ndarray,
    segments: Sequence[Tuple[int, int, float]],
    sample_rate: int,
    noise_floor: float,
) -> List[CalibrationPoint]:
    points: List[CalibrationPoint] = []
    for start, end, freq in segments:
        # Use middle 60% of each tone to avoid fades/transients
        length = end - start
        a = start + int(length * 0.2)
        b = start + int(length * 0.8)
        window = recording[a:b]
        if len(window) < 16:
            window = recording[start:end]
        energy = goertzel(window, freq, sample_rate)
        # Adjacent band (±500 Hz) for selectivity estimate
        adj = 0.5 * (
            goertzel(window, max(50.0, freq - 500.0), sample_rate)
            + goertzel(window, freq + 500.0, sample_rate)
        )
        harm = goertzel(window, min(freq * 2.0, sample_rate / 2 - 100), sample_rate)
        peak = float(np.max(np.abs(window))) if len(window) else 0.0
        snr = 10.0 * np.log10((energy + 1e-20) / (noise_floor + 1e-20))
        points.append(
            CalibrationPoint(
                frequency=freq,
                energy=energy,
                noise_floor=noise_floor,
                snr_db=float(snr),
                adjacent_energy=float(adj),
                estimated_detector_snr_db=float(snr),
                clipping=peak >= 0.99,
                harmonic_energy=float(harm),
            )
        )
    return points


def estimate_noise_from_gaps(
    recording: np.ndarray,
    segments: Sequence[Tuple[int, int, float]],
    sample_rate: int,
    probe_freq: float,
) -> float:
    """Estimate noise using Goertzel at probe_freq on inter-tone gaps."""
    energies: List[float] = []
    for i in range(len(segments) - 1):
        gap_start = segments[i][1]
        gap_end = segments[i + 1][0]
        if gap_end - gap_start < 32:
            continue
        window = recording[gap_start:gap_end]
        energies.append(goertzel(window, probe_freq, sample_rate))
    if not energies:
        # Fall back to first 100 ms
        n = min(len(recording), int(0.1 * sample_rate))
        return goertzel(recording[:n], probe_freq, sample_rate)
    return float(np.median(energies))


def recommend_frequencies(
    points: Sequence[CalibrationPoint],
    min_separation: float,
    min_snr_db: float = 10.0,
) -> Optional[Tuple[float, float]]:
    """Pick two high-SNR frequencies with enough separation."""
    candidates = sorted(
        [p for p in points if p.snr_db >= min_snr_db],
        key=lambda p: p.snr_db,
        reverse=True,
    )
    if len(candidates) < 2:
        candidates = sorted(points, key=lambda p: p.snr_db, reverse=True)
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            if abs(a.frequency - b.frequency) >= min_separation:
                pair = sorted([a.frequency, b.frequency])
                return pair[0], pair[1]
    if len(candidates) >= 2:
        pair = sorted([candidates[0].frequency, candidates[1].frequency])
        return pair[0], pair[1]
    return None


def print_table(points: Sequence[CalibrationPoint]) -> None:
    table = Table(title="Calibration results")
    table.add_column("Frequency (Hz)", justify="right")
    table.add_column("Energy", justify="right")
    table.add_column("Noise floor", justify="right")
    table.add_column("SNR (dB)", justify="right")
    for p in points:
        table.add_row(
            f"{p.frequency:.0f}",
            f"{p.energy:.4e}",
            f"{p.noise_floor:.4e}",
            f"{p.snr_db:.1f}",
        )
    console.print(table)


def play_and_record(
    waveform: np.ndarray,
    sample_rate: int,
    input_device: Optional[int],
    output_device: Optional[int],
    *,
    near_ultrasonic: bool = False,
    probe_frequency_hz: float = 1000.0,
) -> np.ndarray:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is required") from exc

    from src.safety import assert_calibration_playback

    peak = float(np.max(np.abs(waveform))) if len(waveform) else 0.0
    dur = len(waveform) / float(sample_rate) if sample_rate else 0.0
    assert_calibration_playback(
        peak_amplitude=peak,
        sample_rate=sample_rate,
        duration_s=dur,
        max_probe_hz=max(probe_frequency_hz, 1000.0),
        near_ultrasonic=near_ultrasonic or probe_frequency_hz > 17000,
    )

    if input_device is not None:
        from src.audio_devices import validate_input_device

        validate_input_device(input_device)
    if output_device is not None:
        from src.audio_devices import validate_output_device

        validate_output_device(output_device)

    # Record slightly longer than playback to catch trailing energy
    pad = int(0.3 * sample_rate)
    n = len(waveform) + pad
    recording = sd.rec(
        n,
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=input_device,
    )
    time.sleep(0.05)
    sd.play(waveform.astype(np.float32), samplerate=sample_rate, device=output_device)
    sd.wait()
    time.sleep(0.2)
    sd.stop()
    return np.asarray(recording, dtype=np.float64).reshape(-1)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    f_start_def, f_stop_def, step_def = default_range(args.near_ultrasonic)
    f_start = (
        args.start_frequency
        if args.start_frequency is not None
        else (args.f_start if args.f_start is not None else f_start_def)
    )
    f_stop = (
        args.end_frequency
        if args.end_frequency is not None
        else (args.f_stop if args.f_stop is not None else f_stop_def)
    )
    step = args.step if args.step is not None else step_def

    if (f_start > HIGH_FREQ_WARNING_HZ or f_stop > HIGH_FREQ_WARNING_HZ) and not (
        args.near_ultrasonic
    ):
        console.print(
            f"[red]Sweep above {HIGH_FREQ_WARNING_HZ:.0f} Hz requires "
            f"--near-ultrasonic[/red]"
        )
        return 2

    if args.near_ultrasonic:
        console.print(
            Panel(
                "[bold yellow]Near-ultrasonic calibration[/bold yellow]\n\n"
                "Hardware (speakers, mics, codecs, analogue filters) often "
                "attenuates or blocks energy near or above 20 kHz.\n"
                "A sample rate of 48 kHz has a theoretical Nyquist limit of "
                "24 kHz, but real devices may fail well below that.\n"
                "Keep amplitude low. Prefer wired devices.",
                border_style="yellow",
            )
        )
        time.sleep(1.0)

    nyquist = args.sample_rate / 2.0
    if f_stop >= nyquist:
        console.print(
            f"[red]f-stop {f_stop} >= Nyquist {nyquist}; "
            "lower the stop frequency or raise sample rate.[/red]"
        )
        return 2
    if f_start <= 0 or f_stop <= f_start or step <= 0:
        console.print("[red]Invalid frequency range or step.[/red]")
        return 2
    if not (0.0 < args.amplitude <= 0.5):
        console.print("[red]amplitude must be in (0, 0.5][/red]")
        return 2

    frequencies = list(np.arange(f_start, f_stop + step * 0.5, step))
    provenance = (
        Provenance.SIMULATED_RX.value if args.dry_run else Provenance.PHYSICAL_RX.value
    )
    console.print("[bold]Active calibration configuration[/bold]")
    console.print(f"  sample_rate = {args.sample_rate}")
    console.print(f"  range       = {f_start:.0f}–{f_stop:.0f} Hz")
    console.print(f"  step        = {step}")
    console.print(f"  n_tones     = {len(frequencies)}")
    console.print(f"  amplitude   = {args.amplitude}")
    console.print(f"  dry_run     = {args.dry_run}")
    console.print(f"  provenance  = {provenance}")

    pilot = generate_sync_pilot(args.sample_rate, duration=0.05, amplitude=args.amplitude)
    waveform, segments = build_sweep_waveform(
        frequencies,
        args.sample_rate,
        args.tone_duration,
        args.gap,
        args.amplitude,
    )
    # Prepend silence (ambient) + pilot + silence before sweep
    ambient_n = int(0.5 * args.sample_rate)
    pad = int(0.15 * args.sample_rate)
    tx_full = np.concatenate(
        [
            np.zeros(ambient_n),
            pilot,
            np.zeros(pad),
            waveform,
        ]
    )
    # Shift segment indices to account for ambient+pilot+pad
    offset = ambient_n + len(pilot) + pad
    segments = [(s + offset, e + offset, f) for s, e, f in segments]
    duration = len(tx_full) / args.sample_rate
    console.print(f"Sweep duration (with pilot): {duration:.2f} s")

    latency_info = {
        "detected": False,
        "latency_seconds": None,
        "confidence": 0.0,
        "correlation_peak": 0.0,
    }

    if args.dry_run:
        rng = np.random.default_rng(0)
        recording = tx_full * 0.4 + rng.normal(0, 0.01, size=tx_full.shape)
        for start, end, freq in segments:
            if freq > 16_000:
                recording[start:end] *= max(0.05, 1.0 - (freq - 16_000) / 8_000)
        # Synthetic latency
        delay = int(0.04 * args.sample_rate)
        recording = np.concatenate([np.zeros(delay), recording[:-delay]])
    else:
        try:
            recording = play_and_record(
                tx_full,
                args.sample_rate,
                args.input_device,
                args.output_device,
                near_ultrasonic=bool(args.near_ultrasonic),
                probe_frequency_hz=float(max(f_start, f_stop)),
            )
        except Exception as exc:
            console.print(f"[red]Audio I/O error:[/red] {exc}")
            console.print(
                "Tip: python -m src.audio_devices; see README troubleshooting."
            )
            return 1

    lat = estimate_latency(pilot, recording[ambient_n:], args.sample_rate)
    latency_info = {
        "detected": lat.detected,
        "latency_seconds": lat.latency_seconds,
        "latency_samples": lat.latency_samples,
        "confidence": lat.confidence,
        "correlation_peak": lat.correlation_peak,
    }
    console.print(
        f"Latency: detected={lat.detected} "
        f"s={lat.latency_seconds:.4f} conf={lat.confidence:.3f}"
    )
    if lat.detected:
        # Align so ambient starts at 0 relative to tx_full timing
        recording = align_recording(recording, lat)
    elif not args.dry_run:
        console.print(
            "[yellow]Pilot not detected with confidence — "
            "keeping raw alignment (not fabricating).[/yellow]"
        )

    mid = frequencies[len(frequencies) // 2]
    noise = estimate_noise_from_gaps(
        recording, segments, args.sample_rate, probe_freq=mid
    )
    # Ambient noise from first half-second
    ambient = recording[: min(len(recording), ambient_n)]
    ambient_rms = float(np.sqrt(np.mean(ambient**2))) if len(ambient) else 0.0

    if len(recording) < segments[-1][1]:
        console.print("[yellow]Recording shorter than expected sweep.[/yellow]")

    points = measure_response(recording, segments, args.sample_rate, noise)
    print_table(points)

    freq_points = [
        FreqPoint(
            frequency=p.frequency,
            estimated_detector_snr_db=p.estimated_detector_snr_db,
            energy=p.energy,
        )
        for p in points
    ]
    recs = recommend_carrier_pairs(
        freq_points,
        sample_rate=args.sample_rate,
        min_separation_hz=args.min_separation,
    )
    for r in recs:
        console.print(
            f"[green]{r.label}:[/green] f0={r.frequency_zero:.0f} "
            f"f1={r.frequency_one:.0f} "
            f"estimated_detector_snr_db={r.estimated_snr_db:.1f} "
            f"symbol_duration={r.recommended_symbol_duration:.3f}s"
        )
        console.print(f"  notes: {r.notes}")

    recommended = (
        (recs[0].frequency_zero, recs[0].frequency_one) if recs else None
    )
    if not recommended:
        recommended = recommend_frequencies(points, args.min_separation)
        if recommended:
            console.print(
                f"[green]Fallback pair:[/green] "
                f"{recommended[0]:.0f} / {recommended[1]:.0f} Hz"
            )

    plot_path = args.plot
    if args.physical or args.dry_run:
        out_dir = args.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        plot_path = out_dir / "response.png"
        try:
            commit = (
                subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
                )
                .decode()
                .strip()
            )
        except Exception:
            commit = "unknown"
        meta = {
            "provenance": provenance,
            "git_commit": commit,
            "sample_rate": args.sample_rate,
            "f_start": f_start,
            "f_stop": f_stop,
            "step": step,
            "amplitude": args.amplitude,
            "dry_run": args.dry_run,
            "latency": latency_info,
            "ambient_rms": ambient_rms,
            "noise_floor_goertzel": noise,
            "recommendations": recommendations_as_dict(recs),
            "snr_note": (
                "estimated_detector_snr_db is Goertzel tone energy vs gap noise; "
                "not calibrated acoustic SPL"
            ),
        }
        (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
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
        wavfile.write(str(out_dir / "tx_reference.wav"), args.sample_rate, tx_full.astype(np.float32))
        wavfile.write(
            str(out_dir / "rx_physical.wav" if not args.dry_run else out_dir / "rx_simulated.wav"),
            args.sample_rate,
            recording.astype(np.float32),
        )
        # noise floor plot
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 3))
        ax.plot([p.frequency for p in points], [p.noise_floor for p in points], label="noise ref")
        ax.plot(
            [p.frequency for p in points],
            [p.estimated_detector_snr_db for p in points],
            label="estimated_detector_snr_db",
        )
        ax.set_title(f"Noise / SNR ({provenance})")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / "noise_floor.png", dpi=120)
        plt.close(fig)
        report = [
            f"# Calibration report\n\n",
            f"Provenance: **{provenance}**\n\n",
            f"Range: {f_start:.0f}–{f_stop:.0f} Hz step {step}\n\n",
            f"Latency detected={latency_info['detected']} "
            f"({latency_info.get('latency_seconds')})\n\n",
            f"Ambient RMS: {ambient_rms:.6f}\n\n",
            "## Recommendations\n\n",
        ]
        for r in recs:
            report.append(
                f"- **{r.label}**: f0={r.frequency_zero:.0f} f1={r.frequency_one:.0f} "
                f"SNR≈{r.estimated_snr_db:.1f} dB "
                f"Tsym={r.recommended_symbol_duration:.3f}s\n"
            )
        report.append(
            "\n`estimated_detector_snr_db` is not calibrated SPL.\n"
        )
        (out_dir / "report.md").write_text("".join(report))
        console.print(f"Saved calibration package: {out_dir}")

    save_frequency_response(
        [p.frequency for p in points],
        [p.energy for p in points],
        noise,
        plot_path,
        recommended=recommended,
    )
    console.print(f"Saved frequency-response plot: {plot_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
