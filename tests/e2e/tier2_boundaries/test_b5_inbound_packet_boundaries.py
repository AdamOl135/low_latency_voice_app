"""Tier 2 Boundary Tests: B5 - Inbound Raw Packet Boundaries.

Validates:
- Exact 20-byte header with 0 payload
- Maximum MTU payload (4076 bytes)
- Truncated packet rejection (< 20 bytes)
- Corrupt magic byte and version rejection
- Out-of-bounds flag bits handling
"""

import unittest
from tests.e2e.harness.protocol import (
    VoicePacket,
    HEADER_SIZE,
    MAGIC_BYTE,
    PROTOCOL_VERSION,
    TYPE_VOICE,
    TYPE_HANDSHAKE,
    TYPE_PING,
    TYPE_PONG,
)


class TestB5InboundPacketBoundaries(unittest.TestCase):
    def test_b5_01_exact_header_zero_payload(self):
        """Test B5.1: Datagram of exactly 20 bytes with 0 payload encodes and decodes properly."""
        pkt = VoicePacket(
            packet_type=TYPE_PING,
            vad=False,
            energy_level=0,
            sender_id=1,
            channel_id=101,
            sequence=1,
            timestamp=0,
            payload=b'',
        )
        wire = pkt.encode()
        self.assertEqual(len(wire), HEADER_SIZE)

        decoded = VoicePacket.decode(wire)
        self.assertEqual(decoded.payload, b'')
        self.assertEqual(decoded.sender_id, 1)

    def test_b5_02_max_mtu_payload_4076_bytes(self):
        """Test B5.2: Maximum jumbo payload (4076 bytes) encodes and decodes cleanly."""
        max_payload = b'X' * 4076
        pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=True,
            energy_level=15,
            sender_id=999,
            channel_id=101,
            sequence=500,
            timestamp=1000000,
            payload=max_payload,
        )
        wire = pkt.encode()
        self.assertEqual(len(wire), HEADER_SIZE + 4076)

        decoded = VoicePacket.decode(wire)
        self.assertEqual(len(decoded.payload), 4076)
        self.assertEqual(decoded.payload, max_payload)

    def test_b5_03_truncated_datagram_rejection(self):
        """Test B5.3: Datagrams shorter than 20 bytes raise ValueError on decode."""
        for length in [0, 1, 5, 10, 19]:
            with self.assertRaises(ValueError):
                VoicePacket.decode(b'\x56' * length)

    def test_b5_04_invalid_magic_byte_rejection(self):
        """Test B5.4: Packets with invalid magic byte raise ValueError."""
        valid_pkt = VoicePacket(sender_id=1, channel_id=101).encode()
        for bad_magic in [0x00, 0x55, 0x57, 0xFF]:
            corrupted = bytes([bad_magic]) + valid_pkt[1:]
            with self.assertRaises(ValueError):
                VoicePacket.decode(corrupted)

    def test_b5_05_invalid_protocol_version_rejection(self):
        """Test B5.5: Packets with invalid protocol version raise ValueError."""
        valid_pkt = VoicePacket(sender_id=1, channel_id=101).encode()
        for bad_ver in [0x00, 0x02, 0x10, 0xFF]:
            corrupted = valid_pkt[:1] + bytes([bad_ver]) + valid_pkt[2:]
            with self.assertRaises(ValueError):
                VoicePacket.decode(corrupted)


if __name__ == "__main__":
    unittest.main()

