"""BFSK receiver CLI — records microphone audio or simulates a channel.

Uses Goertzel detection, preamble/sync search, CRC validation, and a
rich live status display. Supports --simulate for hardware-free tests.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from scipy.io import wavfile

from src.modulation import (
    DEFAULT_AMPLITUDE,
    DEFAULT_FREQUENCY_ONE,
    DEFAULT_FREQUENCY_ZERO,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SYMBOL_DURATION,
    HIGH_FREQ_WARNING_HZ,
    ModulationConfig,
    SymbolDecision,
    add_channel_impairments,
    bits_to_waveform,
    modulate,
    demodulate_bits,
    detect_clipping,
    estimate_noise_floor,
    find_best_timing_offset,
    normalize_gain,
    soft_bits_from_decisions,
)
from src.cli_common import add_profile_argument, apply_profile
from src.protocol import (
    FEC_MODES,
    FEC_NONE,
    PREAMBLE_AND_SYNC,
    DecodeResult,
    decode_bits,
    encode_message,
    validate_payload,
)
from src.synchronization import find_sync_correlation, find_sync_soft_energy
from src.visualizer import (
    save_bit_timeline,
    save_energy_over_time,
    save_spectrogram,
    save_waveform_plot,
)

console = Console()


@dataclass
class QualityStats:
    """Signal quality and decode statistics."""

    n_symbols: int = 0
    n_certain: int = 0
    n_uncertain: int = 0
    mean_confidence: float = 0.0
    noise_floor: float = 0.0
    clipping: bool = False
    snr_estimate_db: Optional[float] = None
    bit_error_rate: Optional[float] = None
    frame_success: bool = False
    recovered_message: Optional[str] = None
    decode_error: Optional[str] = None
    preamble_found: bool = False
    timing_offset_samples: int = 0
    preamble_score: int = 0
    fec_corrected_bits: int = 0
    syndrome_corrections_attempted: int = 0
    fec_codewords_with_nonzero_syndrome: int = 0
    post_fec_crc_valid: bool = False
    sync_state: str = "NO_SIGNAL"
    sync_score: float = 0.0
    nominal_symbol_duration_ms: float = 0.0
    estimated_symbol_duration_ms: float = 0.0
    clock_drift_percent: float = 0.0
    combine_mode: str = "none"  # none | direct | soft_log_energy
    frames_combined: int = 0


@dataclass
class LiveStatus:
    """Mutable state for the rich live display."""

    recording: bool = False
    current_frequency: str = "—"
    energy_zero: float = 0.0
    energy_one: float = 0.0
    detected_bit: str = "—"
    confidence: float = 0.0
    bits_collected: int = 0
    preamble_status: str = "searching"
    crc_status: str = "—"
    recovered_message: str = "—"
    notes: List[str] = field(default_factory=list)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.receiver",
        description=(
            "Educational acoustic-channel receiver (BFSK + Goertzel). "
            "Audible mode is the default. Default profile is fast (~8 bit/s)."
        ),
    )
    add_profile_argument(parser)
    parser.add_argument("--input-device", type=int, default=None)
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Recording duration in seconds",
    )
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument(
        "--symbol-duration", type=float, default=DEFAULT_SYMBOL_DURATION
    )
    parser.add_argument(
        "--frequency-zero", type=float, default=DEFAULT_FREQUENCY_ZERO
    )
    parser.add_argument(
        "--frequency-one", type=float, default=DEFAULT_FREQUENCY_ONE
    )
    parser.add_argument(
        "--near-ultrasonic",
        action="store_true",
        help="Required when using frequencies above 17 kHz",
    )
    parser.add_argument(
        "--min-energy",
        type=float,
        default=1e-4,
        help="Minimum Goertzel energy to accept a symbol",
    )
    parser.add_argument(
        "--min-ratio",
        type=float,
        default=1.5,
        help="Minimum energy ratio between tones to decide a bit",
    )
    parser.add_argument(
        "--noise-threshold",
        type=float,
        default=None,
        help="Override auto noise floor (Goertzel energy units)",
    )
    parser.add_argument(
        "--bandpass",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply band-pass around BFSK tones (default: on)",
    )
    parser.add_argument(
        "--normalize-gain",
        action="store_true",
        help="Optional automatic gain normalization",
    )
    parser.add_argument(
        "--save-raw-wav",
        type=Path,
        default=None,
        help="Diagnostic: save raw microphone audio before processing",
    )
    parser.add_argument(
        "--spectrogram", type=Path, default=None, help="Save spectrogram PNG"
    )
    parser.add_argument(
        "--energy-plot", type=Path, default=None, help="Save energy-over-time PNG"
    )
    parser.add_argument(
        "--bit-timeline", type=Path, default=None, help="Save bit timeline PNG"
    )
    parser.add_argument(
        "--waveform-plot", type=Path, default=None, help="Save waveform PNG"
    )
    # Simulation mode
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Decode a synthetic waveform in memory (no hardware)",
    )
    parser.add_argument(
        "--message",
        default="DEMO-LAB-2027",
        help="Payload used in --simulate mode",
    )
    parser.add_argument(
        "--noise-level",
        type=float,
        default=0.0,
        help="Gaussian noise std-dev for --simulate",
    )
    parser.add_argument(
        "--attenuation",
        type=float,
        default=1.0,
        help="Amplitude scale for --simulate",
    )
    parser.add_argument(
        "--timing-offset",
        type=int,
        default=0,
        help="Sample timing offset for --simulate",
    )
    parser.add_argument(
        "--amplitude",
        type=float,
        default=DEFAULT_AMPLITUDE,
        help="TX amplitude used when synthesizing in --simulate",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for simulate")
    parser.add_argument(
        "--modulation",
        choices=("bfsk", "cpfsk"),
        default="bfsk",
        help="Waveform used in --simulate (must match TX)",
    )
    parser.add_argument(
        "--fec",
        choices=FEC_MODES,
        default=FEC_NONE,
        help="Must match transmitter FEC mode",
    )
    parser.add_argument(
        "--sync-mode",
        choices=("legacy", "correlation"),
        default="legacy",
        help="Preamble sync: exact match (legacy) or Hamming-tolerant correlation",
    )
    parser.add_argument(
        "--frequency-search-hz",
        type=float,
        default=0.0,
        help="Search ±Hz around each carrier (0 disables)",
    )
    parser.add_argument(
        "--frequency-search-step-hz",
        type=float,
        default=10.0,
        help="Step size for carrier neighbourhood search",
    )
    return parser


def log_config(config: ModulationConfig, **extra: object) -> None:
    console.print("[bold]Active receiver configuration[/bold]")
    console.print(f"  sample_rate      = {config.sample_rate}")
    console.print(f"  symbol_duration  = {config.symbol_duration}")
    console.print(f"  frequency_zero   = {config.frequency_zero}")
    console.print(f"  frequency_one    = {config.frequency_one}")
    console.print(f"  near_ultrasonic  = {config.near_ultrasonic}")
    for key, value in extra.items():
        console.print(f"  {key:17}= {value}")


def render_status(status: LiveStatus) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    rows = [
        ("Recording", "YES" if status.recording else "no"),
        ("Current frequency", status.current_frequency),
        ("Energy f0", f"{status.energy_zero:.4e}"),
        ("Energy f1", f"{status.energy_one:.4e}"),
        ("Detected bit", status.detected_bit),
        ("Confidence", f"{status.confidence:.2f}"),
        ("Bits collected", str(status.bits_collected)),
        ("Preamble", status.preamble_status),
        ("CRC", status.crc_status),
        ("Message", status.recovered_message),
    ]
    for label, value in rows:
        table.add_row(label, value)
    note_text = "\n".join(status.notes[-3:]) if status.notes else ""
    body = Group(table, note_text) if note_text else table
    return Panel(body, title="Acoustic channel receiver", border_style="cyan")


def _certain_bits(bits: Sequence[Optional[int]]) -> List[int]:
    """Replace uncertain symbols with 0 for scanning; track separately."""
    return [b if b is not None else 0 for b in bits]


def _find_preamble_in_optional(
    bits: Sequence[Optional[int]],
) -> Tuple[bool, int]:
    pattern = PREAMBLE_AND_SYNC
    plen = len(pattern)
    for i in range(max(0, len(bits) - plen + 1)):
        window = bits[i : i + plen]
        if any(b is None for b in window):
            continue
        if tuple(window) == pattern:  # type: ignore[arg-type]
            return True, i
    return False, -1


def _find_all_preambles(bits: Sequence[int]) -> List[int]:
    """Return start indices of every exact preamble+sync match."""
    pattern = PREAMBLE_AND_SYNC
    plen = len(pattern)
    hits: List[int] = []
    i = 0
    while i <= len(bits) - plen:
        if tuple(bits[i : i + plen]) == pattern:
            hits.append(i)
            i += plen  # skip past this match
        else:
            i += 1
    return hits


def _soft_log_energy_combine(
    soft_bits: Sequence[int],
    decisions: Sequence[SymbolDecision],
    fec: str = FEC_NONE,
    eps: float = 1e-20,
) -> Tuple[DecodeResult, int]:
    """Soft log-energy combining across repeated preamble-aligned copies.

    For each symbol position accumulates ``log((e1+eps)/(e0+eps))`` from each
    contributing copy, then hard-decides the sign. Prefer any directly
    CRC-valid frame before combining (caller responsibility).
    """
    hits = _find_all_preambles(list(soft_bits))
    if len(hits) < 2:
        return DecodeResult(success=False, error="Not enough frame copies"), 0

    frames: List[List[int]] = []
    frame_decisions: List[List[SymbolDecision]] = []
    for h in hits:
        header = soft_bits[h + len(PREAMBLE_AND_SYNC) : h + len(PREAMBLE_AND_SYNC) + 16]
        if len(header) < 16:
            continue
        try:
            from src.protocol import bits_to_bytes, frame_bit_count

            length = bits_to_bytes(header[8:16])[0]
        except Exception:
            continue
        if length < 1 or length > 32:
            continue
        try:
            frame_bits = frame_bit_count(length, fec=fec)
        except Exception:
            frame_bits = len(PREAMBLE_AND_SYNC) + 16 + length * 8 + 16
        chunk = list(soft_bits[h : h + frame_bits])
        if len(chunk) < frame_bits // 2:
            continue
        region = list(decisions[h : h + min(len(chunk), len(decisions) - h)])
        if region:
            mean_e = float(
                np.mean([max(d.energy_zero, d.energy_one) for d in region])
            )
            if mean_e < 1e-4:
                continue
        frames.append(chunk)
        frame_decisions.append(region)

    if len(frames) < 2:
        return DecodeResult(success=False, error="Not enough aligned copies"), 0

    lengths = [len(f) for f in frames]
    target_len = max(set(lengths), key=lengths.count)
    kept = [(f, d) for f, d in zip(frames, frame_decisions) if len(f) == target_len]
    if len(kept) < 2:
        return DecodeResult(success=False, error="Not enough equal-length copies"), 0

    combined: List[int] = []
    for i in range(target_len):
        score = 0.0
        for _frame_bits, region in kept:
            if i < len(region):
                d = region[i]
                score += float(
                    np.log((d.energy_one + eps) / (d.energy_zero + eps))
                )
            else:
                # Fall back to hard bit when energies unavailable
                score += 1.0 if _frame_bits[i] else -1.0
        combined.append(1 if score > 0.0 else 0)
    return decode_bits(combined, fec=fec), len(kept)


# Backwards-compatible alias (hard majority was inaccurate naming)
def _majority_vote_decode(
    soft_bits: Sequence[int],
    decisions: Sequence[SymbolDecision],
    fec: str = FEC_NONE,
) -> DecodeResult:
    result, _n = _soft_log_energy_combine(soft_bits, decisions, fec=fec)
    return result


def _try_decode_candidates(
    hard_bits: Sequence[int],
    soft_bits: Sequence[int],
    decisions: Sequence[SymbolDecision],
    min_preamble_confidence: float = 0.15,
    fec: str = FEC_NONE,
    sync_mode: str = "legacy",
) -> Tuple[DecodeResult, str, int, float]:
    """Decode using hard bits first; soft energy sync / combining to repair.

    Returns:
        (result, combine_mode, frames_combined, sync_score)
    """
    hard_result = decode_bits(hard_bits, fec=fec)
    if hard_result.success:
        return hard_result, "direct", 1, 1.0

    # Soft repair at the hard-detected sync point (CRC flips, etc.)
    if hard_result.sync_offset is not None:
        data_start = hard_result.sync_offset
        preamble_start = data_start - len(PREAMBLE_AND_SYNC)
        if preamble_start >= 0:
            soft_result = decode_bits(soft_bits[preamble_start:], fec=fec)
            if soft_result.success:
                return soft_result, "direct", 1, 1.0

    sync_score = 0.0
    # Soft energy correlation (preferred) or legacy hard Hamming correlation
    if sync_mode in ("correlation", "soft", "soft_correlation"):
        soft_sync = find_sync_soft_energy(decisions)
        if soft_sync.best is not None:
            sync_score = float(soft_sync.best.score)
            cand = decode_bits(soft_bits[soft_sync.best.bit_index :], fec=fec)
            if cand.success:
                return cand, "direct", 1, sync_score
            if soft_sync.best.bit_index < len(hard_bits):
                cand_h = decode_bits(hard_bits[soft_sync.best.bit_index :], fec=fec)
                if cand_h.success:
                    return cand_h, "direct", 1, sync_score
        # Legacy hard-bit correlation as fallback
        sync = find_sync_correlation(soft_bits, max_hamming=2)
        if sync.best is not None:
            sync_score = max(sync_score, float(sync.best.score))
            cand = decode_bits(soft_bits[sync.best.bit_index :], fec=fec)
            if cand.success:
                return cand, "direct", 1, sync_score
            if sync.best.bit_index < len(hard_bits):
                cand_h = decode_bits(hard_bits[sync.best.bit_index :], fec=fec)
                if cand_h.success:
                    return cand_h, "direct", 1, sync_score

    # Explicit hard preamble hits (repeated frames)
    for idx in _find_all_preambles(list(hard_bits)):
        for stream in (hard_bits[idx:], soft_bits[idx:]):
            result = decode_bits(stream, fec=fec)
            if result.success:
                return result, "direct", 1, sync_score

    # Soft preamble search with confidence gate
    for idx in _find_all_preambles(list(soft_bits)):
        region = decisions[idx : idx + len(PREAMBLE_AND_SYNC)]
        if not region:
            continue
        mean_conf = float(np.mean([d.confidence for d in region]))
        mean_energy = float(
            np.mean([max(d.energy_zero, d.energy_one) for d in region])
        )
        if mean_conf < min_preamble_confidence and mean_energy < 1e-3:
            continue
        result = decode_bits(soft_bits[idx:], fec=fec)
        if result.success:
            return result, "direct", 1, sync_score

    # Soft log-energy combining across repeated copies (only if no direct CRC)
    combined, n_frames = _soft_log_energy_combine(soft_bits, decisions, fec=fec)
    if combined.success:
        return combined, "soft_log_energy", n_frames, sync_score

    return hard_result, "none", 0, sync_score


def decode_from_samples(
    samples: np.ndarray,
    config: ModulationConfig,
    min_energy: float,
    min_ratio: float,
    apply_bandpass: bool = True,
    noise_threshold: Optional[float] = None,
    expected_bits: Optional[Sequence[int]] = None,
    status: Optional[LiveStatus] = None,
    timing_search: bool = True,
    timing_steps: int = 24,
    fec: str = FEC_NONE,
    sync_mode: str = "legacy",
    frequency_search_hz: float = 0.0,
    frequency_search_step_hz: float = 10.0,
    symbol_duration_search_percent: float = 2.5,
    symbol_duration_search_steps: int = 7,
) -> Tuple[QualityStats, List[SymbolDecision], DecodeResult]:
    """Full demodulation + protocol decode with timing and clock-drift recovery.

    When ``symbol_duration_search_percent`` > 0, searches a bounded grid of
    symbol durations around the nominal configuration.
    """
    stats = QualityStats()
    stats.nominal_symbol_duration_ms = config.symbol_duration * 1000.0
    stats.estimated_symbol_duration_ms = stats.nominal_symbol_duration_ms
    if len(samples) > 0:
        samples = np.concatenate(
            [samples, np.zeros(config.samples_per_symbol * 2, dtype=np.float64)]
        )
    stats.clipping = detect_clipping(
        samples[: max(0, len(samples) - config.samples_per_symbol * 2)]
    )
    if stats.clipping and status is not None:
        status.notes.append("WARNING: clipping detected in recording")

    noise = (
        noise_threshold
        if noise_threshold is not None
        else estimate_noise_floor(samples, config)
    )
    stats.noise_floor = noise
    effective_min_energy = max(min_energy, noise * 2.0)

    duration_candidates = [config.symbol_duration]
    if (
        timing_search
        and symbol_duration_search_percent > 0
        and symbol_duration_search_steps > 1
    ):
        half = symbol_duration_search_percent / 100.0
        duration_candidates = [
            float(config.symbol_duration * (1.0 + frac))
            for frac in np.linspace(-half, half, symbol_duration_search_steps)
        ]

    best_pack = None
    for tsym in duration_candidates:
        trial_cfg = ModulationConfig(
            sample_rate=config.sample_rate,
            symbol_duration=float(tsym),
            frequency_zero=config.frequency_zero,
            frequency_one=config.frequency_one,
            amplitude=config.amplitude,
            near_ultrasonic=config.near_ultrasonic,
        )
        if timing_search and len(samples) >= trial_cfg.samples_per_symbol:
            offset, bits_opt, decisions, preamble_score = find_best_timing_offset(
                samples,
                trial_cfg,
                min_energy=effective_min_energy,
                min_ratio=min_ratio,
                apply_bandpass=apply_bandpass,
                n_steps=timing_steps,
                frequency_search_hz=frequency_search_hz,
                frequency_search_step_hz=frequency_search_step_hz,
            )
        else:
            bits_opt, decisions = demodulate_bits(
                samples,
                trial_cfg,
                min_energy=effective_min_energy,
                min_ratio=min_ratio,
                apply_bandpass=apply_bandpass,
                frequency_search_hz=frequency_search_hz,
                frequency_search_step_hz=frequency_search_step_hz,
            )
            offset, preamble_score = 0, 0

        hard = _certain_bits(bits_opt)
        soft = soft_bits_from_decisions(decisions)
        result, combine_mode, frames_combined, sync_score = _try_decode_candidates(
            hard, soft, decisions, fec=fec, sync_mode=sync_mode
        )
        pack = (
            trial_cfg,
            offset,
            bits_opt,
            decisions,
            preamble_score,
            result,
            combine_mode,
            frames_combined,
            sync_score,
        )
        if best_pack is None:
            best_pack = pack
        elif result.success and not best_pack[5].success:
            best_pack = pack
        elif result.success and best_pack[5].success:
            if sync_score > best_pack[8] or preamble_score > best_pack[4]:
                best_pack = pack
        elif not best_pack[5].success and not result.success:
            def _fail_rank(res, pscore, sscore, dur):
                err = (res.error or "")
                # Prefer framed CRC failures over garbage length/sync errors
                if "CRC" in err:
                    quality = 3
                elif "Preamble" in err or "sync" in err.lower():
                    quality = 2
                elif "length" in err.lower():
                    quality = 0
                else:
                    quality = 1
                # Prefer nominal duration on ties
                prox = -abs(dur - config.symbol_duration)
                return (quality, pscore, sscore, prox)

            if _fail_rank(result, preamble_score, sync_score, tsym) > _fail_rank(
                best_pack[5], best_pack[4], best_pack[8], best_pack[0].symbol_duration
            ):
                best_pack = pack
        if result.success and abs(tsym - config.symbol_duration) < 1e-12:
            break

    assert best_pack is not None
    (
        used_cfg,
        offset,
        bits_opt,
        decisions,
        preamble_score,
        result,
        combine_mode,
        frames_combined,
        sync_score,
    ) = best_pack
    config = used_cfg
    stats.timing_offset_samples = offset
    stats.preamble_score = preamble_score
    stats.estimated_symbol_duration_ms = used_cfg.symbol_duration * 1000.0
    if stats.nominal_symbol_duration_ms > 0:
        stats.clock_drift_percent = (
            (stats.estimated_symbol_duration_ms - stats.nominal_symbol_duration_ms)
            / stats.nominal_symbol_duration_ms
            * 100.0
        )
    stats.sync_score = sync_score
    stats.combine_mode = combine_mode
    stats.frames_combined = frames_combined
    stats.n_symbols = len(decisions)
    stats.n_certain = sum(1 for d in decisions if d.bit is not None)
    stats.n_uncertain = stats.n_symbols - stats.n_certain
    if decisions:
        stats.mean_confidence = float(np.mean([d.confidence for d in decisions]))

    signal_energies = [
        max(d.energy_zero, d.energy_one) for d in decisions if d.bit is not None
    ]
    if signal_energies and noise > 0:
        stats.snr_estimate_db = float(
            10.0 * np.log10(np.mean(signal_energies) / (noise + 1e-20))
        )
        if stats.snr_estimate_db < 6.0 and status is not None:
            status.notes.append(
                f"WARNING: low SNR estimate ({stats.snr_estimate_db:.1f} dB)"
            )

    found, idx = _find_preamble_in_optional(bits_opt)
    soft = soft_bits_from_decisions(decisions)
    hard = _certain_bits(bits_opt)
    if not found:
        soft_hits = _find_all_preambles(soft)
        if soft_hits:
            found, idx = True, soft_hits[0]
    if sync_mode in ("correlation", "soft", "soft_correlation"):
        soft_sync = find_sync_soft_energy(decisions)
        stats.sync_state = soft_sync.state
        if soft_sync.best is not None:
            found = True
            idx = soft_sync.best.bit_index
            stats.sync_score = max(stats.sync_score, float(soft_sync.best.score))
    else:
        stats.sync_state = "SYNCED" if found else "NO_SIGNAL"
    stats.preamble_found = found
    if status is not None:
        status.preamble_status = (
            f"found @ symbol {idx} (offset {stats.timing_offset_samples})"
            if found
            else "not found"
        )
        status.bits_collected = stats.n_certain
        if decisions:
            last = decisions[-1]
            status.energy_zero = last.energy_zero
            status.energy_one = last.energy_one
            status.confidence = last.confidence
            status.detected_bit = str(last.bit) if last.bit is not None else "?"
            if last.bit == 1:
                status.current_frequency = f"{config.frequency_one:.0f} Hz"
            elif last.bit == 0:
                status.current_frequency = f"{config.frequency_zero:.0f} Hz"
            else:
                status.current_frequency = "uncertain"

    if not result.success and timing_search:
        sps = config.samples_per_symbol
        step = max(1, sps // max(4, timing_steps))
        refine_offsets = {
            max(0, stats.timing_offset_samples + d)
            for d in (-step // 2, step // 2, -step, step)
            if 0 <= stats.timing_offset_samples + d < sps
        }
        for off in refine_offsets:
            b2, d2 = demodulate_bits(
                samples,
                config,
                min_energy=effective_min_energy,
                min_ratio=min_ratio,
                apply_bandpass=apply_bandpass,
                timing_offset_samples=off,
                frequency_search_hz=frequency_search_hz,
                frequency_search_step_hz=frequency_search_step_hz,
            )
            cand, cmode, nfr, sscore = _try_decode_candidates(
                _certain_bits(b2),
                soft_bits_from_decisions(d2),
                d2,
                fec=fec,
                sync_mode=sync_mode,
            )
            if cand.success:
                result = cand
                bits_opt, decisions = b2, d2
                soft = soft_bits_from_decisions(decisions)
                hard = _certain_bits(bits_opt)
                stats.timing_offset_samples = off
                stats.n_symbols = len(decisions)
                stats.n_certain = sum(1 for d in decisions if d.bit is not None)
                stats.n_uncertain = stats.n_symbols - stats.n_certain
                stats.combine_mode = cmode
                stats.frames_combined = nfr
                stats.sync_score = sscore
                found, idx = _find_preamble_in_optional(bits_opt)
                stats.preamble_found = found or bool(_find_all_preambles(soft))
                break

    stats.frame_success = result.success
    stats.decode_error = result.error
    stats.fec_corrected_bits = result.fec_corrected_bits
    stats.syndrome_corrections_attempted = result.fec_corrected_bits
    stats.fec_codewords_with_nonzero_syndrome = result.fec_corrected_bits
    stats.post_fec_crc_valid = bool(result.success)
    if result.success and result.frame is not None:
        stats.recovered_message = result.frame.payload_text
        stats.preamble_found = True
        stats.sync_state = "CRC_VALID"
        if status is not None:
            status.crc_status = "OK"
            status.recovered_message = result.frame.payload_text
            status.preamble_status = (
                f"locked (offset {stats.timing_offset_samples} samples)"
            )
    else:
        if result.error and "CRC" in result.error:
            stats.sync_state = "CRC_FAILED"
        if status is not None:
            status.crc_status = result.error or "fail"

    compare_bits = soft if soft else hard
    if expected_bits is not None and len(compare_bits) >= len(expected_bits):
        align_idx = 0
        hits = _find_all_preambles(compare_bits)
        if hits:
            align_idx = hits[0]
        elif found and idx >= 0:
            align_idx = idx
        compare = compare_bits[align_idx : align_idx + len(expected_bits)]
        n = min(len(compare), len(expected_bits))
        if n > 0:
            errors = sum(1 for a, b in zip(compare[:n], expected_bits[:n]) if a != b)
            stats.bit_error_rate = errors / n

    return stats, decisions, result



def record_audio(
    duration: float,
    sample_rate: int,
    input_device: Optional[int],
    status: LiveStatus,
) -> np.ndarray:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is required for recording") from exc

    if input_device is not None:
        from src.audio_devices import validate_input_device

        validate_input_device(input_device)

    n_samples = int(round(duration * sample_rate))
    status.recording = True
    status.notes.append(f"Recording {duration:.1f}s …")
    with Live(render_status(status), console=console, refresh_per_second=4):
        recording = sd.rec(
            n_samples,
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=input_device,
        )
        # Update live UI while waiting
        start = time.time()
        while time.time() - start < duration:
            elapsed = time.time() - start
            status.notes = [f"Recording {elapsed:.1f}/{duration:.1f}s …"]
            # Live will refresh; sleep briefly
            time.sleep(0.25)
        sd.wait()
    status.recording = False
    samples = np.asarray(recording, dtype=np.float64).reshape(-1)
    return samples


def run_simulation(args: argparse.Namespace, config: ModulationConfig) -> int:
    validate_payload(args.message)
    expected_bits = encode_message(args.message, fec=args.fec)
    tx_cfg = ModulationConfig(
        sample_rate=config.sample_rate,
        symbol_duration=config.symbol_duration,
        frequency_zero=config.frequency_zero,
        frequency_one=config.frequency_one,
        amplitude=args.amplitude,
        near_ultrasonic=config.near_ultrasonic,
    )
    modulation = getattr(args, "modulation", "bfsk")
    tx = modulate(expected_bits, tx_cfg, modulation=modulation)
    rng = np.random.default_rng(args.seed)
    rx = add_channel_impairments(
        tx,
        noise_level=args.noise_level,
        attenuation=args.attenuation,
        timing_offset_samples=args.timing_offset,
        rng=rng,
    )
    status = LiveStatus()
    with Live(render_status(status), console=console, refresh_per_second=8):
        # Process in chunks to animate the live UI
        sps = config.samples_per_symbol
        # Full decode at end; animate decisions for UX
        stats, decisions, result = decode_from_samples(
            rx,
            config,
            min_energy=args.min_energy,
            min_ratio=args.min_ratio,
            apply_bandpass=args.bandpass,
            noise_threshold=args.noise_threshold,
            expected_bits=expected_bits,
            status=status,
            fec=args.fec,
            sync_mode=args.sync_mode,
            frequency_search_hz=args.frequency_search_hz,
            frequency_search_step_hz=args.frequency_search_step_hz,
        )
        for i, d in enumerate(decisions[:: max(1, len(decisions) // 20)]):
            status.bits_collected = min(len(decisions), (i + 1) * 20)
            status.energy_zero = d.energy_zero
            status.energy_one = d.energy_one
            status.confidence = d.confidence
            status.detected_bit = str(d.bit) if d.bit is not None else "?"
            time.sleep(0.02)
        # Final status already set by decode_from_samples

    _print_stats(stats)
    _maybe_save_plots(args, rx, config, decisions)
    return 0 if stats.frame_success else 1


def _print_stats(stats: QualityStats) -> None:
    console.print("[bold]Decode statistics[/bold]")
    console.print(f"  symbols          = {stats.n_symbols}")
    console.print(f"  certain / uncertain = {stats.n_certain} / {stats.n_uncertain}")
    console.print(f"  mean confidence  = {stats.mean_confidence:.3f}")
    console.print(f"  noise floor      = {stats.noise_floor:.4e}")
    console.print(f"  clipping         = {stats.clipping}")
    console.print(f"  timing offset    = {stats.timing_offset_samples} samples")
    console.print(f"  preamble score   = {stats.preamble_score}")
    if stats.snr_estimate_db is not None:
        console.print(f"  SNR estimate     = {stats.snr_estimate_db:.1f} dB")
    console.print(f"  preamble found   = {stats.preamble_found}")
    console.print(f"  frame success    = {stats.frame_success}")
    if stats.bit_error_rate is not None:
        console.print(f"  bit error rate   = {stats.bit_error_rate:.4f}")
    if stats.frame_success:
        console.print(
            f"[green]Recovered message:[/green] {stats.recovered_message!r}"
        )
    else:
        console.print(f"[red]Decode failed:[/red] {stats.decode_error}")


def _maybe_save_plots(
    args: argparse.Namespace,
    samples: np.ndarray,
    config: ModulationConfig,
    decisions: List[SymbolDecision],
) -> None:
    if args.spectrogram:
        save_spectrogram(samples, config.sample_rate, args.spectrogram)
        console.print(f"Saved spectrogram: {args.spectrogram}")
    if args.energy_plot:
        save_energy_over_time(samples, config, args.energy_plot)
        console.print(f"Saved energy plot: {args.energy_plot}")
    if args.bit_timeline:
        save_bit_timeline(decisions, config.symbol_duration, args.bit_timeline)
        console.print(f"Saved bit timeline: {args.bit_timeline}")
    if args.waveform_plot:
        save_waveform_plot(samples, config.sample_rate, args.waveform_plot)
        console.print(f"Saved waveform plot: {args.waveform_plot}")


def run_live(args: argparse.Namespace, config: ModulationConfig) -> int:
    status = LiveStatus()
    try:
        samples = record_audio(
            args.duration, config.sample_rate, args.input_device, status
        )
    except Exception as exc:
        console.print(f"[red]Recording error:[/red] {exc}")
        console.print(
            "Tip: python -m src.audio_devices — check mic permissions, "
            "PipeWire/Pulse/ALSA. See README troubleshooting."
        )
        return 1

    if args.save_raw_wav:
        # Save raw audio before aggressive processing (diagnostic)
        path = Path(args.save_raw_wav)
        path.parent.mkdir(parents=True, exist_ok=True)
        wavfile.write(str(path), config.sample_rate, samples.astype(np.float32))
        console.print(f"Saved raw WAV (pre-processing): {path}")

    samples_for_decode = samples
    if args.normalize_gain:
        samples_for_decode = normalize_gain(samples_for_decode)

    with Live(render_status(status), console=console, refresh_per_second=8):
        stats, decisions, _result = decode_from_samples(
            samples_for_decode,
            config,
            min_energy=args.min_energy,
            min_ratio=args.min_ratio,
            apply_bandpass=args.bandpass,
            noise_threshold=args.noise_threshold,
            status=status,
            fec=args.fec,
            sync_mode=args.sync_mode,
            frequency_search_hz=args.frequency_search_hz,
            frequency_search_step_hz=args.frequency_search_step_hz,
        )
        time.sleep(0.3)

    _print_stats(stats)
    _maybe_save_plots(args, samples_for_decode, config, decisions)
    return 0 if stats.frame_success else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args = apply_profile(args, argv)

    try:
        config = ModulationConfig(
            sample_rate=args.sample_rate,
            symbol_duration=args.symbol_duration,
            frequency_zero=args.frequency_zero,
            frequency_one=args.frequency_one,
            amplitude=args.amplitude,
            near_ultrasonic=args.near_ultrasonic,
        )
    except ValueError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        return 2

    if config.requires_near_ultrasonic_flag() and not args.near_ultrasonic:
        console.print(
            f"[red]Frequencies above {HIGH_FREQ_WARNING_HZ:.0f} Hz require "
            f"--near-ultrasonic[/red]"
        )
        return 2

    if config.requires_near_ultrasonic_flag():
        console.print(
            Panel(
                f"[yellow]High-frequency mode[/yellow]: "
                f"max={config.max_frequency:.0f} Hz. Hardware may filter "
                "content near or above 20 kHz.",
                border_style="yellow",
            )
        )

    log_config(
        config,
        simulate=args.simulate,
        duration=args.duration,
        min_energy=args.min_energy,
        min_ratio=args.min_ratio,
        bandpass=args.bandpass,
    )

    if args.simulate:
        return run_simulation(args, config)
    return run_live(args, config)


if __name__ == "__main__":
    sys.exit(main())
