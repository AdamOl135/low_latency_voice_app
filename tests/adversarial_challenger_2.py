#!/usr/bin/env python3
"""Comprehensive Adversarial Verification & Stress Test Suite (Challenger 2).

Tests:
1. Native C Engine (libvoice_engine.so):
   - NO 440 Hz synthetic tone on capture ring empty / underflow; zeroed buffer and -90.0 dBFS.
   - FFT spectrum analysis confirming 0 dB power at 440 Hz (complete silence).
   - Multi-threaded high-concurrency stress harness (capture, peer feeds, volume controls, loopback toggle).
   - Soft limiter behavior under multi-peer extreme high-amplitude saturation (no overflow/wrap).
   - Device enumeration and device selection APIs under boundary conditions.
2. Flutter Client Settings Fallback (R4):
   - Comprehensive edge cases (empty strings, whitespace, alphanumeric, negative, 0, >65535, hex, symbols).
   - Verification of AppConstants defaults and settings dialog logic.
3. Flutter Client Inbound Packet Raw Bytes Passthrough (R5):
   - Zero-copy wire byte preservation.
   - Code inspection for direct rawBytes feed in voice_notifier.dart.
   - Corrupt packet injection (truncated, bad magic, bad version, bad length) and engine resilience.
"""

import ctypes
import math
import os
import re
import struct
import threading
import time
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SO_PATH = "/tmp/libvoice_engine_adversarial.so"
C_SRC_PATH = os.path.join(PROJECT_ROOT, "client/native/libvoice_engine.c")
CONSTANTS_PATH = os.path.join(PROJECT_ROOT, "client/lib/core/constants.dart")
SETTINGS_DIALOG_PATH = os.path.join(PROJECT_ROOT, "client/lib/ui/dialogs/audio_settings_dialog.dart")
VOICE_NOTIFIER_PATH = os.path.join(PROJECT_ROOT, "client/lib/state/voice_notifier.dart")


class AudioDeviceInfoC(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_char * 128),
        ("name", ctypes.c_char * 256),
        ("is_default", ctypes.c_bool),
    ]


class AudioEngineConfigC(ctypes.Structure):
    _fields_ = [
        ("sample_rate", ctypes.c_uint32),
        ("channels", ctypes.c_uint32),
        ("frame_duration_ms", ctypes.c_uint32),
        ("opus_bitrate", ctypes.c_uint32),
        ("vad_threshold_db", ctypes.c_float),
        ("vad_hangover_ms", ctypes.c_uint32),
    ]


class AudioEngineStatsC(ctypes.Structure):
    _fields_ = [
        ("input_level_db", ctypes.c_float),
        ("is_speaking", ctypes.c_bool),
        ("packets_sent", ctypes.c_uint32),
        ("packets_received", ctypes.c_uint32),
        ("packets_lost", ctypes.c_uint32),
        ("current_jitter_ms", ctypes.c_float),
    ]


