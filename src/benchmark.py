"""Reliability benchmark for the acoustic channel PoC.

Runs multiple synthetic payloads (simulate or live speaker/mic) and
reports frame-success rate, mean BER, and per-message results.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
from rich.console import Console
from rich.table import Table

from src.modulation import (
    DEFAULT_AMPLITUDE,
    DEFAULT_FREQUENCY_ONE,
    DEFAULT_FREQUENCY_ZERO,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SYMBOL_DURATION,
    HIGH_FREQ_WARNING_HZ,
    ModulationConfig,
    add_channel_impairments,
    bits_to_waveform,
)
from src.protocol import encode_message, estimate_duration, validate_payload
from src.receiver import decode_from_samples

console = Console()

DEFAULT_MESSAGES: tuple[str, ...] = (
    "DEMO-LAB-2027",
    "HELLO",
    "OK",
    "TEST-01",
    "ABC123",
    "PING",
    "CYBER-LAB",
    "MSG-42",
)


@dataclass
class TrialResult:
    message: str
    success: bool
    recovered: Optional[str]
    ber: Optional[float]
    snr_db: Optional[float]
    clipping: bool
    timing_offset: int
    error: Optional[str]
    duration_s: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.benchmark",
        description=(
            "Measure acoustic-channel reliability across several messages. "
            "Reports frame success %% and bit-error rate."
        ),
    )
    parser.add_argument(
        "--messages",
        nargs="+",
        default=list(DEFAULT_MESSAGES),
        help="Synthetic payloads to transmit (default: built-in set)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="Repeat the full message list this many times",
    )
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument(
        "--symbol-duration", type=float, default=DEFAULT_SYMBOL_DURATION
    )
    parser.add_argument(
        "--frequency-zero", type=float, default=DEFAULT_FREQUENCY_ZERO
    )
    parser.add_argument(
        "--frequency-one", type=float, default=DEFAULT_FREQUENCY_ONE
    )
    parser.add_argument("--amplitude", type=float, default=0.25)
    parser.add_argument("--repeats", type=int, default=2, choices=(1, 2, 3))
    parser.add_argument("--inter-frame-silence", type=float, default=0.4)
    parser.add_argument("--near-ultrasonic", action="store_true")
    parser.add_argument("--min-energy", type=float, default=1e-5)
    parser.add_argument("--min-ratio", type=float, default=1.2)
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="In-memory channel (no speaker/mic)",
    )
    parser.add_argument("--noise-level", type=float, default=0.02)
    parser.add_argument("--attenuation", type=float, default=0.7)
    parser.add_argument("--timing-offset", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--input-device", type=int, default=0)
    parser.add_argument("--output-device", type=int, default=0)
    parser.add_argument(
        "--gap",
        type=float,
        default=1.0,
        help="Silence before each live TX while RX is already recording",
    )
    return parser


def run_simulate_trial(
    message: str,
    config: ModulationConfig,
    args: argparse.Namespace,
    rng: np.random.Generator,
) -> TrialResult:
    expected = encode_message(message)
    wave = bits_to_waveform(
        expected,
        config,
        repeats=args.repeats,
        inter_frame_silence=args.inter_frame_silence,
    )
    # Randomize timing a bit per trial
    offset = int(args.timing_offset) + int(rng.integers(0, max(1, config.samples_per_symbol // 4)))
    rx = add_channel_impairments(
        wave,
        noise_level=args.noise_level,
        attenuation=args.attenuation,
        timing_offset_samples=offset,
        rng=rng,
    )
    # Leading silence
    pad = np.zeros(int(0.3 * config.sample_rate))
    rx = np.concatenate([pad, rx])
    t0 = time.time()
    stats, _, result = decode_from_samples(
        rx,
        config,
        min_energy=args.min_energy,
        min_ratio=args.min_ratio,
        apply_bandpass=True,
        expected_bits=expected,
        timing_search=True,
    )
    return TrialResult(
        message=message,
        success=result.success and stats.recovered_message == message,
        recovered=stats.recovered_message,
        ber=stats.bit_error_rate,
        snr_db=stats.snr_estimate_db,
        clipping=stats.clipping,
        timing_offset=stats.timing_offset_samples,
        error=None if result.success else result.error,
        duration_s=time.time() - t0,
    )


def run_live_trial(
    message: str,
    config: ModulationConfig,
    args: argparse.Namespace,
) -> TrialResult:
    """Live trial: record in a background thread while playing on the speaker.

    Uses ``sounddevice`` InputStream + OutputStream on the configured
    devices. Falls back to the proven two-phase pattern if duplex fails.
    """
    import sounddevice as sd
    from scipy.io import wavfile

    expected = encode_message(message)
    wave = bits_to_waveform(
        expected,
        config,
        repeats=args.repeats,
        inter_frame_silence=args.inter_frame_silence,
    ).astype(np.float32)

    tx_duration = len(wave) / config.sample_rate
    total = args.gap + tx_duration + 1.5
    n = int(round(total * config.sample_rate))

    console.print(
        f"  TX {message!r}  ({tx_duration:.1f}s audio, "
        f"{args.repeats}x, listen {total:.1f}s)"
    )

    recorded: list[np.ndarray] = []

    def _callback(indata, frames, time_info, status) -> None:  # type: ignore[no-untyped-def]
        del frames, time_info
        if status:
            pass
        recorded.append(indata.copy().reshape(-1))

    samples: np.ndarray
    try:
        with sd.InputStream(
            samplerate=config.sample_rate,
            channels=1,
            dtype="float32",
            device=args.input_device,
            callback=_callback,
        ):
            time.sleep(args.gap)
            sd.play(
                wave,
                samplerate=config.sample_rate,
                device=args.output_device,
            )
            sd.wait()
            time.sleep(0.8)
        if recorded:
            samples = np.concatenate(recorded).astype(np.float64)
            samples = samples[:n]
        else:
            samples = np.zeros(n, dtype=np.float64)
    except Exception as exc:
        console.print(f"  [yellow]duplex stream failed ({exc}); fallback[/yellow]")
        rec = sd.rec(
            n,
            samplerate=config.sample_rate,
            channels=1,
            dtype="float32",
            device=args.input_device,
        )
        time.sleep(args.gap)
        sd.play(wave, samplerate=config.sample_rate, device=args.output_device)
        sd.wait()
        time.sleep(0.5)
        sd.wait()
        samples = np.asarray(rec, dtype=np.float64).reshape(-1)

    if not np.isfinite(samples).all():
        bad = int(np.size(samples) - np.isfinite(samples).sum())
        samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
        console.print(
            f"  [yellow]warning:[/yellow] {bad} non-finite samples replaced"
        )

    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    rms = float(np.sqrt(np.mean(samples**2))) if len(samples) else 0.0
    console.print(f"  capture peak={peak:.3f} rms={rms:.4f}")

    # Keep last capture for debugging
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in message)
    wavfile.write(
        str(out_dir / f"bench_{safe}.wav"),
        config.sample_rate,
        samples.astype(np.float32),
    )

    t0 = time.time()
    stats, _, result = decode_from_samples(
        samples,
        config,
        min_energy=args.min_energy,
        min_ratio=args.min_ratio,
        apply_bandpass=True,
        expected_bits=expected,
        timing_search=True,
    )
    ok = bool(result.success and stats.recovered_message == message)
    return TrialResult(
        message=message,
        success=ok,
        recovered=stats.recovered_message,
        ber=stats.bit_error_rate,
        snr_db=stats.snr_estimate_db,
        clipping=stats.clipping,
        timing_offset=stats.timing_offset_samples,
        error=None if ok else (result.error or "mismatch"),
        duration_s=time.time() - t0,
    )


def summarize(results: Sequence[TrialResult]) -> None:
    table = Table(title="Reliability benchmark")
    table.add_column("#", justify="right")
    table.add_column("Message")
    table.add_column("OK")
    table.add_column("Recovered")
    table.add_column("BER", justify="right")
    table.add_column("SNR dB", justify="right")
    table.add_column("Offset", justify="right")
    table.add_column("Notes")

    for i, r in enumerate(results, 1):
        ber = f"{r.ber:.3f}" if r.ber is not None else "—"
        snr = f"{r.snr_db:.1f}" if r.snr_db is not None else "—"
        note = ""
        if r.clipping:
            note = "clip"
        if not r.success and r.error:
            note = (note + " " if note else "") + (r.error[:40])
        table.add_row(
            str(i),
            r.message,
            "[green]YES[/green]" if r.success else "[red]NO[/red]",
            r.recovered or "—",
            ber,
            snr,
            str(r.timing_offset),
            note,
        )
    console.print(table)

    n = len(results)
    ok = sum(1 for r in results if r.success)
    bers = [r.ber for r in results if r.ber is not None]
    mean_ber = float(np.mean(bers)) if bers else float("nan")
    success_pct = 100.0 * ok / n if n else 0.0

    console.print()
    console.print("[bold]Summary[/bold]")
    console.print(f"  trials            = {n}")
    console.print(f"  frames OK         = {ok}/{n}")
    console.print(f"  frame success     = {success_pct:.1f}%")
    console.print(f"  mean BER          = {mean_ber:.4f}")
    console.print(
        f"  payload delivery  = {success_pct:.1f}% of messages arrived intact"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    for msg in args.messages:
        try:
            validate_payload(msg)
        except Exception as exc:
            console.print(f"[red]Bad payload {msg!r}:[/red] {exc}")
            return 2

    try:
        config = ModulationConfig(
            sample_rate=args.sample_rate,
            symbol_duration=args.symbol_duration,
            frequency_zero=args.frequency_zero,
            frequency_one=args.frequency_one,
            amplitude=args.amplitude,
            near_ultrasonic=args.near_ultrasonic,
        )
    except ValueError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        return 2

    if config.requires_near_ultrasonic_flag() and not args.near_ultrasonic:
        console.print(
            f"[red]Frequencies above {HIGH_FREQ_WARNING_HZ:.0f} Hz require "
            f"--near-ultrasonic[/red]"
        )
        return 2

    per_msg = estimate_duration(
        args.messages[0],
        args.symbol_duration,
        repeats=args.repeats,
        inter_frame_silence=args.inter_frame_silence,
    )
    console.print("[bold]Benchmark configuration[/bold]")
    console.print(f"  mode             = {'simulate' if args.simulate else 'live'}")
    console.print(f"  messages         = {args.messages}")
    console.print(f"  rounds           = {args.rounds}")
    console.print(f"  symbol_duration  = {args.symbol_duration}")
    console.print(f"  frequencies      = {config.frequency_zero}/{config.frequency_one}")
    console.print(f"  amplitude        = {args.amplitude}")
    console.print(f"  repeats          = {args.repeats}")
    console.print(f"  ~seconds/msg     = {per_msg:.1f}")

    results: List[TrialResult] = []
    rng = np.random.default_rng(args.seed)

    if not args.simulate:
        console.print(
            "[yellow]Live mode: keep mic ~20–50 cm from speaker, "
            "avoid feedback, volume moderate.[/yellow]"
        )

    for round_i in range(args.rounds):
        console.print(f"\n[bold]Round {round_i + 1}/{args.rounds}[/bold]")
        for message in args.messages:
            if args.simulate:
                trial = run_simulate_trial(message, config, args, rng)
            else:
                try:
                    trial = run_live_trial(message, config, args)
                except Exception as exc:
                    console.print(f"[red]Audio error:[/red] {exc}")
                    trial = TrialResult(
                        message=message,
                        success=False,
                        recovered=None,
                        ber=None,
                        snr_db=None,
                        clipping=False,
                        timing_offset=0,
                        error=str(exc),
                        duration_s=0.0,
                    )
            mark = "OK" if trial.success else "FAIL"
            ber_s = f"BER={trial.ber:.3f}" if trial.ber is not None else "BER=—"
            console.print(
                f"  [{mark}] {message!r} → {trial.recovered!r}  {ber_s}"
            )
            results.append(trial)

    summarize(results)
    ok = sum(1 for r in results if r.success)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
