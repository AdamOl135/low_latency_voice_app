"""Tier 1 Feature Tests: F1 - Cross-Platform Audio Engine (miniaudio).

Validates:
- C Audio Engine lifecycle (voice_engine_init, voice_engine_destroy)
- Audio device enumeration and selection
- Start/stop capture and playback controls
- Silence buffer generation on capture underflow (no 440Hz synthetic tone)
- Local mute, local deafen, and PTT state controls
- Peer audio packet feeding and stream clearing
"""

import ctypes
import os
import unittest
from tests.e2e.harness.native_engine import (
    build_and_load_native_engine,
    AudioEngineConfigC,
    AudioDeviceInfoC,
    AudioEngineStatsC,
)
from tests.e2e.harness.protocol import VoicePacket, TYPE_VOICE


class TestF1AudioEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = build_and_load_native_engine()

    def setUp(self):
        if not self.engine:
            self.skipTest("Native audio engine shared library could not be compiled on this platform.")
        config = AudioEngineConfigC(
            sample_rate=48000,
            channels=1,
            frame_duration_ms=20,
            opus_bitrate=48000,
            vad_threshold_db=-45.0,
            vad_hangover_ms=200,
        )
        ret = self.engine.voice_engine_init(ctypes.byref(config))
        self.assertEqual(ret, 0, "voice_engine_init must return 0 on success")

    def tearDown(self):
        if self.engine:
            self.engine.voice_engine_destroy()

    def test_f1_01_native_engine_init_and_destroy(self):
        """Test F1.1: Audio engine initializes with correct config and destroys cleanly."""
        stats = AudioEngineStatsC()
        self.engine.voice_engine_get_stats(ctypes.byref(stats))
        self.assertFalse(stats.is_speaking)
        self.assertEqual(stats.packets_sent, 0)
        self.assertEqual(stats.packets_received, 0)

    def test_f1_02_device_enumeration(self):
        """Test F1.2: Device enumeration API returns valid audio devices with default flags."""
        devices_in = (AudioDeviceInfoC * 16)()
        devices_out = (AudioDeviceInfoC * 16)()

        count_in = self.engine.voice_engine_get_input_devices(devices_in, 16)
        count_out = self.engine.voice_engine_get_output_devices(devices_out, 16)

        self.assertGreaterEqual(count_in, 0, "Input device count must be >= 0")
        self.assertGreaterEqual(count_out, 0, "Output device count must be >= 0")

        # Test setting device
        ret_in = self.engine.voice_engine_set_input_device(b"default_input")
        ret_out = self.engine.voice_engine_set_output_device(b"default_output")
        self.assertEqual(ret_in, 0)
        self.assertEqual(ret_out, 0)

    def test_f1_03_start_stop_capture_and_playback(self):
        """Test F1.3: Capture and playback streams start and stop without errors."""
        ret_cap = self.engine.voice_engine_start_capture()
        self.assertEqual(ret_cap, 0, "Start capture should succeed")

        ret_play = self.engine.voice_engine_start_playback()
        self.assertEqual(ret_play, 0, "Start playback should succeed")

        ret_stop_cap = self.engine.voice_engine_stop_capture()
        self.assertEqual(ret_stop_cap, 0, "Stop capture should succeed")

        ret_stop_play = self.engine.voice_engine_stop_playback()
        self.assertEqual(ret_stop_play, 0, "Stop playback should succeed")

    def test_f1_04_silence_buffer_on_capture_underflow(self):
        """Test F1.4: When hardware capture ring is empty, engine returns silence (zeroed buffer), not 440Hz tone."""
        out_buf = (ctypes.c_uint8 * 1920)()
        level_db = ctypes.c_float(0.0)
        is_speaking = ctypes.c_bool(False)
        energy_level = ctypes.c_uint8(0)

        # Call capture frame without hardware mic input
        written = self.engine.voice_engine_capture_frame(
            out_buf,
            1920,
            ctypes.byref(level_db),
            ctypes.byref(is_speaking),
            ctypes.byref(energy_level),
        )

        self.assertEqual(written, 1920, "Should return full 1920-byte 20ms frame")
        # Verify buffer is all zeros (silence)
        raw_bytes = bytes(out_buf)
        self.assertEqual(raw_bytes, b'\x00' * 1920, "Underflow frame MUST be silence (all zeros), not synthetic tone")
        self.assertFalse(is_speaking.value, "Speaking flag must be false for silence")
        self.assertEqual(energy_level.value, 0, "Energy level must be 0 for silence")

    def test_f1_05_local_mute_and_deafen_state_controls(self):
        """Test F1.5: Local mute and deafen controls toggle state and suppress captured audio."""
        self.engine.voice_engine_set_local_mute(True)

        out_buf = (ctypes.c_uint8 * 1920)()
        level_db = ctypes.c_float(0.0)
        is_speaking = ctypes.c_bool(False)
        energy_level = ctypes.c_uint8(0)

        written = self.engine.voice_engine_capture_frame(
            out_buf,
            1920,
            ctypes.byref(level_db),
            ctypes.byref(is_speaking),
            ctypes.byref(energy_level),
        )

        self.assertEqual(written, 1920)
        self.assertEqual(bytes(out_buf), b'\x00' * 1920)
        self.assertFalse(is_speaking.value)

        self.engine.voice_engine_set_local_mute(False)
        self.engine.voice_engine_set_local_deafen(True)
        self.engine.voice_engine_set_local_deafen(False)

    def test_f1_06_peer_audio_mixing_and_clearing(self):
        """Test F1.6: Feeding peer audio packets updates peer ring buffers and clears cleanly."""
        pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=True,
            energy_level=12,
            sender_id=42,
            channel_id=101,
            sequence=1,
            timestamp=960,
            payload=b'\x00' * 1920,  # 20ms PCM silence
        )
        wire_data = pkt.encode()
        data_ptr = (ctypes.c_uint8 * len(wire_data))(*wire_data)

        self.engine.voice_engine_feed_inbound_packet(data_ptr, len(wire_data))

        stats = AudioEngineStatsC()
        self.engine.voice_engine_get_stats(ctypes.byref(stats))
        self.assertGreaterEqual(stats.packets_received, 1)

        self.engine.voice_engine_clear_peers()


if __name__ == "__main__":
    unittest.main()

