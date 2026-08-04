"""Guided physical / simulated experiment runner."""

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
from rich.panel import Panel
from scipy.io import wavfile

from src.modulation import ModulationConfig, modulate
from src.protocol import encode_message, estimate_duration
from src.provenance import Provenance
from src.receiver import decode_from_samples

console = Console()


def _git_commit() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def _prompt(msg: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    console.print(f"[bold cyan]{msg}{suffix}[/bold cyan]")
    try:
        line = input("> ").strip()
    except EOFError:
        line = ""
    if not line and default is not None:
        return default
    return line


def _wait(instruction: str) -> None:
    console.print(Panel(instruction, title="Physical action", border_style="yellow"))
    try:
        input("Press Enter when ready… ")
    except EOFError:
        time.sleep(2.0)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m src.experiment")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--simulate", action="store_true", help="Hardware-free simulation")
    p.add_argument("--input-device", type=int, default=0)
    p.add_argument("--output-device", type=int, default=0)
    p.add_argument("--message", default="DEMO-LAB-2027")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--modulation", choices=("bfsk", "cpfsk"), default="cpfsk")
    p.add_argument("--fec", choices=("none", "hamming74"), default="none")
    p.add_argument("--symbol-duration", type=float, default=0.12)
    p.add_argument("--frequency-zero", type=float, default=3500.0)
    p.add_argument("--frequency-one", type=float, default=7500.0)
    p.add_argument("--amplitude", type=float, default=0.25)
    p.add_argument("--distance-cm", type=float, default=30.0)
    p.add_argument("--orientation", default="mic-facing-speaker")
    p.add_argument("--room", default="lab-quiet")
    p.add_argument(
        "--remote-tx",
        default=None,
        help="SSH host for remote TX (or ACOUSTIC_REMOTE_TX). Example placeholder: demo-user@tx-host",
    )
    p.add_argument("--remote-dir", default="/path/to/repository")
    p.add_argument("--remote-output-device", type=int, default=1)
    return p


