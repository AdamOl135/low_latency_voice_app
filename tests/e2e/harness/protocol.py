"""UDP Binary Wire Protocol Specification and Parser for Low-Latency Voice App.

Protocol Structure:
- 20-byte Fixed Binary Header (Big-Endian):
  [0:1]   Magic Byte: 0x56 ('V')
  [1:2]   Protocol Version: 0x01
  [2:3]   Packet Type:
            0x01 = TypeVoice
            0x02 = TypePing
            0x03 = TypePong
            0x04 = TypeHandshake
            0x05 = TypeLeave
  [3:4]   Flags Bitfield:
            Bit 0: VAD speaking indicator (1 = speaking, 0 = silent)
            Bit 1: Local Mute state
            Bit 2: Local Deafen state
            Bit 3: PTT Active
            Bits 4-7: Energy Level (0-15)
  [4:8]   Sender User ID (uint32)
  [8:12]  Channel ID (uint32)
  [12:14] Sequence Number (uint16)
  [14:16] Payload Length (uint16)
  [16:20] Timestamp ms (uint32)
  [20:N]  Audio Payload (Opus or 48kHz PCM bytes)
"""

import struct
from typing import Dict, Any, Optional

MAGIC_BYTE = 0x56
PROTOCOL_VERSION = 0x01

TYPE_VOICE = 0x01
TYPE_PING = 0x02
TYPE_PONG = 0x03
TYPE_HANDSHAKE = 0x04
TYPE_LEAVE = 0x05

HEADER_FORMAT = '>BBBBIIHHI'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # Exactly 20 bytes


class VoicePacket:
    """Represents an encoded or decoded 20-byte binary UDP Voice Packet."""

    def __init__(
        self,
        packet_type: int = TYPE_VOICE,
        vad: bool = True,
        energy_level: int = 10,
        sender_id: int = 1,
        channel_id: int = 101,
        sequence: int = 0,
        timestamp: int = 0,
        payload: bytes = b'',
        magic: int = MAGIC_BYTE,
        version: int = PROTOCOL_VERSION,
        is_muted: bool = False,
        is_deafened: bool = False,
        is_ptt: bool = False,
    ):
        self.magic = magic
        self.version = version
        self.packet_type = packet_type
        self.vad = bool(vad)
        self.energy_level = max(0, min(15, int(energy_level)))
        self.sender_id = sender_id & 0xFFFFFFFF
        self.channel_id = channel_id & 0xFFFFFFFF
        self.sequence = sequence & 0xFFFF
        self.timestamp = timestamp & 0xFFFFFFFF
        self.payload = bytes(payload)
        self.is_muted = bool(is_muted)
        self.is_deafened = bool(is_deafened)
        self.is_ptt = bool(is_ptt)

    @property
    def flags_byte(self) -> int:
        """Construct the 8-bit flags field."""
        vad_bit = 1 if self.vad else 0
        mute_bit = (1 if self.is_muted else 0) << 1
        deafen_bit = (1 if self.is_deafened else 0) << 2
        ptt_bit = (1 if self.is_ptt else 0) << 3
        energy_bits = (self.energy_level & 0x0F) << 4
        return energy_bits | ptt_bit | deafen_bit | mute_bit | vad_bit

    def encode(self) -> bytes:
        """Serialize into 20-byte binary header + payload."""
        payload_len = len(self.payload)
        header = struct.pack(
            HEADER_FORMAT,
            self.magic,
            self.version,
            self.packet_type,
            self.flags_byte,
            self.sender_id,
            self.channel_id,
            self.sequence,
            payload_len,
            self.timestamp,
        )
        return header + self.payload

    @classmethod
    def decode(cls, data: bytes) -> 'VoicePacket':
        """Parse raw bytes into a VoicePacket instance."""
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Packet too short: {len(data)} bytes, minimum required is {HEADER_SIZE}")

        magic, version, pkt_type, flags, sender_id, channel_id, seq, payload_len, timestamp = (
            struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        )

        if magic != MAGIC_BYTE:
            raise ValueError(f"Invalid magic byte: 0x{magic:02X}, expected 0x{MAGIC_BYTE:02X}")
        if version != PROTOCOL_VERSION:
            raise ValueError(f"Invalid protocol version: 0x{version:02X}, expected 0x{PROTOCOL_VERSION:02X}")

        vad = bool(flags & 0x01)
        is_muted = bool(flags & 0x02)
        is_deafened = bool(flags & 0x04)
        is_ptt = bool(flags & 0x08)
        energy_level = (flags >> 4) & 0x0F

        payload = data[HEADER_SIZE:HEADER_SIZE + payload_len]

        return cls(
            packet_type=pkt_type,
            vad=vad,
            energy_level=energy_level,
            sender_id=sender_id,
            channel_id=channel_id,
            sequence=seq,
            timestamp=timestamp,
            payload=payload,
            magic=magic,
            version=version,
            is_muted=is_muted,
            is_deafened=is_deafened,
            is_ptt=is_ptt,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "magic": hex(self.magic),
            "version": self.version,
            "packet_type": self.packet_type,
            "vad": self.vad,
            "energy_level": self.energy_level,
            "sender_id": self.sender_id,
            "channel_id": self.channel_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "payload_length": len(self.payload),
        }

