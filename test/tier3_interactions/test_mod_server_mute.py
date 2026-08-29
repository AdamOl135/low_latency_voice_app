"""Tier 3.2: Server-Side Mute Action and SFU Ingress Packet Gating Tests.

Validates:
- F24: Server-Side Mute Action (server-enforced suppression of incoming voice packets at UDP router)
- F27: Real-Time State Sync Broadcast (voice_state_update server_muted)
- Invariant: Server-mute is enforced server-side regardless of client-side microphone state.
"""

import asyncio
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_server_mute_suppresses_udp_audio_forwarding(client_factory):
    """Verify server-side mute suppresses transmitted UDP audio at the SFU router (F24)."""
    admin = await client_factory(username="AdminMuter")
    target = await client_factory(username="MuteTarget")
    listener = await client_factory(username="MuteListener")

    await target.join_voice_channel(channel_id=101)
    await listener.join_voice_channel(channel_id=101)

    # Initial audio flows normally
    await target.send_voice_frame(is_speaking=True)
    pkt1 = await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert pkt1 is not None

    # Admin applies server mute
    res = await admin.set_server_mute(target_user_id=target.user_id, muted=True)
    assert res.get("status") == "ok"

    # Verify voice_state_update broadcast
    evt = await listener.wait_for_event(
        "voice_state_update",
        lambda e: e.get("user_id") == target.user_id and e.get("server_muted") is True,
        timeout=3.0,
    )
    assert evt.get("server_muted") is True

    # Target attempts to send voice packets while server-muted
    for _ in range(5):
        await target.send_voice_frame(is_speaking=True)

    # Drain any old packets
    while not listener.voice_packets_queue.empty():
        listener.voice_packets_queue.get_nowait()

    # Listener should receive NO packets from muted target
    with pytest.raises(TimeoutError):
        await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=0.5)


@pytest.mark.asyncio
async def test_server_unmute_restores_audio_forwarding(client_factory):
    """Verify unmuting immediately restores UDP audio stream forwarding."""
    admin = await client_factory(username="AdminUnmute")
    target = await client_factory(username="TargetUnmute")
    listener = await client_factory(username="ListenerUnmute")

    await target.join_voice_channel(channel_id=101)
    await listener.join_voice_channel(channel_id=101)

    # Mute then Unmute
    await admin.set_server_mute(target_user_id=target.user_id, muted=True)
    await admin.set_server_mute(target_user_id=target.user_id, muted=False)

    # Verify audio flows again
    await target.send_voice_frame(is_speaking=True)
    pkt = await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert pkt is not None
    assert pkt.sender_id == target.user_id


@pytest.mark.asyncio
async def test_unauthorized_server_mute_rejected(client_factory):
    """Verify non-admin cannot execute server-mute."""
    _admin = await client_factory(username="AdminCreator")
    member = await client_factory(username="MemberAttempter")
    target = await client_factory(username="TargetMember")

    res = await member.set_server_mute(target_user_id=target.user_id, muted=True)
    assert res.get("status") == "error"
