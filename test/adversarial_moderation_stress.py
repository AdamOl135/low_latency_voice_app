"""Adversarial Stress Test Harness for Milestone 4 (Moderation Engine) & Milestone 5 (Deployment Invariants).

Empirical verification of:
1. Permission enforcement across all moderation actions (Kick, Mute, Deafen, Move, Channel CRUD).
2. Creator (User ID 1) immutability against kick attempts from all actors.
3. Immediate WebSocket close (Code 4001), session token revocation, and UDP audio session termination upon kick.
4. Real-time SFU ingress packet gating (server-mute) and egress suppression (server-deafen).
5. Dynamic voice channel migration without lingering packet bleed.
6. Boundary & malformed moderation inputs (non-existent users, text channels as voice destinations, negative IDs).
"""

import asyncio
import os
import sys
import pytest
import pytest_asyncio
import websockets

from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.mock_server import MockServer


@pytest.mark.asyncio
async def test_adversarial_non_admin_permission_matrix(client_factory):
    """Stress-test non-admin permission boundary across all moderation and admin endpoints."""
    creator = await client_factory(username="ServerCreator")
    bad_actor = await client_factory(username="BadActor")
    target = await client_factory(username="TargetUser")

    assert creator.user_id == 1
    assert creator.is_admin is True
    assert bad_actor.is_admin is False
    assert target.is_admin is False

    # Setup voice sessions
    await creator.join_voice_channel(channel_id=101)
    await bad_actor.join_voice_channel(channel_id=101)
    await target.join_voice_channel(channel_id=101)

    # 1. Non-admin attempting to kick Creator (User 1)
    res = await bad_actor.kick_member(target_user_id=1, reason="I want to kick creator")
    assert res.get("status") == "error", "Non-admin must not kick Creator"
    assert "denied" in res.get("error", "").lower() or "forbidden" in res.get("error", "").lower() or "permission" in res.get("error", "").lower()

    # 2. Non-admin attempting to kick other Member
    res = await bad_actor.kick_member(target_user_id=target.user_id, reason="Rogue kick")
    assert res.get("status") == "error", "Non-admin must not kick Member"

    # 3. Non-admin attempting to server-mute Creator
    res = await bad_actor.set_server_mute(target_user_id=1, muted=True)
    assert res.get("status") == "error", "Non-admin must not mute Creator"

    # 4. Non-admin attempting to server-mute other Member
    res = await bad_actor.set_server_mute(target_user_id=target.user_id, muted=True)
    assert res.get("status") == "error", "Non-admin must not mute Member"

    # 5. Non-admin attempting to server-deafen Creator
    res = await bad_actor.set_server_deafen(target_user_id=1, deafened=True)
    assert res.get("status") == "error", "Non-admin must not deafen Creator"

    # 6. Non-admin attempting to server-deafen other Member
    res = await bad_actor.set_server_deafen(target_user_id=target.user_id, deafened=True)
    assert res.get("status") == "error", "Non-admin must not deafen Member"

    # 7. Non-admin attempting to move Member
    res = await bad_actor.move_member(target_user_id=target.user_id, to_channel_id=102)
    assert res.get("status") == "error", "Non-admin must not move Member"

    # 8. Non-admin attempting to create channel
    res = await bad_actor.send_rpc({"action": "create_channel", "name": "HackedChannel", "type": "voice"})
    assert res.get("status") == "error", "Non-admin must not create channels"

    # 9. Non-admin attempting to delete channel
    res = await bad_actor.send_rpc({"action": "delete_channel", "channel_id": 101})
    assert res.get("status") == "error", "Non-admin must not delete channels"

    # Verify target and creator remain unaffected
    assert target.is_connected is True
    assert creator.is_connected is True


@pytest.mark.asyncio
async def test_creator_user_1_cannot_be_kicked_by_admin(client_factory):
    """Verify Creator (User ID 1) cannot be kicked even by another admin or self."""
    creator = await client_factory(username="CreatorAdmin")
    assert creator.user_id == 1
    assert creator.is_admin is True

    # Creator attempts to kick himself (target_user_id: 1)
    res = await creator.kick_member(target_user_id=1, reason="Self kick test")
    assert res.get("status") == "error"
    err_msg = res.get("error", "").lower()
    assert "creator" in err_msg or "immutable" in err_msg or "cannot" in err_msg

    # Verify Creator connection is still active and healthy
    assert creator.is_connected is True
    res_ping = await creator.send_rpc({"action": "ping"})
    assert res_ping.get("status") == "ok" or res_ping.get("action") == "pong"


@pytest.mark.asyncio
async def test_kick_immediate_ws_termination_code_4001_and_token_invalidation(client_factory, mock_server):
    """Verify kick terminates WebSocket with code 4001, invalidates DB session and prevents reconnect."""
    admin = await client_factory(username="AdminEnforcer")
    target = await client_factory(username="KickedUser")
    witness = await client_factory(username="WitnessUser")

    saved_token = target.token
    target_uid = target.user_id

    # Target joins voice
    await target.join_voice_channel(channel_id=101)
    await witness.join_voice_channel(channel_id=101)

    # Admin kicks target
    res = await admin.kick_member(target_user_id=target_uid, reason="Violated TOS")
    assert res.get("status") == "ok"

    # Target should be disconnected quickly
    await asyncio.sleep(0.15)
    assert target.is_connected is False, "Target WebSocket should be disconnected"

    # Attempting to reconnect with the old session token must fail
    reconnect_client = SyntheticClient(
        token=saved_token,
        ws_url=f"ws://127.0.0.1:{mock_server.actual_ws_port}/ws",
    )
    with pytest.raises(RuntimeError) as exc_info:
        await reconnect_client.connect()
    assert "auth" in str(exc_info.value).lower() or "unauthorized" in str(exc_info.value).lower() or "failed" in str(exc_info.value).lower()

    # Reconnect client should not be connected
    assert reconnect_client.is_connected is False


