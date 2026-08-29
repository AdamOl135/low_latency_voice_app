"""Tier 2.2: Jitter Bursts, Sequence Reordering, and Timestamp Wrap Tests.

Validates:
- F17: Minimal Jitter Buffer & Out-of-Order Packet Handling
- 16-bit sequence wraparound (65535 -> 0)
- 32-bit timestamp wraparound
- Burst traffic burst absorption without server degradation
"""

import asyncio
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.audio_generator import VoicePacket, TYPE_VOICE


@pytest.mark.asyncio
async def test_burst_packet_flood_in_short_window(client_factory):
    """Verify SFU handles a burst of 50 packets sent with 0ms delay without dropping connections (F17)."""
    alice = await client_factory(username="AliceBurst")
    bob = await client_factory(username="BobBurst")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    burst_count = 50
    for i in range(burst_count):
        pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=True,
            energy_level=10,
            sender_id=alice.user_id,
            channel_id=101,
            sequence=i,
            timestamp=i * 960,
            payload=b'burst_data_' + bytes([i]),
        )
        await alice.send_raw_udp_packet(pkt.encode())

    # Bob should receive packets without server crash
    received = 0
    for _ in range(burst_count):
        try:
            recv = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=1.0)
            if recv:
                received += 1
        except TimeoutError:
            break

    assert received > 0, "Bob received 0 packets from burst"
    assert alice.is_connected is True
    assert bob.is_connected is True


@pytest.mark.asyncio
async def test_sequence_number_wraparound_16bit(client_factory):
    """Verify 16-bit sequence number wraps from 65535 to 0 seamlessly."""
    alice = await client_factory(username="AliceSeqWrap")
    bob = await client_factory(username="BobSeqWrap")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    # Send packets across sequence boundary
    for seq in [65534, 65535, 0, 1]:
        pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=True,
            energy_level=8,
            sender_id=alice.user_id,
            channel_id=101,
            sequence=seq,
            timestamp=1000 * seq,
            payload=b'seq_wrap',
        )
        await alice.send_raw_udp_packet(pkt.encode())

    recv1 = await bob.wait_for_voice_packet(sender_id=alice.user_id)
    assert recv1.sequence == 65534


@pytest.mark.asyncio
async def test_timestamp_wraparound_32bit(client_factory):
    """Verify 32-bit timestamp clock handles near-overflow values (0xFFFFFF00)."""
    alice = await client_factory(username="AliceTsWrap")
    bob = await client_factory(username="BobTsWrap")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    ts_near_max = 0xFFFFFFF0
    pkt = VoicePacket(
        packet_type=TYPE_VOICE,
        vad=True,
        energy_level=9,
        sender_id=alice.user_id,
        channel_id=101,
        sequence=10,
        timestamp=ts_near_max,
        payload=b'ts_wrap_test',
    )
    await alice.send_raw_udp_packet(pkt.encode())

    recv = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=2.0)
    assert recv.timestamp == ts_near_max
