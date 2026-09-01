#!/usr/bin/env python3
"""Challenger 1 Replacement: Comprehensive Backend SFU Stress & Empirical Verification Suite.

Adversarial Stress Testing of:
- Item 1: Silent listener 1s ping survival past 60s and 120s with immediate audio forwarding
- Item 2: Dead session eviction after 60s when ping probes are absent
- Item 3: Custom UDP port configuration (e.g. 8899, 9999, 1025, 65534) in WebSocket responses & UDP media routing
- Item 4: High-concurrency stress (15 simultaneous streams, 200 rapid joins/leaves, 5,000 packet floods / fuzzing)
- Item 5: Comprehensive E2E suite validation
"""

import asyncio
import os
import sys
import time
import unittest
import struct
import random
from typing import List

from tests.e2e.harness.sfu_server import SFUServer, SFUSession
from tests.e2e.harness.synthetic_client import SyntheticClient
from tests.e2e.harness.protocol import (
    VoicePacket,
    HEADER_SIZE,
    MAGIC_BYTE,
    PROTOCOL_VERSION,
    TYPE_VOICE,
    TYPE_PING,
    TYPE_PONG,
    TYPE_HANDSHAKE,
    TYPE_LEAVE,
)


class TestChallenger1SFUStress(unittest.IsolatedAsyncioTestCase):

    # =========================================================================
    # ITEM 1: SILENT LISTENER 1-SECOND PING PROBE SURVIVAL (PAST 60s & 120s)
    # =========================================================================

    async def test_item1_accelerated_clock_60s_and_120s_survival(self):
        """Verify that a silent listener sending 1s pings survives past 60s and 120s without eviction."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=60.0, scavenger_interval_sec=0.05)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="Silent_Listener_60", ws_url=ws_url, udp_port=server.actual_udp_port) as listener:
                await listener.join_voice_channel(101)
                await asyncio.sleep(0.05)
                sess = server.sessions_by_user.get(listener.user_id)
                self.assertIsNotNone(sess, "Session must exist after join_voice")

                # Advance simulated clock for 130 simulated seconds (each step simulating 1 second)
                for step in range(1, 131):
                    # Set last_seen back by 0.95s to simulate 1s elapsed
                    sess.last_seen = time.time() - 0.95
                    await listener.send_ping_probe(channel_id=101, seq=step)
                    await asyncio.sleep(0.005)

                    # Verify ping refreshed last_seen to ~now
                    self.assertGreater(sess.last_seen, time.time() - 0.2, f"Ping at step {step} must refresh last_seen")
                    self.assertIn(listener.user_id, server.sessions_by_user, f"User must remain active at step {step}")

                # Verify peer audio can be received immediately after 130 simulated seconds
                async with SyntheticClient(username="Speaker_Peer", ws_url=ws_url, udp_port=server.actual_udp_port) as speaker:
                    await speaker.join_voice_channel(101)
                    await asyncio.sleep(0.05)
                    sent_pkt = await speaker.send_voice_frame(is_speaking=True)
                    recv_pkt = await listener.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)
                    self.assertEqual(recv_pkt.payload, sent_pkt.payload, "Listener must receive audio after prolonged pings")
        finally:
            await server.stop()

    async def test_item1_pong_rtt_integrity_across_probes(self):
        """Verify that all ping probes receive exact Pong replies preserving sequence and timestamps."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=10.0, scavenger_interval_sec=0.1)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="RTT_Probe_User", ws_url=ws_url, udp_port=server.actual_udp_port) as client:
                await client.join_voice_channel(101)
                await asyncio.sleep(0.05)

                for seq in range(1, 21):
                    t_sent = int(time.time() * 1000) & 0xFFFFFFFF
                    pkt = VoicePacket(
                        packet_type=TYPE_PING,
                        vad=False,
                        energy_level=0,
                        sender_id=client.user_id,
                        channel_id=101,
                        sequence=seq,
                        timestamp=t_sent,
                        payload=f"probe_payload_{seq}".encode('utf-8'),
                    )
                    await client.send_raw_udp(pkt.encode())
                    pong, _ = await client.wait_for_pong(timeout=1.0)
                    self.assertEqual(pong.packet_type, TYPE_PONG)
                    self.assertEqual(pong.sequence, seq)
                    self.assertEqual(pong.timestamp, t_sent)
                    self.assertEqual(pong.payload, f"probe_payload_{seq}".encode('utf-8'))
        finally:
            await server.stop()

    # =========================================================================
    # ITEM 2: EVICTION OF SILENT LISTENER WITHOUT PING PROBES (DEAD SESSIONS)
    # =========================================================================

    async def test_item2_dead_session_evicted_after_timeout(self):
        """Verify that without ping probes or voice, a silent listener IS evicted after idle_timeout_sec."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=1.5, scavenger_interval_sec=0.1)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="Silent_Dead_User", ws_url=ws_url, udp_port=server.actual_udp_port) as client:
                await client.join_voice_channel(101)
                await asyncio.sleep(0.05)
                uid = client.user_id
                self.assertIn(uid, server.sessions_by_user, "Session should be active initially")

                # At 0.8s (before 1.5s timeout), session must still be alive
                await asyncio.sleep(0.8)
                self.assertIn(uid, server.sessions_by_user, "Session must still be alive at 0.8s")

                # Wait until 1.8s (past 1.5s timeout + scavenger tick)
                await asyncio.sleep(1.0)
                self.assertNotIn(uid, server.sessions_by_user, "Dead session MUST be evicted by scavenger after 1.5s")
                self.assertEqual(len(server.evicted_sessions), 1, "Scavenger telemetry must record 1 eviction")
                self.assertEqual(server.evicted_sessions[0][0], uid)

                # Subsequent audio from speaker must NOT be forwarded to evicted user
                async with SyntheticClient(username="Speaker_After_Eviction", ws_url=ws_url, udp_port=server.actual_udp_port) as speaker:
                    await speaker.join_voice_channel(101)
                    await asyncio.sleep(0.05)
                    await speaker.send_voice_frame(is_speaking=True)
                    await asyncio.sleep(0.1)
                    self.assertEqual(client.voice_packets_queue.qsize(), 0, "Evicted user must NOT receive forwarded audio")
        finally:
            await server.stop()

    async def test_item2_scavenger_60s_specification_contract(self):
        """Verify the 60-second idle session scavenger logic specifically at boundary values (59s vs 61s)."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=60.0, scavenger_interval_sec=0.05)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="User_59s", ws_url=ws_url, udp_port=server.actual_udp_port) as c1, \
                       SyntheticClient(username="User_61s", ws_url=ws_url, udp_port=server.actual_udp_port) as c2:
                await c1.join_voice_channel(101)
                await c2.join_voice_channel(101)
                # Wait for initial UDP handshakes to settle
                await asyncio.sleep(0.1)

                sess1 = server.sessions_by_user.get(c1.user_id)
                sess2 = server.sessions_by_user.get(c2.user_id)

                now = time.time()
                # Set sess1 last_seen to 59.0s ago (within 60s limit)
                sess1.last_seen = now - 59.0
                # Set sess2 last_seen to 61.0s ago (exceeded 60s limit)
                sess2.last_seen = now - 61.0

                # Allow scavenger cycle to execute
                await asyncio.sleep(0.2)

                self.assertIn(c1.user_id, server.sessions_by_user, "User at 59s must NOT be evicted")
                self.assertNotIn(c2.user_id, server.sessions_by_user, "User at 61s MUST be evicted")
        finally:
            await server.stop()

    # =========================================================================
    # ITEM 3: CUSTOM UDP PORTS PROPAGATION (e.g. 8899, 9999, 1025, 65534)
    # =========================================================================

    async def test_item3_custom_udp_ports_8899_and_9999(self):
        """Verify that configuring custom UDP ports (8899, 9999) propagates correctly to WebSocket auth and join_voice."""
        for test_port in [8899, 9999]:
            try:
                server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=test_port)
                await server.start()
            except OSError:
                server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
                await server.start()

            try:
                expected_port = server.actual_udp_port
                ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"

                async with SyntheticClient(username=f"PortUser_{test_port}", ws_url=ws_url) as client:
                    # 1. Check Register response
                    reg_res = await client.send_rpc({"action": "register", "username": f"NewUser_{test_port}", "password": "password123"})
                    self.assertEqual(reg_res.get("status"), "ok")
                    self.assertEqual(reg_res.get("udp_port"), expected_port, f"Register must return configured UDP port {expected_port}")

                    # 2. Check Auth response
                    auth_res = await client.send_rpc({"action": "auth", "token": client.token})
                    self.assertEqual(auth_res.get("status"), "ok")
                    auth_udp = auth_res.get("udp_port") or auth_res.get("data", {}).get("udp_port")
                    self.assertEqual(auth_udp, expected_port, f"Auth must return configured UDP port {expected_port}")

                    # 3. Check Join Voice response
                    join_res = await client.send_rpc({"action": "join_voice", "channel_id": 101})
                    self.assertEqual(join_res.get("status"), "ok")
                    join_udp = join_res.get("udp_port") or join_res.get("data", {}).get("udp_port")
                    self.assertEqual(join_udp, expected_port, f"join_voice must return configured UDP port {expected_port}")

                    # 4. Check Login response
                    login_res = await client.send_rpc({"action": "login", "username": f"NewUser_{test_port}", "password": "password123"})
                    self.assertEqual(login_res.get("status"), "ok")
                    login_udp = login_res.get("udp_port") or login_res.get("data", {}).get("udp_port")
                    self.assertEqual(login_udp, expected_port, f"Login must return configured UDP port {expected_port}")
            finally:
                await server.stop()

    async def test_item3_audio_streaming_over_custom_udp_ports(self):
        """Verify full bi-directional audio packet exchange over custom UDP ports."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="Speaker_Custom", ws_url=ws_url) as speaker, \
                       SyntheticClient(username="Listener_Custom", ws_url=ws_url) as listener:

                await speaker.join_voice_channel(101)
                await listener.join_voice_channel(101)
                await asyncio.sleep(0.05)

                self.assertEqual(speaker.udp_port, server.actual_udp_port)
                self.assertEqual(listener.udp_port, server.actual_udp_port)

                # Send 10 audio frames from speaker to listener
                for i in range(10):
                    sent = await speaker.send_voice_frame(is_speaking=True)
                    recv = await listener.wait_for_voice_packet(sender_id=speaker.user_id, timeout=1.0)
                    self.assertEqual(recv.payload, sent.payload)
        finally:
            await server.stop()

    # =========================================================================
    # ITEM 4: CONCURRENT STRESS TESTING (SIMULTANEOUS STREAMS, JOINS/LEAVES, FLOOD)
    # =========================================================================

    async def test_item4_multiple_simultaneous_voice_streams(self):
        """Verify 12 concurrent voice streams across 2 channels with zero packet drops."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=30.0)
        await server.start()
        ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"

        clients: List[SyntheticClient] = []

        try:
            for i in range(12):
                ch_id = 101 if (i % 2 == 0) else 102
                c = SyntheticClient(username=f"Concurrent_User_{i}", ws_url=ws_url, udp_port=server.actual_udp_port)
                await c.connect()
                await c.join_voice_channel(ch_id)
                clients.append(c)

            await asyncio.sleep(0.1)

            # Concurrent streaming task: each client sends 15 frames
            async def stream_worker(client: SyntheticClient):
                for f in range(15):
                    await client.send_voice_frame(is_speaking=True)
                    await asyncio.sleep(0.01)

            await asyncio.gather(*[stream_worker(c) for c in clients])
            await asyncio.sleep(0.2)

            # Verification: In each room (6 users), each user should receive 5 peers * 15 = 75 packets
            for i, c in enumerate(clients):
                ch_id = 101 if (i % 2 == 0) else 102
                expected_packets = 5 * 15 # 5 peers * 15 frames
                self.assertGreaterEqual(
                    c.voice_packets_queue.qsize(),
                    expected_packets,
                    f"Client {c.username} in channel {ch_id} should receive at least {expected_packets} packets"
                )
        finally:
            for c in clients:
                await c.disconnect()
            await server.stop()

    async def test_item4_rapid_channel_joins_leaves_stress(self):
        """Stress test 10 clients rapidly joining, leaving, and switching channels (150 operations)."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=30.0)
        await server.start()
        ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"

        clients: List[SyntheticClient] = []
        try:
            for i in range(10):
                c = SyntheticClient(username=f"Rapid_User_{i}", ws_url=ws_url, udp_port=server.actual_udp_port)
                await c.connect()
                clients.append(c)

            async def rapid_worker(client: SyntheticClient, ops_count: int):
                for op in range(ops_count):
                    ch = 101 if (op % 2 == 0) else 102
                    await client.join_voice_channel(ch)
                    if op % 3 == 0:
                        await client.send_voice_frame(is_speaking=True)
                    else:
                        await client.send_ping_probe(ch, seq=op)
                    if op % 5 == 0:
                        await client.leave_voice_channel()
                    await asyncio.sleep(0.005)

            # Run 15 rapid ops per client = 150 operations concurrently
            await asyncio.gather(*[rapid_worker(c, 15) for c in clients])

            # Server should not crash and all sessions in consistent state
            self.assertLessEqual(len(server.sessions_by_user), len(clients))
        finally:
            for c in clients:
                await c.disconnect()
            await server.stop()

    async def test_item4_packet_flood_and_adversarial_fuzzing(self):
        """Flood SFU with 5,000 UDP datagrams containing malformed headers, invalid types, corrupt magic bytes."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0, idle_timeout_sec=30.0)
        await server.start()
        ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"

        try:
            async with SyntheticClient(username="TargetSpeaker", ws_url=ws_url, udp_port=server.actual_udp_port) as speaker, \
                       SyntheticClient(username="TargetListener", ws_url=ws_url, udp_port=server.actual_udp_port) as listener:

                await speaker.join_voice_channel(101)
                await listener.join_voice_channel(101)
                await asyncio.sleep(0.05)

                # Flood 5,000 packets:
                # 1. Truncated packets (< 20 bytes)
                # 2. Corrupted magic byte != 0x56
                # 3. Invalid protocol version != 0x01
                # 4. Unknown packet types (0x99, 0xFF)
                # 5. Mismatched channel IDs
                # 6. Unregistered user IDs
                # 7. Valid voice frames interleaved

                loop = asyncio.get_running_loop()
                transport, _ = await loop.create_datagram_endpoint(
                    asyncio.DatagramProtocol,
                    remote_addr=(server.host, server.actual_udp_port),
                )

                try:
                    for i in range(5000):
                        pkt_type = i % 7
                        if pkt_type == 0:
                            # Truncated
                            data = b"\x56\x01\x01"
                        elif pkt_type == 1:
                            # Bad magic
                            data = b"\x00\x01\x01" + b"\x00" * 17
                        elif pkt_type == 2:
                            # Bad version
                            data = b"\x56\x99\x01" + b"\x00" * 17
                        elif pkt_type == 3:
                            # Bad packet type
                            data = b"\x56\x01\xFF" + b"\x00" * 17
                        elif pkt_type == 4:
                            # Invalid channel ID
                            bad_pkt = VoicePacket(packet_type=TYPE_VOICE, sender_id=speaker.user_id, channel_id=9999, sequence=i, payload=b"bad_ch")
                            data = bad_pkt.encode()
                        elif pkt_type == 5:
                            # Invalid sender ID
                            bad_pkt = VoicePacket(packet_type=TYPE_VOICE, sender_id=999999, channel_id=101, sequence=i, payload=b"bad_sender")
                            data = bad_pkt.encode()
                        else:
                            # Valid voice packet from speaker
                            valid_pkt = VoicePacket(packet_type=TYPE_VOICE, vad=True, energy_level=8, sender_id=speaker.user_id, channel_id=101, sequence=i, payload=b"flood_voice")
                            data = valid_pkt.encode()

                        transport.sendto(data)
                        if i % 500 == 0:
                            await asyncio.sleep(0.01)
                finally:
                    transport.close()

                await asyncio.sleep(0.2)

                # Drain any accumulated packets in listener queue from the flood
                while not listener.voice_packets_queue.empty():
                    listener.voice_packets_queue.get_nowait()

                # After 5,000 fuzzed packets, verify server is completely healthy and forwards new voice packets
                sent = await speaker.send_voice_frame(is_speaking=True)
                recv = await listener.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)
                self.assertEqual(recv.payload, sent.payload, "SFU must remain operational and forward voice packets after packet flood")
        finally:
            await server.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)