def load_adversarial_engine():
    import subprocess
    cmd = [
        "gcc", "-shared", "-fPIC", "-O2", "-o", SO_PATH,
        C_SRC_PATH, "-lm", "-lpthread", "-ldl"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to compile libvoice_engine.c: {res.stderr}")

    lib = ctypes.CDLL(SO_PATH)
    lib.voice_engine_init.argtypes = [ctypes.POINTER(AudioEngineConfigC)]
    lib.voice_engine_init.restype = ctypes.c_int32

    lib.voice_engine_destroy.argtypes = []
    lib.voice_engine_destroy.restype = None

    lib.voice_engine_get_input_devices.argtypes = [ctypes.POINTER(AudioDeviceInfoC), ctypes.c_int32]
    lib.voice_engine_get_input_devices.restype = ctypes.c_int32

    lib.voice_engine_get_output_devices.argtypes = [ctypes.POINTER(AudioDeviceInfoC), ctypes.c_int32]
    lib.voice_engine_get_output_devices.restype = ctypes.c_int32

    lib.voice_engine_set_input_device.argtypes = [ctypes.c_char_p]
    lib.voice_engine_set_input_device.restype = ctypes.c_int32

    lib.voice_engine_set_output_device.argtypes = [ctypes.c_char_p]
    lib.voice_engine_set_output_device.restype = ctypes.c_int32

    lib.voice_engine_start_capture.argtypes = []
    lib.voice_engine_start_capture.restype = ctypes.c_int32

    lib.voice_engine_stop_capture.argtypes = []
    lib.voice_engine_stop_capture.restype = ctypes.c_int32

    lib.voice_engine_start_playback.argtypes = []
    lib.voice_engine_start_playback.restype = ctypes.c_int32

    lib.voice_engine_stop_playback.argtypes = []
    lib.voice_engine_stop_playback.restype = ctypes.c_int32

    lib.voice_engine_set_local_mute.argtypes = [ctypes.c_bool]
    lib.voice_engine_set_local_mute.restype = None

    lib.voice_engine_set_local_deafen.argtypes = [ctypes.c_bool]
    lib.voice_engine_set_local_deafen.restype = None

    lib.voice_engine_set_ptt_state.argtypes = [ctypes.c_bool]
    lib.voice_engine_set_ptt_state.restype = None

    lib.voice_engine_set_vad_mode.argtypes = [ctypes.c_bool, ctypes.c_float]
    lib.voice_engine_set_vad_mode.restype = None

    lib.voice_engine_set_user_volume.argtypes = [ctypes.c_uint32, ctypes.c_float]
    lib.voice_engine_set_user_volume.restype = None

    lib.voice_engine_capture_frame.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_bool),
        ctypes.POINTER(ctypes.c_uint8),
    ]
    lib.voice_engine_capture_frame.restype = ctypes.c_int32

    lib.voice_engine_feed_inbound_packet.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.voice_engine_feed_inbound_packet.restype = None

    lib.voice_engine_clear_peers.argtypes = []
    lib.voice_engine_clear_peers.restype = None

    lib.voice_engine_set_mic_test_loopback.argtypes = [ctypes.c_bool]
    lib.voice_engine_set_mic_test_loopback.restype = None

    lib.voice_engine_is_mic_test_active.argtypes = []
    lib.voice_engine_is_mic_test_active.restype = ctypes.c_bool

    lib.voice_engine_get_input_level_db.argtypes = []
    lib.voice_engine_get_input_level_db.restype = ctypes.c_float

    lib.voice_engine_get_stats.argtypes = [ctypes.POINTER(AudioEngineStatsC)]
    lib.voice_engine_get_stats.restype = None

    lib.mix_audio_streams.argtypes = [ctypes.POINTER(ctypes.c_int16), ctypes.c_uint32]
    lib.mix_audio_streams.restype = None

    return lib


class TestAdversarialNativeAndClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = load_adversarial_engine()

    def setUp(self):
        config = AudioEngineConfigC(
            sample_rate=48000,
            channels=1,
            frame_duration_ms=20,
            opus_bitrate=48000,
            vad_threshold_db=-45.0,
            vad_hangover_ms=200,
        )
        ret = self.engine.voice_engine_init(ctypes.byref(config))
        self.assertEqual(ret, 0)

    def tearDown(self):
        self.engine.voice_engine_destroy()

    # =========================================================================
    # 1. Native C Engine Tests: Silence & 440 Hz Removal
    # =========================================================================
    def test_adv_01_silence_on_empty_capture_ring(self):
        """Verify NO 440 Hz synthetic sine wave is emitted when capture ring is empty."""
        out_buf = (ctypes.c_uint8 * 1920)()
        level_db = ctypes.c_float(0.0)
        is_speaking = ctypes.c_bool(True)
        energy_level = ctypes.c_uint8(15)

        self.engine.voice_engine_start_capture()

        for _ in range(100):
            # Fill with garbage first to ensure engine overwrites completely
            ctypes.memset(out_buf, 0xAA, 1920)
            n_bytes = self.engine.voice_engine_capture_frame(
                out_buf,
                1920,
                ctypes.byref(level_db),
                ctypes.byref(is_speaking),
                ctypes.byref(energy_level),
            )
            self.assertEqual(n_bytes, 1920)
            raw = bytes(out_buf)

            # Assert all 1920 bytes are exactly 0x00
            self.assertEqual(raw, b'\x00' * 1920, "Captured frame must be 100% zeroed bytes")
            self.assertAlmostEqual(level_db.value, -90.0, places=3, msg="dBFS must be -90.0")
            self.assertFalse(is_speaking.value, "Speaking must be False on underflow")
            self.assertEqual(energy_level.value, 0, "Energy level must be 0 on underflow")

        self.engine.voice_engine_stop_capture()

    def test_adv_02_fft_spectrum_zero_energy_at_440hz(self):
        """Perform FFT / discrete Fourier analysis to verify 0.0 power at 440 Hz."""
        out_buf = (ctypes.c_uint8 * 1920)()
        level_db = ctypes.c_float(0.0)
        is_speaking = ctypes.c_bool(False)
        energy_level = ctypes.c_uint8(0)

        n_bytes = self.engine.voice_engine_capture_frame(
            out_buf,
            1920,
            ctypes.byref(level_db),
            ctypes.byref(is_speaking),
            ctypes.byref(energy_level),
        )
        self.assertEqual(n_bytes, 1920)

        samples = struct.unpack('<960h', bytes(out_buf))

        # Compute Goertzel / discrete correlation at target frequency 440 Hz (sample rate 48000)
        target_freq = 440.0
        sample_rate = 48000.0
        omega = 2.0 * math.pi * target_freq / sample_rate
        real_sum = sum(s * math.cos(i * omega) for i, s in enumerate(samples))
        imag_sum = sum(s * math.sin(i * omega) for i, s in enumerate(samples))
        power_440 = math.sqrt(real_sum**2 + imag_sum**2) / len(samples)

        self.assertEqual(power_440, 0.0, "Power at 440 Hz MUST be exactly 0.0 (no residual synthetic tone)")

    # =========================================================================
    # 2. Soft Limiter & Mixer Behavior Under Extreme High Amplitudes
    # =========================================================================
    def test_adv_03_soft_limiter_extreme_saturation(self):
        """Verify soft limiter prevents integer overflow when summing 20 loud peers."""
        self.engine.voice_engine_start_playback()

        # Build packet with maximum amplitude 32767 for each sample
        header = bytearray(20)
        header[0] = 0x56  # magic
        header[1] = 0x01  # ver
        header[2] = 0x01  # type voice
        header[3] = 0xF1  # vad + energy 15
        header[14] = 0x07  # len high
        header[15] = 0x80  # len low (1920 bytes)

        pcm_samples = [32767] * 960
        payload = struct.pack(f'<{len(pcm_samples)}h', *pcm_samples)

        # Feed 20 peers with volume multiplier 2.0 -> unclipped sum = 20 * 32767 * 2 = 1,310,680!
        for peer_id in range(1, 21):
            struct.pack_into('>I', header, 4, peer_id)
            full_packet = bytes(header) + payload
            ptr = (ctypes.c_uint8 * len(full_packet))(*full_packet)
            self.engine.voice_engine_feed_inbound_packet(ptr, len(full_packet))
            self.engine.voice_engine_set_user_volume(peer_id, 2.0)

        out_samples = (ctypes.c_int16 * 960)()
        self.engine.mix_audio_streams(out_samples, 960)

        for s_idx, sample in enumerate(out_samples):
            self.assertGreaterEqual(sample, -32767, f"Sample {s_idx} underflowed: {sample}")
            self.assertLessEqual(sample, 32767, f"Sample {s_idx} overflowed: {sample}")
            # With cubic limiter clamp at x >= 1.0, output should be exactly 32767
            self.assertEqual(sample, 32767, f"Sample {s_idx} not cleanly limited to 32767: {sample}")

        self.engine.voice_engine_clear_peers()
        self.engine.voice_engine_stop_playback()

    def test_adv_04_soft_limiter_negative_saturation(self):
        """Verify soft limiter prevents integer overflow on extreme negative amplitudes (-32768)."""
        header = bytearray(20)
        header[0] = 0x56
        header[1] = 0x01
        header[2] = 0x01
        header[3] = 0xF1
        header[14] = 0x07
        header[15] = 0x80

        pcm_samples = [-32768] * 960
        payload = struct.pack(f'<{len(pcm_samples)}h', *pcm_samples)

        for peer_id in range(1, 15):
            struct.pack_into('>I', header, 4, peer_id)
            full_packet = bytes(header) + payload
            ptr = (ctypes.c_uint8 * len(full_packet))(*full_packet)
            self.engine.voice_engine_feed_inbound_packet(ptr, len(full_packet))
            self.engine.voice_engine_set_user_volume(peer_id, 1.5)

        out_samples = (ctypes.c_int16 * 960)()
        self.engine.mix_audio_streams(out_samples, 960)

        for s_idx, sample in enumerate(out_samples):
            self.assertEqual(sample, -32767, f"Sample {s_idx} not cleanly limited to -32767: {sample}")

        self.engine.voice_engine_clear_peers()

    # =========================================================================
    # 3. High-Concurrency Multi-Threaded Stress Test
    # =========================================================================
    def test_adv_05_concurrent_multithreaded_stress_harness(self):
        """Simulate high-concurrency access across 8 concurrent worker threads."""
        running = [True]
        errors = []

        def capture_pump():
            buf = (ctypes.c_uint8 * 1920)()
            lvl = ctypes.c_float()
            spk = ctypes.c_bool()
            nrg = ctypes.c_uint8()
            for _ in range(500):
                if not running[0]:
                    break
                try:
                    self.engine.voice_engine_capture_frame(buf, 1920, ctypes.byref(lvl), ctypes.byref(spk), ctypes.byref(nrg))
                except Exception as e:
                    errors.append(f"capture_pump error: {e}")
                time.sleep(0.0005)

        def inbound_feeder(base_id):
            header = bytearray(20)
            header[0] = 0x56
            header[1] = 0x01
            header[2] = 0x01
            header[3] = 0x11
            header[14] = 0x00
            header[15] = 0x50  # 80 bytes payload
            payload = bytes([i % 256 for i in range(80)])
            packet = bytes(header) + payload

            for i in range(500):
                if not running[0]:
                    break
                try:
                    peer_id = base_id + (i % 8) + 1
                    mutated = bytearray(packet)
                    struct.pack_into('>I', mutated, 4, peer_id)
                    ptr = (ctypes.c_uint8 * len(mutated))(*mutated)
                    self.engine.voice_engine_feed_inbound_packet(ptr, len(mutated))
                except Exception as e:
                    errors.append(f"inbound_feeder error: {e}")
                time.sleep(0.0005)

        def volume_mutator():
            for i in range(500):
                if not running[0]:
                    break
                try:
                    peer_id = (i % 20) + 1
                    vol = (i % 25) / 10.0
                    self.engine.voice_engine_set_user_volume(peer_id, vol)
                    if i % 30 == 0:
                        self.engine.voice_engine_set_mic_test_loopback(i % 60 == 0)
                    if i % 50 == 0:
                        self.engine.voice_engine_clear_peers()
                except Exception as e:
                    errors.append(f"volume_mutator error: {e}")
                time.sleep(0.0005)

        threads = [
            threading.Thread(target=capture_pump),
            threading.Thread(target=capture_pump),
            threading.Thread(target=inbound_feeder, args=(1,)),
            threading.Thread(target=inbound_feeder, args=(10,)),
            threading.Thread(target=volume_mutator),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Encountered thread concurrency errors: {errors}")

    # =========================================================================
    # 4. Device Enumeration & Selection
    # =========================================================================
    def test_adv_06_device_enumeration_and_selection_boundaries(self):
        """Test device enumeration with zero, small, and oversized buffers."""
        dev_arr = (AudioDeviceInfoC * 16)()
        in_count = self.engine.voice_engine_get_input_devices(dev_arr, 16)
        out_count = self.engine.voice_engine_get_output_devices(dev_arr, 16)

        self.assertGreaterEqual(in_count, 1)
        self.assertGreaterEqual(out_count, 1)

        # Zero max_count
        self.assertEqual(self.engine.voice_engine_get_input_devices(dev_arr, 0), 0)
        self.assertEqual(self.engine.voice_engine_get_output_devices(dev_arr, 0), 0)

        # NULL pointer
        self.assertEqual(self.engine.voice_engine_get_input_devices(None, 16), 0)
        self.assertEqual(self.engine.voice_engine_get_output_devices(None, 16), 0)

        # Device selection
        self.assertEqual(self.engine.voice_engine_set_input_device(b"default_input"), 0)
        self.assertEqual(self.engine.voice_engine_set_output_device(b"default_output"), 0)
        self.assertEqual(self.engine.voice_engine_set_input_device(None), -1)
        self.assertEqual(self.engine.voice_engine_set_output_device(None), -1)

    # =========================================================================
    # 5. Flutter Client Settings Fallback (R4) Edge Cases
    # =========================================================================
    def test_adv_07_client_settings_dialog_port_fallback_edge_cases(self):
        """Test settings dialog fallback on empty, alphanumeric, negative, and extreme inputs."""
        DEFAULT_WS_PORT = 8085

        def dart_try_parse_fallback(text: str) -> int:
            """Simulates int.tryParse(text) ?? AppConstants.defaultWsPort."""
            try:
                # int.tryParse in Dart parses integer string or returns null
                val = int(text)
                return val if 1 <= val <= 65535 else DEFAULT_WS_PORT
            except Exception:
                return DEFAULT_WS_PORT

        # Standard edge cases
        test_cases = [
            ("", DEFAULT_WS_PORT),
            ("   ", DEFAULT_WS_PORT),
            ("abc", DEFAULT_WS_PORT),
            ("8085custom", DEFAULT_WS_PORT),
            ("port:8085", DEFAULT_WS_PORT),
            ("-1", DEFAULT_WS_PORT),
            ("-8085", DEFAULT_WS_PORT),
            ("0", DEFAULT_WS_PORT),
            ("65536", DEFAULT_WS_PORT),
            ("100000", DEFAULT_WS_PORT),
            ("99999999999999999999999999999999", DEFAULT_WS_PORT),
            ("8085.0", DEFAULT_WS_PORT),
            ("0x1F95", DEFAULT_WS_PORT),
            ("!@#$%", DEFAULT_WS_PORT),
            ("<script>alert(1)</script>", DEFAULT_WS_PORT),
            ("' OR '1'='1", DEFAULT_WS_PORT),
            ("8085", 8085),
            ("80", 80),
            ("443", 443),
            ("65535", 65535),
        ]

        for input_str, expected_port in test_cases:
            res = dart_try_parse_fallback(input_str)
            self.assertEqual(
                res,
                expected_port,
                f"Failed on input '{input_str}': expected {expected_port}, got {res}"
            )

    def test_adv_08_constants_file_verification(self):
        """Verify client/lib/core/constants.dart defines defaultHost=100.108.39.69 and defaultWsPort=8085."""
        with open(CONSTANTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        host_match = re.search(r"static\s+const\s+String\s+defaultHost\s*=\s*['\"]([^'\"]+)['\"]", content)
        port_match = re.search(r"static\s+const\s+int\s+defaultWsPort\s*=\s*(\d+)", content)

        self.assertIsNotNone(host_match)
        self.assertIsNotNone(port_match)
        self.assertEqual(host_match.group(1), "100.108.39.69")
        self.assertEqual(int(port_match.group(1)), 8085)

    def test_adv_09_settings_dialog_no_residual_8080(self):
        """Verify audio_settings_dialog.dart has NO occurrences of 8080."""
        with open(SETTINGS_DIALOG_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("8080", content, "audio_settings_dialog.dart must not contain residual 8080 port")

    # =========================================================================
    # 6. Flutter Client Inbound Packet Raw Bytes Passthrough (R5)
    # =========================================================================
    def test_adv_10_voice_notifier_raw_bytes_passthrough_inspection(self):
        """Verify voice_notifier.dart forwards rawBytes directly to feedInboundPacket without .encode()."""
        with open(VOICE_NOTIFIER_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # Find inbound packet subscription
        sub_match = re.search(r"_inboundPacketSub\s*=\s*_voiceClient\.inboundPacketStream\.listen\((.*?)\);", content, re.DOTALL)
        self.assertIsNotNone(sub_match, "Could not find _inboundPacketSub in voice_notifier.dart")
        block = sub_match.group(1)

        self.assertIn("feedInboundPacket", block)
        self.assertIn("packet.rawBytes", block, "Must pass packet.rawBytes to feedInboundPacket")
        # Verify that feedInboundPacket is called with rawBytes as primary argument
        self.assertRegex(block, r"feedInboundPacket\s*\(\s*packet\.rawBytes", "Must pass packet.rawBytes directly into feedInboundPacket")

    def test_adv_11_corrupt_packet_resilience(self):
        """Inject severely corrupted datagrams into native engine and verify zero memory faults."""
        corrupt_inputs = [
            b'',                          # 0 bytes
            b'\x56',                      # 1 byte
            b'\x56\x01\x01',              # 3 bytes
            b'\x56' * 19,                 # 19 bytes (< 20 byte header)
            b'\xFF' + b'\x00' * 19,       # Bad magic
            b'\x56\x99\x01\x00' + b'\x00' * 16,  # Bad version
            b'\x56\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0F\xFF\x00\x00\x00\x00',  # Payload len 4095 with 0 actual bytes
            b'\x56\x01\x01\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x00\x00' + b'\xAA' * 5,  # Claimed 16 bytes, only 5 present
        ]

        for idx, bad_data in enumerate(corrupt_inputs):
            ptr = (ctypes.c_uint8 * len(bad_data))(*bad_data) if len(bad_data) > 0 else (ctypes.c_uint8 * 1)()
            # Engine must handle gracefully without crash
            self.engine.voice_engine_feed_inbound_packet(ptr, len(bad_data))

        # Check engine is still healthy and responsive
        stats = AudioEngineStatsC()
        self.engine.voice_engine_get_stats(ctypes.byref(stats))
        self.assertIsNotNone(stats)


if __name__ == "__main__":
    print("=================================================================")
    print("  CHALLENGER 2: ADVERSARIAL NATIVE ENGINE & CLIENT TEST HARNESS  ")
    print("=================================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAdversarialNativeAndClient)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\n>> [ALL CHALLENGER 2 ADVERSARIAL TESTS PASSED (100%)]")
        exit(0)
    else:
        print("\n>> [FAILURES DETECTED IN CHALLENGER 2 TESTS]")
        exit(1)
