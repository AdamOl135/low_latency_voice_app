"""Tier 4 Real-World Application Scenarios.

Validates:
- Scenario 1: Multi-User Real-Time Voice Exchange (3+ clients connected to same channel hearing each other)
- Scenario 2: Silent Listener Extended Survival (Listener surviving prolonged period with pings while peers speak)
- Scenario 3: Client Unexpected Disconnect and Seamless Reconnection with Token
- Scenario 4: Multi-Room Concurrent Voice Routing & Strict Room Isolation
"""

import asyncio
import time
import unittest
from tests.e2e.harness.sfu_server import SFUServer
from tests.e2e.harness.synthetic_client import SyntheticClient
from tests.e2e.harness.protocol import VoicePacket, TYPE_VOICE


class TestTier4RealWorldScenarios(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 2.0s idle timeout for scavenger
        self.server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=2.0, scavenger_interval_sec=0.1)
        await self.server.start()
        self.ws_url = f"ws://127.0.0.1:{self.server.actual_ws_port}/ws"
        self.udp_port = self.server.actual_udp_port

    async def asyncTearDown(self):
        await self.server.stop()

    async def test_s1_multi_user_voice_mesh_exchange(self):
        """Scenario 1: 3 clients connected to Channel 101 hear each other with zero packet drop."""
        clients = [
            SyntheticClient(username=f"VoiceUser_{i}", ws_url=self.ws_url, udp_port=self.udp_port)
            for i in range(3)
        ]
        try:
            for c in clients:
                await c.connect()
                await c.join_voice_channel(101)

            # Each client sends 5 audio frames
            for c in clients:
                for _ in range(5):
                    await c.send_voice_frame(is_speaking=True)
                    await asyncio.sleep(0.02)

            await asyncio.sleep(0.1)

            # Each client should receive packets from the other 2 clients (10 packets total)
            for c in clients:
                self.assertGreaterEqual(
                    c.voice_packets_queue.qsize(),
                    10,
                    f"Client {c.username} should have received at least 10 forwarded frames from peers"
                )
        finally:
            for c in clients:
                await c.disconnect()

    async def test_s2_silent_listener_extended_survival(self):
        """Scenario 2: Silent listener sending 1s pings survives 3.0s (exceeding 2.0s timeout) and receives peer audio."""
        async with SyntheticClient(username="Silent_Surv", ws_url=self.ws_url, udp_port=self.udp_port) as listener:
            await listener.join_voice_channel(101)

            # Listener listens silently for 3.0 seconds, sending ping every 0.8s
            for i in range(4):
                await asyncio.sleep(0.8)
                await listener.send_ping_probe(channel_id=101, seq=i + 1)

            # Listener should still be in sessions
            self.assertIn(listener.user_id, self.server.sessions_by_user, "Silent listener must survive past timeout")

            # Speaker enters the channel after the prolonged silent listening period and speaks
            async with SyntheticClient(username="Speaker_Surv", ws_url=self.ws_url, udp_port=self.udp_port) as speaker:
                await speaker.join_voice_channel(101)
                sent_pkt = await speaker.send_voice_frame(is_speaking=True)
                recv_pkt = await listener.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)

                self.assertEqual(recv_pkt.payload, sent_pkt.payload, "Listener must receive audio after extended silent survival")

    async def test_s3_client_disconnect_and_reconnect(self):
        """Scenario 3: Client disconnects abruptly, reconnects using session token, and resumes voice streaming."""
        client = SyntheticClient(username="ReconnectUser", ws_url=self.ws_url, udp_port=self.udp_port)
        await client.connect()
        saved_token = client.token
        saved_uid = client.user_id
        await client.join_voice_channel(101)

        # Disconnect abruptly
        await client.disconnect()
        await asyncio.sleep(0.1)

        # Reconnect with saved token
        reconnected_client = SyntheticClient(
            username="ReconnectUser",
            token=saved_token,
            ws_url=self.ws_url,
            udp_port=self.udp_port,
        )
        await reconnected_client.connect()
        self.assertEqual(reconnected_client.user_id, saved_uid, "Reconnected user must retain original User ID")

        # Rejoin voice channel and verify audio flow
        await reconnected_client.join_voice_channel(101)

        async with SyntheticClient(username="Peer_Observer", ws_url=self.ws_url, udp_port=self.udp_port) as peer:
            await peer.join_voice_channel(101)

            sent = await reconnected_client.send_voice_frame(is_speaking=True)
            recv = await peer.wait_for_voice_packet(sender_id=reconnected_client.user_id, timeout=2.0)
            self.assertEqual(recv.payload, sent.payload)

        await reconnected_client.disconnect()

    async def test_s4_multi_room_concurrent_isolation(self):
        """Scenario 4: 4 clients split across Channel 101 and Channel 102; audio is strictly isolated per channel."""
        room_a_clients = [
            SyntheticClient(username=f"RoomA_User_{i}", ws_url=self.ws_url, udp_port=self.udp_port)
            for i in range(2)
        ]
        room_b_clients = [
            SyntheticClient(username=f"RoomB_User_{i}", ws_url=self.ws_url, udp_port=self.udp_port)
            for i in range(2)
        ]
        all_clients = room_a_clients + room_b_clients

        try:
            for c in room_a_clients:
                await c.connect()
                await c.join_voice_channel(101)

            for c in room_b_clients:
                await c.connect()
                await c.join_voice_channel(102)

            # Room A speaker sends audio
            await room_a_clients[0].send_voice_frame(is_speaking=True)
            # Room B speaker sends audio
            await room_b_clients[0].send_voice_frame(is_speaking=True)

            await asyncio.sleep(0.1)

            # Room A listener should receive Room A speaker only
            self.assertEqual(room_a_clients[1].voice_packets_queue.qsize(), 1)
            pkt_a, _ = room_a_clients[1].voice_packets_queue.get_nowait()
            self.assertEqual(pkt_a.sender_id, room_a_clients[0].user_id)

            # Room B listener should receive Room B speaker only
            self.assertEqual(room_b_clients[1].voice_packets_queue.qsize(), 1)
            pkt_b, _ = room_b_clients[1].voice_packets_queue.get_nowait()
            self.assertEqual(pkt_b.sender_id, room_b_clients[0].user_id)
        finally:
            for c in all_clients:
                await c.disconnect()


if __name__ == "__main__":
    unittest.main()

