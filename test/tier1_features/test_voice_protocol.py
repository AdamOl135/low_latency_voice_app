"""Tier 1.4: UDP Voice Binary Protocol & SFU Selective Forwarding Tests.

Validates:
- F13: Ultra-Low-Latency SFU (zero-allocation UDP selective forwarding)
- F14: Binary Wire Protocol (20-byte big-endian header layout)
- F15: Opus 10-20ms Frames (48kHz clock)
- F19: Tailscale Mesh Resiliency (UDP direct transport)
- F20: Round-Trip Latency Measurement (Ping/Pong)
"""

import asyncio
import struct
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.audio_generator import (
    VoicePacket,
    HEADER_SIZE,
    MAGIC_BYTE,
    PROTOCOL_VERSION,
    TYPE_VOICE,
    TYPE_PING,
    TYPE_PONG,
    TYPE_HANDSHAKE,
)


def test_20_byte_header_binary_encoding():
    """Verify exact 20-byte binary structure matching PROJECT.md §1."""
    pkt = VoicePacket(
        packet_type=TYPE_VOICE,
        vad=True,
        energy_level=14,
        sender_id=0x12345678,
        channel_id=0x00000065,  # 101
        sequence=0x002A,        # 42
        timestamp=0x00010000,
        payload=b'\x01\x02\x03\x04\x05',
    )
    raw = pkt.encode()

    assert len(raw) == HEADER_SIZE + 5
    assert raw[0] == MAGIC_BYTE  # 0x56 ('V')
    assert raw[1] == PROTOCOL_VERSION  # 0x01
    assert raw[2] == TYPE_VOICE  # 0x01
    # flags: energy 14 (0xE0) | vad 1 (0x01) -> 0xE1
    assert raw[3] == 0xE1
    
    sender_id, channel_id, seq, payload_len, timestamp = struct.unpack('>IIHHI', raw[4:20])
    assert sender_id == 0x12345678
    assert channel_id == 101
    assert seq == 42
    assert payload_len == 5
    assert timestamp == 0x00010000
    assert raw[20:] == b'\x01\x02\x03\x04\x05'

    # Test decode roundtrip
    decoded = VoicePacket.decode(raw)
    assert decoded.magic == MAGIC_BYTE
    assert decoded.vad is True
    assert decoded.energy_level == 14
    assert decoded.sender_id == 0x12345678
    assert decoded.channel_id == 101
    assert decoded.sequence == 42
    assert decoded.payload == b'\x01\x02\x03\x04\x05'


@pytest.mark.asyncio
async def test_udp_handshake_registration(client_factory):
    """Verify UDP handshake registers endpoint for receiving forwarded audio (F14)."""
    client = await client_factory(username="HandshakeUser")
    res = await client.join_voice_channel(channel_id=101)
    assert res.get("status") == "ok"
    assert client.is_voice_active is True
    assert client.udp_sock is not None


@pytest.mark.asyncio
async def test_opus_frame_forwarding_between_peers(client_factory):
    """Verify SFU selectively forwards 20ms Opus frames between peers in the same channel (F13, F15)."""
    alice = await client_factory(username="AliceSpeaker")
    bob = await client_factory(username="BobListener")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    # Alice sends a 20ms voice packet
    sent_pkt = await alice.send_voice_frame(is_speaking=True, energy_level=12, payload_size=80)

    # Bob waits for and receives the forwarded packet
    recv_pkt = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=3.0)
    
    assert recv_pkt.packet_type == TYPE_VOICE
    assert recv_pkt.sender_id == alice.user_id
    assert recv_pkt.channel_id == 101
    assert recv_pkt.sequence == sent_pkt.sequence
    assert recv_pkt.vad is True
    assert recv_pkt.payload == sent_pkt.payload


@pytest.mark.asyncio
async def test_voice_packet_no_echo(client_factory):
    """Verify the SFU does NOT echo transmitted packets back to the original sender (F13)."""
    alice = await client_factory(username="AliceEchoCheck")
    await alice.join_voice_channel(channel_id=101)

    # Alice sends packets
    for _ in range(5):
        await alice.send_voice_frame(is_speaking=True)

    await asyncio.sleep(0.1)
    # Alice's received queue should be empty (no self-echo)
    assert alice.voice_packets_queue.empty()


@pytest.mark.asyncio
async def test_voice_channel_isolation(client_factory):
    """Verify audio packets in channel 101 are isolated and NOT received by clients in channel 102."""
    alice = await client_factory(username="AliceIn101")
    bob = await client_factory(username="BobIn101")
    charlie = await client_factory(username="CharlieIn102")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)
    await charlie.join_voice_channel(channel_id=102)

    # Alice sends audio in channel 101
    for _ in range(5):
        await alice.send_voice_frame(is_speaking=True)

    # Bob in 101 receives
    recv_bob = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=3.0)
    assert recv_bob is not None
    assert recv_bob.channel_id == 101

    # Charlie in 102 receives 0 packets from Alice
    await asyncio.sleep(0.1)
    assert charlie.voice_packets_queue.empty()


@pytest.mark.asyncio
async def test_udp_ping_pong_loopback(client_factory):
    """Verify UDP ping probe receives instant pong response with matching payload (F20)."""
    client = await client_factory(username="PingUser")
    await client.join_voice_channel(channel_id=101)

    send_payload = struct.pack('>Q', 1234567890)
    ping_pkt = VoicePacket(
        packet_type=TYPE_PING,
        vad=False,
        energy_level=0,
        sender_id=client.user_id,
        channel_id=101,
        sequence=1,
        timestamp=48000,
        payload=send_payload,
    )
    await client.send_raw_udp_packet(ping_pkt.encode())

    pong_pkt = await client.wait_for_voice_packet(timeout=2.0)
    assert pong_pkt.packet_type == TYPE_PONG
    assert pong_pkt.payload == send_payload
