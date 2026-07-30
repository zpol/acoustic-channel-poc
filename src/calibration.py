"""Speaker/microphone frequency calibration utility.

Plays a frequency sweep, records the response, estimates SNR per tone,
and recommends two BFSK frequencies with good separation.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.modulation import (
    DEFAULT_SAMPLE_RATE,
    HIGH_FREQ_WARNING_HZ,
    generate_tone,
    goertzel,
)
from src.visualizer import save_frequency_response

console = Console()


@dataclass(frozen=True)
class CalibrationPoint:
    frequency: float
    energy: float
    noise_floor: float
    snr_db: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.calibration",
        description=(
            "Calibrate speaker/mic frequency response for BFSK. "
            "Default sweep is audible 2–10 kHz. Near-ultrasonic requires "
            "--near-ultrasonic."
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
    parser.add_argument("--f-start", type=float, default=None)
    parser.add_argument("--f-stop", type=float, default=None)
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
        snr = 10.0 * np.log10((energy + 1e-20) / (noise_floor + 1e-20))
        points.append(
            CalibrationPoint(
                frequency=freq,
                energy=energy,
                noise_floor=noise_floor,
                snr_db=float(snr),
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
) -> np.ndarray:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is required") from exc

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
    f_start = args.f_start if args.f_start is not None else f_start_def
    f_stop = args.f_stop if args.f_stop is not None else f_stop_def
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
    console.print("[bold]Active calibration configuration[/bold]")
    console.print(f"  sample_rate = {args.sample_rate}")
    console.print(f"  range       = {f_start:.0f}–{f_stop:.0f} Hz")
    console.print(f"  step        = {step}")
    console.print(f"  n_tones     = {len(frequencies)}")
    console.print(f"  amplitude   = {args.amplitude}")
    console.print(f"  dry_run     = {args.dry_run}")

    waveform, segments = build_sweep_waveform(
        frequencies,
        args.sample_rate,
        args.tone_duration,
        args.gap,
        args.amplitude,
    )
    duration = len(waveform) / args.sample_rate
    console.print(f"Sweep duration: {duration:.2f} s")

    if args.dry_run:
        # Synthetic band-limited response for offline demos/tests
        rng = np.random.default_rng(0)
        recording = waveform * 0.4 + rng.normal(0, 0.01, size=waveform.shape)
        # Simulate roll-off above 16 kHz
        for start, end, freq in segments:
            if freq > 16_000:
                recording[start:end] *= max(0.05, 1.0 - (freq - 16_000) / 8_000)
    else:
        try:
            recording = play_and_record(
                waveform,
                args.sample_rate,
                args.input_device,
                args.output_device,
            )
        except Exception as exc:
            console.print(f"[red]Audio I/O error:[/red] {exc}")
            console.print(
                "Tip: python -m src.audio_devices; see README troubleshooting."
            )
            return 1

    mid = frequencies[len(frequencies) // 2]
    noise = estimate_noise_from_gaps(
        recording, segments, args.sample_rate, probe_freq=mid
    )
    # Align recording length with waveform if padded
    if len(recording) < segments[-1][1]:
        console.print("[yellow]Recording shorter than expected sweep.[/yellow]")

    points = measure_response(recording, segments, args.sample_rate, noise)
    print_table(points)

    recommended = recommend_frequencies(points, args.min_separation)
    if recommended:
        console.print(
            f"[green]Recommended BFSK pair:[/green] "
            f"{recommended[0]:.0f} Hz / {recommended[1]:.0f} Hz"
        )
        console.print(
            "Example:\n"
            f"  python -m src.transmitter --message DEMO-LAB-2027 "
            f"--frequency-zero {recommended[0]:.0f} "
            f"--frequency-one {recommended[1]:.0f}"
            + (" --near-ultrasonic" if args.near_ultrasonic else "")
        )
    else:
        console.print("[yellow]Could not recommend a frequency pair.[/yellow]")

    save_frequency_response(
        [p.frequency for p in points],
        [p.energy for p in points],
        noise,
        args.plot,
        recommended=recommended,
    )
    console.print(f"Saved frequency-response plot: {args.plot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
