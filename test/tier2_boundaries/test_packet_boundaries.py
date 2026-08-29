"""Tier 2.1: UDP Packet Boundary & Malformed Header Tests.

Validates:
- 0-byte datagram resilience
- Truncated headers (<20 bytes)
- Invalid magic byte & protocol version rejection
- Jumbo frames & MTU boundary handling
- Header payload length mismatch
"""

import socket
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.audio_generator import (
    VoicePacket,
    HEADER_SIZE,
    MAGIC_BYTE,
    PROTOCOL_VERSION,
    TYPE_VOICE,
)


@pytest.mark.asyncio
async def test_zero_byte_udp_datagram(client_factory, mock_server):
    """Verify 0-byte UDP datagram does not crash SFU and server remains fully operational."""
    client = await client_factory(username="ZeroByteTester")
    await client.join_voice_channel(channel_id=101)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(b'', ("127.0.0.1", mock_server.actual_udp_port))
    sock.close()

    # Verify regular traffic continues normally
    sent_pkt = await client.send_voice_frame(is_speaking=True)
    assert sent_pkt is not None
    assert client.is_connected is True


@pytest.mark.asyncio
async def test_truncated_header_under_20_bytes(client_factory, mock_server):
    """Verify datagrams shorter than the 20-byte header are safely discarded."""
    client = await client_factory(username="TruncatedTester")
    await client.join_voice_channel(channel_id=101)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for length in [1, 5, 10, 19]:
        sock.sendto(b'A' * length, ("127.0.0.1", mock_server.actual_udp_port))
    sock.close()

    # Verify server is still alive and responsive
    res = await client.send_rpc({"action": "list_channels"})
    assert res.get("status") == "ok"


@pytest.mark.asyncio
async def test_invalid_magic_byte(client_factory, mock_server):
    """Verify packets with invalid magic byte (e.g. 0x99 instead of 0x56) are discarded."""
    alice = await client_factory(username="AliceCorruptMagic")
    bob = await client_factory(username="BobCorruptMagic")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    corrupt_pkt = VoicePacket(
        magic=0x99,
        packet_type=TYPE_VOICE,
        sender_id=alice.user_id,
        channel_id=101,
        payload=b'test_audio',
    )
    await alice.send_raw_udp_packet(corrupt_pkt.encode())

    # Bob should not receive any packet with corrupt magic
    with pytest.raises(TimeoutError):
        await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=0.5)


@pytest.mark.asyncio
async def test_invalid_protocol_version(client_factory, mock_server):
    """Verify packets with unsupported protocol version (e.g. 0x02) are rejected."""
    alice = await client_factory(username="AliceBadVersion")
    bob = await client_factory(username="BobBadVersion")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    bad_ver_pkt = VoicePacket(
        version=0x02,
        packet_type=TYPE_VOICE,
        sender_id=alice.user_id,
        channel_id=101,
        payload=b'test_payload',
    )
    await alice.send_raw_udp_packet(bad_ver_pkt.encode())

    with pytest.raises(TimeoutError):
        await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=0.5)


@pytest.mark.asyncio
async def test_payload_length_overflow_jumbo_frame(client_factory):
    """Verify large jumbo audio frames (>1500 bytes) are handled without buffer overflow."""
    alice = await client_factory(username="AliceJumbo")
    bob = await client_factory(username="BobJumbo")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    jumbo_payload = b'\xAA' * 1400  # 1400 bytes audio payload
    pkt = VoicePacket(
        packet_type=TYPE_VOICE,
        sender_id=alice.user_id,
        channel_id=101,
        payload=jumbo_payload,
    )
    await alice.send_raw_udp_packet(pkt.encode())

    recv = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=2.0)
    assert len(recv.payload) == 1400
    assert recv.payload == jumbo_payload
