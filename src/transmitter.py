"""BFSK transmitter CLI — encodes a synthetic message and plays or saves it.

Only transmits manually supplied synthetic payloads (e.g. DEMO-LAB-2027).
Does not read files, credentials, clipboard, or network data.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
from rich.console import Console
from rich.panel import Panel
from scipy.io import wavfile

from src.modulation import (
    DEFAULT_AMPLITUDE,
    DEFAULT_FREQUENCY_ONE,
    DEFAULT_FREQUENCY_ZERO,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SYMBOL_DURATION,
    HIGH_FREQ_WARNING_HZ,
    ModulationConfig,
    bits_to_waveform,
)
from src.cli_common import add_profile_argument, apply_profile
from src.protocol import (
    MAX_PAYLOAD_BYTES,
    encode_message,
    estimate_duration,
    frame_bit_count,
    validate_payload,
)
from src.visualizer import save_spectrogram, save_waveform_plot

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.transmitter",
        description=(
            "Educational acoustic-channel transmitter (BFSK). "
            "Synthetic payloads only. Audible mode is the default. "
            "Default profile is fast (~8 bit/s)."
        ),
    )
    add_profile_argument(parser)
    parser.add_argument(
        "--message",
        required=True,
        help=f"Synthetic ASCII/UTF-8 payload (max {MAX_PAYLOAD_BYTES} bytes)",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help=f"Sample rate in Hz (default {DEFAULT_SAMPLE_RATE})",
    )
    parser.add_argument(
        "--symbol-duration",
        type=float,
        default=DEFAULT_SYMBOL_DURATION,
        help=f"Seconds per bit (default {DEFAULT_SYMBOL_DURATION})",
    )
    parser.add_argument(
        "--frequency-zero",
        type=float,
        default=DEFAULT_FREQUENCY_ZERO,
        help=f"BFSK frequency for bit 0 (default {DEFAULT_FREQUENCY_ZERO})",
    )
    parser.add_argument(
        "--frequency-one",
        type=float,
        default=DEFAULT_FREQUENCY_ONE,
        help=f"BFSK frequency for bit 1 (default {DEFAULT_FREQUENCY_ONE})",
    )
    parser.add_argument(
        "--amplitude",
        type=float,
        default=DEFAULT_AMPLITUDE,
        help=f"Peak amplitude (0, 0.5], default {DEFAULT_AMPLITUDE} (low)",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        choices=(1, 2, 3),
        help="Transmit the frame 1–3 times",
    )
    parser.add_argument(
        "--inter-frame-silence",
        type=float,
        default=0.25,
        help="Silence between repeated frames (seconds)",
    )
    parser.add_argument(
        "--near-ultrasonic",
        action="store_true",
        help="Required when using frequencies above 17 kHz",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate signal/plots without playing audio",
    )
    parser.add_argument(
        "--output-device",
        type=int,
        default=None,
        help="PortAudio output device index",
    )
    parser.add_argument(
        "--save-wav",
        type=Path,
        default=None,
        help="Path to save generated WAV",
    )
    parser.add_argument(
        "--spectrogram",
        type=Path,
        default=None,
        help="Path to save spectrogram PNG",
    )
    parser.add_argument(
        "--waveform-plot",
        type=Path,
        default=None,
        help="Path to save waveform PNG",
    )
    return parser


def _warn_high_frequency(config: ModulationConfig) -> None:
    console.print(
        Panel(
            f"[bold yellow]WARNING[/bold yellow]\n\n"
            f"Frequencies above {HIGH_FREQ_WARNING_HZ:.0f} Hz are requested "
            f"(max={config.max_frequency:.0f} Hz).\n"
            "Many speakers, microphones, codecs, and analogue filters "
            "attenuate or block energy near or above 18–20 kHz.\n"
            "Keep volume low. Prefer wired devices. This is an experimental "
            "lab mode for an authorized demo only.",
            title="Near-ultrasonic / high-frequency warning",
            border_style="yellow",
        )
    )


def log_config(config: ModulationConfig, message: str, **extra: object) -> None:
    console.print("[bold]Active transmitter configuration[/bold]")
    console.print(f"  message          = {message!r}")
    console.print(f"  sample_rate      = {config.sample_rate}")
    console.print(f"  symbol_duration  = {config.symbol_duration}")
    console.print(f"  frequency_zero   = {config.frequency_zero}")
    console.print(f"  frequency_one    = {config.frequency_one}")
    console.print(f"  amplitude        = {config.amplitude}")
    console.print(f"  near_ultrasonic  = {config.near_ultrasonic}")
    for key, value in extra.items():
        console.print(f"  {key:17}= {value}")


def save_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # float32 WAV; amplitude already low
    wavfile.write(str(path), sample_rate, samples.astype(np.float32))
    console.print(f"Saved WAV: {path}")


def play_waveform(
    samples: np.ndarray,
    sample_rate: int,
    output_device: Optional[int],
) -> None:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is required for playback") from exc

    if output_device is not None:
        from src.audio_devices import validate_output_device

        validate_output_device(output_device)

    console.print(
        "[yellow]Playing at low amplitude. "
        "Ensure speakers are not at maximum volume.[/yellow]"
    )
    sd.play(samples.astype(np.float32), samplerate=sample_rate, device=output_device)
    sd.wait()


def generate_signal(
    message: str,
    config: ModulationConfig,
    repeats: int = 1,
    inter_frame_silence: float = 0.25,
) -> np.ndarray:
    bits = encode_message(message)
    return bits_to_waveform(
        bits,
        config,
        inter_frame_silence=inter_frame_silence,
        repeats=repeats,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args = apply_profile(args, argv)

    try:
        validate_payload(args.message)
    except Exception as exc:
        console.print(f"[red]Payload error:[/red] {exc}")
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

    if config.requires_near_ultrasonic_flag():
        _warn_high_frequency(config)
        time.sleep(1.0)

    duration = estimate_duration(
        args.message,
        args.symbol_duration,
        repeats=args.repeats,
        inter_frame_silence=args.inter_frame_silence,
    )
    n_bits = frame_bit_count(len(args.message.encode("utf-8")))
    log_config(
        config,
        args.message,
        repeats=args.repeats,
        inter_frame_silence=args.inter_frame_silence,
        dry_run=args.dry_run,
        bits_per_frame=n_bits,
        expected_duration_s=f"{duration:.2f}",
    )

    console.print(
        f"[bold]Expected transmission duration:[/bold] {duration:.2f} s "
        f"({n_bits} bits/frame × {args.repeats} repeat(s))"
    )

    try:
        waveform = generate_signal(
            args.message,
            config,
            repeats=args.repeats,
            inter_frame_silence=args.inter_frame_silence,
        )
    except Exception as exc:
        console.print(f"[red]Modulation error:[/red] {exc}")
        return 1

    peak = float(np.max(np.abs(waveform))) if len(waveform) else 0.0
    console.print(f"Waveform samples={len(waveform)}, peak_amplitude={peak:.4f}")

    if args.save_wav:
        save_wav(args.save_wav, waveform, config.sample_rate)
    if args.spectrogram:
        fmin = max(0, min(config.frequency_zero, config.frequency_one) - 2000)
        fmax = min(
            config.sample_rate / 2,
            max(config.frequency_zero, config.frequency_one) + 2000,
        )
        save_spectrogram(
            waveform,
            config.sample_rate,
            args.spectrogram,
            title=f"BFSK spectrogram — {args.message!r}",
            fmin=fmin,
            fmax=fmax,
        )
        console.print(f"Saved spectrogram: {args.spectrogram}")
    if args.waveform_plot:
        save_waveform_plot(
            waveform,
            config.sample_rate,
            args.waveform_plot,
            title=f"Waveform — {args.message!r}",
        )
        console.print(f"Saved waveform plot: {args.waveform_plot}")

    if args.dry_run:
        console.print("[green]Dry-run complete — no audio played.[/green]")
        return 0

    try:
        play_waveform(waveform, config.sample_rate, args.output_device)
    except Exception as exc:
        console.print(f"[red]Playback error:[/red] {exc}")
        console.print(
            "Tip: check device index with python -m src.audio_devices; "
            "see README troubleshooting for PortAudioError / PipeWire."
        )
        return 1

    console.print("[green]Transmission finished.[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
