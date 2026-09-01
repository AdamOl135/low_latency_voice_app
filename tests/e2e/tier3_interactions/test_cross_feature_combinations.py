"""Tier 3 Cross-Feature Interaction Tests: Pairwise Feature Combinations.

Validates:
- Silent Listeners (F2) + Speaking Peers (F1, F5)
- Custom Dynamic UDP Port (F3) + Raw Packet Audio Stream (F5)
- Auth (F3) + Voice Join (F3) + Ping Lifecycle (F2)
- Admin Member Move (F23) + Dynamic Port + Channel Isolation
- Server Mute Gating (F24) + Silent Listener Survival (F2) + Voice Stream
"""

import asyncio
import unittest
from tests.e2e.harness.sfu_server import SFUServer
from tests.e2e.harness.synthetic_client import SyntheticClient
from tests.e2e.harness.protocol import VoicePacket, TYPE_VOICE


class TestTier3Interactions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 1.5s idle timeout, 0.1s check interval
        self.server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=1.5, scavenger_interval_sec=0.1)
        await self.server.start()
        self.ws_url = f"ws://127.0.0.1:{self.server.actual_ws_port}/ws"
        self.udp_port = self.server.actual_udp_port

    async def asyncTearDown(self):
        await self.server.stop()

    async def test_t3_01_silent_listener_with_speaking_peer(self):
        """Test T3.1: Silent listener pinging SFU receives continuous audio from speaking peer over 2.5s."""
        async with SyntheticClient(username="Speaker_1", ws_url=self.ws_url, udp_port=self.udp_port) as speaker, \
                   SyntheticClient(username="Listener_1", ws_url=self.ws_url, udp_port=self.udp_port) as listener:

            await speaker.join_voice_channel(101)
            await listener.join_voice_channel(101)

            # Speaker sends periodic audio while listener pings
            received_by_listener = 0
            for i in range(10):
                # Listener pings every 250ms
                await listener.send_ping_probe(channel_id=101, seq=i)
                # Speaker streams a frame
                await speaker.send_voice_frame(is_speaking=True)
                await asyncio.sleep(0.25)
                # Check for arrived packet on listener
                while not listener.voice_packets_queue.empty():
                    pkt, _ = listener.voice_packets_queue.get_nowait()
                    if pkt.sender_id == speaker.user_id:
                        received_by_listener += 1

            self.assertGreaterEqual(received_by_listener, 8, "Silent listener MUST continuously receive speaker packets")
            self.assertIn(listener.user_id, self.server.sessions_by_user)
            self.assertIn(speaker.user_id, self.server.sessions_by_user)

    async def test_t3_02_custom_udp_port_with_voice_stream(self):
        """Test T3.2: Dynamic non-7878 UDP port correctly advertises and carries bidirectional voice frames."""
        actual_port = self.server.actual_udp_port
        self.assertNotEqual(actual_port, 7878)

        async with SyntheticClient(username="Peer_A", ws_url=self.ws_url, udp_port=actual_port) as peer_a, \
                   SyntheticClient(username="Peer_B", ws_url=self.ws_url, udp_port=actual_port) as peer_b:

            await peer_a.join_voice_channel(101)
            await peer_b.join_voice_channel(101)

            # A sends to B
            pkt_a = await peer_a.send_voice_frame(is_speaking=True)
            recv_b = await peer_b.wait_for_voice_packet(sender_id=peer_a.user_id, timeout=2.0)
            self.assertEqual(recv_b.payload, pkt_a.payload)

            # B sends to A
            pkt_b = await peer_b.send_voice_frame(is_speaking=True)
            recv_a = await peer_a.wait_for_voice_packet(sender_id=peer_b.user_id, timeout=2.0)
            self.assertEqual(recv_a.payload, pkt_b.payload)

    async def test_t3_03_full_auth_voice_join_ping_lifecycle(self):
        """Test T3.3: Complete lifecycle: register -> auth -> list channels -> join voice -> ping -> leave."""
        async with SyntheticClient(username="LifecycleUser", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            # 1. Auth check
            res_auth = await client.send_rpc({"action": "auth", "token": client.token})
            self.assertEqual(res_auth.get("status"), "ok")

            # 2. List channels
            res_ch = await client.send_rpc({"action": "list_channels"})
            self.assertEqual(res_ch.get("status"), "ok")
            self.assertTrue(len(res_ch.get("channels", [])) >= 2)

            # 3. Join voice
            res_join = await client.join_voice_channel(101)
            self.assertEqual(res_join.get("status"), "ok")

            # 4. Send ping and verify pong
            await client.send_ping_probe(channel_id=101, seq=100)
            pong, _ = await client.wait_for_pong(timeout=2.0)
            self.assertEqual(pong.sequence, 100)

            # 5. Leave voice
            res_leave = await client.leave_voice_channel()
            self.assertEqual(res_leave.get("status"), "ok")
            self.assertNotIn(client.user_id, self.server.sessions_by_user)

    async def test_t3_04_admin_move_during_stream_channel_isolation(self):
        """Test T3.4: Admin moves speaker from Channel 101 to 102; Channel 101 listener immediately stops receiving audio."""
        async with SyntheticClient(username="Admin_Mod", ws_url=self.ws_url, udp_port=self.udp_port) as admin, \
                   SyntheticClient(username="Speaker_Ch1", ws_url=self.ws_url, udp_port=self.udp_port) as speaker, \
                   SyntheticClient(username="Listener_Ch1", ws_url=self.ws_url, udp_port=self.udp_port) as listener:

            self.assertTrue(admin.is_admin, "First registered user must be admin")
            await speaker.join_voice_channel(101)
            await listener.join_voice_channel(101)

            # Speaker sends packet in 101 -> listener gets it
            await speaker.send_voice_frame(is_speaking=True)
            await listener.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)

            # Admin moves speaker to channel 102
            res_move = await admin.send_rpc({
                "action": "move_member",
                "target_user_id": speaker.user_id,
                "to_channel_id": 102,
            })
            self.assertEqual(res_move.get("status"), "ok")

            # Speaker voice generator updates channel_id to 102
            await asyncio.sleep(0.05)
            # Drain listener queue
            while not listener.voice_packets_queue.empty():
                listener.voice_packets_queue.get_nowait()

            # Speaker sends frame in 102
            await speaker.send_voice_frame(is_speaking=True)
            await asyncio.sleep(0.1)

            # Listener in 101 should receive 0 packets from 102
            self.assertEqual(listener.voice_packets_queue.qsize(), 0, "Audio from channel 102 MUST NOT bleed into channel 101")

    async def test_t3_05_server_mute_gating_with_silent_listener(self):
        """Test T3.5: Server mute gates speaker packets while silent listener stays active."""
        async with SyntheticClient(username="Admin_Muter", ws_url=self.ws_url, udp_port=self.udp_port) as admin, \
                   SyntheticClient(username="Muted_Speaker", ws_url=self.ws_url, udp_port=self.udp_port) as speaker, \
                   SyntheticClient(username="Silent_Listener", ws_url=self.ws_url, udp_port=self.udp_port) as listener:

            await speaker.join_voice_channel(101)
            await listener.join_voice_channel(101)

            # Mute speaker
            res_mute = await admin.send_rpc({
                "action": "set_server_mute",
                "target_user_id": speaker.user_id,
                "muted": True,
            })
            self.assertEqual(res_mute.get("status"), "ok")
            await asyncio.sleep(0.05)

            # Speaker tries sending packets
            await speaker.send_voice_frame(is_speaking=True)
            await listener.send_ping_probe(channel_id=101)
            await asyncio.sleep(0.1)

            # Listener should receive no voice packets
            self.assertEqual(listener.voice_packets_queue.qsize(), 0)
            self.assertIn(listener.user_id, self.server.sessions_by_user)
            self.assertGreaterEqual(self.server.dropped_muted_count, 1)


if __name__ == "__main__":
    unittest.main()