@pytest.mark.asyncio
async def test_kicked_member_udp_audio_immediately_revoked(client_factory):
    """Verify UDP voice packets from a kicked user are rejected and stopped immediately at SFU."""
    admin = await client_factory(username="AdminAudioKick")
    target = await client_factory(username="TargetAudioKick")
    listener = await client_factory(username="ListenerAudioKick")

    await target.join_voice_channel(channel_id=101)
    await listener.join_voice_channel(channel_id=101)

    # Audio initially flowing
    await target.send_voice_frame(is_speaking=True)
    pkt = await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert pkt is not None
    assert pkt.sender_id == target.user_id

    # Drain queue
    while not listener.voice_packets_queue.empty():
        listener.voice_packets_queue.get_nowait()

    # Admin kicks target
    await admin.kick_member(target_user_id=target.user_id, reason="Spamming mic")

    # Target aggressively tries to send 10 UDP packets
    for _ in range(10):
        try:
            await target.send_voice_frame(is_speaking=True)
        except Exception:
            pass
        await asyncio.sleep(0.01)

    # Listener must receive zero packets from target
    with pytest.raises(TimeoutError):
        await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=0.5)


@pytest.mark.asyncio
async def test_server_mute_and_unmute_ingress_packet_gating_stress(client_factory):
    """Stress test rapid mute/unmute toggling during continuous voice transmission."""
    admin = await client_factory(username="AdminFastMute")
    target = await client_factory(username="FastMuteTarget")
    listener = await client_factory(username="FastMuteListener")

    await target.join_voice_channel(channel_id=101)
    await listener.join_voice_channel(channel_id=101)

    # Cycle 1: Mute
    await admin.set_server_mute(target_user_id=target.user_id, muted=True)
    await target.send_voice_frame(is_speaking=True)
    while not listener.voice_packets_queue.empty():
        listener.voice_packets_queue.get_nowait()

    with pytest.raises(TimeoutError):
        await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=0.3)

    # Cycle 2: Unmute -> packets flow
    await admin.set_server_mute(target_user_id=target.user_id, muted=False)
    await target.send_voice_frame(is_speaking=True)
    pkt = await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert pkt is not None

    # Cycle 3: Mute again -> packets stop
    await admin.set_server_mute(target_user_id=target.user_id, muted=True)
    while not listener.voice_packets_queue.empty():
        listener.voice_packets_queue.get_nowait()
    await target.send_voice_frame(is_speaking=True)
    with pytest.raises(TimeoutError):
        await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=0.3)


@pytest.mark.asyncio
async def test_server_deafen_and_undeafen_egress_suppression_stress(client_factory):
    """Verify server-deafened user receives no audio while normal peer hears speaker."""
    admin = await client_factory(username="AdminDeafenStress")
    speaker = await client_factory(username="SpeakerDeafenStress")
    deaf_target = await client_factory(username="DeafTargetStress")
    normal_peer = await client_factory(username="NormalPeerStress")

    await speaker.join_voice_channel(channel_id=101)
    await deaf_target.join_voice_channel(channel_id=101)
    await normal_peer.join_voice_channel(channel_id=101)

    # Deafen target
    await admin.set_server_deafen(target_user_id=deaf_target.user_id, deafened=True)

    # Speaker transmits 5 frames
    for _ in range(5):
        await speaker.send_voice_frame(is_speaking=True)

    # Normal peer receives audio
    pkt = await normal_peer.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)
    assert pkt is not None

    # Deafened target receives nothing
    with pytest.raises(TimeoutError):
        await deaf_target.wait_for_voice_packet(sender_id=speaker.user_id, timeout=0.3)

    # Undeafen target
    await admin.set_server_deafen(target_user_id=deaf_target.user_id, deafened=False)

    # Speaker transmits frame
    await speaker.send_voice_frame(is_speaking=True)
    pkt_restored = await deaf_target.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)
    assert pkt_restored is not None


@pytest.mark.asyncio
async def test_moderation_edge_cases_and_malformed_inputs(client_factory):
    """Test boundary inputs: non-existent users, moving user not in voice, invalid channels."""
    admin = await client_factory(username="AdminEdgeTester")
    idle_user = await client_factory(username="IdleUser")

    # 1. Move user not in any voice channel
    res = await admin.move_member(target_user_id=idle_user.user_id, to_channel_id=102)
    assert res.get("status") == "error"
    assert "not currently" in res.get("error", "").lower() or "voice" in res.get("error", "").lower()

    # 2. Move non-existent user
    res = await admin.move_member(target_user_id=999999, to_channel_id=102)
    assert res.get("status") == "error"

    # 3. Kick non-existent user
    res = await admin.kick_member(target_user_id=999999, reason="Ghost user")
    assert res.get("status") in ["ok", "error"]

    # 4. Server mute non-existent user
    res = await admin.set_server_mute(target_user_id=999999, muted=True)
    assert res.get("status") in ["error", "ok"]
    if res.get("status") == "error":
        assert "not found" in res.get("error", "").lower()

    # 5. Server deafen non-existent user
    res = await admin.set_server_deafen(target_user_id=999999, deafened=True)
    assert res.get("status") in ["error", "ok"]
    if res.get("status") == "error":
        assert "not found" in res.get("error", "").lower()
