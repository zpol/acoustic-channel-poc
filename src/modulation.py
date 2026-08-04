"""BFSK modulation and demodulation helpers.

Generates continuous-phase sine symbols with short fade in/out to
reduce clicks. Demodulation uses the Goertzel algorithm for the two
BFSK tone frequencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import butter, filtfilt

# Defaults — tuned for ~8 bit/s with good live reliability on typical PC audio.
# Use profile "reliable" (200 ms, 4/6 kHz) if the room is noisy.
DEFAULT_SAMPLE_RATE: int = 48_000
DEFAULT_SYMBOL_DURATION: float = 0.12
DEFAULT_FREQUENCY_ZERO: float = 3_500.0
DEFAULT_FREQUENCY_ONE: float = 7_500.0
DEFAULT_AMPLITUDE: float = 0.20
DEFAULT_FADE_RATIO: float = 0.05  # fraction of symbol for fade in/out
NEAR_ULTRASONIC_ZERO: float = 18_500.0
NEAR_ULTRASONIC_ONE: float = 19_500.0
HIGH_FREQ_WARNING_HZ: float = 17_000.0

# Named profiles for CLI convenience
PROFILES: dict[str, dict[str, float]] = {
    "reliable": {
        "symbol_duration": 0.20,
        "frequency_zero": 4000.0,
        "frequency_one": 6000.0,
        "amplitude": 0.20,
    },
    "fast": {
        "symbol_duration": 0.12,
        "frequency_zero": 3500.0,
        "frequency_one": 7500.0,
        "amplitude": 0.20,
    },
    "turbo": {
        # Experimental — may drop below ~90% on real hardware
        "symbol_duration": 0.08,
        "frequency_zero": 3000.0,
        "frequency_one": 8000.0,
        "amplitude": 0.22,
    },
}


@dataclass(frozen=True)
class ModulationConfig:
    """Configuration for BFSK encode/decode."""

    sample_rate: int = DEFAULT_SAMPLE_RATE
    symbol_duration: float = DEFAULT_SYMBOL_DURATION
    frequency_zero: float = DEFAULT_FREQUENCY_ZERO
    frequency_one: float = DEFAULT_FREQUENCY_ONE
    amplitude: float = DEFAULT_AMPLITUDE
    fade_ratio: float = DEFAULT_FADE_RATIO
    near_ultrasonic: bool = False

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.symbol_duration <= 0:
            raise ValueError("symbol_duration must be positive")
        if not (0.0 < self.amplitude <= 0.5):
            raise ValueError("amplitude must be in (0, 0.5] to avoid clipping")
        nyquist = self.sample_rate / 2.0
        for name, freq in (
            ("frequency_zero", self.frequency_zero),
            ("frequency_one", self.frequency_one),
        ):
            if freq <= 0 or freq >= nyquist:
                raise ValueError(
                    f"{name}={freq} must be in (0, Nyquist={nyquist})"
                )
        if abs(self.frequency_zero - self.frequency_one) < 100:
            raise ValueError("BFSK frequencies must be at least 100 Hz apart")
        if self.fade_ratio < 0 or self.fade_ratio > 0.45:
            raise ValueError("fade_ratio must be in [0, 0.45]")

    @property
    def samples_per_symbol(self) -> int:
        return int(round(self.symbol_duration * self.sample_rate))

    @property
    def max_frequency(self) -> float:
        return max(self.frequency_zero, self.frequency_one)

    def requires_near_ultrasonic_flag(self) -> bool:
        return self.max_frequency > HIGH_FREQ_WARNING_HZ


def _fade_envelope(n_samples: int, fade_ratio: float) -> np.ndarray:
    """Raised-cosine-ish linear fade in/out envelope."""
    env = np.ones(n_samples, dtype=np.float64)
    fade_len = int(n_samples * fade_ratio)
    if fade_len <= 0:
        return env
    ramp = np.linspace(0.0, 1.0, fade_len, endpoint=False)
    env[:fade_len] = ramp
    env[-fade_len:] = ramp[::-1]
    return env


def generate_tone(
    frequency: float,
    duration: float,
    sample_rate: int,
    amplitude: float,
    phase: float = 0.0,
    fade_ratio: float = DEFAULT_FADE_RATIO,
) -> Tuple[np.ndarray, float]:
    """Generate a faded sine tone.

    Returns:
        (samples, next_phase) so consecutive symbols stay continuous.
    """
    n = int(round(duration * sample_rate))
    t = np.arange(n, dtype=np.float64) / sample_rate
    samples = amplitude * np.sin(2.0 * np.pi * frequency * t + phase)
    samples *= _fade_envelope(n, fade_ratio)
    next_phase = (phase + 2.0 * np.pi * frequency * duration) % (2.0 * np.pi)
    return samples.astype(np.float64), next_phase


def bits_to_waveform(
    bits: Sequence[int],
    config: ModulationConfig,
    inter_frame_silence: float = 0.0,
    repeats: int = 1,
) -> np.ndarray:
    """Modulate a bit sequence as BFSK (optionally repeated frames).

    Args:
        bits: One complete framed bit sequence.
        config: Modulation parameters.
        inter_frame_silence: Silence between repeated frames (seconds).
        repeats: Number of times to transmit the frame (1–3).
    """
    if repeats < 1 or repeats > 3:
        raise ValueError("repeats must be 1, 2, or 3")
    if inter_frame_silence < 0:
        raise ValueError("inter_frame_silence must be >= 0")

    chunks: List[np.ndarray] = []
    silence_n = int(round(inter_frame_silence * config.sample_rate))

    for rep in range(repeats):
        phase = 0.0
        for bit in bits:
            if bit not in (0, 1):
                raise ValueError(f"Invalid bit: {bit!r}")
            freq = (
                config.frequency_one if bit == 1 else config.frequency_zero
            )
            symbol, phase = generate_tone(
                frequency=freq,
                duration=config.symbol_duration,
                sample_rate=config.sample_rate,
                amplitude=config.amplitude,
                phase=phase,
                fade_ratio=config.fade_ratio,
            )
            chunks.append(symbol)
        if rep < repeats - 1 and silence_n > 0:
            chunks.append(np.zeros(silence_n, dtype=np.float64))

    if not chunks:
        return np.zeros(0, dtype=np.float64)

    waveform = np.concatenate(chunks)
    peak = np.max(np.abs(waveform))
    if peak > 0.99:
        waveform = waveform * (0.95 / peak)
    return waveform


def goertzel(
    samples: np.ndarray,
    frequency: float,
    sample_rate: int,
) -> float:
    """Compute Goertzel power at an exact *frequency* (not integer-bin rounded).

    Uses ``omega = 2π f / fs`` so ±10–50 Hz neighbourhood searches remain
    meaningful even when candidates share the same DFT bin index.
    """
    n = len(samples)
    if n == 0:
        return 0.0
    omega = 2.0 * np.pi * float(frequency) / float(sample_rate)
    coeff = 2.0 * np.cos(omega)
    s_prev = 0.0
    s_prev2 = 0.0
    for sample in samples:
        s = float(sample) + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s
    power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
    return float(max(power, 0.0))


@dataclass(frozen=True)
class SymbolDecision:
    """Per-symbol demodulation result."""

    bit: Optional[int]  # 0, 1, or None if uncertain
    energy_zero: float
    energy_one: float
    energy_ratio: float
    confidence: float


def _center_window(samples: np.ndarray, keep_ratio: float = 0.6) -> np.ndarray:
    """Keep the middle portion of a symbol to avoid fade-in/out edges."""
    n = len(samples)
    if n < 16 or keep_ratio >= 0.99:
        return samples
    keep = max(8, int(n * keep_ratio))
    start = (n - keep) // 2
    return samples[start : start + keep]


def decide_symbol(
    samples: np.ndarray,
    config: ModulationConfig,
    min_energy: float = 1e-4,
    min_ratio: float = 1.5,
    use_center: bool = True,
    frequency_search_hz: float = 0.0,
    frequency_search_step_hz: float = 10.0,
) -> SymbolDecision:
    """Decide bit 0/1/uncertain from a symbol-sized window via Goertzel."""
    window = _center_window(samples) if use_center else samples
    if frequency_search_hz > 0:
        from src.synchronization import goertzel_neighbourhood

        _, e0 = goertzel_neighbourhood(
            window,
            config.frequency_zero,
            config.sample_rate,
            search_hz=frequency_search_hz,
            step_hz=frequency_search_step_hz,
        )
        _, e1 = goertzel_neighbourhood(
            window,
            config.frequency_one,
            config.sample_rate,
            search_hz=frequency_search_hz,
            step_hz=frequency_search_step_hz,
        )
    else:
        e0 = goertzel(window, config.frequency_zero, config.sample_rate)
        e1 = goertzel(window, config.frequency_one, config.sample_rate)
    stronger = max(e0, e1)
    weaker = min(e0, e1) + 1e-20
    ratio = stronger / weaker
    confidence = float(min(1.0, (ratio - 1.0) / 10.0)) if stronger > min_energy else 0.0

    if stronger < min_energy:
        return SymbolDecision(
            bit=None,
            energy_zero=e0,
            energy_one=e1,
            energy_ratio=ratio,
            confidence=0.0,
        )
    if ratio < min_ratio:
        return SymbolDecision(
            bit=None,
            energy_zero=e0,
            energy_one=e1,
            energy_ratio=ratio,
            confidence=confidence,
        )
    bit = 1 if e1 > e0 else 0
    return SymbolDecision(
        bit=bit,
        energy_zero=e0,
        energy_one=e1,
        energy_ratio=ratio,
        confidence=confidence,
    )


def bandpass_filter(
    samples: np.ndarray,
    config: ModulationConfig,
    bandwidth: float = 1500.0,
) -> np.ndarray:
    """Band-pass covering both carriers (plus margin) to reduce out-of-band noise.

    Default margin is intentionally wide: a tight filter around distant carriers
    (e.g. 3.5 and 7.5 kHz) can distort edges and flip CRC bits on physical captures.
    """
    low = max(50.0, min(config.frequency_zero, config.frequency_one) - bandwidth)
    high = min(
        config.sample_rate / 2.0 - 50.0,
        max(config.frequency_zero, config.frequency_one) + bandwidth,
    )
    if low >= high:
        return samples
    nyq = config.sample_rate / 2.0
    b, a = butter(2, [low / nyq, high / nyq], btype="band")
    return filtfilt(b, a, samples).astype(np.float64)


def demodulate_bits(
    samples: np.ndarray,
    config: ModulationConfig,
    min_energy: float = 1e-4,
    min_ratio: float = 1.5,
    apply_bandpass: bool = True,
    timing_offset_samples: int = 0,
    frequency_search_hz: float = 0.0,
    frequency_search_step_hz: float = 10.0,
) -> Tuple[List[Optional[int]], List[SymbolDecision]]:
    """Slice *samples* into symbol windows and demodulate each."""
    if apply_bandpass:
        samples = bandpass_filter(samples, config)
    if timing_offset_samples:
        if timing_offset_samples > 0:
            samples = samples[timing_offset_samples:]
        else:
            samples = np.concatenate(
                [np.zeros(-timing_offset_samples), samples]
            )

    sps = config.samples_per_symbol
    decisions: List[SymbolDecision] = []
    bits: List[Optional[int]] = []
    n_symbols = len(samples) // sps
    for i in range(n_symbols):
        window = samples[i * sps : (i + 1) * sps]
        decision = decide_symbol(
            window,
            config,
            min_energy=min_energy,
            min_ratio=min_ratio,
            frequency_search_hz=frequency_search_hz,
            frequency_search_step_hz=frequency_search_step_hz,
        )
        decisions.append(decision)
        bits.append(decision.bit)
    return bits, decisions


def soft_bits_from_decisions(decisions: Sequence[SymbolDecision]) -> List[int]:
    """Force a hard 0/1 from relative tone energy (ignores uncertainty)."""
    return [1 if d.energy_one >= d.energy_zero else 0 for d in decisions]


def preamble_match_score(
    bits: Sequence[Optional[int]],
    pattern: Sequence[int],
) -> Tuple[int, int]:
    """Return (best_score, index) for *pattern* against optional bits.

    Uncertain symbols count as half-matches so slightly noisy preambles
    still rank well during timing search.
    """
    plen = len(pattern)
    best_score = -1
    best_idx = -1
    if len(bits) < plen:
        return 0, -1
    for i in range(len(bits) - plen + 1):
        score = 0
        window = bits[i : i + plen]
        for bit, expected in zip(window, pattern):
            if bit is None:
                score += 0  # uncertain: no credit
            elif bit == expected:
                score += 2
            else:
                score -= 1
        if score > best_score:
            best_score = score
            best_idx = i
    return max(best_score, 0), best_idx


def find_best_timing_offset(
    samples: np.ndarray,
    config: ModulationConfig,
    min_energy: float = 1e-4,
    min_ratio: float = 1.5,
    apply_bandpass: bool = True,
    n_steps: int = 24,
    pattern: Optional[Sequence[int]] = None,
    frequency_search_hz: float = 0.0,
    frequency_search_step_hz: float = 10.0,
) -> Tuple[int, List[Optional[int]], List[SymbolDecision], int]:
    """Search symbol-phase offsets and keep the best preamble alignment.

    Returns:
        (offset_samples, bits, decisions, preamble_score)
    """
    from src.protocol import PREAMBLE_AND_SYNC

    if pattern is None:
        pattern = PREAMBLE_AND_SYNC

    work = bandpass_filter(samples, config) if apply_bandpass else samples
    sps = config.samples_per_symbol
    step = max(1, sps // max(4, n_steps))
    perfect = 2 * len(pattern)

    best_offset = 0
    best_score = -1
    best_bits: List[Optional[int]] = []
    best_decisions: List[SymbolDecision] = []

    for offset in range(0, sps, step):
        bits, decisions = demodulate_bits(
            work,
            config,
            min_energy=min_energy,
            min_ratio=min_ratio,
            apply_bandpass=False,
            timing_offset_samples=offset,
            frequency_search_hz=frequency_search_hz,
            frequency_search_step_hz=frequency_search_step_hz,
        )
        score, idx = preamble_match_score(bits, pattern)
        remaining = len(bits) - idx if idx >= 0 else 0
        if score > best_score or (
            score == best_score and remaining > len(best_bits)
        ):
            best_score = score
            best_offset = offset
            best_bits = bits
            best_decisions = decisions
        if score >= perfect and remaining >= len(pattern) + 32:
            break

    return best_offset, best_bits, best_decisions, max(best_score, 0)


def add_channel_impairments(
    waveform: np.ndarray,
    noise_level: float = 0.0,
    attenuation: float = 1.0,
    timing_offset_samples: int = 0,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """Apply Gaussian noise, attenuation, and optional timing offset."""
    if attenuation < 0:
        raise ValueError("attenuation must be >= 0")
    if noise_level < 0:
        raise ValueError("noise_level must be >= 0")
    out = waveform.astype(np.float64) * attenuation
    if timing_offset_samples > 0:
        out = np.concatenate([np.zeros(timing_offset_samples), out])
    elif timing_offset_samples < 0:
        out = out[-timing_offset_samples:]
    if noise_level > 0:
        if rng is None:
            rng = np.random.default_rng()
        out = out + rng.normal(0.0, noise_level, size=out.shape)
    peak = np.max(np.abs(out)) if len(out) else 0.0
    if peak > 0.99:
        out = out * (0.95 / peak)
    return out


def estimate_noise_floor(
    samples: np.ndarray,
    config: ModulationConfig,
    n_windows: int = 10,
) -> float:
    """Estimate background energy from the quietest weaker-bin windows.

    For each symbol window the *weaker* of the two Goertzel energies is
    retained (approximation of out-of-tone / noise energy). The median of
    the quietest such values is returned so tone-bearing recordings that
    start mid-frame do not inflate the floor.
    """
    sps = config.samples_per_symbol
    if len(samples) < sps:
        e0 = goertzel(samples, config.frequency_zero, config.sample_rate)
        e1 = goertzel(samples, config.frequency_one, config.sample_rate)
        return float(min(e0, e1))
    energies: List[float] = []
    n_symbols = len(samples) // sps
    for i in range(n_symbols):
        window = samples[i * sps : (i + 1) * sps]
        e0 = goertzel(window, config.frequency_zero, config.sample_rate)
        e1 = goertzel(window, config.frequency_one, config.sample_rate)
        energies.append(float(min(e0, e1)))
    if not energies:
        return 0.0
    arr = np.asarray(energies, dtype=np.float64)
    quietest = np.sort(arr)[: max(1, min(n_windows, len(arr)))]
    return float(np.median(quietest))


def detect_clipping(samples: np.ndarray, threshold: float = 0.98) -> bool:
    """Return True if any sample magnitude exceeds *threshold*."""
    if len(samples) == 0:
        return False
    return bool(np.any(np.abs(samples) >= threshold))


def normalize_gain(
    samples: np.ndarray,
    target_peak: float = 0.5,
) -> np.ndarray:
    """Optional automatic gain normalization to *target_peak*."""
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak < 1e-12:
        return samples
    return (samples * (target_peak / peak)).astype(np.float64)


def modulate_bfsk(
    bits: Sequence[int],
    config: ModulationConfig,
    inter_frame_silence: float = 0.0,
    repeats: int = 1,
) -> np.ndarray:
    """Legacy BFSK with per-symbol fades (backward-compatible)."""
    return bits_to_waveform(
        bits,
        config,
        inter_frame_silence=inter_frame_silence,
        repeats=repeats,
    )


def modulate_cpfsk(
    bits: Sequence[int],
    config: ModulationConfig,
    inter_frame_silence: float = 0.0,
    repeats: int = 1,
    frame_fade_ms: float = 5.0,
) -> np.ndarray:
    """Continuous-phase FSK with frame-level fades only.

    Phase is continuous across symbol boundaries. Amplitude stays constant
    except for a short fade at the start and end of each repeated frame
    (not per-symbol silence). This reduces spectral splatter relative to
    legacy per-symbol faded BFSK.
    """
    if repeats < 1 or repeats > 3:
        raise ValueError("repeats must be 1, 2, or 3")
    if inter_frame_silence < 0:
        raise ValueError("inter_frame_silence must be >= 0")

    chunks: List[np.ndarray] = []
    silence_n = int(round(inter_frame_silence * config.sample_rate))
    fade_n = max(1, int(round((frame_fade_ms / 1000.0) * config.sample_rate)))

    for rep in range(repeats):
        phase = 0.0
        parts: List[np.ndarray] = []
        for bit in bits:
            if bit not in (0, 1):
                raise ValueError(f"Invalid bit: {bit!r}")
            freq = config.frequency_one if bit == 1 else config.frequency_zero
            n = config.samples_per_symbol
            t = np.arange(n, dtype=np.float64) / config.sample_rate
            # Instantaneous phase: continuous integration
            samples = config.amplitude * np.sin(
                2.0 * np.pi * freq * t + phase
            )
            phase = (phase + 2.0 * np.pi * freq * config.symbol_duration) % (
                2.0 * np.pi
            )
            parts.append(samples)
        frame = np.concatenate(parts) if parts else np.zeros(0)
        if len(frame) > 2 * fade_n:
            ramp = np.linspace(0.0, 1.0, fade_n, endpoint=False)
            frame = frame.copy()
            frame[:fade_n] *= ramp
            frame[-fade_n:] *= ramp[::-1]
        chunks.append(frame)
        if rep < repeats - 1 and silence_n > 0:
            chunks.append(np.zeros(silence_n, dtype=np.float64))

    if not chunks:
        return np.zeros(0, dtype=np.float64)
    waveform = np.concatenate(chunks)
    peak = float(np.max(np.abs(waveform))) if len(waveform) else 0.0
    if peak > 0.99:
        waveform = waveform * (0.95 / peak)
    return waveform.astype(np.float64)


def modulate(
    bits: Sequence[int],
    config: ModulationConfig,
    *,
    modulation: str = "bfsk",
    inter_frame_silence: float = 0.0,
    repeats: int = 1,
) -> np.ndarray:
    """Dispatch to BFSK or CPFSK modulators."""
    mode = modulation.lower().strip()
    if mode == "bfsk":
        return modulate_bfsk(
            bits, config, inter_frame_silence=inter_frame_silence, repeats=repeats
        )
    if mode in ("cpfsk", "cp-fsk", "continuous"):
        return modulate_cpfsk(
            bits, config, inter_frame_silence=inter_frame_silence, repeats=repeats
        )
    raise ValueError(f"Unknown modulation: {modulation!r}")
