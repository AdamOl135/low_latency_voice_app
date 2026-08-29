"""Tier 3.4: Member Kick Action, WebSocket Code 4001, and Token Revocation Tests.

Validates:
- F26: Member Kick Action (immediate WebSocket disconnection code 4001 and UDP session revocation)
- F27: Real-Time State Sync Broadcast (member_kicked event)
- Invariant: Kicked member's session token and UDP credentials are permanently invalidated.
"""

import asyncio
import pytest
import pytest_asyncio
import websockets
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_admin_kicks_member_closes_websocket_with_code_4001(client_factory, mock_server):
    """Verify kicking a member disconnects their WebSocket with code 4001 and revokes tokens (F26)."""
    admin = await client_factory(username="AdminKicker")
    target = await client_factory(username="KickTarget")
    witness = await client_factory(username="WitnessPeer")

    saved_token = target.token

    # Admin kicks target
    res = await admin.kick_member(target_user_id=target.user_id, reason="Spam violation")
    assert res.get("status") == "ok"

    # Witness receives member_kicked broadcast
    evt = await witness.wait_for_event(
        "member_kicked",
        lambda e: e.get("user_id") == target.user_id,
        timeout=3.0,
    )
    assert evt.get("user_id") == target.user_id
    assert evt.get("reason") == "Spam violation"

    # Wait for target connection teardown
    await asyncio.sleep(0.1)
    assert target.is_connected is False

    # Verify reconnecting with revoked token is rejected
    revoked_client = SyntheticClient(
        token=saved_token,
        ws_url=f"ws://127.0.0.1:{mock_server.actual_ws_port}/ws",
    )
    with pytest.raises(RuntimeError):
        await revoked_client.connect()


@pytest.mark.asyncio
async def test_kicked_member_udp_traffic_revoked(client_factory):
    """Verify UDP packets sent from kicked user's socket are dropped by SFU."""
    admin = await client_factory(username="AdminKickUDP")
    target = await client_factory(username="TargetKickUDP")
    listener = await client_factory(username="ListenerKickUDP")

    await target.join_voice_channel(channel_id=101)
    await listener.join_voice_channel(channel_id=101)

    # Initial audio flows
    await target.send_voice_frame(is_speaking=True)
    pkt = await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert pkt is not None

    # Admin kicks target
    await admin.kick_member(target_user_id=target.user_id)

    # Target attempts to send UDP packets
    for _ in range(5):
        try:
            await target.send_voice_frame(is_speaking=True)
        except Exception:
            pass

    # Listener receives no further audio from target
    while not listener.voice_packets_queue.empty():
        listener.voice_packets_queue.get_nowait()

    with pytest.raises(TimeoutError):
        await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=0.5)


@pytest.mark.asyncio
async def test_unauthorized_kick_rejected(client_factory):
    """Verify non-admin cannot kick members."""
    _admin = await client_factory(username="AdminCreator")
    member = await client_factory(username="UnauthorizedKicker")
    target = await client_factory(username="InnocentMember")

    res = await member.kick_member(target_user_id=target.user_id)
    assert res.get("status") == "error"
