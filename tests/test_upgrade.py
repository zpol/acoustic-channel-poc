"""Tests for FEC, CPFSK, sync, safety, and latency."""

from __future__ import annotations

import numpy as np
import pytest

from src.fec import (
    decode_hamming74,
    decode_hamming74_block,
    encode_hamming74,
    encode_hamming74_block,
)
from src.modulation import ModulationConfig, modulate, goertzel
from src.protocol import encode_message
from src.safety import SafetyError, require_safe, validate_transmission
from src.synchronization import (
    align_recording,
    estimate_latency,
    find_sync_correlation,
    generate_sync_pilot,
)


class TestHamming74:
    def test_roundtrip(self) -> None:
        data = [1, 0, 1, 1]
        cw = encode_hamming74_block(data)
        assert len(cw) == 7
        out, corr = decode_hamming74_block(cw)
        assert out == data
        assert corr == 0

    def test_single_bit_correction_all_positions(self) -> None:
        data = [1, 0, 1, 0]
        cw = encode_hamming74_block(data)
        for i in range(7):
            broken = list(cw)
            broken[i] ^= 1
            out, corr = decode_hamming74_block(broken)
            assert corr == 1
            assert out == data

    def test_stream_roundtrip(self) -> None:
        bits = encode_message("HELLO")
        coded = encode_hamming74(bits)
        result = decode_hamming74(coded)
        assert result.bits == bits
        assert result.corrected_bits == 0


class TestCPFSK:
    def test_length_and_amplitude(self) -> None:
        cfg = ModulationConfig(symbol_duration=0.05, amplitude=0.2)
        bits = [0, 1, 1, 0, 1]
        w = modulate(bits, cfg, modulation="cpfsk")
        assert len(w) == cfg.samples_per_symbol * len(bits)
        assert float(np.max(np.abs(w))) <= 0.21

    def test_phase_continuity_no_nan(self) -> None:
        cfg = ModulationConfig(symbol_duration=0.05, amplitude=0.15)
        bits = [0, 0, 1, 1, 0, 1]
        w = modulate(bits, cfg, modulation="cpfsk")
        assert np.isfinite(w).all()
        # No hard zeros in the middle (unlike per-symbol faded BFSK)
        mid = w[cfg.samples_per_symbol // 2 : -cfg.samples_per_symbol // 2]
        assert float(np.max(np.abs(mid))) > 0.05

    def test_dominant_frequency(self) -> None:
        cfg = ModulationConfig(symbol_duration=0.1, amplitude=0.2)
        for bit, freq in ((0, cfg.frequency_zero), (1, cfg.frequency_one)):
            w = modulate([bit], cfg, modulation="cpfsk")
            e_match = goertzel(w, freq, cfg.sample_rate)
            other = cfg.frequency_one if bit == 0 else cfg.frequency_zero
            e_other = goertzel(w, other, cfg.sample_rate)
            assert e_match > e_other * 3

    def test_deterministic(self) -> None:
        cfg = ModulationConfig(symbol_duration=0.05)
        bits = encode_message("OK")
        a = modulate(bits, cfg, modulation="cpfsk")
        b = modulate(bits, cfg, modulation="cpfsk")
        assert np.allclose(a, b)


class TestSync:
    def test_latency_synthetic(self) -> None:
        sr = 48000
        pilot = generate_sync_pilot(sr, duration=0.04, amplitude=0.2)
        delay = 2400
        rec = np.concatenate([np.zeros(delay), pilot, np.zeros(1000)])
        rec += np.random.default_rng(0).normal(0, 0.001, size=rec.shape)
        est = estimate_latency(pilot, rec, sr)
        assert est.detected
        assert abs(est.latency_samples - delay) <= 5
        aligned = align_recording(rec, est)
        assert len(aligned) < len(rec)

    def test_correlation_sync_with_errors(self) -> None:
        from src.protocol import PREAMBLE_AND_SYNC

        bits = list(PREAMBLE_AND_SYNC) + [0] * 16
        bits[3] ^= 1  # one bit error in preamble
        result = find_sync_correlation(bits, max_hamming=2)
        assert result.state == "SYNCED"
        assert result.best is not None
        assert result.best.bit_index == 0


class TestSafety:
    def test_amplitude_limit(self) -> None:
        with pytest.raises(SafetyError):
            require_safe(
                amplitude=0.9,
                frequency_zero=3500,
                frequency_one=7500,
                sample_rate=48000,
                symbol_duration=0.12,
                payload_bytes=8,
                repeats=1,
                near_ultrasonic=False,
                estimated_duration_s=10,
            )

    def test_near_us_requires_flag(self) -> None:
        report = validate_transmission(
            amplitude=0.1,
            frequency_zero=18500,
            frequency_one=19500,
            sample_rate=48000,
            symbol_duration=0.12,
            payload_bytes=5,
            repeats=1,
            near_ultrasonic=False,
            estimated_duration_s=10,
        )
        assert not report.ok


class TestProtocolFec:
    def test_fec_roundtrip_crc(self) -> None:
        from src.protocol import decode_bits, encode_message

        bits = encode_message("HELLO", fec="hamming74")
        assert decode_bits(bits, fec="hamming74").success
        assert decode_bits(bits, fec="none").success is False

    def test_fec_single_bit_body_flip(self) -> None:
        from src.protocol import decode_bits, encode_message

        bits = encode_message("OK", fec="hamming74")
        # Flip one bit in coded body
        broken = list(bits)
        broken[len(broken) // 2] ^= 1
        result = decode_bits(broken, fec="hamming74")
        assert result.success
        assert result.frame is not None
        assert result.frame.payload_text == "OK"
        assert result.fec_corrected_bits >= 1


class TestFrequencySearch:
    def test_offset_carriers(self) -> None:
        from src.modulation import ModulationConfig, modulate, demodulate_bits
        from src.protocol import encode_message

        cfg = ModulationConfig(symbol_duration=0.08, amplitude=0.2)
        bits = encode_message("HI")
        w = modulate(bits, cfg, modulation="cpfsk")
        # Retune detector slightly off
        cfg2 = ModulationConfig(
            symbol_duration=0.08,
            amplitude=0.2,
            frequency_zero=cfg.frequency_zero + 40,
            frequency_one=cfg.frequency_one + 40,
        )
        soft_fail, _ = demodulate_bits(w, cfg2, min_ratio=1.2, frequency_search_hz=0)
        soft_ok, _ = demodulate_bits(
            w, cfg2, min_ratio=1.2, frequency_search_hz=80, frequency_search_step_hz=10
        )
        # With search, more certain bits expected
        assert sum(b is not None for b in soft_ok) >= sum(b is not None for b in soft_fail)


class TestCarrierRecommend:
    def test_three_labels(self) -> None:
        from src.carrier_recommend import FreqPoint, recommend_carrier_pairs

        pts = [
            FreqPoint(f, snr, 1.0)
            for f, snr in [
                (3000, 20),
                (4000, 22),
                (5000, 18),
                (6000, 17),
                (8000, 15),
                (16000, 9),
                (18000, 6),
            ]
        ]
        recs = recommend_carrier_pairs(pts)
        labels = {r.label for r in recs}
        assert "MOST_RELIABLE" in labels
