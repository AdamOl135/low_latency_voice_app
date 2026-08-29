"""Tier 3.3: Server-Side Deafen Action and Egress Audio Suppression Tests.

Validates:
- F25: Server-Side Deafen Action (server-enforced suppression of outgoing voice packets to target client)
- F27: Real-Time State Sync Broadcast (voice_state_update server_deafened)
- Invariant: Server-deafen suppresses egress packets to deafened client while other channel peers continue receiving audio.
"""

import asyncio
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_server_deafen_suppresses_audio_egress(client_factory):
    """Verify server-deafened client does not receive audio packets forwarded by SFU (F25)."""
    admin = await client_factory(username="AdminDeafener")
    speaker = await client_factory(username="ActiveSpeaker")
    deaf_target = await client_factory(username="DeafenTarget")
    normal_peer = await client_factory(username="NormalPeer")

    await speaker.join_voice_channel(channel_id=101)
    await deaf_target.join_voice_channel(channel_id=101)
    await normal_peer.join_voice_channel(channel_id=101)

    # Admin deafens target
    res = await admin.set_server_deafen(target_user_id=deaf_target.user_id, deafened=True)
    assert res.get("status") == "ok"

    # Verify voice_state_update broadcast
    evt = await deaf_target.wait_for_event(
        "voice_state_update",
        lambda e: e.get("user_id") == deaf_target.user_id and e.get("server_deafened") is True,
        timeout=3.0,
    )
    assert evt.get("server_deafened") is True

    # Speaker transmits voice
    for _ in range(5):
        await speaker.send_voice_frame(is_speaking=True)

    # Normal peer receives audio
    pkt = await normal_peer.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)
    assert pkt is not None

    # Deafened target receives NO audio packets
    with pytest.raises(TimeoutError):
        await deaf_target.wait_for_voice_packet(sender_id=speaker.user_id, timeout=0.5)


@pytest.mark.asyncio
async def test_server_undeafen_restores_audio_egress(client_factory):
    """Verify undeafening a member restores normal audio packet reception."""
    admin = await client_factory(username="AdminUndeafen")
    speaker = await client_factory(username="Speaker2")
    target = await client_factory(username="TargetUndeafen")

    await speaker.join_voice_channel(channel_id=101)
    await target.join_voice_channel(channel_id=101)

    # Deafen and then undeafen
    await admin.set_server_deafen(target_user_id=target.user_id, deafened=True)
    await admin.set_server_deafen(target_user_id=target.user_id, deafened=False)

    # Speaker sends audio
    await speaker.send_voice_frame(is_speaking=True)

    # Target receives packet
    pkt = await target.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)
    assert pkt is not None


@pytest.mark.asyncio
async def test_unauthorized_server_deafen_rejected(client_factory):
    """Verify non-admin cannot server-deafen other members."""
    _admin = await client_factory(username="AdminCreator")
    member = await client_factory(username="BadActorDeafen")
    target = await client_factory(username="TargetMember2")

    res = await member.set_server_deafen(target_user_id=target.user_id, deafened=True)
    assert res.get("status") == "error"
