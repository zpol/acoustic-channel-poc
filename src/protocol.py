"""Binary framing protocol for the acoustic channel PoC.

Frame layout::

    PREAMBLE | SYNC | VERSION | PAYLOAD_LENGTH | PAYLOAD | CRC16

- Preamble: alternating bits ``1010101010101010`` (16 bits)
- Sync word: unique 16-bit pattern unlikely to occur accidentally
- Version: 1 byte (currently ``0x01``)
- Payload length: 1 byte (0–32)
- Payload: ASCII/UTF-8 bytes, maximum 32 bytes
- CRC: CRC-16-CCITT over version + length + payload
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# Protocol constants
PROTOCOL_VERSION: int = 0x01
MAX_PAYLOAD_BYTES: int = 32
PREAMBLE_BITS: Tuple[int, ...] = tuple(int(b) for b in "1010101010101010")
# Sync word chosen to be distinct from the alternating preamble (0xA5F0).
SYNC_WORD_BITS: Tuple[int, ...] = tuple(int(b) for b in "1010010111110000")
PREAMBLE_AND_SYNC: Tuple[int, ...] = PREAMBLE_BITS + SYNC_WORD_BITS

# CRC-16-CCITT parameters (poly 0x1021, init 0xFFFF, no final XOR).
CRC16_POLY: int = 0x1021
CRC16_INIT: int = 0xFFFF


class ProtocolError(ValueError):
    """Raised when a frame cannot be encoded or decoded."""


def crc16_ccitt(data: bytes, init: int = CRC16_INIT) -> int:
    """Compute CRC-16-CCITT over *data*.

    Args:
        data: Bytes to checksum.
        init: Initial CRC register value.

    Returns:
        16-bit CRC value.
    """
    crc = init & 0xFFFF
    for byte in data:
        crc ^= (byte << 8) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ CRC16_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def text_to_bits(text: str) -> List[int]:
    """Convert a UTF-8/ASCII string to a list of bits (MSB first per byte)."""
    raw = text.encode("utf-8")
    return bytes_to_bits(raw)


def bits_to_text(bits: Sequence[int]) -> str:
    """Convert a bit list (MSB first per byte) back to a UTF-8 string."""
    if len(bits) % 8 != 0:
        raise ProtocolError(
            f"Bit length {len(bits)} is not a multiple of 8"
        )
    return bits_to_bytes(bits).decode("utf-8")


def bytes_to_bits(data: bytes) -> List[int]:
    """Convert bytes to bits, MSB first within each byte."""
    bits: List[int] = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def bits_to_bytes(bits: Sequence[int]) -> bytes:
    """Convert bits (MSB first) to bytes."""
    if len(bits) % 8 != 0:
        raise ProtocolError(
            f"Bit length {len(bits)} is not a multiple of 8"
        )
    out = bytearray()
    for i in range(0, len(bits), 8):
        value = 0
        for bit in bits[i : i + 8]:
            if bit not in (0, 1):
                raise ProtocolError(f"Invalid bit value: {bit!r}")
            value = (value << 1) | int(bit)
        out.append(value)
    return bytes(out)


def validate_payload(payload: str) -> bytes:
    """Validate and encode a payload string.

    Raises:
        ProtocolError: If empty or longer than ``MAX_PAYLOAD_BYTES``.
    """
    if not payload:
        raise ProtocolError("Empty payload is not allowed")
    raw = payload.encode("utf-8")
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ProtocolError(
            f"Payload is {len(raw)} bytes; maximum is {MAX_PAYLOAD_BYTES}"
        )
    return raw


@dataclass(frozen=True)
class Frame:
    """Decoded / encoded acoustic channel frame."""

    version: int
    payload: bytes
    crc: int

    @property
    def payload_text(self) -> str:
        """Decode payload as UTF-8."""
        return self.payload.decode("utf-8")

    @property
    def payload_length(self) -> int:
        return len(self.payload)


def build_frame(payload: str, version: int = PROTOCOL_VERSION) -> Frame:
    """Build a validated frame from a text payload."""
    raw = validate_payload(payload)
    if not (0 <= version <= 255):
        raise ProtocolError(f"Invalid version byte: {version}")
    body = bytes([version, len(raw)]) + raw
    crc = crc16_ccitt(body)
    return Frame(version=version, payload=raw, crc=crc)


def frame_to_bits(frame: Frame) -> List[int]:
    """Serialize a frame to the full on-wire bit sequence including preamble/sync."""
    body = bytes([frame.version, len(frame.payload)]) + frame.payload
    crc_bytes = bytes([(frame.crc >> 8) & 0xFF, frame.crc & 0xFF])
    data_bits = bytes_to_bits(body + crc_bytes)
    return list(PREAMBLE_AND_SYNC) + data_bits


def encode_message(payload: str, version: int = PROTOCOL_VERSION) -> List[int]:
    """Encode a text message into the complete framed bit sequence."""
    frame = build_frame(payload, version=version)
    return frame_to_bits(frame)


def _find_preamble_sync(bits: Sequence[int]) -> Optional[int]:
    """Return the index of the first bit after preamble+sync, or None."""
    pattern = PREAMBLE_AND_SYNC
    pattern_len = len(pattern)
    if len(bits) < pattern_len:
        return None
    for i in range(len(bits) - pattern_len + 1):
        if tuple(bits[i : i + pattern_len]) == pattern:
            return i + pattern_len
    return None


@dataclass(frozen=True)
class DecodeResult:
    """Result of attempting to decode a bit stream."""

    success: bool
    frame: Optional[Frame] = None
    error: Optional[str] = None
    sync_offset: Optional[int] = None


def decode_bits(bits: Sequence[int]) -> DecodeResult:
    """Search for preamble+sync and decode the following frame.

    The receiver does not assume recording begins at the start of a
    transmission; it scans the bit stream for the known pattern.
    """
    data_start = _find_preamble_sync(bits)
    if data_start is None:
        return DecodeResult(
            success=False,
            error="Preamble/sync word not found",
        )

    remaining = bits[data_start:]
    # Need at least version (8) + length (8) + CRC (16) = 32 bits
    min_header = 8 + 8 + 16
    if len(remaining) < min_header:
        return DecodeResult(
            success=False,
            error="Insufficient bits after sync for header+CRC",
            sync_offset=data_start,
        )

    try:
        version = bits_to_bytes(remaining[0:8])[0]
        length = bits_to_bytes(remaining[8:16])[0]
    except ProtocolError as exc:
        return DecodeResult(
            success=False,
            error=str(exc),
            sync_offset=data_start,
        )

    if length == 0:
        return DecodeResult(
            success=False,
            error="Payload length is zero (empty payload rejected)",
            sync_offset=data_start,
        )
    if length > MAX_PAYLOAD_BYTES:
        return DecodeResult(
            success=False,
            error=(
                f"Payload length {length} exceeds maximum "
                f"{MAX_PAYLOAD_BYTES}"
            ),
            sync_offset=data_start,
        )

    payload_bits = length * 8
    total_needed = 16 + payload_bits + 16  # ver+len + payload + crc
    if len(remaining) < total_needed:
        return DecodeResult(
            success=False,
            error=(
                f"Insufficient bits for payload+CRC "
                f"(need {total_needed}, have {len(remaining)})"
            ),
            sync_offset=data_start,
        )

    try:
        payload = bits_to_bytes(remaining[16 : 16 + payload_bits])
        crc_bytes = bits_to_bytes(
            remaining[16 + payload_bits : 16 + payload_bits + 16]
        )
    except ProtocolError as exc:
        return DecodeResult(
            success=False,
            error=str(exc),
            sync_offset=data_start,
        )

    received_crc = (crc_bytes[0] << 8) | crc_bytes[1]
    body = bytes([version, length]) + payload
    expected_crc = crc16_ccitt(body)
    if received_crc != expected_crc:
        return DecodeResult(
            success=False,
            error=(
                f"CRC mismatch: received 0x{received_crc:04X}, "
                f"expected 0x{expected_crc:04X}"
            ),
            sync_offset=data_start,
        )

    if version != PROTOCOL_VERSION:
        return DecodeResult(
            success=False,
            error=f"Unsupported protocol version: {version}",
            sync_offset=data_start,
            frame=Frame(version=version, payload=payload, crc=received_crc),
        )

    frame = Frame(version=version, payload=payload, crc=received_crc)
    return DecodeResult(
        success=True,
        frame=frame,
        sync_offset=data_start,
    )


def frame_bit_count(payload_len: int) -> int:
    """Return total bit count for a frame with the given payload length."""
    # preamble+sync + version + length + payload + crc
    return (
        len(PREAMBLE_AND_SYNC)
        + 8
        + 8
        + payload_len * 8
        + 16
    )


def estimate_duration(
    payload: str,
    symbol_duration: float,
    repeats: int = 1,
    inter_frame_silence: float = 0.0,
) -> float:
    """Estimate transmission duration in seconds for a payload."""
    raw = validate_payload(payload)
    bits_per_frame = frame_bit_count(len(raw))
    frame_time = bits_per_frame * symbol_duration
    if repeats < 1:
        raise ProtocolError("repeats must be >= 1")
    total = repeats * frame_time
    if repeats > 1:
        total += (repeats - 1) * inter_frame_silence
    return total
