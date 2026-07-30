"""Carrier-pair recommendation from calibration measurements."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class CarrierRecommendation:
    label: str  # MOST_RELIABLE / HIGHEST_FREQUENCY / BEST_COMPROMISE
    frequency_zero: float
    frequency_one: float
    estimated_snr_db: float
    recommended_symbol_duration: float
    notes: str


@dataclass(frozen=True)
class FreqPoint:
    frequency: float
    estimated_detector_snr_db: float
    energy: float = 0.0


def _pair_score(
    a: FreqPoint,
    b: FreqPoint,
    min_sep: float,
    nyquist: float,
) -> Optional[float]:
    sep = abs(a.frequency - b.frequency)
    if sep < min_sep:
        return None
    # Avoid near-Nyquist
    if max(a.frequency, b.frequency) > 0.9 * nyquist:
        return None
    snr = min(a.estimated_detector_snr_db, b.estimated_detector_snr_db)
    if snr < 3.0:
        return None
    balance = 1.0 / (1.0 + abs(a.estimated_detector_snr_db - b.estimated_detector_snr_db))
    # Penalize harmonic overlap (approx 2x)
    harm = 0.0
    for x, y in ((a, b), (b, a)):
        if abs(2 * x.frequency - y.frequency) < min_sep * 0.5:
            harm += 5.0
    return snr + 2.0 * balance + 0.001 * sep - harm


def _symbol_duration_for(f0: float, f1: float) -> float:
    cycles = 40.0
    fmin = min(f0, f1)
    dur = cycles / max(fmin, 1.0)
    return float(np.clip(dur, 0.08, 0.25))


def recommend_carrier_pairs(
    points: Sequence[FreqPoint],
    sample_rate: int = 48000,
    min_separation_hz: float = 1000.0,
    min_snr_db: float = 8.0,
) -> List[CarrierRecommendation]:
    """Return MOST_RELIABLE, HIGHEST_FREQUENCY, BEST_COMPROMISE when possible."""
    nyquist = sample_rate / 2.0
    usable = [p for p in points if p.estimated_detector_snr_db >= min_snr_db]
    if len(usable) < 2:
        usable = sorted(points, key=lambda p: p.estimated_detector_snr_db, reverse=True)[:12]

    scored: List[Tuple[float, FreqPoint, FreqPoint]] = []
    for i, a in enumerate(usable):
        for b in usable[i + 1 :]:
            s = _pair_score(a, b, min_separation_hz, nyquist)
            if s is not None:
                lo, hi = (a, b) if a.frequency < b.frequency else (b, a)
                scored.append((s, lo, hi))
    scored.sort(key=lambda t: t[0], reverse=True)
    if not scored:
        return []

    out: List[CarrierRecommendation] = []
    # MOST_RELIABLE: best score
    s, a, b = scored[0]
    out.append(
        CarrierRecommendation(
            label="MOST_RELIABLE",
            frequency_zero=a.frequency,
            frequency_one=b.frequency,
            estimated_snr_db=min(a.estimated_detector_snr_db, b.estimated_detector_snr_db),
            recommended_symbol_duration=_symbol_duration_for(a.frequency, b.frequency),
            notes="Highest combined detector SNR with separation/balance constraints",
        )
    )
    # HIGHEST_FREQUENCY: maximize mid frequency among pairs with SNR >= 6
    high = [
        t
        for t in scored
        if min(t[1].estimated_detector_snr_db, t[2].estimated_detector_snr_db) >= 6.0
    ]
    if high:
        high.sort(key=lambda t: (t[1].frequency + t[2].frequency) / 2.0, reverse=True)
        _, a, b = high[0]
        out.append(
            CarrierRecommendation(
                label="HIGHEST_FREQUENCY",
                frequency_zero=a.frequency,
                frequency_one=b.frequency,
                estimated_snr_db=min(a.estimated_detector_snr_db, b.estimated_detector_snr_db),
                recommended_symbol_duration=_symbol_duration_for(a.frequency, b.frequency),
                notes="Highest usable carrier region supported by measured SNR",
            )
        )
    # BEST_COMPROMISE: mid-band preference
    mid = sorted(
        scored,
        key=lambda t: abs((t[1].frequency + t[2].frequency) / 2.0 - 5000.0),
    )
    _, a, b = mid[0]
    out.append(
        CarrierRecommendation(
            label="BEST_COMPROMISE",
            frequency_zero=a.frequency,
            frequency_one=b.frequency,
            estimated_snr_db=min(a.estimated_detector_snr_db, b.estimated_detector_snr_db),
            recommended_symbol_duration=_symbol_duration_for(a.frequency, b.frequency),
            notes="Balance of SNR and mid-band placement for demos",
        )
    )
    # Deduplicate labels if same pair
    seen = set()
    unique: List[CarrierRecommendation] = []
    for r in out:
        key = (r.label, r.frequency_zero, r.frequency_one)
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def recommendations_as_dict(recs: Sequence[CarrierRecommendation]) -> dict:
    return {r.label: asdict(r) for r in recs}
