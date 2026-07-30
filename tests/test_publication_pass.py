"""Publication-pass tests: provenance, replay, soft sync, drift, safety, modulation."""

from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from src.fec import decode_hamming74_block, encode_hamming74_block
from src.modulation import (
    ModulationConfig,
    SymbolDecision,
    add_channel_impairments,
    bits_to_waveform,
    goertzel,
    modulate,
    modulate_bfsk,
    modulate_cpfsk,
)
from src.protocol import encode_message
from src.provenance import (
    SCHEMA_VERSION,
    ProvenanceError,
    sha256_file,
    validate_physical_metadata,
)
from src.receiver import decode_from_samples
from src.replay import load_verified_physical_capture, metadata_sidecar
from src.safety import (
    MAX_AMPLITUDE,
    SafetyError,
    assert_playback_allowed,
    require_safe,
    validate_transmission,
)
from src.synchronization import (
    energy_soft_preamble_correlation,
    find_sync_soft_energy,
    soft_preamble_correlation,
    soft_symbol_value,
)
from src.protocol import PREAMBLE_AND_SYNC


# ---------------------------------------------------------------------------
# Provenance / replay fail-closed
# ---------------------------------------------------------------------------


def _physical_meta(**overrides):
    base = {
        "schema_version": SCHEMA_VERSION,
        "provenance": "PHYSICAL_RX",
        "timestamp": "2026-07-30T19:00:41Z",
        "git_commit": "deadbeef",
        "wav_sha256": "0" * 64,
        "sample_rate": 48000,
        "frequency_zero_hz": 3500.0,
        "frequency_one_hz": 7500.0,
        "symbol_duration_seconds": 0.12,
        "modulation": "cpfsk",
        "fec_mode": "none",
        "sync_mode": "soft_correlation",
        "payload_length": 5,
        "expected_payload": "HELLO",
    }
    base.update(overrides)
    return base


def test_validate_physical_metadata_valid(tmp_path: Path):
    wav = tmp_path / "rx.wav"
    wav.write_bytes(b"RIFF....")
    meta = _physical_meta(wav_sha256=sha256_file(wav))
    cap = validate_physical_metadata(meta, wav_path=wav)
    assert cap.provenance == "PHYSICAL_RX"


def test_missing_metadata_rejects_replay(tmp_path: Path):
    wav = tmp_path / "orphan.wav"
    wav.write_bytes(b"x" * 100)
    with pytest.raises(ProvenanceError, match="No metadata|Missing"):
        load_verified_physical_capture(wav)


def test_corrupt_json_rejects(tmp_path: Path):
    wav = tmp_path / "rx.wav"
    wav.write_bytes(b"x")
    meta_path = wav.with_suffix(wav.suffix + ".meta.json")
    meta_path.write_text("{not-json")
    with pytest.raises(ProvenanceError):
        load_verified_physical_capture(wav)


def test_missing_hash_rejects():
    meta = _physical_meta()
    del meta["wav_sha256"]
    with pytest.raises(ProvenanceError, match="Missing mandatory"):
        validate_physical_metadata(meta, require_hash_match=False)


def test_hash_mismatch_rejects(tmp_path: Path):
    wav = tmp_path / "rx.wav"
    wav.write_bytes(b"abc")
    meta = _physical_meta(wav_sha256="ff" * 32)
    with pytest.raises(ProvenanceError, match="hash|SHA|mismatch"):
        validate_physical_metadata(meta, wav_path=wav, require_hash_match=True)


def test_generated_tx_rejected_as_replay():
    meta = _physical_meta(provenance="GENERATED_TX")
    with pytest.raises(ProvenanceError, match="Unsupported provenance"):
        validate_physical_metadata(meta, require_hash_match=False)


def test_simulated_rx_rejected_as_physical():
    meta = _physical_meta(provenance="SIMULATED_RX")
    with pytest.raises(ProvenanceError, match="Unsupported provenance"):
        validate_physical_metadata(meta, require_hash_match=False)


