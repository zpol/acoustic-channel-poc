"""Synchronization pilots, latency estimation, and preamble correlation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from src.modulation import ModulationConfig, goertzel
from src.protocol import PREAMBLE_AND_SYNC


@dataclass(frozen=True)
class LatencyEstimate:
    latency_seconds: float
    latency_samples: int
    correlation_peak: float
    confidence: float
    detected: bool


@dataclass(frozen=True)
class SyncCandidate:
    bit_index: int
    score: float
    hamming_distance: int
    confidence: float


@dataclass(frozen=True)
class SyncResult:
    state: str  # NO_SIGNAL / PREAMBLE_CANDIDATE / SYNCED / ...
    candidates: Tuple[SyncCandidate, ...]
    best: Optional[SyncCandidate]


def generate_sync_pilot(
    sample_rate: int,
    duration: float = 0.05,
    f_start: float = 2000.0,
    f_stop: float = 8000.0,
    amplitude: float = 0.12,
) -> np.ndarray:
    """Generate a linear chirp pilot for latency estimation."""
    n = int(round(duration * sample_rate))
    t = np.arange(n, dtype=np.float64) / sample_rate
    # Instantaneous frequency sweep
    k = (f_stop - f_start) / max(duration, 1e-9)
    phase = 2.0 * np.pi * (f_start * t + 0.5 * k * t * t)
    env = np.ones(n, dtype=np.float64)
    fade = max(1, n // 20)
    env[:fade] = np.linspace(0, 1, fade, endpoint=False)
    env[-fade:] = np.linspace(1, 0, fade, endpoint=False)
    return (amplitude * np.sin(phase) * env).astype(np.float64)


def estimate_latency(
    reference: np.ndarray,
    recording: np.ndarray,
    sample_rate: int,
    max_latency_s: float = 1.0,
) -> LatencyEstimate:
    """Estimate playback→capture delay via normalized cross-correlation."""
    if len(reference) == 0 or len(recording) == 0:
        return LatencyEstimate(0.0, 0, 0.0, 0.0, False)
    ref = reference.astype(np.float64)
    rec = recording.astype(np.float64)
    # Correlate ref against beginning of recording (up to max latency + ref)
    max_lag = int(max_latency_s * sample_rate) + len(ref)
    window = rec[: min(len(rec), max_lag)]
    if len(window) < len(ref):
        return LatencyEstimate(0.0, 0, 0.0, 0.0, False)
    corr = np.correlate(window, ref, mode="valid")
    peak_idx = int(np.argmax(np.abs(corr)))
    peak = float(corr[peak_idx])
    # Confidence: peak vs RMS of correlation
    rms = float(np.sqrt(np.mean(corr**2))) + 1e-12
    confidence = float(min(1.0, abs(peak) / (rms * 8.0)))
    detected = confidence >= 0.25 and abs(peak) > 1e-6
    return LatencyEstimate(
        latency_seconds=peak_idx / sample_rate,
        latency_samples=peak_idx,
        correlation_peak=peak,
        confidence=confidence,
        detected=detected,
    )


def align_recording(
    recording: np.ndarray,
    latency: LatencyEstimate,
) -> np.ndarray:
    """Drop leading samples corresponding to measured latency."""
    if not latency.detected or latency.latency_samples <= 0:
        return recording
    if latency.latency_samples >= len(recording):
        return recording[-1:]
    return recording[latency.latency_samples :]


def soft_preamble_correlation(
    soft_bits: Sequence[int],
    pattern: Sequence[int] = PREAMBLE_AND_SYNC,
) -> List[SyncCandidate]:
    """Score every alignment of *pattern* against hard/soft bits."""
    plen = len(pattern)
    out: List[SyncCandidate] = []
    if len(soft_bits) < plen:
        return out
    for i in range(len(soft_bits) - plen + 1):
        window = soft_bits[i : i + plen]
        matches = sum(1 for a, b in zip(window, pattern) if a == b)
        ham = plen - matches
        score = matches / plen
        out.append(
            SyncCandidate(
                bit_index=i,
                score=score,
                hamming_distance=ham,
                confidence=score,
            )
        )
    out.sort(key=lambda c: (-c.score, c.bit_index))
    return out


def find_sync_correlation(
    soft_bits: Sequence[int],
    max_hamming: int = 2,
    pattern: Sequence[int] = PREAMBLE_AND_SYNC,
) -> SyncResult:
    """Correlation sync with Hamming-distance tolerance."""
    cands = soft_preamble_correlation(soft_bits, pattern)
    accepted = [c for c in cands if c.hamming_distance <= max_hamming]
    if not soft_bits:
        return SyncResult(state="NO_SIGNAL", candidates=(), best=None)
    if not accepted:
        if cands and cands[0].score > 0.6:
            return SyncResult(
                state="PREAMBLE_CANDIDATE",
                candidates=tuple(cands[:5]),
                best=cands[0],
            )
        return SyncResult(state="NO_SIGNAL", candidates=tuple(cands[:3]), best=None)
    best = accepted[0]
    return SyncResult(
        state="SYNCED",
        candidates=tuple(accepted[:5]),
        best=best,
    )


def goertzel_neighbourhood(
    samples: np.ndarray,
    center_hz: float,
    sample_rate: int,
    search_hz: float = 100.0,
    step_hz: float = 10.0,
) -> Tuple[float, float]:
    """Return (best_frequency, energy) in a neighbourhood of *center_hz*."""
    if search_hz <= 0:
        e = goertzel(samples, center_hz, sample_rate)
        return center_hz, e
    best_f = center_hz
    best_e = -1.0
    f = center_hz - search_hz
    while f <= center_hz + search_hz + 1e-9:
        if 0 < f < sample_rate / 2:
            e = goertzel(samples, f, sample_rate)
            if e > best_e:
                best_e = e
                best_f = f
        f += step_hz
    return best_f, float(max(best_e, 0.0))
