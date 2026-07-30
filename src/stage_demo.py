"""Polished terminal stage demo for conference presentation."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from scipy.io import wavfile

from src.modulation import ModulationConfig, modulate
from src.protocol import encode_message, estimate_duration, validate_payload
from src.provenance import Provenance
from src.receiver import decode_from_samples
from src.safety import require_safe

console = Console()


def _panel(title: str, body: str, style: str = "cyan") -> Panel:
    return Panel(body, title=title, border_style=style)


def run_simulation_demo(message: str, modulation: str, profile_fast: bool = True) -> int:
    validate_payload(message)
    cfg = ModulationConfig()
    bits = encode_message(message)
    dur = estimate_duration(message, cfg.symbol_duration, repeats=1)
    require_safe(
        amplitude=cfg.amplitude,
        frequency_zero=cfg.frequency_zero,
        frequency_one=cfg.frequency_one,
        sample_rate=cfg.sample_rate,
        symbol_duration=cfg.symbol_duration,
        payload_bytes=len(message.encode("utf-8")),
        repeats=1,
        near_ultrasonic=False,
        estimated_duration_s=dur,
    )
    tx = modulate(bits, cfg, modulation=modulation)
    # Simulate mild channel
    rng = np.random.default_rng(1)
    rx = tx * 0.7 + rng.normal(0, 0.015, size=tx.shape)
    rx = np.concatenate([np.zeros(int(0.2 * cfg.sample_rate)), rx])

    mode = "SYNTHETIC SIMULATION"
    state = "TX"
    with Live(console=console, refresh_per_second=8) as live:
        live.update(
            _panel(
                mode,
                f"PAYLOAD: {message}\nMODULATION: {modulation}\n"
                f"f0/f1: {cfg.frequency_zero}/{cfg.frequency_one}\n"
                f"symbol: {cfg.symbol_duration}s\nSTATE: TRANSMITTING…",
            )
        )
        time.sleep(1.0)
        stats, _, result = decode_from_samples(
            rx, cfg, min_energy=1e-5, min_ratio=1.2, expected_bits=bits
        )
        crc = "CRC VALID" if stats.frame_success else f"CRC FAILED ({result.error})"
        live.update(
            _panel(
                mode,
                f"PAYLOAD: {message}\n"
                f"RECOVERED: {stats.recovered_message!r}\n"
                f"FRAME STATE: {'FRAME_DECODED' if stats.frame_success else 'FAILED'}\n"
                f"CRC STATUS: {crc}\n"
                f"BER: {stats.bit_error_rate}\n"
                f"TIMING OFFSET: {stats.timing_offset_samples} samples\n"
                f"PROVENANCE: {Provenance.SIMULATED_RX.value}",
                style="green" if stats.frame_success else "red",
            )
        )
        time.sleep(2.0)
    return 0 if stats.frame_success else 1


def run_replay_demo(wav_path: Path, message: Optional[str], modulation: str) -> int:
    from src.replay import load_capture

    sr, samples, meta = load_capture(wav_path)
    cfg = ModulationConfig(sample_rate=sr)
    expected = encode_message(message) if message else None
    console.print(
        Panel(
            f"[bold yellow]PHYSICAL CAPTURE REPLAY[/bold yellow]\n"
            f"file={wav_path}\nprovenance={meta.get('provenance')}",
            border_style="yellow",
        )
    )
    stats, _, result = decode_from_samples(
        samples, cfg, min_energy=1e-6, min_ratio=1.15, expected_bits=expected
    )
    table = Table(title="Replay decode")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("MODE", "PHYSICAL CAPTURE REPLAY")
    table.add_row("SUCCESS", str(stats.frame_success))
    table.add_row("RECOVERED", repr(stats.recovered_message))
    table.add_row("CRC", "VALID" if stats.frame_success else (result.error or "FAIL"))
    table.add_row("BER", str(stats.bit_error_rate))
    console.print(table)
    return 0 if stats.frame_success else 1


def run_live_demo(
    message: str,
    input_device: int,
    output_device: int,
    modulation: str,
) -> int:
    """Live physical demo: record while playing (same-host)."""
    import sounddevice as sd

    validate_payload(message)
    cfg = ModulationConfig()
    bits = encode_message(message)
    tx = modulate(bits, cfg, modulation=modulation).astype(np.float32)
    gap = 1.2
    total = gap + len(tx) / cfg.sample_rate + 1.0
    n = int(total * cfg.sample_rate)
    console.print(
        Panel(
            "[bold green]LIVE PHYSICAL CHANNEL[/bold green]\n"
            f"payload={message!r} modulation={modulation}\n"
            "Keep mic ~30 cm from speaker. Press Enter to start.",
            border_style="green",
        )
    )
    input()
    recorded: list[np.ndarray] = []

    def cb(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
        del frames, time_info, status
        recorded.append(indata.copy().reshape(-1))

    with sd.InputStream(
        samplerate=cfg.sample_rate,
        channels=1,
        dtype="float32",
        device=input_device,
        callback=cb,
    ):
        time.sleep(gap)
        sd.play(tx, samplerate=cfg.sample_rate, device=output_device)
        sd.wait()
        time.sleep(0.6)
    samples = np.concatenate(recorded).astype(np.float64) if recorded else np.zeros(n)
    out_dir = Path("experiments") / time.strftime("stage-%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    rx_path = out_dir / "rx.wav"
    tx_path = out_dir / "tx.wav"
    wavfile.write(str(tx_path), cfg.sample_rate, tx)
    wavfile.write(str(rx_path), cfg.sample_rate, samples.astype(np.float32))
    meta = {
        "provenance": Provenance.PHYSICAL_RX.value,
        "message": message,
        "modulation": modulation,
        "frequency_zero": cfg.frequency_zero,
        "frequency_one": cfg.frequency_one,
        "symbol_duration": cfg.symbol_duration,
    }
    (rx_path.with_suffix(".json")).write_text(json.dumps(meta, indent=2))
    (tx_path.with_suffix(".json")).write_text(
        json.dumps({**meta, "provenance": Provenance.GENERATED_TX.value}, indent=2)
    )
    stats, _, result = decode_from_samples(
        samples, cfg, min_energy=1e-6, min_ratio=1.15, expected_bits=bits
    )
    console.print(
        Panel(
            f"RECOVERED: {stats.recovered_message!r}\n"
            f"CRC: {'VALID' if stats.frame_success else result.error}\n"
            f"Saved: {out_dir}",
            title="LIVE PHYSICAL CHANNEL",
            border_style="green" if stats.frame_success else "red",
        )
    )
    return 0 if stats.frame_success else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.stage_demo")
    parser.add_argument("--wizard", action="store_true")
    parser.add_argument("--message", default="DEMO-LAB-2027")
    parser.add_argument("--modulation", choices=("bfsk", "cpfsk"), default="cpfsk")
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--replay", type=Path, default=None)
    parser.add_argument("--input-device", type=int, default=0)
    parser.add_argument("--output-device", type=int, default=0)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)

    if args.wizard:
        console.print(
            Panel(
                "Stage wizard\n"
                "1) Prefer --simulate for rehearsal\n"
                "2) Use --live for physical channel\n"
                "3) Use --replay <physical rx.wav> as fallback\n"
                "Running simulation rehearsal now…",
                title="WIZARD",
            )
        )
        return run_simulation_demo(args.message, args.modulation)

    if args.replay:
        return run_replay_demo(args.replay, args.message, args.modulation)
    if args.live:
        return run_live_demo(
            args.message, args.input_device, args.output_device, args.modulation
        )
    return run_simulation_demo(args.message, args.modulation)


if __name__ == "__main__":
    sys.exit(main())
