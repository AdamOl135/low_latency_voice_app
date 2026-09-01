"""Python ctypes wrapper for Native C Audio Engine (libvoice_engine.so)."""

import ctypes
import os
import subprocess
from typing import Optional, List, Dict, Any

SO_PATH = "/tmp/libvoice_engine_e2e.so"
C_SRC_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../client/native/libvoice_engine.c")
)


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


def build_and_load_native_engine() -> Optional[ctypes.CDLL]:
    """Compile libvoice_engine.c to a shared object and load with ctypes."""
    if not os.path.exists(C_SRC_PATH):
        return None

    cmd = [
        "gcc",
        "-shared",
        "-fPIC",
        "-O2",
        "-o",
        SO_PATH,
        C_SRC_PATH,
        "-lm",
        "-lpthread",
        "-ldl",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return None

    try:
        lib = ctypes.CDLL(SO_PATH)
        # Setup function signatures
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

        lib.voice_engine_get_stats.argtypes = [ctypes.POINTER(AudioEngineStatsC)]
        lib.voice_engine_get_stats.restype = None

        return lib
    except Exception:
        return None