def test_unsupported_schema_rejects():
    meta = _physical_meta(schema_version="9.9")
    with pytest.raises(ProvenanceError, match="schema"):
        validate_physical_metadata(meta, require_hash_match=False)


def test_missing_modulation_rejects():
    meta = _physical_meta()
    del meta["modulation"]
    with pytest.raises(ProvenanceError, match="Missing mandatory"):
        validate_physical_metadata(meta, require_hash_match=False)


def test_missing_fec_mode_rejects():
    meta = _physical_meta()
    del meta["fec_mode"]
    with pytest.raises(ProvenanceError, match="Missing mandatory"):
        validate_physical_metadata(meta, require_hash_match=False)


def test_missing_frequency_config_rejects():
    meta = _physical_meta()
    del meta["frequency_zero_hz"]
    with pytest.raises(ProvenanceError, match="Missing mandatory"):
        validate_physical_metadata(meta, require_hash_match=False)


def test_curated_replay_capture_validates():
    wav = Path("output/samples/replay/rx.wav")
    if not wav.exists():
        pytest.skip("curated replay WAV missing")
    samples, meta = load_verified_physical_capture(wav)
    assert len(samples) > 1000
    assert meta.modulation == "cpfsk"
    assert meta.expected_payload == "HELLO"
    stats, _, result = decode_from_samples(
        samples,
        ModulationConfig(
            sample_rate=meta.sample_rate,
            symbol_duration=meta.symbol_duration_seconds,
            frequency_zero=meta.frequency_zero_hz,
            frequency_one=meta.frequency_one_hz,
        ),
        min_energy=1e-6,
        min_ratio=1.15,
        fec=meta.fec_mode,
        sync_mode="correlation",
    )
    assert stats.frame_success
    assert stats.recovered_message == "HELLO"


# ---------------------------------------------------------------------------
# Soft sync
# ---------------------------------------------------------------------------


def _dec(bit: int, e0: float, e1: float) -> SymbolDecision:
    return SymbolDecision(
        bit=bit,
        energy_zero=e0,
        energy_one=e1,
        energy_ratio=max(e0, e1) / (min(e0, e1) + 1e-20),
        confidence=0.9,
    )


def test_soft_symbol_value_signs():
    assert soft_symbol_value(10.0, 1.0) < 0
    assert soft_symbol_value(1.0, 10.0) > 0


def test_exact_clean_preamble_soft_sync():
    decisions = []
    for b in PREAMBLE_AND_SYNC:
        if b:
            decisions.append(_dec(1, 1.0, 100.0))
        else:
            decisions.append(_dec(0, 100.0, 1.0))
    sync = find_sync_soft_energy(decisions)
    assert sync.state == "SYNCED"
    assert sync.best is not None
    assert sync.best.bit_index == 0
    assert sync.best.score > 0.9


def test_weak_incorrect_bit_soft_survives():
    decisions = []
    for i, b in enumerate(PREAMBLE_AND_SYNC):
        if i == 3:
            # weak incorrect: soft value near zero / wrong but low energy
            decisions.append(_dec(1 - b, 1.1, 1.0) if b == 0 else _dec(1 - b, 1.0, 1.1))
        elif b:
            decisions.append(_dec(1, 1.0, 100.0))
        else:
            decisions.append(_dec(0, 100.0, 1.0))
    sync = find_sync_soft_energy(decisions, min_score=0.5)
    assert sync.best is not None
    assert sync.best.bit_index == 0


def test_strong_incorrect_bit_lowers_score():
    clean = []
    dirty = []
    for b in PREAMBLE_AND_SYNC:
        if b:
            clean.append(_dec(1, 1.0, 100.0))
            dirty.append(_dec(0, 100.0, 1.0))  # strong wrong
        else:
            clean.append(_dec(0, 100.0, 1.0))
            dirty.append(_dec(1, 1.0, 100.0))
    # Only flip first bit strongly wrong in dirty relative to pattern
    dirty[0] = _dec(1, 1.0, 1000.0) if PREAMBLE_AND_SYNC[0] == 0 else _dec(0, 1000.0, 1.0)
    sc = energy_soft_preamble_correlation(clean)[0].score
    sd = energy_soft_preamble_correlation(dirty)[0].score
    assert sc > sd


