"""Centralized safety limits for the acoustic-channel PoC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


HIGH_FREQ_WARNING_HZ: float = 17_000.0
MAX_AMPLITUDE: float = 0.35
DEFAULT_AMPLITUDE: float = 0.20
MAX_PAYLOAD_BYTES: int = 32
MAX_TRANSMISSION_SECONDS: float = 180.0
MAX_SYMBOL_DURATION: float = 1.0
MIN_SYMBOL_DURATION: float = 0.02


class SafetyError(ValueError):
    """Raised when a configuration violates safety policy."""


@dataclass(frozen=True)
class SafetyReport:
    ok: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


def validate_transmission(
    *,
    amplitude: float,
    frequency_zero: float,
    frequency_one: float,
    sample_rate: int,
    symbol_duration: float,
    payload_bytes: int,
    repeats: int,
    near_ultrasonic: bool,
    estimated_duration_s: float,
) -> SafetyReport:
    """Validate TX parameters. Does not mute or raise OS volume."""
    warnings: list[str] = []
    errors: list[str] = []

    if not (0.0 < amplitude <= MAX_AMPLITUDE):
        errors.append(
            f"amplitude {amplitude} outside (0, {MAX_AMPLITUDE}]"
        )
    if payload_bytes < 1 or payload_bytes > MAX_PAYLOAD_BYTES:
        errors.append(
            f"payload_bytes {payload_bytes} outside [1, {MAX_PAYLOAD_BYTES}]"
        )
    if not (MIN_SYMBOL_DURATION <= symbol_duration <= MAX_SYMBOL_DURATION):
        errors.append(
            f"symbol_duration {symbol_duration} outside "
            f"[{MIN_SYMBOL_DURATION}, {MAX_SYMBOL_DURATION}]"
        )
    if repeats < 1 or repeats > 5:
        errors.append(f"repeats {repeats} outside [1, 5]")
    nyquist = sample_rate / 2.0
    for name, f in (("f0", frequency_zero), ("f1", frequency_one)):
        if f <= 0 or f >= nyquist:
            errors.append(f"{name}={f} must be in (0, Nyquist={nyquist})")
    max_f = max(frequency_zero, frequency_one)
    if max_f > HIGH_FREQ_WARNING_HZ:
        warnings.append(
            f"Frequencies above {HIGH_FREQ_WARNING_HZ:.0f} Hz "
            f"(max={max_f:.0f}). Hardware may roll off."
        )
        if not near_ultrasonic:
            errors.append(
                "Frequencies above 17 kHz require --near-ultrasonic"
            )
    if estimated_duration_s > MAX_TRANSMISSION_SECONDS:
        errors.append(
            f"estimated duration {estimated_duration_s:.1f}s exceeds "
            f"limit {MAX_TRANSMISSION_SECONDS:.0f}s"
        )
    if abs(frequency_zero - frequency_one) < 100:
        errors.append("Carrier separation must be at least 100 Hz")

    return SafetyReport(
        ok=not errors,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def require_safe(**kwargs: object) -> SafetyReport:
    """Validate and raise ``SafetyError`` on failure."""
    # type: ignore[arg-type]
    report = validate_transmission(**kwargs)  # type: ignore[arg-type]
    if not report.ok:
        raise SafetyError("; ".join(report.errors))
    return report
