"""Centralized safety limits for the acoustic-channel PoC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


HIGH_FREQ_WARNING_HZ: float = 17_000.0
MAX_AMPLITUDE: float = 0.35
DEFAULT_AMPLITUDE: float = 0.20
MAX_PAYLOAD_BYTES: int = 64
MAX_TRANSMISSION_SECONDS: float = 180.0
MAX_SYMBOL_DURATION: float = 1.0
MIN_SYMBOL_DURATION: float = 0.02
MIN_CARRIER_SEPARATION_HZ: float = 100.0


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
    if abs(frequency_zero - frequency_one) < MIN_CARRIER_SEPARATION_HZ:
        errors.append(
            f"Carrier separation must be at least {MIN_CARRIER_SEPARATION_HZ:.0f} Hz"
        )

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


def assert_calibration_playback(
    *,
    peak_amplitude: float,
    sample_rate: int,
    duration_s: float,
    max_probe_hz: float,
    near_ultrasonic: bool,
) -> SafetyReport:
    """Safety gate for frequency-sweep calibration playback."""
    warnings: list[str] = []
    errors: list[str] = []
    if peak_amplitude > MAX_AMPLITUDE:
        errors.append(
            f"calibration peak {peak_amplitude} exceeds {MAX_AMPLITUDE}"
        )
    if peak_amplitude <= 0:
        errors.append("calibration waveform has zero amplitude")
    nyquist = sample_rate / 2.0
    if max_probe_hz <= 0 or max_probe_hz >= nyquist:
        errors.append(f"probe {max_probe_hz} must be in (0, Nyquist={nyquist})")
    if max_probe_hz > HIGH_FREQ_WARNING_HZ:
        warnings.append(
            f"Calibration includes frequencies above {HIGH_FREQ_WARNING_HZ:.0f} Hz"
        )
        if not near_ultrasonic:
            errors.append(
                "Frequencies above 17 kHz require --near-ultrasonic"
            )
    if duration_s > 600.0:
        errors.append(f"calibration duration {duration_s:.1f}s exceeds 600s")
    report = SafetyReport(ok=not errors, warnings=tuple(warnings), errors=tuple(errors))
    if not report.ok:
        raise SafetyError("; ".join(report.errors))
    return report


def assert_playback_allowed(
    *,
    config: object,
    payload: str,
    repeats: int = 1,
    inter_frame_silence: float = 0.25,
    near_ultrasonic: bool = False,
    fec: str = "none",
) -> SafetyReport:
    """Convenience wrapper used by all public playback entry points."""
    from src.protocol import estimate_duration

    amplitude = float(getattr(config, "amplitude"))
    f0 = float(getattr(config, "frequency_zero"))
    f1 = float(getattr(config, "frequency_one"))
    sr = int(getattr(config, "sample_rate"))
    tsym = float(getattr(config, "symbol_duration"))
    payload_bytes = len(payload.encode("utf-8"))
    dur = estimate_duration(
        payload,
        tsym,
        repeats=repeats,
        inter_frame_silence=inter_frame_silence,
        fec=fec,
    )
    return require_safe(
        amplitude=amplitude,
        frequency_zero=f0,
        frequency_one=f1,
        sample_rate=sr,
        symbol_duration=tsym,
        payload_bytes=payload_bytes,
        repeats=repeats,
        near_ultrasonic=near_ultrasonic,
        estimated_duration_s=dur,
    )
