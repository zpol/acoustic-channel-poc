"""Unit tests for BFSK modulation and Goertzel detection."""

from __future__ import annotations

import numpy as np
import pytest

from src.modulation import (
    ModulationConfig,
    add_channel_impairments,
    bits_to_waveform,
    decide_symbol,
    demodulate_bits,
    generate_tone,
    goertzel,
)
from src.protocol import encode_message


class TestToneGeneration:
    def test_length_and_amplitude(self) -> None:
        samples, phase = generate_tone(4000, 0.2, 48000, 0.15)
        assert len(samples) == 9600
        assert np.max(np.abs(samples)) <= 0.15 + 1e-9
        assert 0 <= phase < 2 * np.pi

    def test_fade_reduces_edges(self) -> None:
        samples, _ = generate_tone(4000, 0.2, 48000, 0.15, fade_ratio=0.05)
        assert abs(samples[0]) < 0.01
        assert abs(samples[-1]) < 0.01


class TestGoertzel:
    def test_detects_matching_frequency(self) -> None:
        sr = 48000
        tone, _ = generate_tone(4000, 0.2, sr, 0.2, fade_ratio=0.0)
        e_match = goertzel(tone, 4000, sr)
        e_other = goertzel(tone, 6000, sr)
        assert e_match > e_other * 5

    def test_config_rejects_above_nyquist(self) -> None:
        with pytest.raises(ValueError, match="Nyquist"):
            ModulationConfig(frequency_zero=30000, frequency_one=31000)


class TestWaveform:
    def test_bit_length_matches_symbols(self) -> None:
        bits = [0, 1, 0, 1]
        cfg = ModulationConfig()
        wave = bits_to_waveform(bits, cfg)
        assert len(wave) == cfg.samples_per_symbol * len(bits)

    def test_repeats(self) -> None:
        bits = [1, 0]
        cfg = ModulationConfig(symbol_duration=0.05)
        once = bits_to_waveform(bits, cfg, repeats=1)
        twice = bits_to_waveform(bits, cfg, repeats=2, inter_frame_silence=0.0)
        assert len(twice) == 2 * len(once)

    def test_no_clipping(self) -> None:
        bits = encode_message("DEMO-LAB-2027")
        wave = bits_to_waveform(bits, ModulationConfig(amplitude=0.15))
        assert np.max(np.abs(wave)) < 0.99


class TestDemodulation:
    def test_clean_symbol_decision(self) -> None:
        cfg = ModulationConfig()
        zero, _ = generate_tone(
            cfg.frequency_zero, cfg.symbol_duration, cfg.sample_rate, 0.2
        )
        one, _ = generate_tone(
            cfg.frequency_one, cfg.symbol_duration, cfg.sample_rate, 0.2
        )
        assert decide_symbol(zero, cfg).bit == 0
        assert decide_symbol(one, cfg).bit == 1

    def test_uncertain_when_silent(self) -> None:
        cfg = ModulationConfig()
        silence = np.zeros(cfg.samples_per_symbol)
        d = decide_symbol(silence, cfg, min_energy=1e-3)
        assert d.bit is None

    def test_demodulate_known_bits(self) -> None:
        bits = [0, 1, 1, 0, 1, 0]
        cfg = ModulationConfig(symbol_duration=0.1)
        wave = bits_to_waveform(bits, cfg)
        decoded, decisions = demodulate_bits(wave, cfg, apply_bandpass=False)
        assert all(d.bit is not None for d in decisions)
        assert decoded == bits


class TestImpairments:
    def test_noise_and_attenuation(self) -> None:
        bits = [0, 1, 0, 1]
        cfg = ModulationConfig(symbol_duration=0.1)
        wave = bits_to_waveform(bits, cfg)
        rng = np.random.default_rng(0)
        impaired = add_channel_impairments(
            wave, noise_level=0.01, attenuation=0.5, rng=rng
        )
        assert len(impaired) == len(wave)
        decoded, _ = demodulate_bits(impaired, cfg, apply_bandpass=True)
        assert decoded == bits
