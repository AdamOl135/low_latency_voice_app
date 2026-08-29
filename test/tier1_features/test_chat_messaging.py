"""Tier 1.3: Text Chat Messaging, History Pagination, and Real-Time Broadcast.

Validates:
- F03: Real-Time Chat Stream (timestamps, cursor pagination, ordering)
- F04: Rich Text Input (multi-line formatting, limits)
- F27: Real-Time State Sync Broadcast
"""

import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_send_and_broadcast_chat_message(client_factory):
    """Verify sending a chat message produces a real-time broadcast to connected peers (F03, F27)."""
    alice = await client_factory(username="AliceChat")
    bob = await client_factory(username="BobChat")

    # Alice sends a message in text channel 201
    content = "Hello low-latency world!"
    send_res = await alice.send_chat_message(channel_id=201, content=content)
    assert send_res.get("status") == "ok"
    msg_id = send_res.get("message_id")

    # Bob receives the broadcast
    evt = await bob.wait_for_event(
        "chat_message",
        lambda e: e.get("id") == msg_id or e.get("content") == content,
        timeout=3.0,
    )
    assert evt.get("content") == content
    assert evt.get("sender_id") == alice.user_id
    assert evt.get("sender_name") == alice.username
    assert evt.get("channel_id") == 201
    assert "timestamp" in evt


@pytest.mark.asyncio
async def test_multiline_chat_message(client_factory):
    """Verify multi-line text formatting is preserved without truncation."""
    sender = await client_factory(username="MultilineSender")
    receiver = await client_factory(username="MultilineReceiver")

    multiline_text = "Line 1: System Init\nLine 2: Opus 48kHz\nLine 3: Sub-30ms SLA"
    await sender.send_chat_message(channel_id=201, content=multiline_text)

    evt = await receiver.wait_for_event(
        "chat_message",
        lambda e: e.get("content") == multiline_text,
        timeout=3.0,
    )
    assert evt.get("content") == multiline_text
    assert "\n" in evt.get("content")


@pytest.mark.asyncio
async def test_chat_history_pagination(client_factory):
    """Verify chat history supports limit and before_id cursor pagination (F03)."""
    client = await client_factory(username="HistoryPaginator")
    
    # Send 10 messages
    msg_ids = []
    for i in range(10):
        res = await client.send_chat_message(channel_id=201, content=f"History item #{i+1}")
        msg_ids.append(res.get("message_id"))

    # Fetch last 5 messages
    res_recent = await client.get_chat_history(channel_id=201, limit=5)
    assert res_recent.get("status") == "ok"
    messages = res_recent.get("messages", [])
    assert len(messages) == 5
    assert messages[-1]["content"] == "History item #10"

    # Fetch previous messages before the earliest of the recent batch
    earliest_id = messages[0]["id"]
    res_older = await client.get_chat_history(channel_id=201, limit=5, before_id=earliest_id)
    assert res_older.get("status") == "ok"
    older_messages = res_older.get("messages", [])
    assert len(older_messages) > 0
    assert all(m["id"] < earliest_id for m in older_messages)


@pytest.mark.asyncio
async def test_chat_message_channel_separation(client_factory):
    """Verify chat messages retain distinct channel_id tagging for stream filtering."""
    sender = await client_factory(username="ChannelSender")
    receiver = await client_factory(username="ChannelReceiver")

    await sender.send_chat_message(channel_id=201, content="General channel message")
    await sender.send_chat_message(channel_id=202, content="Announcements channel message")

    evt1 = await receiver.wait_for_event("chat_message", lambda e: e.get("channel_id") == 201)
    evt2 = await receiver.wait_for_event("chat_message", lambda e: e.get("channel_id") == 202)

    assert evt1.get("content") == "General channel message"
    assert evt2.get("content") == "Announcements channel message"


@pytest.mark.asyncio
async def test_empty_chat_message_rejected(client_factory):
    """Verify sending an empty chat message is rejected."""
    client = await client_factory(username="EmptySender")
    res = await client.send_chat_message(channel_id=201, content="")
    assert res.get("status") == "error"


@pytest.mark.asyncio
async def test_rapid_chat_sequential_ordering(client_factory):
    """Verify rapid consecutive messages maintain strict monotonically increasing IDs."""
    sender = await client_factory(username="RapidChatSender")
    receiver = await client_factory(username="RapidChatReceiver")

    sent_count = 5
    for i in range(sent_count):
        await sender.send_chat_message(channel_id=201, content=f"Rapid seq {i}")

    received_ids = []
    for i in range(sent_count):
        evt = await receiver.wait_for_event("chat_message", lambda e: f"Rapid seq {i}" in e.get("content", ""))
        received_ids.append(evt.get("id"))

    assert received_ids == sorted(received_ids)
    assert len(received_ids) == sent_count
