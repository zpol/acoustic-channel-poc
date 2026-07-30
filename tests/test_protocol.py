"""Unit tests for the acoustic channel framing protocol."""

from __future__ import annotations

import pytest

from src.protocol import (
    MAX_PAYLOAD_BYTES,
    PREAMBLE_AND_SYNC,
    PROTOCOL_VERSION,
    ProtocolError,
    bits_to_text,
    build_frame,
    crc16_ccitt,
    decode_bits,
    encode_message,
    frame_to_bits,
    text_to_bits,
    validate_payload,
)


class TestTextBitConversion:
    def test_roundtrip_ascii(self) -> None:
        text = "DEMO-LAB-2027"
        bits = text_to_bits(text)
        assert bits_to_text(bits) == text

    def test_roundtrip_single_byte(self) -> None:
        bits = text_to_bits("A")
        assert len(bits) == 8
        assert bits == [0, 1, 0, 0, 0, 0, 0, 1]
        assert bits_to_text(bits) == "A"

    def test_bits_not_multiple_of_eight(self) -> None:
        with pytest.raises(ProtocolError, match="multiple of 8"):
            bits_to_text([1, 0, 1])


class TestCRC:
    def test_crc_deterministic(self) -> None:
        data = b"\x01\x0cDEMO-LAB-2027"
        assert crc16_ccitt(data) == crc16_ccitt(data)

    def test_crc_known_vector(self) -> None:
        # Empty body with init 0xFFFF yields 0x1D0F for CCITT-FALSE variant
        # over empty is init; for "123456789" classic vector:
        assert crc16_ccitt(b"123456789") == 0x29B1

    def test_crc_changes_with_data(self) -> None:
        assert crc16_ccitt(b"abc") != crc16_ccitt(b"abd")


class TestFrameConstruction:
    def test_build_frame_fields(self) -> None:
        frame = build_frame("DEMO-LAB-2027")
        assert frame.version == PROTOCOL_VERSION
        assert frame.payload == b"DEMO-LAB-2027"
        assert frame.payload_length == 13
        body = bytes([frame.version, frame.payload_length]) + frame.payload
        assert frame.crc == crc16_ccitt(body)

    def test_encode_includes_preamble_and_sync(self) -> None:
        bits = encode_message("HI")
        assert tuple(bits[: len(PREAMBLE_AND_SYNC)]) == PREAMBLE_AND_SYNC

    def test_roundtrip_encode_decode(self) -> None:
        bits = encode_message("DEMO-LAB-2027")
        result = decode_bits(bits)
        assert result.success
        assert result.frame is not None
        assert result.frame.payload_text == "DEMO-LAB-2027"

    def test_decode_with_leading_noise_bits(self) -> None:
        noise = [0, 1, 1, 0, 0, 1, 0, 1, 1, 1]
        bits = noise + encode_message("OK")
        result = decode_bits(bits)
        assert result.success
        assert result.frame is not None
        assert result.frame.payload_text == "OK"
        assert result.sync_offset == len(noise) + len(PREAMBLE_AND_SYNC)


class TestPayloadValidation:
    def test_empty_payload_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="Empty"):
            validate_payload("")

    def test_empty_payload_build_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="Empty"):
            build_frame("")

    def test_payload_too_long_rejected(self) -> None:
        long_msg = "A" * (MAX_PAYLOAD_BYTES + 1)
        with pytest.raises(ProtocolError, match="maximum"):
            validate_payload(long_msg)

    def test_max_payload_accepted(self) -> None:
        msg = "B" * MAX_PAYLOAD_BYTES
        raw = validate_payload(msg)
        assert len(raw) == MAX_PAYLOAD_BYTES

    def test_decode_rejects_zero_length(self) -> None:
        # Manually craft bits: preamble+sync + version + length=0 + crc
        from src.protocol import PREAMBLE_AND_SYNC, bytes_to_bits, crc16_ccitt

        body = bytes([PROTOCOL_VERSION, 0])
        crc = crc16_ccitt(body)
        crc_bytes = bytes([(crc >> 8) & 0xFF, crc & 0xFF])
        bits = list(PREAMBLE_AND_SYNC) + bytes_to_bits(body + crc_bytes)
        result = decode_bits(bits)
        assert not result.success
        assert result.error is not None
        assert "zero" in result.error.lower() or "empty" in result.error.lower()

    def test_decode_rejects_oversized_length(self) -> None:
        from src.protocol import PREAMBLE_AND_SYNC, bytes_to_bits

        # length byte = 33, followed by dummy payload bits + crc
        length = MAX_PAYLOAD_BYTES + 1
        header = bytes([PROTOCOL_VERSION, length])
        fake_payload = b"X" * length
        crc = crc16_ccitt(header + fake_payload)
        crc_bytes = bytes([(crc >> 8) & 0xFF, crc & 0xFF])
        bits = list(PREAMBLE_AND_SYNC) + bytes_to_bits(
            header + fake_payload + crc_bytes
        )
        result = decode_bits(bits)
        assert not result.success
        assert result.error is not None
        assert "exceeds" in result.error.lower()


class TestCRCValidation:
    def test_invalid_crc_rejected(self) -> None:
        bits = encode_message("DEMO")
        # Flip last CRC bit
        bits[-1] = 1 - bits[-1]
        result = decode_bits(bits)
        assert not result.success
        assert result.error is not None
        assert "CRC" in result.error

    def test_corrupted_payload_crc_fails(self) -> None:
        frame = build_frame("TEST")
        bits = frame_to_bits(frame)
        # Flip a payload bit (after preamble+sync+version+length)
        flip_idx = len(PREAMBLE_AND_SYNC) + 16 + 1
        bits[flip_idx] = 1 - bits[flip_idx]
        result = decode_bits(bits)
        assert not result.success
        assert "CRC" in (result.error or "")


class TestPreambleDetection:
    def test_no_preamble(self) -> None:
        result = decode_bits([0] * 64)
        assert not result.success
        assert "Preamble" in (result.error or "")

    def test_partial_preamble(self) -> None:
        result = decode_bits(list(PREAMBLE_AND_SYNC[:10]))
        assert not result.success