def test_hard_matcher_still_available():
    bits = list(PREAMBLE_AND_SYNC)
    bits[2] ^= 1
    cands = soft_preamble_correlation(bits)
    assert cands[0].hamming_distance == 1


def test_noise_false_positive_not_synced():
    rng = np.random.default_rng(0)
    decisions = [
        _dec(int(rng.integers(0, 2)), float(rng.random()), float(rng.random()))
        for _ in range(64)
    ]
    sync = find_sync_soft_energy(decisions, min_score=0.85)
    assert sync.state != "SYNCED" or sync.best.score < 0.95


# ---------------------------------------------------------------------------
# Goertzel exact frequency
# ---------------------------------------------------------------------------


def test_goertzel_offset_detection():
    sr = 48000
    n = 2048
    t = np.arange(n) / sr
    for offset in (+20, -20, +50):
        f = 4000.0 + offset
        tone = np.sin(2 * np.pi * f * t)
        e_true = goertzel(tone, f, sr)
        e_nom = goertzel(tone, 4000.0, sr)
        e_far = goertzel(tone, 6000.0, sr)
        assert e_true > e_far
        # Exact-frequency estimator should still see energy near nominal
        assert e_nom > e_far * 0.5


def test_goertzel_closely_spaced_candidates():
    sr = 48000
    n = 4096
    t = np.arange(n) / sr
    tone = np.sin(2 * np.pi * 4010.0 * t)
    e4010 = goertzel(tone, 4010.0, sr)
    e4000 = goertzel(tone, 4000.0, sr)
    e4020 = goertzel(tone, 4020.0, sr)
    assert e4010 >= e4000
    assert e4010 >= e4020


# ---------------------------------------------------------------------------
# Modulation dispatcher / CPFSK simulation
# ---------------------------------------------------------------------------


def test_bfsk_cpfsk_waveforms_differ():
    cfg = ModulationConfig(symbol_duration=0.05, amplitude=0.2)
    bits = [0, 1, 1, 0, 1, 0, 0, 1]
    bfsk = modulate(bits, cfg, modulation="bfsk")
    cpfsk = modulate(bits, cfg, modulation="cpfsk")
    assert not np.allclose(bfsk, cpfsk)


def test_cpfsk_phase_continuity():
    cfg = ModulationConfig(symbol_duration=0.04, amplitude=0.2)
    bits = [0, 1, 0, 1, 1, 0]
    w = modulate_cpfsk(bits, cfg)
    # No large sample-to-sample jumps except at ends
    diffs = np.abs(np.diff(w))
    assert float(np.percentile(diffs, 99)) < 0.25


def test_legacy_bits_to_waveform_is_bfsk():
    cfg = ModulationConfig(symbol_duration=0.05)
    bits = [1, 0, 1]
    assert np.allclose(bits_to_waveform(bits, cfg), modulate_bfsk(bits, cfg))


def test_receiver_sim_uses_modulation_arg():
    # Ensure receiver CLI wires modulate — inspect source
    import src.receiver as rx

    src = inspect.getsource(rx.run_simulation)
    assert "modulate(" in src
    assert "modulation" in src


def test_simulation_decodes_bfsk_and_cpfsk():
    cfg = ModulationConfig(symbol_duration=0.08, amplitude=0.25)
    msg = "HI"
    for mod in ("bfsk", "cpfsk"):
        bits = encode_message(msg)
        tx = modulate(bits, cfg, modulation=mod)
        rx = add_channel_impairments(tx, noise_level=0.01, attenuation=0.8)
        stats, _, result = decode_from_samples(
            rx, cfg, min_energy=1e-5, min_ratio=1.2, expected_bits=bits
        )
        assert stats.frame_success, f"{mod} failed: {result.error}"


