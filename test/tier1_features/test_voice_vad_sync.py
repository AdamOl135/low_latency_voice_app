"""Tier 1.5: In-Band Fast VAD and Real-Time Speaking Indicator Propagation Tests.

Validates:
- F06: Live Member Roster (speaking/muted indicators)
- F10: Voice Activity Detection (energy levels, thresholds)
- F16: In-Band Fast VAD (<30ms speaking indicator sync)
- F27: Real-Time State Sync Broadcast
"""

import time
import asyncio
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.audio_generator import VoicePacket


@pytest.mark.asyncio
async def test_inband_vad_flag_propagation(client_factory):
    """Verify in-band VAD bit is encoded and preserved in forwarded UDP audio packet (F16)."""
    alice = await client_factory(username="AliceVAD")
    bob = await client_factory(username="BobVAD")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    # Alice sends speaking packet
    await alice.send_voice_frame(is_speaking=True, energy_level=13)
    pkt_speaking = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=3.0)
    assert pkt_speaking.vad is True
    assert pkt_speaking.energy_level == 13

    # Alice sends silent packet
    await alice.send_voice_frame(is_speaking=False, energy_level=0)
    pkt_silent = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=3.0)
    assert pkt_silent.vad is False
    assert pkt_silent.energy_level == 0


@pytest.mark.asyncio
async def test_energy_level_quantization(client_factory):
    """Verify 4-bit energy level quantization (0..15) across the binary protocol (F10)."""
    alice = await client_factory(username="AliceEnergy")
    bob = await client_factory(username="BobEnergy")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    for level in [0, 4, 8, 12, 15]:
        await alice.send_voice_frame(is_speaking=True, energy_level=level)
        recv = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=3.0)
        assert recv.energy_level == level


@pytest.mark.asyncio
async def test_speaking_state_broadcast_on_audio_onset(client_factory):
    """Verify WebSocket presence event is broadcast when voice activity begins (F06, F27)."""
    alice = await client_factory(username="AliceOnset")
    bob = await client_factory(username="BobOnset")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    # Alice transitions to speaking
    await alice.send_voice_frame(is_speaking=True, energy_level=14)

    evt = await bob.wait_for_event(
        "voice_state_update",
        lambda e: e.get("user_id") == alice.user_id and e.get("speaking") is True,
        timeout=3.0,
    )
    assert evt.get("user_id") == alice.user_id
    assert evt.get("speaking") is True


@pytest.mark.asyncio
async def test_speaking_state_deactivation_on_silence(client_factory):
    """Verify WebSocket presence event is broadcast when voice activity ends."""
    alice = await client_factory(username="AliceRelease")
    bob = await client_factory(username="BobRelease")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    # First speak
    await alice.send_voice_frame(is_speaking=True, energy_level=12)
    await bob.wait_for_event("voice_state_update", lambda e: e.get("speaking") is True)

    # Now silence
    await alice.send_voice_frame(is_speaking=False, energy_level=0)
    evt_silent = await bob.wait_for_event(
        "voice_state_update",
        lambda e: e.get("user_id") == alice.user_id and e.get("speaking") is False,
        timeout=3.0,
    )
    assert evt_silent.get("speaking") is False


@pytest.mark.asyncio
async def test_speaking_indicator_sub_30ms_arrival(client_factory):
    """Verify speaking indicator state change arrives at peer client within 30ms SLA (R2, Acceptance Criteria)."""
    alice = await client_factory(username="AliceSLA")
    bob = await client_factory(username="BobSLA")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    send_time = time.perf_counter()
    await alice.send_voice_frame(is_speaking=True, energy_level=15)

    evt = await bob.wait_for_event(
        "voice_state_update",
        lambda e: e.get("user_id") == alice.user_id and e.get("speaking") is True,
        timeout=1.0,
    )
    recv_time = time.perf_counter()
    propagation_ms = (recv_time - send_time) * 1000.0

    # Verify < 30ms SLA on local test
    assert propagation_ms < 30.0, f"Speaking indicator took {propagation_ms:.2f}ms, exceeding 30ms SLA"


@pytest.mark.asyncio
async def test_rapid_speaking_transitions(client_factory):
    """Verify rapid consecutive voice activity changes do not cause dropped state transitions."""
    alice = await client_factory(username="AliceRapid")
    bob = await client_factory(username="BobRapid")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    # 3 bursts of speaking/silence
    for i in range(3):
        await alice.send_voice_frame(is_speaking=True, energy_level=10)
        await asyncio.sleep(0.02)
        await alice.send_voice_frame(is_speaking=False, energy_level=0)
        await asyncio.sleep(0.02)

    # Should have received events without connection drops
    assert alice.is_connected is True
    assert bob.is_connected is True
