#!/usr/bin/env python3
"""Challenger 1 Replacement: Real-Time Wall-Clock 65-Second Silent Listener & Dead Session Test.

Executes real-time, wall-clock tests:
1. Real-Time 65s Silent Listener: Sends 1s ping probes every 1.0s for 65 seconds against a 60.0s idle timeout SFU.
   Verifies user is alive at t=65s and immediately receives audio from speaker.
2. Real-Time 62s Dead Session Eviction: Silent user sends NO pings for 62 seconds against a 60.0s idle timeout SFU.
   Verifies user is evicted at t=62s and receives 0 audio packets from speaker.
"""

import asyncio
import time
import unittest
from tests.e2e.harness.sfu_server import SFUServer
from tests.e2e.harness.synthetic_client import SyntheticClient


class TestRealTimeSurvivalAndEviction(unittest.IsolatedAsyncioTestCase):

    async def test_realtime_65s_silent_listener_with_pings(self):
        """Real-time wall-clock test: 1s pings over 65 seconds prevent eviction on a 60s scavenger SFU."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=60.0, scavenger_interval_sec=1.0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="WallClock_Silent_Listener", ws_url=ws_url, udp_port=server.actual_udp_port) as listener:
                await listener.join_voice_channel(101)
                await asyncio.sleep(0.1)

                print("\n[Real-Time 65s Test] Starting 65-second wall clock ping test...")
                start_time = time.time()
                for i in range(65):
                    await asyncio.sleep(1.0)
                    await listener.send_ping_probe(channel_id=101, seq=i + 1)
                    if (i + 1) % 15 == 0 or (i + 1) == 65:
                        elapsed = time.time() - start_time
                        print(f"  [Real-Time 65s Test] Elapsed: {elapsed:.1f}s, Pings sent: {i+1}, User active: {listener.user_id in server.sessions_by_user}")

                elapsed_total = time.time() - start_time
                self.assertGreaterEqual(elapsed_total, 64.0, "Must have run for at least 64 real seconds")
                self.assertIn(listener.user_id, server.sessions_by_user, "Listener MUST survive past 60s idle timeout with 1s pings")

                # Verify immediate audio reception from speaker at second 65
                async with SyntheticClient(username="WallClock_Speaker", ws_url=ws_url, udp_port=server.actual_udp_port) as speaker:
                    await speaker.join_voice_channel(101)
                    await asyncio.sleep(0.1)
                    sent = await speaker.send_voice_frame(is_speaking=True)
                    recv = await listener.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)
                    self.assertEqual(recv.payload, sent.payload, "Listener must receive forwarded audio at 65s")
                print("[Real-Time 65s Test] SUCCESS: Listener survived 65s and received audio packet.")
        finally:
            await server.stop()

    async def test_realtime_62s_dead_session_eviction_without_pings(self):
        """Real-time wall-clock test: Silent user without pings is evicted at 62s on a 60s scavenger SFU."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=60.0, scavenger_interval_sec=1.0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="WallClock_Dead_User", ws_url=ws_url, udp_port=server.actual_udp_port) as dead_user:
                await dead_user.join_voice_channel(101)
                await asyncio.sleep(0.1)
                uid = dead_user.user_id
                self.assertIn(uid, server.sessions_by_user, "User should be active initially")

                print("\n[Real-Time 62s Eviction Test] Starting 62-second dead session eviction test...")
                start_time = time.time()
                for i in range(62):
                    await asyncio.sleep(1.0)
                    if (i + 1) % 15 == 0 or (i + 1) == 62:
                        elapsed = time.time() - start_time
                        print(f"  [Real-Time 62s Eviction Test] Elapsed: {elapsed:.1f}s, User active: {uid in server.sessions_by_user}")

                elapsed_total = time.time() - start_time
                self.assertGreaterEqual(elapsed_total, 61.0, "Must have run for at least 61 real seconds")
                self.assertNotIn(uid, server.sessions_by_user, "Dead user MUST be evicted after 60s idle timeout")
                self.assertEqual(len(server.evicted_sessions), 1, "Eviction must be recorded in telemetry")

                # Verify speaker audio is NOT received by dead user
                async with SyntheticClient(username="Speaker_Peer_Evict", ws_url=ws_url, udp_port=server.actual_udp_port) as speaker:
                    await speaker.join_voice_channel(101)
                    await asyncio.sleep(0.1)
                    await speaker.send_voice_frame(is_speaking=True)
                    await asyncio.sleep(0.2)
                    self.assertEqual(dead_user.voice_packets_queue.qsize(), 0, "Evicted user must NOT receive audio")
                print("[Real-Time 62s Eviction Test] SUCCESS: Dead user was evicted and received zero audio packets.")
        finally:
            await server.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)