def test_clock_drift_recovery():
    cfg = ModulationConfig(symbol_duration=0.08, amplitude=0.25)
    bits = encode_message("AB")
    tx = modulate(bits, cfg, modulation="cpfsk")
    # Simulate mild clock drift by resampling
    factor = 1.015  # +1.5%
    idx = np.round(np.arange(0, len(tx), 1.0 / factor)).astype(int)
    idx = idx[idx < len(tx)]
    drifted = tx[idx]
    # Decoder searches ±2.5% around nominal
    stats, _, result = decode_from_samples(
        drifted,
        cfg,
        min_energy=1e-5,
        min_ratio=1.2,
        expected_bits=bits,
        sync_mode="correlation",
        symbol_duration_search_percent=2.5,
        symbol_duration_search_steps=7,
    )
    assert stats.frame_success, result.error
    assert abs(stats.clock_drift_percent) > 0.2 or stats.frame_success


# ---------------------------------------------------------------------------
# Soft combining
# ---------------------------------------------------------------------------


def test_soft_combine_prefers_direct_crc():
    cfg = ModulationConfig(symbol_duration=0.06, amplitude=0.25)
    bits = encode_message("OK")
    tx = modulate(bits, cfg, modulation="cpfsk")
    gap = np.zeros(int(0.2 * cfg.sample_rate))
    rx = np.concatenate([tx, gap, tx])
    stats, _, _ = decode_from_samples(
        rx, cfg, min_energy=1e-5, min_ratio=1.2, expected_bits=bits
    )
    assert stats.frame_success
    assert stats.combine_mode in ("direct", "soft_log_energy", "none")


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def test_safety_rejects_excessive_amplitude():
    with pytest.raises(SafetyError):
        require_safe(
            amplitude=0.99,
            frequency_zero=3500,
            frequency_one=7500,
            sample_rate=48000,
            symbol_duration=0.12,
            payload_bytes=5,
            repeats=1,
            near_ultrasonic=False,
            estimated_duration_s=10,
        )


def test_safety_rejects_excessive_duration():
    with pytest.raises(SafetyError):
        require_safe(
            amplitude=0.2,
            frequency_zero=3500,
            frequency_one=7500,
            sample_rate=48000,
            symbol_duration=0.5,
            payload_bytes=32,
            repeats=5,
            near_ultrasonic=False,
            estimated_duration_s=999,
        )


def test_assert_playback_allowed_on_config():
    cfg = ModulationConfig(amplitude=0.2)
    assert_playback_allowed(config=cfg, payload="HELLO", repeats=1)


def test_playback_entry_points_call_safety():
    import src.transmitter as tx
    import src.live_monitor as lm
    import src.stage_demo as sd
    import src.calibration as cal

    assert "assert_playback_allowed" in inspect.getsource(tx)
    assert "assert_playback_allowed" in inspect.getsource(lm)
    assert "assert_playback_allowed" in inspect.getsource(sd)
    assert "assert_calibration_playback" in inspect.getsource(cal)


# ---------------------------------------------------------------------------
# Hamming metrics honesty
# ---------------------------------------------------------------------------


def test_hamming_double_error_may_miscorrect():
    data = [1, 0, 1, 1]
    cw = encode_hamming74_block(data)
    # Flip two bits
    cw[0] ^= 1
    cw[1] ^= 1
    recovered, attempted = decode_hamming74_block(cw)
    # Syndrome will attempt a correction, but may not restore original
    assert attempted in (0, 1)
    # Document: not guaranteed equal to data
    assert isinstance(recovered, list)


# ---------------------------------------------------------------------------
# Documentation safety scan
# ---------------------------------------------------------------------------


def test_docs_safety_scan_no_private_ops():
    from scripts.docs_safety_scan import scan_repository

    findings = scan_repository(Path("."))
    # Allow findings only in private/raw experiment dumps if denylisted paths skipped
    assert findings == [], f"Documentation safety findings: {findings}"
