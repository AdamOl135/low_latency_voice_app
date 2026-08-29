"""Tier 3.1: Admin Channel Movement Action During Active Voice Streaming.

Validates:
- F23: Channel Movement Action (Admin moves connected member with immediate client-side audio migration)
- F27: Real-Time State Sync Broadcast (member_moved event)
- Invariant: Audio stream seamlessly transfers to destination channel without audio bleed into previous channel.
"""

import asyncio
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_admin_moves_streaming_member_migrates_audio(client_factory):
    """Verify Admin moving a member during active audio streaming migrates audio routing immediately (F23)."""
    admin = await client_factory(username="AdminMover")
    target = await client_factory(username="StreamingTarget")
    peer_in_101 = await client_factory(username="PeerIn101")
    peer_in_102 = await client_factory(username="PeerIn102")

    # Target and PeerIn101 join channel 101
    await target.join_voice_channel(channel_id=101)
    await peer_in_101.join_voice_channel(channel_id=101)
    await peer_in_102.join_voice_channel(channel_id=102)

    # Target starts speaking in channel 101
    await target.send_voice_frame(is_speaking=True)
    pkt_initial = await peer_in_101.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert pkt_initial.channel_id == 101

    # Admin moves target to channel 102
    move_res = await admin.move_member(target_user_id=target.user_id, to_channel_id=102)
    assert move_res.get("status") == "ok"

    # Verify Target receives member_moved event and updates local channel
    move_evt = await target.wait_for_event(
        "member_moved",
        lambda e: e.get("user_id") == target.user_id and e.get("to_channel_id") == 102,
        timeout=3.0,
    )
    assert move_evt.get("to_channel_id") == 102

    # Target transmits in new channel
    await target.send_voice_frame(is_speaking=True)

    # Peer in 102 receives the audio packet
    pkt_migrated = await peer_in_102.wait_for_voice_packet(sender_id=target.user_id, timeout=3.0)
    assert pkt_migrated.channel_id == 102

    # Peer in 101 receives no further packets from target
    await asyncio.sleep(0.1)
    # Drain any old packets and verify no new packets
    while not peer_in_101.voice_packets_queue.empty():
        peer_in_101.voice_packets_queue.get_nowait()
    
    await target.send_voice_frame(is_speaking=True)
    with pytest.raises(TimeoutError):
        await peer_in_101.wait_for_voice_packet(sender_id=target.user_id, timeout=0.5)


@pytest.mark.asyncio
async def test_unauthorized_member_move_rejected(client_factory):
    """Verify non-admin members cannot move other users."""
    _admin = await client_factory(username="AdminCreator")
    member_actor = await client_factory(username="UnauthorizedActor")
    target = await client_factory(username="TargetUser")

    res = await member_actor.move_member(target_user_id=target.user_id, to_channel_id=102)
    assert res.get("status") == "error"
    assert "denied" in res.get("error", "").lower() or "unauthorized" in res.get("error", "").lower()
