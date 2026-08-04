"""Live terminal monitor for the acoustic receive path.

Recording uses ``sounddevice.rec`` + ``wait`` on a background thread
(no Python PortAudio callback). Mid-stream ``decode_from_samples`` is
never run — it held the GIL and caused input overflows. Full decode
runs once after capture completes.

Examples::

    python -m src.live_monitor --remote-tx demo-user@tx-host \\
        --remote-output-device 1 --message DEMO-LAB-2027 --modulation cpfsk
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from scipy.io import wavfile

from src.modulation import ModulationConfig, goertzel
from src.protocol import encode_message, estimate_duration
from src.provenance import Provenance
from src.receiver import decode_from_samples
from src.safety import SafetyError, assert_playback_allowed

console = Console()


def _sparkline(samples: np.ndarray, width: int = 64) -> str:
    if len(samples) == 0:
        return "░" * width
    blocks = " ▁▂▃▄▅▆▇█"
    n = max(1, len(samples) // width)
    vals = []
    for i in range(width):
        chunk = samples[i * n : (i + 1) * n]
        vals.append(float(np.max(np.abs(chunk))) if len(chunk) else 0.0)
    peak = max(vals) or 1.0
    return "".join(blocks[min(8, int(v / peak * 8))] for v in vals)


def _bar(value: float, max_value: float, width: int = 24) -> str:
    filled = int(round(width * min(1.0, value / max_value))) if max_value > 0 else 0
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
    p.add_argument("--amplitude", type=float, default=0.28)
    p.add_argument("--min-ratio", type=float, default=1.12)
    p.add_argument("--repeats", type=int, default=2, choices=(1, 2, 3))
    p.add_argument("--self-tx", action="store_true")
    p.add_argument(
        "--remote-tx",
        default=None,
        help="SSH host for remote TX playback only "
        "(or set ACOUSTIC_REMOTE_TX). Public docs use demo-user@tx-host.",
    )
    p.add_argument(
        "--remote-dir",
        default=None,
        help="Remote repository path (or ACOUSTIC_REMOTE_DIR). Placeholder: /path/to/repository",
    )
    p.add_argument("--remote-output-device", type=int, default=1)
    p.add_argument("--near-ultrasonic", action="store_true")
    p.add_argument("--tx-delay", type=float, default=2.5)
    p.add_argument("--save-wav", type=Path, default=None)
    p.add_argument(
        "--bandpass",
        action="store_true",
        help="Enable RX bandpass (off by default; can flip CRC bits on some physical captures)",
    )
    p.add_argument(
        "--no-bandpass",
        action="store_true",
        help="Deprecated alias: bandpass is already off by default",
    )
    p.add_argument(
        "--sync-mode",
        choices=("legacy", "correlation"),
        default="correlation",
    )
    p.add_argument(
        "--frequency-search-hz",
        type=float,
        default=None,
        help="Carrier neighbourhood search (±Hz). Default 150 for near-US, 0 otherwise.",
    )
    p.add_argument(
        "--frequency-search-step-hz",
        type=float,
        default=25.0,
        help="Step for carrier neighbourhood search",
    )
    p.add_argument(
        "--tail-seconds",
        type=float,
        default=None,
        help="Extra listen time after TX (default 4s, 6s if near-US)",
    )
    return p


def _render(
    mode: str,
    cfg: ModulationConfig,
    wave: np.ndarray,
    e0: float,
    e1: float,
    emax: float,
    bit: str,
    status: str,
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
            f"STATUS: [bold]{status}[/bold]\nCRC: {crc}\nNOTE: {notes}",
            title="FRAME",
            border_style="cyan",
        ),
    )
    return Group(
        header,
        Panel(
            Text(_sparkline(wave, 72), style="bright_green"),
            title="WAVEFORM (live mic buffer)",
            border_style="green",
        ),
        Panel(
            f"f0 {_bar(e0, emax)} {e0:.2e}\n"
            f"f1 {_bar(e1, emax)} {e1:.2e}\n"
            f"bit → [bold yellow]{bit}[/bold yellow]",
            title="TONE ENERGY (from capture buffer)",
            border_style="yellow",
        ),
        Panel(
            f"[bold white]{recovered or '—'}[/bold white]",
            title="RECOVERED MESSAGE",
            border_style="bright_white",
        ),
    )


def _launch_remote_tx(args: argparse.Namespace, cfg: ModulationConfig) -> subprocess.Popen:
    import shlex

    # Single-quote for the remote shell so $, !, etc. are not expanded (e.g. p4$$w0rd).
    msg_q = shlex.quote(args.message)
    remote = (
        f"cd {shlex.quote(str(args.remote_dir))} && . .venv/bin/activate && "
        f"export PYTHONPATH=. && "
        f"python -m src.transmitter --message {msg_q} "
        f"--output-device {int(args.remote_output_device)} "
        f"--symbol-duration {cfg.symbol_duration} "
        f"--frequency-zero {cfg.frequency_zero} "
        f"--frequency-one {cfg.frequency_one} "
        f"--amplitude {args.amplitude} --repeats {args.repeats} "
        f"--inter-frame-silence 0.3 --modulation {args.modulation} "
        f"--fec {args.fec}"
        + (" --near-ultrasonic" if args.near_ultrasonic else "")
    )
    return subprocess.Popen(
        ["ssh", args.remote_tx, remote],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _launch_local_tx(args: argparse.Namespace, cfg: ModulationConfig) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "src.transmitter",
        "--message", args.message,
        "--output-device", str(args.output_device),
        "--symbol-duration", str(cfg.symbol_duration),
        "--frequency-zero", str(cfg.frequency_zero),
        "--frequency-one", str(cfg.frequency_one),
        "--amplitude", str(args.amplitude),
        "--repeats", str(args.repeats),
        "--inter-frame-silence", "0.3",
        "--modulation", args.modulation,
        "--fec", args.fec,
    ]
    if args.near_ultrasonic:
        cmd.append("--near-ultrasonic")
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.remote_tx:
        import os

        args.remote_tx = os.environ.get("ACOUSTIC_REMOTE_TX") or None
    if not args.remote_dir:
        import os

        args.remote_dir = os.environ.get("ACOUSTIC_REMOTE_DIR") or "/path/to/repository"
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

    auto_tx = bool(args.self_tx or args.remote_tx)
    if auto_tx:
        try:
            assert_playback_allowed(
                config=cfg,
                payload=args.message,
                repeats=args.repeats,
                inter_frame_silence=0.3,
                near_ultrasonic=bool(args.near_ultrasonic),
                fec=args.fec,
            )
        except SafetyError as exc:
            console.print(f"[red]Safety rejection:[/red] {exc}")
            return 2

    try:
        import sounddevice as sd
    except ImportError as exc:
        console.print(f"[red]sounddevice required:[/red] {exc}")
        return 1

    if auto_tx:
        tx_dur = estimate_duration(
            args.message, cfg.symbol_duration,
            repeats=args.repeats, inter_frame_silence=0.3, fec=args.fec,
        )
        tail = args.tail_seconds
        if tail is None:
            tail = 6.0 if args.near_ultrasonic else 4.0
        duration = args.tx_delay + tx_dur + float(tail)
        freq_search = args.frequency_search_hz
        if freq_search is None:
            freq_search = 150.0 if args.near_ultrasonic else 0.0
        args.frequency_search_hz = float(freq_search)
        if args.near_ultrasonic and args.min_ratio >= 1.12:
            # Slightly looser tone decisions for weak HF response
            args.min_ratio = 1.08
        console.print(
            f"[cyan]Auto-TX armed:[/cyan] message={args.message!r} "
            f"tx≈{tx_dur:.1f}s listen≈{duration:.1f}s "
            f"({args.repeats}× {args.modulation} fec={args.fec})\n"
            f"  RX: min_ratio={args.min_ratio} "
            f"freq_search=±{args.frequency_search_hz:.0f}Hz "
            f"bandpass={'on' if args.bandpass else 'off'}"
        )
    else:
        duration = args.duration
        if args.frequency_search_hz is None:
            args.frequency_search_hz = 150.0 if args.near_ultrasonic else 0.0

    mode = "LIVE PHYSICAL CHANNEL"
    provenance = Provenance.PHYSICAL_RX.value
    if args.remote_tx:
        mode = "LIVE PHYSICAL CHANNEL (remote TX)"
    elif args.self_tx:
        mode = "LIVE PHYSICAL CHANNEL (local self-TX)"

    n_samples = int(round(duration * cfg.sample_rate))
    rec_error: List[str] = []
    # Hold the live buffer reference from sd.rec
    nonlocal_buf: List[Optional[np.ndarray]] = [None]

    def _recorder() -> None:
        try:
            buf = sd.rec(
                n_samples,
                samplerate=cfg.sample_rate,
                channels=1,
                dtype="float32",
                device=args.input_device,
                blocking=False,
            )
            nonlocal_buf[0] = buf
            sd.wait()
        except Exception as exc:  # noqa: BLE001
            rec_error.append(str(exc))

    rec_thread = threading.Thread(target=_recorder, daemon=True)
    rec_thread.start()
    # Give PortAudio a moment to arm
    time.sleep(0.15)

    tx_proc: Optional[subprocess.Popen] = None
    tx_started = False
    tx_err = ""
    status = "LISTENING"
    notes = f"{provenance} | sd.rec thread (decode after capture)"
    recovered = ""
    crc = "—"
    e0 = e1 = 0.0
    emax = 1e-6
    bit = "?"
    expected = encode_message(args.message, fec=args.fec)
    t0 = time.time()
    window = int(0.05 * cfg.sample_rate)

    try:
        with Live(console=console, refresh_per_second=8) as live:
            while time.time() - t0 < duration:
                elapsed = time.time() - t0
                if auto_tx and not tx_started and elapsed >= args.tx_delay:
                    status = "TRANSMITTING"
                    notes = "TX started"
                    tx_proc = (
                        _launch_remote_tx(args, cfg)
                        if args.remote_tx
                        else _launch_local_tx(args, cfg)
                    )
                    tx_started = True

                live_buf = nonlocal_buf[0]
                wave = np.zeros(window)
                if live_buf is not None:
                    # Approximate write cursor from elapsed time
                    cursor = min(len(live_buf), max(window, int(elapsed * cfg.sample_rate)))
                    chunk = np.asarray(live_buf[:cursor], dtype=np.float64).reshape(-1)
                    if len(chunk) >= window:
                        wave = chunk[-window:]
                        search = float(args.frequency_search_hz or 0.0)
                        if search > 0:
                            from src.synchronization import goertzel_neighbourhood

                            _, e0 = goertzel_neighbourhood(
                                wave,
                                cfg.frequency_zero,
                                cfg.sample_rate,
                                search_hz=search,
                                step_hz=float(args.frequency_search_step_hz),
                            )
                            _, e1 = goertzel_neighbourhood(
                                wave,
                                cfg.frequency_one,
                                cfg.sample_rate,
                                search_hz=search,
                                step_hz=float(args.frequency_search_step_hz),
                            )
                        else:
                            e0 = goertzel(wave, cfg.frequency_zero, cfg.sample_rate)
                            e1 = goertzel(wave, cfg.frequency_one, cfg.sample_rate)
                        emax = max(emax, e0, e1, 1e-6)
                        bit = "1" if e1 >= e0 else "0"

                if tx_proc is not None and tx_proc.poll() is not None and status == "TRANSMITTING":
                    if tx_proc.returncode == 0:
                        status = "TX DONE — trailing capture"
                        notes = "TX finished"
                    else:
                        status = "TX ERROR"
                        out = (tx_proc.stdout.read() if tx_proc.stdout else "") or ""
                        err = (tx_proc.stderr.read() if tx_proc.stderr else "") or ""
                        tx_err = (err or out)[-400:]
                        notes = f"TX rc={tx_proc.returncode}"

                live.update(
                    _render(
                        mode, cfg, wave, e0, e1, emax, bit,
                        status, recovered, crc, elapsed, duration, notes,
                    )
                )
                time.sleep(0.1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted — waiting for recorder[/yellow]")
    finally:
        rec_thread.join(timeout=duration + 10)
        if tx_proc is not None and tx_proc.poll() is None:
            try:
                tx_proc.wait(timeout=5)
            except Exception:
                tx_proc.kill()
        if tx_proc is not None and tx_proc.returncode not in (0, None) and not tx_err:
            tx_err = ((tx_proc.stderr.read() if tx_proc.stderr else "") or "")[-400:]

    if rec_error:
        console.print(f"[red]Recorder error:[/red] {rec_error[0]}")
        return 1

    live_buf = nonlocal_buf[0]
    if live_buf is None:
        console.print("[red]No recording buffer[/red]")
        return 1
    full_audio = np.asarray(live_buf, dtype=np.float64).reshape(-1)

    if args.save_wav:
        args.save_wav.parent.mkdir(parents=True, exist_ok=True)
        wavfile.write(str(args.save_wav), cfg.sample_rate, full_audio.astype(np.float32))
        console.print(f"Saved capture: {args.save_wav}")

    console.print(
        f"[cyan]Capture done:[/cyan] samples={len(full_audio)} "
        f"({len(full_audio)/cfg.sample_rate:.1f}s) "
        f"peak={float(np.max(np.abs(full_audio))):.3f} — full decode…"
    )
    if tx_err:
        console.print(f"[red]TX diagnostics:[/red] {tx_err}")

    stats, _, result = decode_from_samples(
        full_audio,
        cfg,
        min_energy=1e-6,
        min_ratio=args.min_ratio,
        expected_bits=expected,
        fec=args.fec,
        sync_mode=args.sync_mode,
        timing_steps=24,
        apply_bandpass=bool(args.bandpass) and not args.no_bandpass,
        frequency_search_hz=float(args.frequency_search_hz or 0.0),
        frequency_search_step_hz=float(args.frequency_search_step_hz),
        symbol_duration_search_percent=3.0 if args.near_ultrasonic else 2.5,
        symbol_duration_search_steps=7,
    )
    if stats.frame_success and stats.recovered_message:
        recovered = stats.recovered_message
        crc = "CRC VALID"
        status = "CRC_VALID"
    else:
        recovered = stats.recovered_message or ""
        crc = result.error or "decode failed"
        status = stats.sync_state or "FAILED"

    console.print(
        Panel(
            f"Recovered: {recovered!r}\nCRC: {crc}\nStatus: {status}\n"
            f"Audio samples: {len(full_audio)}\nProvenance: {provenance}",
            title="RESULT",
            border_style="green" if crc == "CRC VALID" else "red",
        )
    )
    return 0 if crc == "CRC VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
