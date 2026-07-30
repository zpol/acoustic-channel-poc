"""Live terminal monitor: waveform, tone energies, bits → recovered message.

Conference-friendly real-time view of the acoustic receive path.

Examples::

    # Listen only (wait for a transmitter)
    python -m src.live_monitor --duration 25

    # Self-demo: start monitor then auto-TX (local two-process)
    python -m src.live_monitor --self-tx --message DEMO-LAB-2027

    # Remote TX laptop emits; this host captures
    python -m src.live_monitor --remote-tx nkn@192.168.68.109 \\
        --remote-output-device 1 --message DEMO-LAB-2027
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.modulation import (
    ModulationConfig,
    decide_symbol,
)
from src.protocol import decode_bits, encode_message, estimate_duration
from src.provenance import Provenance
from src.receiver import decode_from_samples
from src.synchronization import find_sync_correlation

console = Console()


def _sparkline(samples: np.ndarray, width: int = 64) -> str:
    if len(samples) == 0:
        return " " * width
    blocks = " ▁▂▃▄▅▆▇█"
    # downsample
    n = max(1, len(samples) // width)
    vals = []
    for i in range(width):
        chunk = samples[i * n : (i + 1) * n]
        vals.append(float(np.max(np.abs(chunk))) if len(chunk) else 0.0)
    peak = max(vals) if vals else 1.0
    peak = peak if peak > 1e-9 else 1.0
    return "".join(blocks[min(8, int(v / peak * 8))] for v in vals)


def _bar(value: float, max_value: float, width: int = 24) -> str:
    if max_value <= 0:
        filled = 0
    else:
        filled = int(round(width * min(1.0, value / max_value)))
    return "█" * filled + "░" * (width - filled)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m src.live_monitor")
    p.add_argument("--input-device", type=int, default=0)
    p.add_argument("--output-device", type=int, default=0)
    p.add_argument("--duration", type=float, default=20.0)
    p.add_argument("--sample-rate", type=int, default=48000)
    p.add_argument("--symbol-duration", type=float, default=0.12)
    p.add_argument("--frequency-zero", type=float, default=3500.0)
    p.add_argument("--frequency-one", type=float, default=7500.0)
    p.add_argument("--modulation", choices=("bfsk", "cpfsk"), default="cpfsk")
    p.add_argument("--fec", choices=("none", "hamming74"), default="none")
    p.add_argument("--message", default="DEMO-LAB-2027")
    p.add_argument("--amplitude", type=float, default=0.25)
    p.add_argument("--min-ratio", type=float, default=1.12)
    p.add_argument("--self-tx", action="store_true", help="Local two-process auto TX")
    p.add_argument("--remote-tx", default=None, help="SSH host for remote TX")
    p.add_argument("--remote-dir", default="~/lab/acoustic-channel-poc")
    p.add_argument("--remote-output-device", type=int, default=1)
    p.add_argument("--near-ultrasonic", action="store_true")
    p.add_argument("--chunk-ms", type=float, default=40.0, help="UI refresh chunk size")
    return p


def _render(
    mode: str,
    cfg: ModulationConfig,
    wave_chunk: np.ndarray,
    e0: float,
    e1: float,
    emax: float,
    bit: str,
    soft_bits: List[int],
    sync_state: str,
    recovered: str,
    crc: str,
    progress_s: float,
    duration_s: float,
    notes: str,
) -> Group:
    header = Table.grid(expand=True)
    header.add_column(ratio=1)
    header.add_column(ratio=1)
    header.add_row(
        Panel(
            f"[bold]{mode}[/bold]\n"
            f"f0={cfg.frequency_zero:.0f}  f1={cfg.frequency_one:.0f}\n"
            f"Tsym={cfg.symbol_duration:.3f}s\n"
            f"t={progress_s:.1f}/{duration_s:.1f}s",
            title="MODE",
            border_style="magenta",
        ),
        Panel(
            f"SYNC: [bold]{sync_state}[/bold]\n"
            f"CRC: {crc}\n"
            f"BITS: {len(soft_bits)}\n"
            f"NOTE: {notes}",
            title="FRAME",
            border_style="cyan",
        ),
    )
    wave = Panel(
        Text(_sparkline(wave_chunk, 72), style="bright_green"),
        title="WAVEFORM (live mic)",
        border_style="green",
    )
    energies = Panel(
        f"f0 {_bar(e0, emax)} {e0:.2e}\n"
        f"f1 {_bar(e1, emax)} {e1:.2e}\n"
        f"bit → [bold yellow]{bit}[/bold yellow]",
        title="TONE ENERGY",
        border_style="yellow",
    )
    bit_str = "".join(str(b) for b in soft_bits[-64:])
    bits_panel = Panel(
        bit_str if bit_str else "(listening…)",
        title="RECENT SOFT BITS",
        border_style="blue",
    )
    msg_panel = Panel(
        f"[bold white]{recovered or '—'}[/bold white]",
        title="RECOVERED MESSAGE",
        border_style="bright_white",
    )
    return Group(header, wave, energies, bits_panel, msg_panel)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = ModulationConfig(
        sample_rate=args.sample_rate,
        symbol_duration=args.symbol_duration,
        frequency_zero=args.frequency_zero,
        frequency_one=args.frequency_one,
        amplitude=args.amplitude,
        near_ultrasonic=args.near_ultrasonic or args.frequency_one > 17000,
    )
    if cfg.requires_near_ultrasonic_flag() and not args.near_ultrasonic:
        console.print("[red]Need --near-ultrasonic for carriers > 17 kHz[/red]")
        return 2

    try:
        import sounddevice as sd
    except ImportError as exc:
        console.print(f"[red]sounddevice required:[/red] {exc}")
        return 1

    duration = args.duration
    if args.self_tx or args.remote_tx:
        duration = estimate_duration(
            args.message,
            cfg.symbol_duration,
            repeats=2,
            inter_frame_silence=0.3,
            fec=args.fec,
        ) + 5.0

    mode = "LIVE PHYSICAL CHANNEL"
    provenance = Provenance.PHYSICAL_RX.value
    if args.remote_tx:
        mode = "LIVE PHYSICAL CHANNEL (remote TX)"
    elif args.self_tx:
        mode = "LIVE PHYSICAL CHANNEL (local self-TX)"

    chunk = int(args.chunk_ms / 1000.0 * cfg.sample_rate)
    sps = cfg.samples_per_symbol
    full_audio = np.zeros(0, dtype=np.float64)
    symbol_cursor = 0
    soft_bits: List[int] = []
    recovered = ""
    crc = "—"
    sync_state = "NO_SIGNAL"
    notes = provenance
    emax = 1e-6
    tx_proc: Optional[subprocess.Popen] = None
    expected = encode_message(args.message, fec=args.fec)
    last_offline = 0.0

    # Start recording stream
    q: List[np.ndarray] = []

    def callback(indata, frames, time_info, status):  # noqa: ANN001
        q.append(np.asarray(indata[:, 0], dtype=np.float64).copy())

    stream = sd.InputStream(
        samplerate=cfg.sample_rate,
        channels=1,
        dtype="float32",
        device=args.input_device,
        blocksize=chunk,
        callback=callback,
    )

    # Launch TX after stream starts
    def launch_tx() -> None:
        nonlocal tx_proc
        if args.self_tx:
            tx_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "src.transmitter",
                    "--message",
                    args.message,
                    "--output-device",
                    str(args.output_device),
                    "--symbol-duration",
                    str(cfg.symbol_duration),
                    "--frequency-zero",
                    str(cfg.frequency_zero),
                    "--frequency-one",
                    str(cfg.frequency_one),
                    "--amplitude",
                    str(args.amplitude),
                    "--repeats",
                    "2",
                    "--inter-frame-silence",
                    "0.3",
                    "--modulation",
                    args.modulation,
                    "--fec",
                    args.fec,
                ]
                + (["--near-ultrasonic"] if args.near_ultrasonic else []),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif args.remote_tx:
            remote = (
                f"cd {args.remote_dir} && . .venv/bin/activate && export PYTHONPATH=. && "
                f"python -m src.transmitter --message {args.message!r} "
                f"--output-device {args.remote_output_device} "
                f"--symbol-duration {cfg.symbol_duration} "
                f"--frequency-zero {cfg.frequency_zero} "
                f"--frequency-one {cfg.frequency_one} "
                f"--amplitude {args.amplitude} --repeats 2 "
                f"--inter-frame-silence 0.3 --modulation {args.modulation} "
                f"--fec {args.fec}"
                + (" --near-ultrasonic" if args.near_ultrasonic else "")
            )
            tx_proc = subprocess.Popen(
                ["ssh", args.remote_tx, remote],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    t0 = time.time()
    stream.start()
    time.sleep(0.4)
    if args.self_tx or args.remote_tx:
        launch_tx()

    last_wave = np.zeros(chunk)
    e0 = e1 = 0.0
    bit = "?"

    try:
        with Live(console=console, refresh_per_second=12) as live:
            while time.time() - t0 < duration:
                while q:
                    block = q.pop(0)
                    last_wave = block
                    full_audio = np.concatenate([full_audio, block])
                # Live per-symbol energies (coarse; may drift)
                while symbol_cursor + sps <= len(full_audio):
                    sym = full_audio[symbol_cursor : symbol_cursor + sps]
                    symbol_cursor += sps
                    d = decide_symbol(sym, cfg, min_energy=1e-6, min_ratio=args.min_ratio)
                    e0, e1 = d.energy_zero, d.energy_one
                    emax = max(emax, e0, e1, 1e-6)
                    bit = str(d.bit) if d.bit is not None else "?"
                    soft_bits.append(1 if e1 >= e0 else 0)

                now = time.time()
                # Robust offline decode every ~1.2s once we have enough audio
                if (
                    crc != "CRC VALID"
                    and now - last_offline > 1.2
                    and len(full_audio) > sps * 40
                ):
                    last_offline = now
                    stats, _, result = decode_from_samples(
                        full_audio.copy(),
                        cfg,
                        min_energy=1e-6,
                        min_ratio=args.min_ratio,
                        expected_bits=expected,
                        fec=args.fec,
                        sync_mode="correlation",
                        timing_steps=16,
                    )
                    sync_state = stats.sync_state
                    if stats.frame_success and stats.recovered_message:
                        recovered = stats.recovered_message
                        crc = "CRC VALID"
                        sync_state = "CRC_VALID"
                        notes = f"{provenance} | offline decode locked"
                    elif result.error:
                        if "CRC" in (result.error or ""):
                            crc = "CRC FAILED"
                        elif soft_bits:
                            sync = find_sync_correlation(soft_bits, max_hamming=2)
                            sync_state = sync.state

                live.update(
                    _render(
                        mode,
                        cfg,
                        last_wave,
                        e0,
                        e1,
                        emax,
                        bit,
                        soft_bits,
                        sync_state,
                        recovered,
                        crc,
                        time.time() - t0,
                        duration,
                        notes,
                    )
                )
                time.sleep(args.chunk_ms / 1000.0)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
    finally:
        stream.stop()
        stream.close()
        if tx_proc is not None:
            try:
                tx_proc.wait(timeout=5)
            except Exception:
                tx_proc.kill()

    # Final offline decode
    if crc != "CRC VALID" and len(full_audio) > sps * 20:
        stats, _, result = decode_from_samples(
            full_audio,
            cfg,
            min_energy=1e-6,
            min_ratio=args.min_ratio,
            expected_bits=expected,
            fec=args.fec,
            sync_mode="correlation",
        )
        if stats.frame_success and stats.recovered_message:
            recovered = stats.recovered_message
            crc = "CRC VALID"
            sync_state = "CRC_VALID"
        elif result.error:
            crc = result.error

    console.print(
        Panel(
            f"Recovered: {recovered!r}\nCRC: {crc}\nSync: {sync_state}\n"
            f"Soft bits: {len(soft_bits)}\nAudio samples: {len(full_audio)}\n"
            f"Provenance: {provenance}",
            title="RESULT",
            border_style="green" if crc == "CRC VALID" else "red",
        )
    )
    return 0 if crc == "CRC VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
