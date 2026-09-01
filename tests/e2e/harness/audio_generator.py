"""Audio Generator and Stream Simulator for Low-Latency Voice App E2E Tests."""

import math
import struct
from typing import Optional, List
from tests.e2e.harness.protocol import (
    VoicePacket,
    TYPE_VOICE,
    TYPE_PING,
    TYPE_PONG,
    TYPE_HANDSHAKE,
    TYPE_LEAVE,
)

SAMPLE_RATE = 48000
FRAME_DURATION_MS = 20
SAMPLES_PER_FRAME = int(SAMPLE_RATE * (FRAME_DURATION_MS / 1000.0))  # 960 samples
PCM_BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2  # 1920 bytes for 16-bit mono


class AudioGenerator:
    """Generates continuous synthetic audio packets simulating microphone input."""

    def __init__(
        self,
        sender_id: int = 1,
        channel_id: int = 101,
        frequency_hz: float = 440.0,
        frame_duration_ms: int = 20,
    ):
        self.sender_id = sender_id
        self.channel_id = channel_id
        self.frequency_hz = frequency_hz
        self.frame_duration_ms = frame_duration_ms
        self.samples_per_frame = int(SAMPLE_RATE * (frame_duration_ms / 1000.0))
        self.sequence = 0
        self.timestamp = 0
        self.sample_index = 0

    def generate_pcm_frame(self, amplitude: float = 0.8) -> bytes:
        """Generate 16-bit mono PCM samples for a pure tone."""
        samples = bytearray(self.samples_per_frame * 2)
        for i in range(self.samples_per_frame):
            t = (self.sample_index + i) / SAMPLE_RATE
            sample_val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * self.frequency_hz * t))
            struct.pack_into('<h', samples, i * 2, max(-32768, min(32767, sample_val)))
        self.sample_index += self.samples_per_frame
        return bytes(samples)

    def generate_opus_payload(self, is_speaking: bool = True, size_bytes: int = 80) -> bytes:
        """Generate simulated Opus payload."""
        if not is_speaking:
            # DTX comfort noise payload
            return b'\xF8\xFF\xFE'

        # Opus frame with TOC byte + pseudo-random voice frequency payload
        toc_byte = 0x78
        pattern = bytes([(int(self.frequency_hz) + i + self.sequence) % 256 for i in range(size_bytes - 1)])
        return bytes([toc_byte]) + pattern

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

    def generate_batch(self, count: int, is_speaking: bool = True) -> List[VoicePacket]:
        """Generate a series of consecutive packets."""
        return [self.next_voice_packet(is_speaking=is_speaking) for _ in range(count)]

    def reset(self):
        self.sequence = 0
        self.timestamp = 0
        self.sample_index = 0

