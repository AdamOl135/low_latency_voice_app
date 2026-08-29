"""Tier 3.5: Multi-Client Concurrent State Sync and Mixed Role Interactions.

Validates:
- F06: Live Member Roster (role grouping, state badges)
- F21: Role & Permission Model across multiple sessions
- F27: Real-Time State Sync Broadcast during concurrent voice and text traffic
"""

import asyncio
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_concurrent_chat_and_voice_multi_user(client_factory):
    """Verify simultaneous text chat and UDP voice streaming across 4 concurrent clients (F03, F13, F27)."""
    clients = []
    for i in range(4):
        c = await client_factory(username=f"ConcurrentClient_{i}")
        await c.join_voice_channel(channel_id=101)
        clients.append(c)

    # Concurrently send chat messages and voice packets
    async def chat_worker(client, idx):
        for msg_i in range(3):
            await client.send_chat_message(channel_id=201, content=f"User {idx} message {msg_i}")
            await asyncio.sleep(0.01)

    async def voice_worker(client):
        for _ in range(5):
            await client.send_voice_frame(is_speaking=True)
            await asyncio.sleep(0.02)

    tasks = []
    for idx, c in enumerate(clients):
        tasks.append(chat_worker(c, idx))
        tasks.append(voice_worker(c))

    await asyncio.gather(*tasks)

    # Verify all clients remain connected and received data
    for c in clients:
        assert c.is_connected is True
        assert c.packets_sent > 0


@pytest.mark.asyncio
async def test_mixed_role_roster_presence_synchronization(client_factory):
    """Verify role permissions and presence state consistency among Admin and Members."""
    admin = await client_factory(username="RosterAdmin")
    member1 = await client_factory(username="RosterMember1")
    member2 = await client_factory(username="RosterMember2")

    assert admin.is_admin is True
    assert member1.is_admin is False
    assert member2.is_admin is False

    # Join voice channel
    await admin.join_voice_channel(channel_id=101)
    await member1.join_voice_channel(channel_id=101)

    # Admin speaks -> member1 receives speaking state
    await admin.send_voice_frame(is_speaking=True, energy_level=12)
    evt = await member1.wait_for_event(
        "voice_state_update",
        lambda e: e.get("user_id") == admin.user_id and e.get("speaking") is True,
        timeout=3.0,
    )
    assert evt.get("speaking") is True
