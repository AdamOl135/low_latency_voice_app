"""E2E Test Harness Package for Low-Latency Voice App."""

from tests.e2e.harness.protocol import (
    VoicePacket,
    TYPE_VOICE,
    TYPE_PING,
    TYPE_PONG,
    TYPE_HANDSHAKE,
    TYPE_LEAVE,
    HEADER_SIZE,
    MAGIC_BYTE,
    PROTOCOL_VERSION,
)
from tests.e2e.harness.audio_generator import AudioGenerator
from tests.e2e.harness.simple_ws import (
    WebSocketConnection,
    WebSocketClosed,
    connect_ws,
    SimpleWebSocketServer,
)
from tests.e2e.harness.sfu_server import SFUServer, SFUSession, SFUUser
from tests.e2e.harness.synthetic_client import SyntheticClient
from tests.e2e.harness.native_engine import (
    build_and_load_native_engine,
    AudioEngineConfigC,
    AudioDeviceInfoC,
    AudioEngineStatsC,
)

__all__ = [
    "VoicePacket",
    "TYPE_VOICE",
    "TYPE_PING",
    "TYPE_PONG",
    "TYPE_HANDSHAKE",
    "TYPE_LEAVE",
    "HEADER_SIZE",
    "MAGIC_BYTE",
    "PROTOCOL_VERSION",
    "AudioGenerator",
    "WebSocketConnection",
    "WebSocketClosed",
    "connect_ws",
    "SimpleWebSocketServer",
    "SFUServer",
    "SFUSession",
    "SFUUser",
    "SyntheticClient",
    "build_and_load_native_engine",
    "AudioEngineConfigC",
    "AudioDeviceInfoC",
    "AudioEngineStatsC",
]

