"""Tier 2 Boundary Tests: B1 - Audio Engine Boundaries.

Validates:
- 0-byte capture buffer handling
- Maximum peer capacity limit (32 peers)
- Extreme VAD threshold limits
- Rapid start/stop capture & playback cycling
- Extreme peer volume multipliers
"""

import ctypes
import unittest
from tests.e2e.harness.native_engine import (
    build_and_load_native_engine,
    AudioEngineConfigC,
    AudioEngineStatsC,
)
from tests.e2e.harness.protocol import VoicePacket, TYPE_VOICE


class TestB1AudioEngineBoundaries(unittest.TestCase):
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

    def test_b1_01_zero_length_capture_buffer(self):
        """Test B1.1: voice_engine_capture_frame with 0 max_len returns 0 without crashing."""
        out_buf = (ctypes.c_uint8 * 1)()
        level_db = ctypes.c_float(0.0)
        is_speaking = ctypes.c_bool(False)
        energy_level = ctypes.c_uint8(0)

        written = self.engine.voice_engine_capture_frame(
            out_buf,
            0,
            ctypes.byref(level_db),
            ctypes.byref(is_speaking),
            ctypes.byref(energy_level),
        )
        self.assertEqual(written, 0)

    def test_b1_02_max_peer_capacity_limit(self):
        """Test B1.2: Feeding audio from 32 distinct peers reaches MAX_PEERS limit safely."""
        for peer_id in range(1, 35):
            pkt = VoicePacket(
                packet_type=TYPE_VOICE,
                sender_id=peer_id,
                channel_id=101,
                sequence=1,
                timestamp=0,
                payload=b'\x00' * 160,
            )
            raw = pkt.encode()
            data_ptr = (ctypes.c_uint8 * len(raw))(*raw)
            self.engine.voice_engine_feed_inbound_packet(data_ptr, len(raw))

        stats = AudioEngineStatsC()
        self.engine.voice_engine_get_stats(ctypes.byref(stats))
        self.assertGreaterEqual(stats.packets_received, 32)
        self.engine.voice_engine_clear_peers()

    def test_b1_03_extreme_vad_threshold_boundaries(self):
        """Test B1.3: Setting VAD threshold to extreme values (-120.0, 0.0, +20.0 dBFS)."""
        # Minimum threshold
        self.engine.voice_engine_set_vad_mode(True, -120.0)
        # Maximum threshold
        self.engine.voice_engine_set_vad_mode(True, 0.0)
        # Overshoot threshold
        self.engine.voice_engine_set_vad_mode(True, 20.0)
        # Disable VAD
        self.engine.voice_engine_set_vad_mode(False, -45.0)

    def test_b1_04_rapid_capture_playback_restart_stress(self):
        """Test B1.4: Rapidly cycling start/stop capture and playback 50 times in a tight loop."""
        for _ in range(50):
            self.engine.voice_engine_start_capture()
            self.engine.voice_engine_start_playback()
            self.engine.voice_engine_stop_capture()
            self.engine.voice_engine_stop_playback()

    def test_b1_05_extreme_peer_volume_multipliers(self):
        """Test B1.5: Setting peer volume multiplier to 0.0, 0.5, 2.0, 10.0, and negative values."""
        self.engine.voice_engine_set_user_volume(1, 0.0)
        self.engine.voice_engine_set_user_volume(2, 0.5)
        self.engine.voice_engine_set_user_volume(3, 2.0)
        self.engine.voice_engine_set_user_volume(4, 10.0)
        self.engine.voice_engine_set_user_volume(5, -1.0)


if __name__ == "__main__":
    unittest.main()

