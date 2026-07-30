"""Replay a cryptographically verified PHYSICAL_RX WAV through the decoder.

Fail-closed: missing/invalid metadata or hash mismatch rejects replay.
Never assumes an unverified WAV is a physical capture.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from rich.console import Console
from rich.panel import Panel
from scipy.io import wavfile

from src.modulation import ModulationConfig
from src.provenance import (
    CaptureMetadata,
    Provenance,
    ProvenanceError,
    load_metadata_json,
    validate_physical_metadata,
)
from src.receiver import decode_from_samples

console = Console()


def metadata_sidecar(wav_path: Path) -> Path:
    """Preferred sidecar: ``foo.wav`` → ``foo.meta.json``, else ``foo.json``."""
    preferred = wav_path.with_suffix(wav_path.suffix + ".meta.json")
    if preferred.exists():
        return preferred
    alt = wav_path.with_name(wav_path.stem + ".meta.json")
    if alt.exists():
        return alt
    return wav_path.with_suffix(".json")


def load_verified_physical_capture(
    wav_path: Path,
) -> Tuple[np.ndarray, CaptureMetadata]:
    """Load WAV + validated metadata. Raises ProvenanceError on any failure."""
    if not wav_path.exists():
        raise ProvenanceError(f"Missing WAV: {wav_path}")
    meta_path = metadata_sidecar(wav_path)
    if not meta_path.exists():
        raise ProvenanceError(
            f"No metadata found for {wav_path} "
            f"(expected {meta_path.name} or {wav_path.stem}.meta.json). "
            "Provenance UNKNOWN — physical replay rejected."
        )
    raw = load_metadata_json(meta_path)
    meta = validate_physical_metadata(raw, wav_path=wav_path, require_hash_match=True)
    sr, data = wavfile.read(str(wav_path))
    if int(sr) != meta.sample_rate:
        raise ProvenanceError(
            f"WAV sample_rate {sr} != metadata sample_rate {meta.sample_rate}"
        )
    x = np.asarray(data, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x, meta


def config_from_metadata(meta: CaptureMetadata) -> ModulationConfig:
    return ModulationConfig(
        sample_rate=meta.sample_rate,
        symbol_duration=meta.symbol_duration_seconds,
        frequency_zero=meta.frequency_zero_hz,
        frequency_one=meta.frequency_one_hz,
        amplitude=meta.amplitude if meta.amplitude is not None else 0.2,
        near_ultrasonic=max(meta.frequency_zero_hz, meta.frequency_one_hz) > 17000,
    )


def print_loaded_config(meta: CaptureMetadata) -> None:
    console.print(
        Panel(
            f"[bold]PHYSICAL CAPTURE REPLAY[/bold]\n"
            f"Git commit: {meta.git_commit}\n"
            f"Timestamp: {meta.timestamp}\n"
            f"Modulation: {meta.modulation.upper()}\n"
            f"FEC: {meta.fec_mode}\n"
            f"Sync: {meta.sync_mode}\n"
            f"f0: {meta.frequency_zero_hz:.0f} Hz\n"
            f"f1: {meta.frequency_one_hz:.0f} Hz\n"
            f"Symbol duration: {meta.symbol_duration_seconds * 1000:.1f} ms\n"
            f"Sample rate: {meta.sample_rate}\n"
            f"SHA-256: VALID\n"
            f"Provenance: {meta.provenance}",
            title="Loaded verified physical capture",
            border_style="green",
        )
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m src.replay")
    p.add_argument("--input-wav", type=Path, required=True)
    p.add_argument(
        "--expected",
        default=None,
        help="Override expected payload (default: metadata.expected_payload)",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        samples, meta = load_verified_physical_capture(args.input_wav)
    except ProvenanceError as exc:
        console.print(f"[red]Replay rejected:[/red] {exc}")
        return 2

    print_loaded_config(meta)
    cfg = config_from_metadata(meta)
    expected = args.expected or meta.expected_payload
    expected_bits = None
    if expected:
        from src.protocol import encode_message

        expected_bits = encode_message(expected, fec=meta.fec_mode)

    stats, _, result = decode_from_samples(
        samples,
        cfg,
        min_energy=1e-6,
        min_ratio=1.12,
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
    console.print(f"frame_success={stats.frame_success}")
    console.print(f"message={stats.recovered_message!r}")
    console.print(f"error={result.error}")
    console.print(f"BER={stats.bit_error_rate}")
    console.print(f"fec_corrected_bits={result.fec_corrected_bits}")
    console.print(f"mode_label={Provenance.PHYSICAL_REPLAY.value}")
    return 0 if stats.frame_success else 1


if __name__ == "__main__":
    sys.exit(main())
