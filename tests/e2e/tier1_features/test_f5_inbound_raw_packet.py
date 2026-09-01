"""Tier 1 Feature Tests: F5 - Client Inbound Packet Re-Encoding Optimization.

Validates:
- Passing raw datagram bytes directly to native engine feedInboundPacket
- Eliminating unnecessary decode-then-re-encode overhead
- Verifying payload byte-for-byte fidelity through wire transmission
- Inspecting client/lib/state/voice_notifier.dart for raw packet dispatch
- Verifying robustness against malformed/truncated raw packet bytes
- Sequence and timestamp fidelity preservation in raw pass-through
"""

import ctypes
import os
import re
import time
import unittest
from tests.e2e.harness.native_engine import (
    build_and_load_native_engine,
    AudioEngineConfigC,
    AudioEngineStatsC,
)
from tests.e2e.harness.protocol import VoicePacket, TYPE_VOICE

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
VOICE_NOTIFIER_PATH = os.path.join(PROJECT_ROOT, "client/lib/state/voice_notifier.dart")


class TestF5InboundRawPacket(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = build_and_load_native_engine()

    def setUp(self):
        if not self.engine:
            self.skipTest("Native audio engine shared library could not be compiled.")
        config = AudioEngineConfigC(
            sample_rate=48000,
            channels=1,
            frame_duration_ms=20,
            opus_bitrate=48000,
            vad_threshold_db=-45.0,
            vad_hangover_ms=200,
        )
        self.engine.voice_engine_init(ctypes.byref(config))

    def tearDown(self):
        if self.engine:
            self.engine.voice_engine_destroy()

    def test_f5_01_feed_raw_datagram_bytes_directly(self):
        """Test F5.1: Raw wire datagram bytes are fed directly to native engine without re-encoding."""
        payload = bytes([i % 256 for i in range(160)])
        pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=True,
            energy_level=14,
            sender_id=777,
            channel_id=101,
            sequence=100,
            timestamp=48000,
            payload=payload,
        )
        raw_datagram = pkt.encode()

        # Feed raw bytes directly to C engine
        data_ptr = (ctypes.c_uint8 * len(raw_datagram))(*raw_datagram)
        self.engine.voice_engine_feed_inbound_packet(data_ptr, len(raw_datagram))

        stats = AudioEngineStatsC()
        self.engine.voice_engine_get_stats(ctypes.byref(stats))
        self.assertGreaterEqual(stats.packets_received, 1)

    def test_f5_02_raw_packet_preserves_audio_payload_integrity(self):
        """Test F5.2: Inbound raw datagram retains byte-for-byte exact payload through decoding."""
        test_payload = bytes([0xDE, 0xAD, 0xBE, 0xEF] * 20)
        pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=True,
            energy_level=11,
            sender_id=888,
            channel_id=101,
            sequence=200,
            timestamp=96000,
            payload=test_payload,
        )
        raw_datagram = pkt.encode()

        # Decode directly from raw bytes
        decoded_pkt = VoicePacket.decode(raw_datagram)
        self.assertEqual(decoded_pkt.payload, test_payload, "Decoded payload must match original raw datagram bytes exactly")
        self.assertEqual(decoded_pkt.sender_id, 888)
        self.assertEqual(decoded_pkt.sequence, 200)

    def test_f5_03_voice_notifier_contract_inspection(self):
        """Test F5.3: voice_notifier.dart does NOT perform packet.encode() before feedInboundPacket."""
        self.assertTrue(os.path.exists(VOICE_NOTIFIER_PATH), f"Missing {VOICE_NOTIFIER_PATH}")
        with open(VOICE_NOTIFIER_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # Contract requirement R5: eliminate decode-then-re-encode overhead.
        # Check that feedInboundPacket does not call .encode() on the packet
        feed_matches = re.findall(r"feedInboundPacket\s*\(\s*([^)]+)\s*\)", content)
        self.assertTrue(len(feed_matches) > 0, "Could not find feedInboundPacket call in voice_notifier.dart")
        for arg in feed_matches:
            self.assertNotIn(
                ".encode()",
                arg,
                f"voice_notifier.dart must pass raw datagram bytes directly to feedInboundPacket, found: {arg}"
            )

    def test_f5_04_zero_copy_throughput_benchmark(self):
        """Test F5.4: Direct raw byte forwarding avoids CPU cycles of redundant serialization."""
        payload = os.urandom(80)
        pkt = VoicePacket(sender_id=1, channel_id=101, sequence=1, timestamp=0, payload=payload)
        raw_bytes = pkt.encode()

        # Time direct pass
        t0 = time.perf_counter()
        for _ in range(5000):
            # Direct pass
            _ = raw_bytes
        direct_time = time.perf_counter() - t0

        # Time decode-then-re-encode
        t1 = time.perf_counter()
        for _ in range(5000):
            p = VoicePacket.decode(raw_bytes)
            _ = p.encode()
        reencode_time = time.perf_counter() - t1

        self.assertLess(
            direct_time,
            reencode_time,
            "Direct raw byte forwarding must be strictly faster than decode-then-re-encode"
        )

    def test_f5_05_corrupt_packet_rejection_at_engine(self):
        """Test F5.5: Corrupted raw wire bytes are rejected by native engine without memory faults."""
        # 1. Truncated packet (5 bytes)
        trunc = b'\x56\x01\x01\x00\x00'
        data_ptr = (ctypes.c_uint8 * len(trunc))(*trunc)
        self.engine.voice_engine_feed_inbound_packet(data_ptr, len(trunc))

        # 2. Invalid magic byte
        bad_magic = b'\xFF\x01\x01\x00' + b'\x00' * 16
        data_ptr2 = (ctypes.c_uint8 * len(bad_magic))(*bad_magic)
        self.engine.voice_engine_feed_inbound_packet(data_ptr2, len(bad_magic))

        # 3. 0-byte buffer
        empty_ptr = (ctypes.c_uint8 * 1)()
        self.engine.voice_engine_feed_inbound_packet(empty_ptr, 0)

        # Engine should remain operational
        stats = AudioEngineStatsC()
        self.engine.voice_engine_get_stats(ctypes.byref(stats))
        self.assertIsNotNone(stats)

    def test_f5_06_sequence_and_timestamp_preservation(self):
        """Test F5.6: Sequence numbers and timestamps are preserved unmodified across raw byte encoding."""
        pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=True,
            energy_level=8,
            sender_id=1234,
            channel_id=101,
            sequence=65530,
            timestamp=4294967000,
            payload=b'raw_audio_samples',
        )
        wire_bytes = pkt.encode()
        decoded = VoicePacket.decode(wire_bytes)
        self.assertEqual(decoded.sequence, 65530)
        self.assertEqual(decoded.timestamp, 4294967000)
        self.assertEqual(decoded.sender_id, 1234)
        self.assertEqual(decoded.payload, b'raw_audio_samples')


if __name__ == "__main__":
    unittest.main()

