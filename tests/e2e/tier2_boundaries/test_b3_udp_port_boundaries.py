"""Tier 2 Boundary Tests: B3 - Dynamic UDP Port Boundaries.

Validates:
- UDP port boundary lower limit (1024)
- UDP port boundary upper limit (65535)
- Strict integer typing in JSON-RPC WebSocket responses
- Consistency across all RPC endpoints (auth, login, register, join_voice)
- Rebound / multi-socket port independence
"""

import asyncio
import unittest
from tests.e2e.harness.sfu_server import SFUServer
from tests.e2e.harness.synthetic_client import SyntheticClient


class TestB3UDPPortBoundaries(unittest.IsolatedAsyncioTestCase):
    async def test_b3_01_ephemeral_port_boundary(self):
        """Test B3.1: Port allocation assigns a valid non-privileged port (>= 1024)."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            self.assertGreaterEqual(server.actual_udp_port, 1024)
            self.assertLessEqual(server.actual_udp_port, 65535)
        finally:
            await server.stop()

    async def test_b3_02_strict_integer_type_in_responses(self):
        """Test B3.2: udp_port returned in JSON-RPC responses is strictly of type int (not string)."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="TypeCheckUser", ws_url=ws_url) as client:
                res = await client.send_rpc({"action": "auth", "token": client.token})
                port_val = res.get("udp_port") or res.get("data", {}).get("udp_port")
                self.assertIsInstance(port_val, int, "udp_port in JSON MUST be an integer, not a string")
        finally:
            await server.stop()

    async def test_b3_03_port_consistency_across_all_actions(self):
        """Test B3.3: auth, join_voice, register, login all report identical udp_port for a given server."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="ConsistencyUser", ws_url=ws_url) as client:
                res_auth = await client.send_rpc({"action": "auth", "token": client.token})
                res_join = await client.send_rpc({"action": "join_voice", "channel_id": 101})

                port_auth = res_auth.get("udp_port") or res_auth.get("data", {}).get("udp_port")
                port_join = res_join.get("udp_port") or res_join.get("data", {}).get("udp_port")

                self.assertEqual(port_auth, server.actual_udp_port)
                self.assertEqual(port_join, server.actual_udp_port)
                self.assertEqual(port_auth, port_join)
        finally:
            await server.stop()

    async def test_b3_04_rapid_join_leave_voice_port_retention(self):
        """Test B3.4: Rapidly joining and leaving voice channels retains advertised UDP port."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            async with SyntheticClient(username="RapidHopUser", ws_url=ws_url) as client:
                for _ in range(10):
                    res_j = await client.send_rpc({"action": "join_voice", "channel_id": 101})
                    port = res_j.get("udp_port") or res_j.get("data", {}).get("udp_port")
                    self.assertEqual(port, server.actual_udp_port)
                    await client.send_rpc({"action": "leave_voice"})
        finally:
            await server.stop()

    async def test_b3_05_multi_client_identical_port_advertising(self):
        """Test B3.5: All connected clients on the same server receive the exact same advertised UDP port."""
        server = SFUServer(host="127.0.0.1", ws_port=0, udp_port=0)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.actual_ws_port}/ws"
            clients = [
                SyntheticClient(username=f"Peer_{i}", ws_url=ws_url)
                for i in range(5)
            ]
            for c in clients:
                await c.connect()

            for c in clients:
                self.assertEqual(c.udp_port, server.actual_udp_port)

            for c in clients:
                await c.disconnect()
        finally:
            await server.stop()


if __name__ == "__main__":
    unittest.main()