def run_trial(
    exp_dir: Path,
    trial_i: int,
    message: str,
    cfg: ModulationConfig,
    args: argparse.Namespace,
) -> dict:
    trial = exp_dir / f"trial-{trial_i:03d}"
    trial.mkdir(parents=True, exist_ok=True)
    bits = encode_message(message, fec=args.fec)
    tx = modulate(bits, cfg, modulation=args.modulation, repeats=2, inter_frame_silence=0.3)
    wavfile.write(str(trial / "tx.wav"), cfg.sample_rate, tx.astype(np.float32))

    if args.simulate:
        from src.modulation import add_channel_impairments

        rng = np.random.default_rng(1000 + trial_i)
        rx = add_channel_impairments(tx, noise_level=0.002, attenuation=0.5, timing_offset_samples=200, rng=rng)
        provenance = Provenance.SIMULATED_RX.value
    elif args.remote_tx:
        t_tx = estimate_duration(message, cfg.symbol_duration, repeats=2, inter_frame_silence=0.3, fec=args.fec)
        rec_dur = t_tx + 5.0
        raw = trial / "rx.wav"
        rx_cmd = [
            sys.executable, "-m", "src.receiver",
            "--input-device", str(args.input_device),
            "--duration", f"{rec_dur:.2f}",
            "--symbol-duration", str(cfg.symbol_duration),
            "--frequency-zero", str(cfg.frequency_zero),
            "--frequency-one", str(cfg.frequency_one),
            "--min-ratio", "1.12", "--fec", args.fec,
            "--sync-mode", "correlation",
            "--save-raw-wav", str(raw),
        ]
        import shlex

        remote = (
            f"cd {shlex.quote(str(args.remote_dir))} && . .venv/bin/activate && "
            f"export PYTHONPATH=. && "
            f"python -m src.transmitter --message {shlex.quote(message)} "
            f"--output-device {args.remote_output_device} "
            f"--symbol-duration {cfg.symbol_duration} "
            f"--frequency-zero {cfg.frequency_zero} --frequency-one {cfg.frequency_one} "
            f"--amplitude {args.amplitude} --repeats 2 --inter-frame-silence 0.3 "
            f"--modulation {args.modulation} --fec {args.fec}"
        )
        proc = subprocess.Popen(rx_cmd, cwd=Path.cwd(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.5)
        subprocess.run(["ssh", args.remote_tx, remote], capture_output=True)
        try:
            proc.communicate(timeout=rec_dur + 45)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        if not raw.exists():
            return {"trial": trial_i, "success": False, "error": "no recording"}
        sr, data = wavfile.read(str(raw))
        rx = np.asarray(data, dtype=np.float64)
        if rx.ndim > 1:
            rx = rx.mean(1)
        provenance = Provenance.PHYSICAL_RX.value
    else:
        # Local two-process TX/RX
        t_tx = estimate_duration(message, cfg.symbol_duration, repeats=2, inter_frame_silence=0.3, fec=args.fec)
        rec_dur = t_tx + 4.0
        raw = trial / "rx.wav"
        rx_cmd = [
            sys.executable, "-m", "src.receiver",
            "--input-device", str(args.input_device),
            "--duration", f"{rec_dur:.2f}",
            "--symbol-duration", str(cfg.symbol_duration),
            "--frequency-zero", str(cfg.frequency_zero),
            "--frequency-one", str(cfg.frequency_one),
            "--min-ratio", "1.12", "--fec", args.fec,
            "--sync-mode", "correlation",
            "--save-raw-wav", str(raw),
        ]
        tx_cmd = [
            sys.executable, "-m", "src.transmitter",
            "--message", message, "--output-device", str(args.output_device),
            "--symbol-duration", str(cfg.symbol_duration),
            "--frequency-zero", str(cfg.frequency_zero),
            "--frequency-one", str(cfg.frequency_one),
            "--amplitude", str(args.amplitude), "--repeats", "2",
            "--inter-frame-silence", "0.3",
            "--modulation", args.modulation, "--fec", args.fec,
            "--save-wav", str(trial / "tx_play.wav"),
        ]
        proc = subprocess.Popen(rx_cmd, cwd=Path.cwd(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.2)
        subprocess.run(tx_cmd, cwd=Path.cwd(), capture_output=True)
        try:
            proc.communicate(timeout=rec_dur + 40)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        if not raw.exists():
            return {"trial": trial_i, "success": False, "error": "no recording"}
        sr, data = wavfile.read(str(raw))
        rx = np.asarray(data, dtype=np.float64)
        if rx.ndim > 1:
            rx = rx.mean(1)
        provenance = Provenance.PHYSICAL_RX.value

    wavfile.write(str(trial / "rx.wav"), cfg.sample_rate, rx.astype(np.float32))
    stats, _, result = decode_from_samples(
        rx,
        cfg,
        min_energy=1e-6,
        min_ratio=1.12,
        expected_bits=bits,
        fec=args.fec,
        sync_mode="correlation",
    )
    ok = bool(result.success and stats.recovered_message == message)
    dec = {
        "provenance": provenance,
        "message": message,
        "success": ok,
        "recovered": stats.recovered_message,
        "ber": stats.bit_error_rate,
        "error": result.error,
        "fec_corrected_bits": result.fec_corrected_bits,
        "sync_state": stats.sync_state,
        "snr_estimate_db": stats.snr_estimate_db,
        "clipping": stats.clipping,
    }
    (trial / "decoder.json").write_text(json.dumps(dec, indent=2))
    (trial / "decoder.log").write_text(json.dumps(dec, indent=2) + "\n")
    return {"trial": trial_i, **dec}


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.remote_tx:
        import os

        args.remote_tx = os.environ.get("ACOUSTIC_REMOTE_TX") or None
    if not args.non_interactive and not args.simulate:
        console.print(Panel(
            "Guided acoustic experiment.\n"
            "Only synthetic CLI payloads are transmitted.\n"
            "Provenance labels distinguish PHYSICAL vs SIMULATED artefacts.",
            title="experiment",
        ))
        args.input_device = int(_prompt("Input device id", str(args.input_device)))
        args.output_device = int(_prompt("Output device id", str(args.output_device)))
        mode = _prompt("Mode: audible / near-us / simulate", "audible")
        if mode.startswith("sim"):
            args.simulate = True
        args.modulation = _prompt("Modulation bfsk/cpfsk", args.modulation)
        args.fec = _prompt("FEC none/hamming74", args.fec)
        args.distance_cm = float(_prompt("Mic distance cm", str(args.distance_cm)))
        args.orientation = _prompt("Orientation label", args.orientation)
        args.room = _prompt("Room condition label", args.room)
        args.message = _prompt("Synthetic payload", args.message)
        args.trials = int(_prompt("Number of trials", str(args.trials)))
        if not args.simulate:
            _wait(
                f"Place the microphone ~{args.distance_cm:.0f} cm from the speaker.\n"
                "Disable mic monitoring / echo cancellation if possible.\n"
                "Keep the room quiet."
            )

    stamp = time.strftime("%Y%m%dT%H%M%S")
    tag = "sim" if args.simulate else ("remote" if args.remote_tx else "local")
    exp = Path("experiments") / f"{stamp}-{tag}-{args.modulation}-{args.fec}"
    exp.mkdir(parents=True, exist_ok=True)

    cfg = ModulationConfig(
        symbol_duration=args.symbol_duration,
        frequency_zero=args.frequency_zero,
        frequency_one=args.frequency_one,
        amplitude=args.amplitude,
        near_ultrasonic=args.frequency_one > 17000,
    )
    meta = {
        "timestamp": stamp,
        "git_commit": _git_commit(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "provenance_default": Provenance.SIMULATED_RX.value if args.simulate else Provenance.PHYSICAL_RX.value,
        "modulation": args.modulation,
        "fec": args.fec,
        "frequency_zero": args.frequency_zero,
        "frequency_one": args.frequency_one,
        "symbol_duration": args.symbol_duration,
        "amplitude": args.amplitude,
        "payload": args.message,
        "payload_length": len(args.message.encode("utf-8")),
        "distance_cm": args.distance_cm,
        "orientation": args.orientation,
        "room_condition": args.room,
        "input_device": args.input_device,
        "output_device": args.output_device,
        "remote_tx": args.remote_tx,
    }
    (exp / "metadata.json").write_text(json.dumps(meta, indent=2))
    (exp / "configuration.json").write_text(json.dumps(meta, indent=2))

    results: List[dict] = []
    for i in range(1, args.trials + 1):
        console.print(f"[bold]Trial {i}/{args.trials}[/bold] payload={args.message!r}")
        results.append(run_trial(exp, i, args.message, cfg, args))
        mark = "OK" if results[-1].get("success") else "FAIL"
        console.print(f"  [{mark}] {results[-1].get('recovered')!r} {results[-1].get('error') or ''}")

    n_ok = sum(1 for r in results if r.get("success"))
    summary = {
        "n_trials": len(results),
        "n_ok": n_ok,
        "success_rate": n_ok / max(1, len(results)),
        "trials": results,
        "git_commit": meta["git_commit"],
        "provenance": meta["provenance_default"],
    }
    (exp / "summary.json").write_text(json.dumps(summary, indent=2))
    lines = [
        f"# Experiment summary\n\n",
        f"Provenance: **{meta['provenance_default']}**\n\n",
        f"Success: {n_ok}/{len(results)} ({100 * summary['success_rate']:.0f}%)\n\n",
        f"Modulation={args.modulation} FEC={args.fec} "
        f"f0/f1={args.frequency_zero}/{args.frequency_one} Tsym={args.symbol_duration}\n\n",
    ]
    for r in results:
        lines.append(
            f"- trial {r['trial']}: {'OK' if r.get('success') else 'FAIL'} "
            f"BER={r.get('ber')} {r.get('error') or ''}\n"
        )
    (exp / "summary.md").write_text("".join(lines))
    # simple CSV
    with (exp / "summary.csv").open("w") as fh:
        fh.write("trial,success,ber,error\n")
        for r in results:
            fh.write(f"{r['trial']},{int(bool(r.get('success')))},{r.get('ber')},{r.get('error') or ''}\n")
    console.print(f"Saved {exp}")
    return 0 if n_ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
