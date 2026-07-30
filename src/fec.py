"""Hamming(7,4) forward error correction for the acoustic channel.

Encode path (documented):
    frame bits (including preamble..CRC) may optionally have the *payload
    body* protected, OR the entire post-sync data region.

This module provides transparent block codecs used by the protocol layer.
CRC remains the final integrity check after FEC decode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

# Generator matrix columns for systematic Hamming(7,4): data d1..d4, parity p1..p3
# Bit order in codeword: [d1, d2, d3, d4, p1, p2, p3]
# p1 = d1⊕d2⊕d3; p2 = d1⊕d2⊕d4; p3 = d1⊕d3⊕d4


@dataclass(frozen=True)
class FecResult:
    """Result of FEC decoding a bit sequence."""

    bits: List[int]
    corrected_bits: int
    uncorrectable_blocks: int
    blocks: int


def _parity3(d: Sequence[int]) -> Tuple[int, int, int]:
    d1, d2, d3, d4 = (int(x) & 1 for x in d)
    p1 = d1 ^ d2 ^ d3
    p2 = d1 ^ d2 ^ d4
    p3 = d1 ^ d3 ^ d4
    return p1, p2, p3


def encode_hamming74_block(data4: Sequence[int]) -> List[int]:
    """Encode 4 data bits into a 7-bit Hamming codeword."""
    if len(data4) != 4:
        raise ValueError("Hamming(7,4) expects exactly 4 data bits")
    for b in data4:
        if b not in (0, 1):
            raise ValueError(f"Invalid bit: {b!r}")
    p1, p2, p3 = _parity3(data4)
    return [int(data4[0]), int(data4[1]), int(data4[2]), int(data4[3]), p1, p2, p3]


def decode_hamming74_block(codeword: Sequence[int]) -> Tuple[List[int], int]:
    """Decode one codeword.

    Returns:
        (data4, corrected_bit_count) where corrected_bit_count is 0 or 1.
        Double errors may be miscorrected (classic Hamming limitation).
    """
    if len(codeword) != 7:
        raise ValueError("Hamming(7,4) expects a 7-bit codeword")
    c = [int(x) & 1 for x in codeword]
    d1, d2, d3, d4, p1, p2, p3 = c
    # Syndrome
    s1 = p1 ^ d1 ^ d2 ^ d3
    s2 = p2 ^ d1 ^ d2 ^ d4
    s3 = p3 ^ d1 ^ d3 ^ d4
    syndrome = (s1 << 2) | (s2 << 1) | s3
    # Map syndrome to bit position in codeword (1-indexed style table)
    # 0 = no error
    pos_map = {
        0: None,
        0b100: 4,  # p1
        0b010: 5,  # p2
        0b001: 6,  # p3
        0b111: 0,  # d1
        0b110: 1,  # d2
        0b101: 2,  # d3
        0b011: 3,  # d4
    }
    corrected = 0
    idx = pos_map.get(syndrome)
    if idx is not None:
        c[idx] ^= 1
        corrected = 1
    return c[:4], corrected


def encode_hamming74(bits: Sequence[int], pad_value: int = 0) -> List[int]:
    """Encode a bit stream with Hamming(7,4), padding to a multiple of 4."""
    data = list(bits)
    pad = (-len(data)) % 4
    data.extend([pad_value] * pad)
    out: List[int] = []
    # Store pad length in first 4 bits of a header codeword for exact trim
    # Header: 4-bit pad count (0-3) encoded as its own codeword
    header = encode_hamming74_block(
        [(pad >> 3) & 1, (pad >> 2) & 1, (pad >> 1) & 1, pad & 1]
    )
    out.extend(header)
    for i in range(0, len(data), 4):
        out.extend(encode_hamming74_block(data[i : i + 4]))
    return out


def decode_hamming74(code_bits: Sequence[int]) -> FecResult:
    """Decode a Hamming(7,4) bit stream produced by ``encode_hamming74``."""
    if len(code_bits) < 7 or len(code_bits) % 7 != 0:
        raise ValueError(
            f"Coded length {len(code_bits)} must be a positive multiple of 7"
        )
    blocks = len(code_bits) // 7
    corrected_total = 0
    # First block = pad header
    pad_bits, c0 = decode_hamming74_block(code_bits[0:7])
    corrected_total += c0
    pad = (pad_bits[0] << 3) | (pad_bits[1] << 2) | (pad_bits[2] << 1) | pad_bits[3]
    if pad > 3:
        # Likely uncorrectable header corruption
        pad = 0
        uncorrectable = 1
    else:
        uncorrectable = 0
    data: List[int] = []
    for b in range(1, blocks):
        chunk = code_bits[b * 7 : (b + 1) * 7]
        d4, c = decode_hamming74_block(chunk)
        corrected_total += c
        data.extend(d4)
    if pad:
        data = data[: len(data) - pad]
    return FecResult(
        bits=data,
        corrected_bits=corrected_total,
        uncorrectable_blocks=uncorrectable,
        blocks=blocks,
    )


def interleave(bits: Sequence[int], rows: int = 7) -> List[int]:
    """Simple block interleaver (column-major write, row-major read)."""
    if rows < 2:
        return list(bits)
    cols = (len(bits) + rows - 1) // rows
    pad = rows * cols - len(bits)
    buf = list(bits) + [0] * pad
    out: List[int] = []
    for r in range(rows):
        for c in range(cols):
            out.append(buf[c * rows + r])
    # Store pad in a trivial way: append pad length nibble is handled outside
    return out + [pad & 1, (pad >> 1) & 1, (pad >> 2) & 1, (pad >> 3) & 1]


def deinterleave(bits: Sequence[int], rows: int = 7) -> List[int]:
    """Inverse of ``interleave``."""
    if rows < 2 or len(bits) < 4:
        return list(bits)
    meta = bits[-4:]
    pad = meta[0] | (meta[1] << 1) | (meta[2] << 2) | (meta[3] << 3)
    body = bits[:-4]
    cols = len(body) // rows
    buf = [0] * (rows * cols)
    i = 0
    for r in range(rows):
        for c in range(cols):
            buf[c * rows + r] = body[i]
            i += 1
    data = buf
    if pad:
        data = data[: len(data) - pad]
    return data
