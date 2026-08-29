"""Tier 4.1: Sub-30ms Latency SLA & Precision Nanosecond Timing Verification.

Validates:
- Acceptance Criteria §Audio Performance: Automated loopback latency under 30ms on local/VPN networks.
- F20: Round-Trip Latency Measurement with sub-millisecond precision.
- F16: In-Band Speaking Indicator Propagation under 30ms SLA.
- RFC 3550 Interarrival Jitter < 10ms.
"""

import time
import asyncio
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.latency_probe import LatencyProbe, RFC3550JitterCalculator


@pytest.mark.asyncio
async def test_nanosecond_udp_ping_sub_30ms_sla(client_factory, mock_server):
    """Verify UDP ping/pong round-trip latency meets strict sub-30ms SLA (F20)."""
    client = await client_factory(username="LatencySLAClient")
    await client.join_voice_channel(channel_id=101)

    probe = LatencyProbe(
        host="127.0.0.1",
        port=mock_server.actual_udp_port,
        sender_id=client.user_id,
        channel_id=101,
        timeout=1.0,
    )

    stats = await probe.async_run_probe(count=30, interval_sec=0.005)
    
    assert stats.count > 0, "No ping responses received"
    assert stats.packet_loss_rate == 0.0, f"Packet loss detected: {stats.packet_loss_rate * 100}%"
    assert stats.mean_ms < 30.0, f"Mean latency {stats.mean_ms:.2f}ms exceeds 30ms SLA"
    assert stats.p95_ms < 30.0, f"P95 latency {stats.p95_ms:.2f}ms exceeds 30ms SLA"


@pytest.mark.asyncio
async def test_speaking_state_propagation_sub_30ms(client_factory):
    """Verify speaking indicator state changes arrive at peer client within 30ms of threshold crossing (Acceptance Criteria)."""
    alice = await client_factory(username="AliceSpeed")
    bob = await client_factory(username="BobSpeed")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    # Warmup
    await alice.send_voice_frame(is_speaking=False)
    await asyncio.sleep(0.05)

    measurements = []
    for _ in range(5):
        t0 = time.perf_counter()
        await alice.send_voice_frame(is_speaking=True, energy_level=14)

        evt = await bob.wait_for_event(
            "voice_state_update",
            lambda e: e.get("user_id") == alice.user_id and e.get("speaking") is True,
            timeout=1.0,
        )
        t1 = time.perf_counter()
        measurements.append((t1 - t0) * 1000.0)

        # Reset to silent
        await alice.send_voice_frame(is_speaking=False, energy_level=0)
        await asyncio.sleep(0.02)

    avg_propagation_ms = sum(measurements) / len(measurements)
    assert avg_propagation_ms < 30.0, f"Avg speaking sync latency {avg_propagation_ms:.2f}ms exceeds 30ms SLA"


@pytest.mark.asyncio
async def test_jitter_rfc3550_sub_10ms(client_factory):
    """Verify continuous 20ms audio frame streaming maintains RFC 3550 jitter under 10ms (F17)."""
    alice = await client_factory(username="AliceJitter")
    bob = await client_factory(username="BobJitter")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    frame_count = 25
    for i in range(frame_count):
        t_start = time.perf_counter()
        await alice.send_voice_frame(is_speaking=True)
        elapsed = time.perf_counter() - t_start
        sleep_dur = max(0.0, 0.020 - elapsed)
        if sleep_dur > 0:
            await asyncio.sleep(sleep_dur)

    # Wait for bob to receive
    await asyncio.sleep(0.1)
    jitter = bob.jitter_calc.jitter_ms
    assert jitter < 10.0, f"RFC 3550 Jitter {jitter:.2f}ms exceeds 10ms threshold"
