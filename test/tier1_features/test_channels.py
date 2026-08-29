"""Tier 1.2: Channel Hierarchy, Creation, Categories, and Presence Sync Tests.

Validates:
- F02: Channel Hierarchy Tree (Voice & Text channels, categories)
- F05: Voice HUD Dock & Channel Join/Leave
- F27: Real-Time State Sync Broadcast (channel events)
"""

import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_list_default_channels(client_factory):
    """Verify default server channel hierarchy contains both voice and text channels (F02)."""
    client = await client_factory(username="UserListChannels")
    res = await client.send_rpc({"action": "list_channels"})
    
    assert res.get("status") == "ok"
    channels = res.get("channels", [])
    assert len(channels) >= 2
    
    types = {ch["type"] for ch in channels}
    assert "voice" in types
    assert "text" in types

    categories = {ch.get("category") for ch in channels}
    assert "Voice Rooms" in categories or "Text Channels" in categories


@pytest.mark.asyncio
async def test_create_voice_channel(client_factory):
    """Verify Admin can create a categorized voice channel."""
    admin = await client_factory(username="AdminCreateVoice")
    res = await admin.send_rpc({
        "action": "create_channel",
        "name": "Squad Voice 1",
        "type": "voice",
        "category": "Gaming Rooms",
    })
    
    assert res.get("status") == "ok"
    ch = res.get("channel", {})
    assert ch.get("name") == "Squad Voice 1"
    assert ch.get("type") == "voice"
    assert ch.get("category") == "Gaming Rooms"
    assert ch.get("id") is not None


@pytest.mark.asyncio
async def test_create_text_channel(client_factory):
    """Verify Admin can create a categorized text channel."""
    admin = await client_factory(username="AdminCreateText")
    res = await admin.send_rpc({
        "action": "create_channel",
        "name": "developer-logs",
        "type": "text",
        "category": "Engineering",
    })
    
    assert res.get("status") == "ok"
    ch = res.get("channel", {})
    assert ch.get("name") == "developer-logs"
    assert ch.get("type") == "text"


@pytest.mark.asyncio
async def test_channel_creation_broadcast(client_factory):
    """Verify connected clients receive real-time 'channel_created' event (F27)."""
    admin = await client_factory(username="AdminBroadcaster")
    listener = await client_factory(username="ListenerMember")

    await admin.send_rpc({
        "action": "create_channel",
        "name": "Announcements 2",
        "type": "text",
        "category": "Text Channels",
    })

    evt = await listener.wait_for_event(
        "channel_created",
        lambda e: e.get("channel", {}).get("name") == "Announcements 2",
        timeout=3.0,
    )
    assert evt is not None
    assert evt.get("channel", {}).get("name") == "Announcements 2"


@pytest.mark.asyncio
async def test_join_and_leave_voice_channel(client_factory):
    """Verify joining and leaving a voice channel updates state and UDP credentials."""
    user = await client_factory(username="VoiceJoiner")
    
    # Join
    join_res = await user.join_voice_channel(channel_id=101)
    assert join_res.get("status") == "ok"
    assert user.current_channel_id == 101
    assert user.is_voice_active is True
    assert user.udp_token is not None

    # Leave
    leave_res = await user.leave_voice_channel()
    assert leave_res.get("status") == "ok"
    assert user.current_channel_id is None
    assert user.is_voice_active is False


@pytest.mark.asyncio
async def test_voice_channel_peer_presence_events(client_factory):
    """Verify other clients in channel receive join and leave events."""
    user1 = await client_factory(username="VoicePeer1")
    user2 = await client_factory(username="VoicePeer2")

    await user1.join_voice_channel(channel_id=101)
    await user2.join_voice_channel(channel_id=101)

    join_evt = await user1.wait_for_event(
        "user_joined_voice",
        lambda e: e.get("user_id") == user2.user_id,
        timeout=3.0,
    )
    assert join_evt.get("channel_id") == 101

    await user2.leave_voice_channel()

    leave_evt = await user1.wait_for_event(
        "user_left_voice",
        lambda e: e.get("user_id") == user2.user_id,
        timeout=3.0,
    )
    assert leave_evt.get("user_id") == user2.user_id
