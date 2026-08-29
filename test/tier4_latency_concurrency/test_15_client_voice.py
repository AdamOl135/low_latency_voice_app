"""Tier 4.2: 15-Client Concurrent Active Voice Streaming Load Test.

Validates:
- Acceptance Criteria: Synthetic multi-client load test simulates 15 concurrent active voice streams
  in a single channel without packet drop cascading or audio degradation.
- F18: 15-Client Voice Mixing & High-Throughput Selective Forwarding.
- F13: Zero-Allocation UDP Packet Router.
"""

import asyncio
import time
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_15_concurrent_voice_streams_in_single_channel(client_factory):
    """Simulate 15 concurrent active voice streams in a single channel without packet drop cascading (F18, R2)."""
    num_clients = 15
    clients = []

    # 1. Spawn and connect 15 distinct synthetic clients
    for i in range(num_clients):
        c = await client_factory(username=f"VoiceUser_{i+1:02d}")
        await c.join_voice_channel(channel_id=101)
        clients.append(c)

    assert len(clients) == num_clients

    # Allow UDP sockets to register handshakes
    await asyncio.sleep(0.05)

    # 2. Concurrently stream 20ms Opus frames from all 15 clients
    frames_per_client = 20  # 400ms duration
    frame_interval = 0.020  # 20ms

    async def client_stream_worker(client: SyntheticClient):
        for _ in range(frames_per_client):
            t_start = time.perf_counter()
            await client.send_voice_frame(is_speaking=True, payload_size=80)
            elapsed = time.perf_counter() - t_start
            sleep_time = max(0.0, frame_interval - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    # Launch all 15 streams concurrently
    start_load_time = time.perf_counter()
    await asyncio.gather(*(client_stream_worker(c) for c in clients))
    total_stream_time = time.perf_counter() - start_load_time

    # Allow residual packets in flight to arrive
    await asyncio.sleep(0.15)

    # 3. Verify metrics across all 15 clients
    total_packets_sent = sum(c.packets_sent for c in clients)
    total_packets_received = sum(c.packets_received for c in clients)

    # Each client sent frames_per_client frames + handshake
    for idx, c in enumerate(clients):
        assert c.is_connected is True, f"Client {c.username} disconnected under load"
        assert c.packets_received > 0, f"Client {c.username} received 0 packets"

    # Verify no packet drop cascading: high throughput preserved
    assert total_packets_received > (total_packets_sent * (num_clients - 2)), (
        f"Forwarding throughput too low: {total_packets_received} received for {total_packets_sent} sent"
    )


@pytest.mark.asyncio
async def test_15_client_mixed_speaking_and_silent_workload(client_factory):
    """Verify SFU selective forwarding with 8 active speakers and 7 silent listeners."""
    num_speakers = 8
    num_listeners = 7
    
    speakers = []
    for i in range(num_speakers):
        c = await client_factory(username=f"Speaker_{i+1:02d}")
        await c.join_voice_channel(channel_id=101)
        speakers.append(c)

    listeners = []
    for i in range(num_listeners):
        c = await client_factory(username=f"Listener_{i+1:02d}")
        await c.join_voice_channel(channel_id=101)
        listeners.append(c)

    await asyncio.sleep(0.05)

    # Speakers transmit 15 frames each
    async def speak(client):
        for _ in range(15):
            await client.send_voice_frame(is_speaking=True)
            await asyncio.sleep(0.02)

    await asyncio.gather(*(speak(s) for s in speakers))
    await asyncio.sleep(0.1)

    # All listeners should receive audio from speakers
    for l in listeners:
        assert l.packets_received >= (num_speakers * 10), (
            f"Listener {l.username} received only {l.packets_received} packets"
        )
