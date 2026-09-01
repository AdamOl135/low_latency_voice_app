"""Tier 1 Feature Tests: F2 - Backend UDP Session Scavenger LastSeen Touch.

Validates:
- handlePing refreshes session.LastSeen on every ping datagram
- Silent listeners sending 1-second pings survive beyond scavenger idle timeout
- Idle sessions without pings or voice are evicted
- Packets from evicted sessions are dropped
- Active speakers continuously touch LastSeen via voice packets
- Ping probe receives immediate Pong response preserving timestamp and payload
"""

import asyncio
import time
import unittest
from tests.e2e.harness.sfu_server import SFUServer
from tests.e2e.harness.synthetic_client import SyntheticClient
from tests.e2e.harness.protocol import TYPE_PING, TYPE_PONG, TYPE_VOICE, VoicePacket


class TestF2SessionScavenger(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Configure fast scavenger for tests: 1.0s idle timeout, 0.1s check interval
        self.server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=1.0, scavenger_interval_sec=0.1)
        await self.server.start()
        self.ws_url = f"ws://127.0.0.1:{self.server.actual_ws_port}/ws"
        self.udp_port = self.server.actual_udp_port

    async def asyncTearDown(self):
        await self.server.stop()

    async def test_f2_01_handle_ping_updates_last_seen(self):
        """Test F2.1: Sending TypePing updates the session's LastSeen timestamp."""
        async with SyntheticClient(username="User_Ping", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)
            sess = self.server.sessions_by_user.get(client.user_id)
            self.assertIsNotNone(sess)

            t0 = sess.last_seen
            await asyncio.sleep(0.2)

            await client.send_ping_probe(channel_id=101, seq=1)
            await asyncio.sleep(0.05)

            t1 = sess.last_seen
            self.assertGreater(t1, t0, "handlePing MUST update session.LastSeen")

    async def test_f2_02_silent_listener_not_evicted_with_pings(self):
        """Test F2.2: Silent listener sending regular pings is NOT evicted by 1.0s scavenger over 2.5s."""
        async with SyntheticClient(username="Silent_Listener", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)
            uid = client.user_id

            # Keep alive with periodic pings every 0.3s for 2.5s (exceeding 1.0s timeout)
            for i in range(8):
                await asyncio.sleep(0.3)
                await client.send_ping_probe(channel_id=101, seq=i + 1)

            self.assertIn(uid, self.server.sessions_by_user, "Silent listener sending pings MUST remain active in SFU")
            self.assertEqual(len(self.server.evicted_sessions), 0, "No eviction should have occurred for active pinger")

    async def test_f2_03_idle_session_without_pings_is_evicted(self):
        """Test F2.3: Idle user who sends no voice and no pings gets evicted after idle timeout."""
        async with SyntheticClient(username="Idle_User", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)
            uid = client.user_id

            self.assertIn(uid, self.server.sessions_by_user)
            # Sleep past the 1.0s timeout + scavenger interval
            await asyncio.sleep(1.3)

            self.assertNotIn(uid, self.server.sessions_by_user, "Idle session must be evicted by scavenger")
            evicted_uids = [u for u, _ in self.server.evicted_sessions]
            self.assertIn(uid, evicted_uids, "Evicted user ID must be recorded in scavenger telemetry")

    async def test_f2_04_evicted_user_audio_dropped(self):
        """Test F2.4: When an evicted user tries to send audio, SFU drops the packet."""
        async with SyntheticClient(username="Listener", ws_url=self.ws_url, udp_port=self.udp_port) as listener:
            await listener.join_voice_channel(101)

            async with SyntheticClient(username="Speaker_Evicted", ws_url=self.ws_url, udp_port=self.udp_port) as speaker:
                await speaker.join_voice_channel(101)
                spk_uid = speaker.user_id

                # Keep listener alive with pings
                # Wait for speaker to be evicted (1.3s)
                for _ in range(4):
                    await listener.send_ping_probe(101)
                    await asyncio.sleep(0.35)

                self.assertNotIn(spk_uid, self.server.sessions_by_user, "Speaker should be evicted")
                self.assertIn(listener.user_id, self.server.sessions_by_user, "Listener should stay alive")

                # Speaker tries sending voice packet after eviction
                await speaker.send_voice_frame(is_speaking=True)
                await asyncio.sleep(0.1)

                # Listener should NOT receive the packet
                self.assertEqual(listener.voice_packets_queue.qsize(), 0, "Evicted user voice must NOT be forwarded to peers")

    async def test_f2_05_active_speaker_touches_last_seen(self):
        """Test F2.5: Active voice stream touches LastSeen and prevents eviction."""
        async with SyntheticClient(username="Active_Speaker", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)
            uid = client.user_id

            # Stream audio frames continuously for 2.0s without manual pings
            await client.stream_audio(duration_sec=2.0, frame_ms=20, is_speaking=True)

            self.assertIn(uid, self.server.sessions_by_user, "Active speaker must not be evicted")

    async def test_f2_06_ping_probe_receives_pong_with_same_timestamp(self):
        """Test F2.6: Ping probe receives immediate Pong preserving sequence and timestamp."""
        async with SyntheticClient(username="Probe_User", ws_url=self.ws_url, udp_port=self.udp_port) as client:
            await client.join_voice_channel(101)
            req_seq = 4200
            t_probe = int(time.time() * 1000) & 0xFFFFFFFF

            pkt = VoicePacket(
                packet_type=TYPE_PING,
                vad=False,
                energy_level=0,
                sender_id=client.user_id,
                channel_id=101,
                sequence=req_seq,
                timestamp=t_probe,
                payload=b'probe_telemetry',
            )
            await client.send_raw_udp(pkt.encode())

            pong_pkt, recv_time = await client.wait_for_pong(timeout=2.0)
            self.assertEqual(pong_pkt.packet_type, TYPE_PONG)
            self.assertEqual(pong_pkt.sequence, req_seq)
            self.assertEqual(pong_pkt.timestamp, t_probe)
            self.assertEqual(pong_pkt.payload, b'probe_telemetry')


if __name__ == "__main__":
    unittest.main()

