"""Polished terminal stage demo for conference presentation.

Modes (never conflated):
  LIVE AUDIBLE
  LIVE NEAR-ULTRASONIC EXPERIMENTAL
  PHYSICAL CAPTURE REPLAY
  SIMULATION

All decoding uses the production ``decode_from_samples`` pipeline.
All real playback calls centralized safety validation first.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from scipy.io import wavfile

from src.modulation import ModulationConfig, modulate
from src.protocol import encode_message, estimate_duration, validate_payload
from src.provenance import Provenance, ProvenanceError, SCHEMA_VERSION, sha256_file
from src.receiver import decode_from_samples
from src.replay import (
    config_from_metadata,
    load_verified_physical_capture,
    print_loaded_config,
)
from src.safety import SafetyError, assert_playback_allowed

console = Console()

DEFAULT_DEMO_CONFIG = Path("configs/conference-audible-demo.yaml")


def _panel(title: str, body: str, style: str = "cyan") -> Panel:
    return Panel(body, title=title, border_style=style)


def _load_yaml_config(path: Path) -> dict:
    raw = path.read_text()
    try:
        import yaml  # type: ignore

        return dict(yaml.safe_load(raw) or {})
    except Exception:
        # Minimal YAML subset for our flat conference config
        out: dict = {}
        notes: list = []
        in_notes = False
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("notes:"):
                in_notes = True
                continue
            if in_notes and s.startswith("- "):
                notes.append(s[2:].strip().strip("'\""))
                continue
            in_notes = False
            if ":" in s:
                k, v = s.split(":", 1)
                out[k.strip()] = v.strip().strip("'\"")
        if notes:
            out["notes"] = notes
        return out


def config_from_demo_file(path: Path) -> ModulationConfig:
    data = _load_yaml_config(path)
    return ModulationConfig(
        sample_rate=int(float(data.get("sample_rate", 48000))),
        symbol_duration=float(data.get("symbol_duration_seconds", 0.07)),
        frequency_zero=float(data.get("frequency_zero_hz", 3000)),
        frequency_one=float(data.get("frequency_one_hz", 8000)),
        amplitude=float(data.get("amplitude", 0.28)),
        near_ultrasonic=False,
    )


def run_simulation_demo(
    message: str,
    modulation: str,
    cfg: Optional[ModulationConfig] = None,
    fec: str = "none",
) -> int:
    validate_payload(message)
    cfg = cfg or ModulationConfig()
    bits = encode_message(message, fec=fec)
    dur = estimate_duration(message, cfg.symbol_duration, repeats=1, fec=fec)
    assert_playback_allowed(
        config=cfg,
        payload=message,
        repeats=1,
        near_ultrasonic=False,
        fec=fec,
    )
    tx = modulate(bits, cfg, modulation=modulation)
    rng = np.random.default_rng(1)
    rx = tx * 0.7 + rng.normal(0, 0.015, size=tx.shape)
    rx = np.concatenate([np.zeros(int(0.2 * cfg.sample_rate)), rx])

    mode = "SIMULATION"
    with Live(console=console, refresh_per_second=8) as live:
        live.update(
            _panel(
                mode,
                f"PAYLOAD: {message}\nMODULATION: {modulation}\n"
                f"FEC: {fec}\n"
                f"f0/f1: {cfg.frequency_zero}/{cfg.frequency_one}\n"
                f"symbol: {cfg.symbol_duration}s\nSTATE: DECODING…\n"
                f"PROVENANCE: {Provenance.SIMULATED_RX.value}",
            )
        )
        time.sleep(0.4)
        stats, _, result = decode_from_samples(
            rx,
            cfg,
            min_energy=1e-5,
            min_ratio=1.2,
            expected_bits=bits,
            fec=fec,
            sync_mode="correlation",
        )
        crc = "CRC VALID" if stats.frame_success else f"CRC FAILED ({result.error})"
        live.update(
            _panel(
                mode,
                f"PAYLOAD: {message}\n"
                f"RECOVERED: {stats.recovered_message!r}\n"
                f"FRAME STATE: {'FRAME_DECODED' if stats.frame_success else 'FAILED'}\n"
                f"CRC STATUS: {crc}\n"
                f"FEC syndrome_corrections_attempted: "
                f"{stats.syndrome_corrections_attempted}\n"
                f"post_fec_crc_valid: {stats.post_fec_crc_valid}\n"
                f"BER: {stats.bit_error_rate}\n"
                f"sync_score: {stats.sync_score:.3f}\n"
                f"TIMING OFFSET: {stats.timing_offset_samples} samples\n"
                f"PROVENANCE: {Provenance.SIMULATED_RX.value}",
                style="green" if stats.frame_success else "red",
            )
        )
        time.sleep(1.2)
    return 0 if stats.frame_success else 1


def run_replay_demo(wav_path: Path, message: Optional[str] = None) -> int:
    try:
        samples, meta = load_verified_physical_capture(wav_path)
    except ProvenanceError as exc:
        console.print(f"[red]Replay rejected:[/red] {exc}")
        return 2
    print_loaded_config(meta)
    cfg = config_from_metadata(meta)
    expected = message or meta.expected_payload
    expected_bits = encode_message(expected, fec=meta.fec_mode) if expected else None
    stats, _, result = decode_from_samples(
        samples,
        cfg,
        min_energy=1e-6,
        min_ratio=1.15,
        expected_bits=expected_bits,
        apply_bandpass=meta.filter_enabled,
        fec=meta.fec_mode,
        sync_mode=(
            "correlation"
            if meta.sync_mode in ("correlation", "soft_correlation", "soft")
            else "legacy"
        ),
        frequency_search_hz=meta.frequency_search_hz,
        frequency_search_step_hz=meta.frequency_search_step_hz,
    )
    table = Table(title="PHYSICAL CAPTURE REPLAY")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("MODE", "PHYSICAL CAPTURE REPLAY")
    table.add_row("SUCCESS", str(stats.frame_success))
    table.add_row("RECOVERED", repr(stats.recovered_message))
    table.add_row("CRC", "VALID" if stats.frame_success else (result.error or "FAIL"))
    table.add_row("BER", str(stats.bit_error_rate))
    table.add_row("MODULATION", meta.modulation)
    table.add_row("FEC", meta.fec_mode)
    table.add_row(
        "syndrome_corrections_attempted",
        str(stats.syndrome_corrections_attempted),
    )
    console.print(table)
    return 0 if stats.frame_success else 1


def run_live_demo(
    message: str,
    input_device: int,
    output_device: int,
    modulation: str,
    cfg: Optional[ModulationConfig] = None,
    fec: str = "none",
    near_ultrasonic: bool = False,
    repeats: int = 1,
) -> int:
    """Live physical demo: record while playing (same-host)."""
    import sounddevice as sd

    validate_payload(message)
    cfg = cfg or ModulationConfig()
    try:
        assert_playback_allowed(
            config=cfg,
            payload=message,
            repeats=repeats,
            near_ultrasonic=near_ultrasonic,
            fec=fec,
        )
    except SafetyError as exc:
        console.print(f"[red]Safety rejection:[/red] {exc}")
        return 2

    bits = encode_message(message, fec=fec)
    tx = modulate(bits, cfg, modulation=modulation).astype(np.float32)
    if repeats > 1:
        gap = np.zeros(int(0.25 * cfg.sample_rate), dtype=np.float32)
        parts = []
        for i in range(repeats):
            if i:
                parts.append(gap)
            parts.append(tx)
        tx = np.concatenate(parts)

    mode = (
        "LIVE NEAR-ULTRASONIC EXPERIMENTAL"
        if near_ultrasonic
        else "LIVE AUDIBLE"
    )
    gap_s = 1.2
    console.print(
        Panel(
            f"[bold green]{mode}[/bold green]\n"
            f"payload={message!r} modulation={modulation} fec={fec}\n"
            f"f0/f1={cfg.frequency_zero}/{cfg.frequency_one} "
            f"tsym={cfg.symbol_duration}s\n"
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
        time.sleep(gap_s)
        sd.play(tx, samplerate=cfg.sample_rate, device=output_device)
        sd.wait()
        time.sleep(0.6)
    samples = (
        np.concatenate(recorded).astype(np.float64)
        if recorded
        else np.zeros(int(3 * cfg.sample_rate))
    )
    out_dir = Path("experiments") / time.strftime("stage-%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    rx_path = out_dir / "rx.wav"
    tx_path = out_dir / "tx.wav"
    wavfile.write(str(tx_path), cfg.sample_rate, tx)
    wavfile.write(str(rx_path), cfg.sample_rate, samples.astype(np.float32))

    git_commit = "unknown"
    try:
        git_commit = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        pass

    stats, _, result = decode_from_samples(
        samples,
        cfg,
        min_energy=1e-6,
        min_ratio=1.15,
        expected_bits=bits,
        fec=fec,
        sync_mode="correlation",
    )

    rx_meta = {
        "schema_version": SCHEMA_VERSION,
        "provenance": Provenance.PHYSICAL_RX.value,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": git_commit,
        "wav_sha256": sha256_file(rx_path),
        "sample_rate": cfg.sample_rate,
        "frequency_zero_hz": cfg.frequency_zero,
        "frequency_one_hz": cfg.frequency_one,
        "symbol_duration_seconds": cfg.symbol_duration,
        "modulation": modulation,
        "fec_mode": fec,
        "sync_mode": "soft_correlation",
        "payload_length": len(message.encode("utf-8")),
        "expected_payload": message,
        "filter_enabled": True,
        "amplitude": cfg.amplitude,
        "crc_valid": bool(stats.frame_success),
        "recovered_payload": stats.recovered_message,
        "mode_label": mode,
    }
    (rx_path.with_suffix(rx_path.suffix + ".meta.json")).write_text(
        json.dumps(rx_meta, indent=2) + "\n"
    )
    (tx_path.with_suffix(".json")).write_text(
        json.dumps(
            {**rx_meta, "provenance": Provenance.GENERATED_TX.value},
            indent=2,
        )
        + "\n"
    )
    console.print(
        Panel(
            f"MODE: {mode}\n"
            f"RECOVERED: {stats.recovered_message!r}\n"
            f"CRC: {'VALID' if stats.frame_success else result.error}\n"
            f"syndrome_corrections_attempted: "
            f"{stats.syndrome_corrections_attempted}\n"
            f"sync_score: {stats.sync_score:.3f}\n"
            f"Saved: {out_dir}",
            title=mode,
            border_style="green" if stats.frame_success else "red",
        )
    )
    return 0 if stats.frame_success else 1


def run_wizard(args: argparse.Namespace) -> int:
    """Interactive physical/simulation wizard (not simulation-only)."""
    console.print(
        Panel(
            "Conference stage wizard\n"
            "Modes: LIVE AUDIBLE | LIVE NEAR-US | REPLAY | SIMULATION",
            title="WIZARD",
            border_style="magenta",
        )
    )
    try:
        from src.audio_devices import list_devices

        devices = list_devices()
    except Exception as exc:
        console.print(f"[yellow]Device enumeration unavailable:[/yellow] {exc}")
        devices = []

    if devices:
        table = Table(title="Audio devices")
        table.add_column("Index")
        table.add_column("Name")
        table.add_column("In")
        table.add_column("Out")
        for d in devices:
            table.add_row(
                str(d.index),
                d.name,
                str(d.max_input_channels),
                str(d.max_output_channels),
            )
        console.print(table)

    mode = Prompt.ask(
        "Select mode",
        choices=["live-audible", "live-near-us", "replay", "simulation"],
        default="simulation",
    )

    if mode == "simulation":
        msg = Prompt.ask("Synthetic payload", default=args.message)
        return run_simulation_demo(msg, args.modulation, fec=args.fec)

    if mode == "replay":
        default_wav = Path("output/samples/replay/rx.wav")
        wav = Path(Prompt.ask("Verified physical WAV", default=str(default_wav)))
        return run_replay_demo(wav)

    # Physical paths
    in_dev = int(Prompt.ask("Input device index", default=str(args.input_device)))
    out_dev = int(Prompt.ask("Output device index", default=str(args.output_device)))

    if Confirm.ask("Verify microphone with a short recording?", default=True):
        try:
            import sounddevice as sd

            console.print("Recording 0.5 s ambient…")
            rec = sd.rec(
                int(0.5 * 48000),
                samplerate=48000,
                channels=1,
                dtype="float32",
                device=in_dev,
            )
            sd.wait()
            rms = float(np.sqrt(np.mean(np.square(rec))))
            console.print(f"Mic RMS={rms:.6f} (non-zero expected)")
        except Exception as exc:
            console.print(f"[red]Mic check failed:[/red] {exc}")
            return 2

    if Confirm.ask("Verify low-level playback tone?", default=True):
        try:
            import sounddevice as sd

            sr = 48000
            t = np.linspace(0, 0.2, int(0.2 * sr), endpoint=False)
            tone = (0.05 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
            from types import SimpleNamespace

            assert_playback_allowed(
                config=SimpleNamespace(
                    amplitude=0.05,
                    frequency_zero=1000.0,
                    frequency_one=2000.0,
                    sample_rate=sr,
                    symbol_duration=0.2,
                    near_ultrasonic=False,
                ),
                payload="T",
                repeats=1,
                near_ultrasonic=False,
                fec="none",
            )
            sd.play(tone, samplerate=sr, device=out_dev)
            sd.wait()
            console.print("Playback tone finished.")
        except Exception as exc:
            console.print(f"[red]Playback check failed:[/red] {exc}")
            return 2

    cfg_path = Path(
        Prompt.ask(
            "Demo configuration YAML",
            default=str(DEFAULT_DEMO_CONFIG if DEFAULT_DEMO_CONFIG.exists() else ""),
        )
    )
    if cfg_path.exists():
        cfg = config_from_demo_file(cfg_path)
        console.print(f"Loaded configuration from {cfg_path}")
    else:
        cfg = ModulationConfig(
            frequency_zero=3000,
            frequency_one=8000,
            symbol_duration=0.07,
            amplitude=0.28,
        )
        console.print("Using built-in conference audible defaults (recalibrate per room).")

    msg = Prompt.ask("Manually entered synthetic payload", default=args.message)
    validate_payload(msg)
    near_us = mode == "live-near-us"
    if near_us:
        cfg = ModulationConfig(
            sample_rate=cfg.sample_rate,
            symbol_duration=cfg.symbol_duration,
            frequency_zero=18500,
            frequency_one=19500,
            amplitude=min(cfg.amplitude, 0.25),
            near_ultrasonic=True,
        )
        console.print(
            "[yellow]Near-ultrasonic physical decode was not reliable on the "
            "documented laboratory hardware. Proceed only for education.[/yellow]"
        )

    try:
        assert_playback_allowed(
            config=cfg,
            payload=msg,
            repeats=2,
            near_ultrasonic=near_us,
            fec=args.fec,
        )
    except SafetyError as exc:
        console.print(f"[red]Safety rejection:[/red] {exc}")
        if Confirm.ask("Retry with safer defaults (0.07s, 3/8 kHz, amp 0.25)?"):
            cfg = ModulationConfig(
                frequency_zero=3000,
                frequency_one=8000,
                symbol_duration=0.07,
                amplitude=0.25,
            )
            near_us = False
        else:
            return 2

    console.print("Starting receiver + playback…")
    rc = run_live_demo(
        msg,
        in_dev,
        out_dev,
        args.modulation,
        cfg=cfg,
        fec=args.fec,
        near_ultrasonic=near_us,
        repeats=2,
    )
    if Confirm.ask("Offer verified physical capture replay?", default=False):
        run_replay_demo(Path("output/samples/replay/rx.wav"))
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.stage_demo")
    parser.add_argument("--wizard", action="store_true")
    parser.add_argument("--message", default="DEMO-LAB-2027")
    parser.add_argument("--modulation", choices=("bfsk", "cpfsk"), default="cpfsk")
    parser.add_argument("--fec", choices=("none", "hamming74"), default="none")
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--replay", type=Path, default=None)
    parser.add_argument("--input-device", type=int, default=0)
    parser.add_argument("--output-device", type=int, default=0)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--near-ultrasonic", action="store_true")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_DEMO_CONFIG if DEFAULT_DEMO_CONFIG.exists() else None,
    )
    args = parser.parse_args(argv)

    cfg = None
    if args.config and args.config.exists():
        cfg = config_from_demo_file(args.config)

    if args.wizard:
        return run_wizard(args)
    if args.replay:
        argv_list = list(argv) if argv is not None else sys.argv[1:]
        override = (
            args.message
            if any(a == "--message" or a.startswith("--message=") for a in argv_list)
            else None
        )
        return run_replay_demo(args.replay, override)
    if args.live:
        return run_live_demo(
            args.message,
            args.input_device,
            args.output_device,
            args.modulation,
            cfg=cfg,
            fec=args.fec,
            near_ultrasonic=args.near_ultrasonic,
        )
    # Default / --simulate: clearly labelled simulation
    return run_simulation_demo(args.message, args.modulation, cfg=cfg, fec=args.fec)


if __name__ == "__main__":
    sys.exit(main())
