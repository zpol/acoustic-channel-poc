"""Replay a previously captured PHYSICAL_RX WAV through the decoder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np
from rich.console import Console
from scipy.io import wavfile

from src.modulation import ModulationConfig
from src.provenance import Provenance
from src.receiver import decode_from_samples

console = Console()


def load_capture(path: Path) -> tuple[int, np.ndarray, dict]:
    meta_path = path.with_suffix(".json")
    meta: dict = {"provenance": Provenance.PHYSICAL_RX.value}
    if meta_path.exists():
        meta.update(json.loads(meta_path.read_text()))
    sr, data = wavfile.read(str(path))
    x = np.asarray(data, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return int(sr), x, meta


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.replay")
    parser.add_argument("--input-wav", type=Path, required=True)
    parser.add_argument("--frequency-zero", type=float, default=3500.0)
    parser.add_argument("--frequency-one", type=float, default=7500.0)
    parser.add_argument("--symbol-duration", type=float, default=0.12)
    parser.add_argument("--expected", default=None)
    args = parser.parse_args(argv)

    if not args.input_wav.exists():
        console.print(f"[red]Missing capture:[/red] {args.input_wav}")
        return 2
    sr, samples, meta = load_capture(args.input_wav)
    prov = meta.get("provenance", Provenance.PHYSICAL_RX.value)
    if prov not in (
        Provenance.PHYSICAL_RX.value,
        Provenance.PHYSICAL_REPLAY.value,
    ):
        console.print(
            f"[yellow]Warning:[/yellow] provenance={prov!r} — "
            "replay UI will label PHYSICAL CAPTURE REPLAY only for physical captures."
        )
    console.print(
        f"[bold]PHYSICAL CAPTURE REPLAY[/bold]  provenance={prov}  file={args.input_wav}"
    )
    cfg = ModulationConfig(
        sample_rate=sr,
        symbol_duration=args.symbol_duration,
        frequency_zero=args.frequency_zero,
        frequency_one=args.frequency_one,
    )
    expected_bits = None
    if args.expected:
        from src.protocol import encode_message

        expected_bits = encode_message(args.expected)
    stats, _, result = decode_from_samples(
        samples,
        cfg,
        min_energy=1e-6,
        min_ratio=1.15,
        expected_bits=expected_bits,
    )
    console.print(f"frame_success={stats.frame_success}")
    console.print(f"message={stats.recovered_message!r}")
    console.print(f"error={result.error}")
    console.print(f"BER={stats.bit_error_rate}")
    return 0 if stats.frame_success else 1


if __name__ == "__main__":
    sys.exit(main())
