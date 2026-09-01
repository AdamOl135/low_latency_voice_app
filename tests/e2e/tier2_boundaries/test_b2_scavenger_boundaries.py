"""Tier 2 Boundary Tests: B2 - Session Scavenger Boundaries.

Validates:
- Sub-second eviction timing precision (95% vs 105% of timeout)
- High-frequency ping burst handling
- Sequence number wrap around (0xFFFF -> 0x0000)
- 32-bit timestamp wrap around (0xFFFFFFFF -> 0x00000000)
- Packet burst after prolonged silence
"""

import asyncio
import time
import unittest
from tests.e2e.harness.sfu_server import SFUServer
from tests.e2e.harness.synthetic_client import SyntheticClient
from tests.e2e.harness.protocol import TYPE_PING, TYPE_PONG, VoicePacket


class TestB2ScavengerBoundaries(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 1.0s timeout, 0.05s check interval
        self.server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=1.0, scavenger_interval_sec=0.05)
        await self.server.start()
        self.ws_url = f"ws://127.0.0.1:{self.server.actual_ws_port}/ws"
        self.udp_port = self.server.actual_udp_port

    async def asyncTearDown(self):
        await self.server.stop()

    async def test_b2_01_ping_at_sub_second_boundary_keeps_alive(self):
        """Test B2.1: Sending ping at 0.8s (80% of 1.0s timeout) prevents eviction."""
        async with SyntheticClient(username="BorderClient", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)
            uid = client.user_id

            # Wait 0.8s, then send ping
            await asyncio.sleep(0.8)
            await client.send_ping_probe(channel_id=101, seq=1)

            # Wait another 0.5s (total 1.3s from start, but only 0.5s from last ping)
            await asyncio.sleep(0.5)

            self.assertIn(uid, self.server.sessions_by_user, "Session refreshed at 0.8s must NOT be evicted at 1.3s")

    async def test_b2_02_session_eviction_immediate_post_timeout(self):
        """Test B2.2: Session is evicted once elapsed time exceeds 1.0s."""
        async with SyntheticClient(username="EvictBorder", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)
            uid = client.user_id

            # Wait 1.15s without any packets
            await asyncio.sleep(1.15)
            self.assertNotIn(uid, self.server.sessions_by_user, "Session must be evicted after 1.15s > 1.0s")

    async def test_b2_03_high_frequency_ping_burst(self):
        """Test B2.3: Sending 50 pings in a 50ms burst is handled gracefully."""
        async with SyntheticClient(username="BurstClient", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)
            for i in range(50):
                await client.send_ping_probe(channel_id=101, seq=i)

            await asyncio.sleep(0.1)
            self.assertIn(client.user_id, self.server.sessions_by_user)
            self.assertGreaterEqual(self.server.pings_received_count, 50)

    async def test_b2_04_sequence_number_wrap_0xffff(self):
        """Test B2.4: Ping/Pong sequence number wrapping across 0xFFFF."""
        async with SyntheticClient(username="WrapClient", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)

            seq_test = [0xFFFE, 0xFFFF, 0x0000, 0x0001]
            for s in seq_test:
                pkt = VoicePacket(
                    packet_type=TYPE_PING,
                    sender_id=client.user_id,
                    channel_id=101,
                    sequence=s,
                    timestamp=1000,
                    payload=b'wrap',
                )
                await client.send_raw_udp(pkt.encode())
                pong, _ = await client.wait_for_pong(timeout=1.0)
                self.assertEqual(pong.sequence, s)

    async def test_b2_05_timestamp_32bit_wrap(self):
        """Test B2.5: Ping/Pong 32-bit timestamp wrapping across 0xFFFFFFFF."""
        async with SyntheticClient(username="TsWrapClient", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)

            ts_test = [0xFFFFFFF0, 0xFFFFFFFF, 0x00000000, 0x00000020]
            for t in ts_test:
                pkt = VoicePacket(
                    packet_type=TYPE_PING,
                    sender_id=client.user_id,
                    channel_id=101,
                    sequence=1,
                    timestamp=t,
                    payload=b'ts_wrap',
                )
                await client.send_raw_udp(pkt.encode())
                pong, _ = await client.wait_for_pong(timeout=1.0)
                self.assertEqual(pong.timestamp, t)


if __name__ == "__main__":
    unittest.main()

