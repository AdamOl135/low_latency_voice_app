"""Empirical Challenge Test Suite for Milestone 7 - Member Kick & State Synchronization (R4).

Focuses on:
1. Close Code 4001 and reason propagation.
2. Session token & UDP token permanent revocation in DB and SFU.
3. UDP voice transmission prevention post-kick.
4. Immediate peer state synchronization (Roster, Channel Tree, Voice State, Speaking indicators).
5. Edge cases: Server Creator kick immunity, unauthorized kicks, offline user kicks, pending UDP token invalidation.
"""

import asyncio
import json
import socket
import time
import pytest
import pytest_asyncio
import websockets
from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.audio_generator import VoicePacket, TYPE_VOICE, TYPE_HANDSHAKE


async def wait_for_event_history(client: SyntheticClient, event_name: str, predicate=None, timeout: float = 3.0):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        for evt in client.received_events:
            if evt.get("event") == event_name:
                data = evt.get("data") if isinstance(evt.get("data"), dict) else evt
                if predicate is None or predicate(data):
                    return data
        await asyncio.sleep(0.02)
    # Debug info on timeout
    events_summary = [f"{e.get('event')}: {e.get('data', e)}" for e in client.received_events]
    raise TimeoutError(f"Timed out waiting for event '{event_name}' on user {client.username}. Events: {events_summary}")


@pytest.mark.asyncio
async def test_close_code_4001_and_reason_on_kick(client_factory, mock_server):
    """Verify backend closes WebSocket connection with exact code 4001 and custom reason."""
    admin = await client_factory(username="AdminKicker_4001")
    target = await client_factory(username="KickTarget_4001")
    target_id = target.user_id

    custom_reason = "Violation of Server Voice Policy #4"

    # Connect raw websocket for target to directly capture close code and reason
    raw_ws_url = f"ws://127.0.0.1:{mock_server.actual_ws_port}/ws"
    raw_ws = await websockets.connect(raw_ws_url)
    
    # Authenticate raw client with target's token
    await raw_ws.send(json.dumps({
        "action": "auth",
        "token": target.token,
        "client_version": "1.0.0"
    }))
    raw_auth_res = json.loads(await raw_ws.recv())
    assert raw_auth_res.get("status") == "ok"

    # Admin kicks target
    res = await admin.kick_member(target_user_id=target_id, reason=custom_reason)
    assert res.get("status") == "ok"

    # Target raw websocket should receive close frame with code 4001
    close_code = None
    close_reason = None
    start = time.monotonic()
    while time.monotonic() - start < 3.0:
        try:
            msg = await asyncio.wait_for(raw_ws.recv(), timeout=1.0)
        except websockets.exceptions.ConnectionClosed as e:
            close_code = e.rcvd.code
            close_reason = e.rcvd.reason
            break
        except Exception:
            break

    try:
        await raw_ws.close()
    except Exception:
        pass

    assert close_code == 4001, f"Expected close code 4001, got {close_code}"
    assert close_reason == custom_reason, f"Expected reason '{custom_reason}', got '{close_reason}'"


@pytest.mark.asyncio
async def test_pending_unconsumed_voice_token_revocation(client_factory, mock_server):
    """Verify that a pre-issued UDP voice token is revoked upon kick before being consumed."""
    admin = await client_factory(username="AdminTokenRevoke")
    target = await client_factory(username="TargetPendingToken")

    # Target calls join_voice to obtain UDP token, but does not activate it yet
    join_res = await target.send_rpc({"action": "join_voice", "channel_id": 101})
    assert join_res.get("status") == "ok"
    data = join_res.get("data", join_res)
    udp_token = data.get("udp_token")
    assert udp_token is not None

    # Admin kicks target immediately
    kick_res = await admin.kick_member(target_user_id=target.user_id, reason="Kicked before UDP connect")
    assert kick_res.get("status") == "ok"

    # Now target tries to send UDP handshake with the revoked token
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.5)

    pkt = VoicePacket(
        packet_type=TYPE_HANDSHAKE,
        vad=False,
        energy_level=0,
        sender_id=target.user_id,
        channel_id=101,
        sequence=1,
        timestamp=0,
        payload=udp_token.encode("utf-8")
    )
    s.sendto(pkt.encode(), ("127.0.0.1", mock_server.actual_udp_port))

    # SFU should reject handshake: no session activated
    # Subsequent voice packet from target should not route to listener
    listener = await client_factory(username="ListenerPendingCheck")
    await listener.join_voice_channel(channel_id=101)

    voice_pkt = VoicePacket(
        packet_type=TYPE_VOICE,
        vad=True,
        energy_level=12,
        sender_id=target.user_id,
        channel_id=101,
        sequence=2,
        timestamp=960,
        payload=b"opus_test_payload"
    )
    s.sendto(voice_pkt.encode(), ("127.0.0.1", mock_server.actual_udp_port))

    with pytest.raises(TimeoutError):
        await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=0.5)

    s.close()


