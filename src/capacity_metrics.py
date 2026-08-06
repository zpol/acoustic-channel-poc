"""Capacity / goodput metrics for Part 3 experiments.

Definitions (measured, not Shannon):
- raw_bitrate_bps: coded bits on air / airtime (1/Tsym for binary FSK)
- payload_goodput_bps: 8 * payload_bytes * successes / sum(airtime of all trials)
- FER: frame error rate = 1 - (CRC-valid exact recoveries / N)
- BER: bit error rate vs expected framed bits when available
"""

from __future__ import annotations

import time
import zlib
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from src.protocol import PREAMBLE_AND_SYNC, encode_message, estimate_duration


@dataclass(frozen=True)
class OverheadBreakdown:
    payload_bytes: int
    payload_bits: int
    preamble_sync_bits: int
    body_bits_uncoded: int
    coded_bits: int
    fec: str
    overhead_fraction: float
    coding_expansion: float


def frame_overhead(payload: str, fec: str = "none") -> OverheadBreakdown:
    """Analytic overhead for one frame (no repeats/silence)."""
    raw = payload.encode("utf-8")
    payload_bits = len(raw) * 8
    uncoded = encode_message(payload, fec="none")
    coded = encode_message(payload, fec=fec)
    body_uncoded = len(uncoded) - len(PREAMBLE_AND_SYNC)
    return OverheadBreakdown(
        payload_bytes=len(raw),
        payload_bits=payload_bits,
        preamble_sync_bits=len(PREAMBLE_AND_SYNC),
        body_bits_uncoded=body_uncoded,
        coded_bits=len(coded),
        fec=fec,
        overhead_fraction=(len(coded) - payload_bits) / max(len(coded), 1),
        coding_expansion=len(coded) / max(len(uncoded), 1),
    )


def airtime_s(
    payload: str,
    symbol_duration: float,
    *,
    fec: str = "none",
    repeats: int = 1,
    inter_frame_silence: float = 0.0,
) -> float:
    return float(
        estimate_duration(
            payload,
            symbol_duration,
            repeats=repeats,
            inter_frame_silence=inter_frame_silence,
            fec=fec,
        )
    )


def raw_symbol_rate_bps(symbol_duration: float, bits_per_symbol: float = 1.0) -> float:
    return bits_per_symbol / symbol_duration


def payload_goodput_bps(
    payload_bytes: int,
    successes: int,
    total_airtime_s: float,
) -> float:
    if total_airtime_s <= 0:
        return 0.0
    return (8.0 * payload_bytes * successes) / total_airtime_s


def fer(successes: int, n: int) -> float:
    if n <= 0:
        return 1.0
    return 1.0 - (successes / n)


@dataclass
class CompressionEval:
    label: str
    original_bytes: int
    compressed_bytes: int
    ratio: float
    cpu_ms: float
    worthwhile_vs_payload_cap: bool


def eval_zlib_compression(label: str, data: bytes, level: int = 6) -> CompressionEval:
    t0 = time.perf_counter()
    out = zlib.compress(data, level=level)
    cpu_ms = (time.perf_counter() - t0) * 1000.0
    ratio = len(out) / max(len(data), 1)
    # Protocol max payload is 64 bytes; compression only helps if both fit and shrink.
    worthwhile = len(out) < len(data) and len(out) <= 64 and len(data) > 1
    return CompressionEval(
        label=label,
        original_bytes=len(data),
        compressed_bytes=len(out),
        ratio=ratio,
        cpu_ms=cpu_ms,
        worthwhile_vs_payload_cap=worthwhile,
    )


def mean(xs: Sequence[float]) -> float:
    return float(sum(xs) / len(xs)) if xs else float("nan")


def summarize_ber(bers: Iterable[Optional[float]]) -> float:
    vals = [b for b in bers if b is not None and b == b]
    return mean(vals)
