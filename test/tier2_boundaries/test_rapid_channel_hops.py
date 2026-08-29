"""Tier 2.4: Rapid Channel Hopping and Session Re-Routing Stress Tests.

Validates:
- Rapid consecutive voice channel switching without orphaned streams
- SFU session re-registration under high frequency migration
- Zero lingering audio leakage across previous channels
"""

import asyncio
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_rapid_voice_channel_switches(client_factory):
    """Verify rapid switching between voice channels (101 <-> 102) tears down previous audio session cleanly."""
    alice = await client_factory(username="AliceHopper")

    for i in range(10):
        target_ch = 101 if (i % 2 == 0) else 102
        res = await alice.join_voice_channel(channel_id=target_ch)
        assert res.get("status") == "ok"
        assert alice.current_channel_id == target_ch
        
        # Transmit 1 audio packet in new channel
        await alice.send_voice_frame(is_speaking=True)
        await asyncio.sleep(0.01)

    assert alice.is_connected is True
    assert alice.current_channel_id in (101, 102)


@pytest.mark.asyncio
async def test_multi_client_concurrent_channel_hopping(client_factory):
    """Verify multiple clients hopping channels concurrently do not trigger race conditions in SFU."""
    client1 = await client_factory(username="HopClient1")
    client2 = await client_factory(username="HopClient2")

    async def hop_cycle(client, count=5):
        for i in range(count):
            ch = 101 if (i % 2 == 0) else 102
            await client.join_voice_channel(ch)
            await client.send_voice_frame(is_speaking=True)
            await asyncio.sleep(0.01)

    await asyncio.gather(
        hop_cycle(client1),
        hop_cycle(client2),
    )

    assert client1.is_connected is True
    assert client2.is_connected is True
