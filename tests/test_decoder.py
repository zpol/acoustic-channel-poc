"""End-to-end decoder tests without physical audio hardware."""

from __future__ import annotations

import numpy as np
import pytest

from src.modulation import (
    ModulationConfig,
    add_channel_impairments,
    bits_to_waveform,
)
from src.protocol import encode_message
from src.receiver import decode_from_samples


MESSAGE = "DEMO-LAB-2027"


def _tx_rx(
    message: str = MESSAGE,
    noise_level: float = 0.0,
    attenuation: float = 1.0,
    timing_offset: int = 0,
    symbol_duration: float = 0.1,
    seed: int = 42,
    leading_silence_s: float = 0.0,
):
    cfg = ModulationConfig(
        symbol_duration=symbol_duration,
        amplitude=0.2,
    )
    bits = encode_message(message)
    wave = bits_to_waveform(bits, cfg)
    if leading_silence_s > 0:
        pad = np.zeros(int(leading_silence_s * cfg.sample_rate))
        wave = np.concatenate([pad, wave])
    rng = np.random.default_rng(seed)
    rx = add_channel_impairments(
        wave,
        noise_level=noise_level,
        attenuation=attenuation,
        timing_offset_samples=timing_offset,
        rng=rng,
    )
    stats, decisions, result = decode_from_samples(
        rx,
        cfg,
        min_energy=1e-5,
        min_ratio=1.3,
        apply_bandpass=True,
        expected_bits=bits,
    )
    return stats, decisions, result, cfg


class TestCleanDecoding:
    def test_clean_signal_recovers_message(self) -> None:
        stats, _, result, _ = _tx_rx(noise_level=0.0)
        assert result.success
        assert stats.frame_success
        assert stats.recovered_message == MESSAGE
        assert stats.bit_error_rate is not None
        assert stats.bit_error_rate == 0.0

    def test_leading_silence_still_syncs(self) -> None:
        stats, _, result, _ = _tx_rx(leading_silence_s=0.5)
        assert result.success
        assert stats.recovered_message == MESSAGE

    def test_short_payload(self) -> None:
        stats, _, result, _ = _tx_rx(message="OK")
        assert result.success
        assert stats.recovered_message == "OK"


class TestNoisyDecoding:
    def test_moderate_noise(self) -> None:
        stats, _, result, _ = _tx_rx(noise_level=0.02, seed=7)
        assert result.success, result.error
        assert stats.recovered_message == MESSAGE

    def test_attenuation(self) -> None:
        stats, _, result, _ = _tx_rx(attenuation=0.3, noise_level=0.005)
        assert result.success
        assert stats.recovered_message == MESSAGE


class TestInvalidFrames:
    def test_crc_corruption_rejected(self) -> None:
        cfg = ModulationConfig(symbol_duration=0.1, amplitude=0.2)
        bits = encode_message(MESSAGE)
        # Flip the final CRC bit so framing still parses but CRC fails
        corrupted = list(bits)
        corrupted[-1] = 1 - corrupted[-1]
        wave = bits_to_waveform(corrupted, cfg)
        stats, _, result = decode_from_samples(
            wave, cfg, min_energy=1e-5, min_ratio=1.3, apply_bandpass=False
        )[:3]
        assert not result.success
        assert not stats.frame_success
        assert result.error is not None
        assert "CRC" in result.error

    def test_empty_payload_rejected_at_encode(self) -> None:
        from src.protocol import ProtocolError, build_frame

        with pytest.raises(ProtocolError):
            build_frame("")

    def test_oversized_payload_rejected_at_encode(self) -> None:
        from src.protocol import MAX_PAYLOAD_BYTES, ProtocolError, build_frame

        with pytest.raises(ProtocolError):
            build_frame("X" * (MAX_PAYLOAD_BYTES + 1))


class TestSymbolDurations:
    @pytest.mark.parametrize("duration", [0.20, 0.15, 0.10, 0.05])
    def test_various_symbol_durations(self, duration: float) -> None:
        stats, _, result, _ = _tx_rx(
            symbol_duration=duration, noise_level=0.01, seed=1
        )
        assert result.success, f"failed at {duration}s: {result.error}"
        assert stats.recovered_message == MESSAGE


class TestTimingRecovery:
    def test_recovers_with_large_timing_offset(self) -> None:
        cfg = ModulationConfig(symbol_duration=0.1, amplitude=0.2)
        bits = encode_message(MESSAGE)
        wave = bits_to_waveform(bits, cfg)
        # Offset by ~40% of a symbol — previously broke sync
        offset = int(0.4 * cfg.samples_per_symbol)
        rx = np.concatenate([np.zeros(offset), wave])
        stats, _, result = decode_from_samples(
            rx,
            cfg,
            min_energy=1e-5,
            min_ratio=1.3,
            apply_bandpass=True,
            expected_bits=bits,
            timing_search=True,
        )
        assert result.success, result.error
        assert stats.recovered_message == MESSAGE
        assert stats.timing_offset_samples >= 0

    def test_noisy_offset_still_ok(self) -> None:
        stats, _, result, _ = _tx_rx(
            noise_level=0.02,
            timing_offset=1500,
            symbol_duration=0.1,
            seed=3,
        )
        assert result.success, result.error
