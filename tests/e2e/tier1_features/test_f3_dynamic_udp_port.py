"""Tier 1 Feature Tests: F3 - Backend Dynamic UDP Port in WS Responses.

Validates:
- handleAuth and handleJoinVoice return the dynamically configured UDP port, not hardcoded 7878
- Clients receive and bind to the advertised UDP port
- Voice media packets stream correctly over custom/non-default UDP ports
- Register and login RPCs return the dynamic UDP port
- Multiple servers on distinct UDP ports isolate traffic cleanly
"""

import asyncio
import unittest
from tests.e2e.harness.sfu_server import SFUServer
from tests.e2e.harness.synthetic_client import SyntheticClient


class TestF3DynamicUDPPort(unittest.IsolatedAsyncioTestCase):
    async def test_f3_01_auth_returns_configured_udp_port(self):
        """Test F3.1: Auth response returns configured UDP port dynamically."""
        # Start server with dynamic port allocation (port 0)
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="AuthUser", ws_url=ws_url) as client:
                res = await client.send_rpc({"action": "auth", "token": client.token})
                self.assertEqual(res.get("status"), "ok")
                # Check top-level or data.udp_port
                returned_port = res.get("udp_port") or res.get("data", {}).get("udp_port")
                self.assertEqual(
                    returned_port,
                    server.actual_udp_port,
                    f"Auth response MUST return actual configured UDP port ({server.actual_udp_port}), not hardcoded 7878"
                )
        finally:
            await server.stop()

    async def test_f3_02_join_voice_returns_configured_udp_port(self):
        """Test F3.2: JoinVoice response returns configured UDP port dynamically."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="VoiceJoinUser", ws_url=ws_url) as client:
                res = await client.send_rpc({"action": "join_voice", "channel_id": 101})
                self.assertEqual(res.get("status"), "ok")
                returned_port = res.get("udp_port") or res.get("data", {}).get("udp_port")
                self.assertEqual(
                    returned_port,
                    server.actual_udp_port,
                    f"join_voice response MUST return configured UDP port ({server.actual_udp_port})"
                )
        finally:
            await server.stop()

    async def test_f3_03_non_default_custom_udp_port(self):
        """Test F3.3: Server configured on non-default UDP port advertises that exact port."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            actual_port = server.actual_udp_port
            self.assertNotEqual(actual_port, 7878, "Dynamic port allocation should assign a non-7878 port")
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"

            async with SyntheticClient(username="CustomPortUser", ws_url=ws_url) as client:
                self.assertEqual(client.udp_port, actual_port)
        finally:
            await server.stop()

    async def test_f3_04_client_streams_to_dynamic_udp_port(self):
        """Test F3.4: Clients stream audio and receive packets over dynamically assigned UDP port."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="Speaker_Dyn", ws_url=ws_url) as speaker, \
                       SyntheticClient(username="Listener_Dyn", ws_url=ws_url) as listener:

                await speaker.join_voice_channel(101)
                await listener.join_voice_channel(101)

                self.assertEqual(speaker.udp_port, server.actual_udp_port)
                self.assertEqual(listener.udp_port, server.actual_udp_port)

                # Send voice packet from speaker
                sent_pkt = await speaker.send_voice_frame(is_speaking=True)
                recv_pkt = await listener.wait_for_voice_packet(sender_id=speaker.user_id, timeout=2.0)

                self.assertEqual(recv_pkt.sender_id, speaker.user_id)
                self.assertEqual(recv_pkt.payload, sent_pkt.payload)
        finally:
            await server.stop()

    async def test_f3_05_register_and_login_return_dynamic_udp_port(self):
        """Test F3.5: Register and Login RPC responses include configured UDP port."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="RegUser", ws_url=ws_url) as client:
                res_reg = await client.send_rpc({"action": "register", "username": "UniqueRegUser_1", "password": "pwd"})
                self.assertEqual(res_reg.get("status"), "ok")
                self.assertEqual(res_reg.get("udp_port"), server.actual_udp_port)

                res_login = await client.send_rpc({"action": "login", "username": "UniqueRegUser_1", "password": "pwd"})
                self.assertEqual(res_login.get("status"), "ok")
                self.assertEqual(res_login.get("udp_port"), server.actual_udp_port)
        finally:
            await server.stop()

    async def test_f3_06_two_servers_distinct_udp_ports(self):
        """Test F3.6: Two independent servers allocate distinct UDP ports without collision."""
        s1 = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        s2 = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await s1.start()
        await s2.start()
        try:
            self.assertNotEqual(s1.actual_udp_port, s2.actual_udp_port)
            ws_url_1 = f"ws://127.0.0.1:{s1.actual_ws_port}/ws"
            ws_url_2 = f"ws://127.0.0.1:{s2.actual_ws_port}/ws"

            async with SyntheticClient(username="Client1", ws_url=ws_url_1) as c1, \
                       SyntheticClient(username="Client2", ws_url=ws_url_2) as c2:
                self.assertEqual(c1.udp_port, s1.actual_udp_port)
                self.assertEqual(c2.udp_port, s2.actual_udp_port)
        finally:
            await s1.stop()
            await s2.stop()


if __name__ == "__main__":
    unittest.main()

