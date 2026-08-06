"""Tests for Part 3 capacity metrics helpers."""

from src.capacity_metrics import (
    airtime_s,
    eval_zlib_compression,
    fer,
    frame_overhead,
    payload_goodput_bps,
    raw_symbol_rate_bps,
)


def test_frame_overhead_hello_none():
    oh = frame_overhead("HELLO", fec="none")
    assert oh.payload_bytes == 5
    assert oh.coded_bits == 104
    assert 0.6 < oh.overhead_fraction < 0.65


def test_frame_overhead_hamming_expands():
    none = frame_overhead("HELLO", fec="none")
    ham = frame_overhead("HELLO", fec="hamming74")
    assert ham.coded_bits > none.coded_bits


def test_goodput_and_fer():
    assert abs(raw_symbol_rate_bps(0.1) - 10.0) < 1e-9
    assert abs(payload_goodput_bps(5, 10, 10.0) - 40.0) < 1e-9
    assert abs(fer(8, 10) - 0.2) < 1e-9
    assert airtime_s("HELLO", 0.07, fec="none", repeats=1) > 0


def test_compression_hello_expands():
    ev = eval_zlib_compression("hello", b"HELLO")
    assert ev.ratio > 1.0
    assert ev.worthwhile_vs_payload_cap is False
