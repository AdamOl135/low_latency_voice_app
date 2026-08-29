"""Synthetic Audio Generator & Wire Protocol Utilities for Low-Latency Voice App.

Implements:
- 48kHz audio frame simulation (10ms = 480 samples, 20ms = 960 samples).
- Synthetic Opus packet generator with sine wave tones or audio patterns.
- 20-byte UDP binary wire protocol encoder and parser:
    Magic: 0x56 ('V')
    Version: 0x01
    Type: 0x01 (Voice), 0x02 (Ping), 0x03 (Pong), 0x04 (Handshake)
    Flags/VAD: Bit 0 = VAD (1=speaking, 0=silent), Bits 4-7 = Energy Level (0-15)
    Sender ID: uint32
    Channel ID: uint32
    Sequence Number: uint16
    Payload Length: uint16
    Timestamp: uint32 (48kHz sample clock)
"""

import struct
import math
import time
from typing import Tuple, Optional, Dict, Any

# Protocol Constants
MAGIC_BYTE = 0x56
PROTOCOL_VERSION = 0x01

# Packet Types
TYPE_VOICE = 0x01
TYPE_PING = 0x02
TYPE_PONG = 0x03
TYPE_HANDSHAKE = 0x04

# Audio constants
SAMPLE_RATE = 48000  # 48kHz clock
FRAME_SIZE_10MS = 480
FRAME_SIZE_20MS = 960

HEADER_STRUCT = struct.Struct('>BBBBIIHHI')
HEADER_SIZE = HEADER_STRUCT.size  # 20 bytes


class VoicePacket:
    """Represents a decoded or to-be-encoded 20-byte UDP Voice Packet."""

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
    ):
        self.magic = magic
        self.version = version
        self.packet_type = packet_type
        self.vad = vad
        self.energy_level = max(0, min(15, energy_level))
        self.sender_id = sender_id
        self.channel_id = channel_id
        self.sequence = sequence & 0xFFFF
        self.timestamp = timestamp & 0xFFFFFFFF
        self.payload = payload

    @property
    def flags_byte(self) -> int:
        """Encode VAD bit (bit 0) and Energy level (bits 4-7)."""
        vad_bit = 1 if self.vad else 0
        energy_bits = (self.energy_level & 0x0F) << 4
        return energy_bits | vad_bit

    def encode(self) -> bytes:
        """Encode into 20-byte header + payload."""
        payload_len = len(self.payload)
        header = HEADER_STRUCT.pack(
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
        """Decode raw bytes into a VoicePacket object."""
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Packet too short: {len(data)} bytes, expected at least {HEADER_SIZE}")
        
        magic, version, pkt_type, flags, sender_id, channel_id, seq, payload_len, timestamp = (
            HEADER_STRUCT.unpack(data[:HEADER_SIZE])
        )
        
        vad = bool(flags & 0x01)
        energy_level = (flags >> 4) & 0x0F
        payload = data[HEADER_SIZE:HEADER_SIZE + payload_len]
        
        pkt = cls(
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
        )
        return pkt

    def to_dict(self) -> Dict[str, Any]:
        return {
            'magic': self.magic,
            'version': self.version,
            'packet_type': self.packet_type,
            'vad': self.vad,
            'energy_level': self.energy_level,
            'sender_id': self.sender_id,
            'channel_id': self.channel_id,
            'sequence': self.sequence,
            'timestamp': self.timestamp,
            'payload_length': len(self.payload),
        }


class AudioGenerator:
    """Generates synthetic audio stream packets with timestamps and sequence numbers."""

    def __init__(
        self,
        sender_id: int = 1,
        channel_id: int = 101,
        frame_duration_ms: int = 20,
        frequency_hz: float = 440.0,
    ):
        self.sender_id = sender_id
        self.channel_id = channel_id
        self.frame_duration_ms = frame_duration_ms
        self.samples_per_frame = int(SAMPLE_RATE * (frame_duration_ms / 1000.0))
        self.frequency_hz = frequency_hz
        self.sequence = 0
        self.timestamp = 0
        self.sample_index = 0

    def generate_pcm_frame(self, amplitude: float = 0.8) -> bytes:
        """Generate 16-bit mono PCM samples for a pure sine wave tone."""
        samples = bytearray(self.samples_per_frame * 2)
        for i in range(self.samples_per_frame):
            t = (self.sample_index + i) / SAMPLE_RATE
            sample_val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * self.frequency_hz * t))
            struct.pack_into('<h', samples, i * 2, max(-32768, min(32767, sample_val)))
        self.sample_index += self.samples_per_frame
        return bytes(samples)

    def generate_opus_payload(self, is_speaking: bool = True, size_bytes: int = 80) -> bytes:
        """Generate a simulated Opus compressed packet (standard Opus payload is 20-120 bytes)."""
        if not is_speaking:
            # Opus DTX / comfort noise packet is typically 2-8 bytes
            return b'\xF8\xFF\xFE'
        
        # Synthetic Opus frame with header marker and audio pattern
        opus_header = bytes([0x78, (self.sequence & 0xFF)])  # Opus config byte + seq
        pattern = bytes([(int(self.frequency_hz) + i + self.sequence) % 256 for i in range(size_bytes - len(opus_header))])
        return opus_header + pattern

    def next_voice_packet(
        self,
        is_speaking: bool = True,
        energy_level: Optional[int] = None,
        payload_size: int = 80,
    ) -> VoicePacket:
        """Produce the next incremental VoicePacket."""
        if energy_level is None:
            energy_level = 12 if is_speaking else 0

        payload = self.generate_opus_payload(is_speaking=is_speaking, size_bytes=payload_size)
        
        pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=is_speaking,
            energy_level=energy_level,
            sender_id=self.sender_id,
            channel_id=self.channel_id,
            sequence=self.sequence,
            timestamp=self.timestamp,
            payload=payload,
        )

        # Advance state
        self.sequence = (self.sequence + 1) & 0xFFFF
        self.timestamp = (self.timestamp + self.samples_per_frame) & 0xFFFFFFFF
        return pkt

    def generate_stream(self, num_packets: int, is_speaking: bool = True) -> list[VoicePacket]:
        """Generate a batch of consecutive packets."""
        return [self.next_voice_packet(is_speaking=is_speaking) for _ in range(num_packets)]

    def reset(self):
        self.sequence = 0
        self.timestamp = 0
        self.sample_index = 0