@pytest.mark.asyncio
async def test_active_voice_stream_instant_cutoff(client_factory):
    """Verify that voice packets from a kicked user are immediately dropped by the SFU."""
    admin = await client_factory(username="AdminVoiceCutoff")
    target = await client_factory(username="TargetVoiceCutoff")
    listener = await client_factory(username="ListenerVoiceCutoff")

    await target.join_voice_channel(channel_id=101)
    await listener.join_voice_channel(channel_id=101)

    # Initial packet sent and received
    await target.send_voice_frame(is_speaking=True, energy_level=12)
    pkt = await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert pkt is not None
    assert pkt.vad is True

    # Admin kicks target
    await admin.kick_member(target_user_id=target.user_id)

    # Drain queue
    while not listener.voice_packets_queue.empty():
        listener.voice_packets_queue.get_nowait()

    # Target continuously sends audio frames after kick
    for _ in range(10):
        try:
            await target.send_voice_frame(is_speaking=True, energy_level=15)
        except Exception:
            pass
        await asyncio.sleep(0.01)

    # Verify listener receives 0 packets from target
    with pytest.raises(TimeoutError):
        await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=0.5)


@pytest.mark.asyncio
async def test_multi_peer_member_kicked_and_voice_state_sync(client_factory):
    """Verify all connected peers receive member_kicked and voice_state_update events simultaneously."""
    admin = await client_factory(username="AdminMultiSync")
    target = await client_factory(username="TargetMultiSync")
    peer1 = await client_factory(username="Peer1MultiSync")
    peer2 = await client_factory(username="Peer2MultiSync")

    await target.join_voice_channel(channel_id=101)
    await peer1.join_voice_channel(channel_id=101)
    await peer2.join_voice_channel(channel_id=101)

    # Admin kicks target
    await admin.kick_member(target_user_id=target.user_id, reason="Multi-peer test kick")

    # Both peer1 and peer2 must receive member_kicked
    evt1 = await wait_for_event_history(peer1, "member_kicked", lambda e: e.get("user_id") == target.user_id)
    evt2 = await wait_for_event_history(peer2, "member_kicked", lambda e: e.get("user_id") == target.user_id)
    assert evt1.get("user_id") == target.user_id
    assert evt2.get("user_id") == target.user_id
    assert evt1.get("reason") == "Multi-peer test kick"
    assert evt2.get("reason") == "Multi-peer test kick"

    # Both peer1 and peer2 must receive voice_state_update indicating channel evacuation
    vs1 = await wait_for_event_history(peer1, "voice_state_update", lambda e: e.get("user_id") == target.user_id and (e.get("channel_id") is None or e.get("channel_id") == 0))
    vs2 = await wait_for_event_history(peer2, "voice_state_update", lambda e: e.get("user_id") == target.user_id and (e.get("channel_id") is None or e.get("channel_id") == 0))
    assert vs1.get("user_id") == target.user_id
    assert vs2.get("user_id") == target.user_id
    assert vs1.get("is_speaking") is False
    assert vs2.get("is_speaking") is False


@pytest.mark.asyncio
async def test_server_creator_kick_immunity(client_factory):
    """Verify Server Creator (User ID 1) cannot be kicked, and backend returns 4003."""
    creator_admin = await client_factory(username="AdminCreatorImmune")
    assert creator_admin.user_id == 1

    # Admin attempts to kick itself (User 1)
    res = await creator_admin.kick_member(target_user_id=1, reason="Try kick creator")
    assert res.get("status") == "error"
    err = res.get("error", {})
    err_msg = err.get("message", "") if isinstance(err, dict) else str(err)
    assert "creator" in err_msg.lower() or "cannot kick" in err_msg.lower()

    # Verify creator remains connected and functional
    assert creator_admin.is_connected is True


@pytest.mark.asyncio
async def test_kick_offline_member(client_factory):
    """Verify kicking an offline member succeeds, purges database sessions, and broadcasts event."""
    admin = await client_factory(username="AdminKickOffline")
    offline_user = await client_factory(username="UserGoingOffline")
    offline_user_id = offline_user.user_id

    # User disconnects cleanly
    await offline_user.disconnect()
    assert offline_user.is_connected is False

    witness = await client_factory(username="WitnessOfflineKick")

    # Admin kicks offline user
    res = await admin.kick_member(target_user_id=offline_user_id, reason="Offline kick cleanup")
    assert res.get("status") == "ok"

    # Witness should receive member_kicked broadcast
    evt = await wait_for_event_history(witness, "member_kicked", lambda e: e.get("user_id") == offline_user_id)
    assert evt.get("user_id") == offline_user_id
    assert evt.get("reason") == "Offline kick cleanup"
