"""Synthetic Asynchronous Client for Low-Latency Voice App E2E Tests."""

import asyncio
import json
import socket
import struct
import time
from typing import Dict, Any, List, Optional, Callable, Tuple
from tests.e2e.harness.protocol import (
    VoicePacket,
    TYPE_VOICE,
    TYPE_PING,
    TYPE_PONG,
    TYPE_HANDSHAKE,
    TYPE_LEAVE,
)
from tests.e2e.harness.audio_generator import AudioGenerator
from tests.e2e.harness.simple_ws import connect_ws, WebSocketConnection, WebSocketClosed


class SyntheticClient:
    """Headless client simulating full desktop application functionality."""

    def __init__(
        self,
        username: str = "TestUser",
        password: str = "password123",
        token: Optional[str] = None,
        ws_url: str = "ws://127.0.0.1:8085/ws",
        udp_host: str = "127.0.0.1",
        udp_port: int = 7878,
    ):
        self.username = username
        self.password = password
        self.token = token
        self.ws_url = ws_url
        self.udp_host = udp_host
        self.udp_port = udp_port

        # State
        self.user_id: Optional[int] = None
        self.is_admin: bool = False
        self.roles: List[str] = []
        self.current_channel_id: Optional[int] = None
        self.udp_token: Optional[str] = None
        self.is_server_muted: bool = False
        self.is_server_deafened: bool = False
        self.is_connected: bool = False
        self.is_voice_active: bool = False
        self.close_code: Optional[int] = None

        # Networking
        self.ws: Optional[WebSocketConnection] = None
        self.udp_sock: Optional[socket.socket] = None
        self.audio_gen: Optional[AudioGenerator] = None

        # Background loops
        self._ws_task: Optional[asyncio.Task] = None
        self._udp_task: Optional[asyncio.Task] = None
        self._running = False

        # Event Queues
        self.events_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.voice_packets_queue: asyncio.Queue[Tuple[VoicePacket, float]] = asyncio.Queue()
        self.pong_packets_queue: asyncio.Queue[Tuple[VoicePacket, float]] = asyncio.Queue()
        self.received_events: List[Dict[str, Any]] = []
        self.received_voice_packets: List[Tuple[VoicePacket, float]] = []

        # Metrics
        self.packets_sent = 0
        self.packets_received = 0
        self.bytes_sent = 0
        self.bytes_received = 0

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self, timeout: float = 5.0):
        """Establish WebSocket connection, authenticate/register, and bind UDP socket."""
        self._running = True
        self.ws = await connect_ws(self.ws_url, timeout=timeout)
        self.is_connected = True
        self._ws_task = asyncio.create_task(self._ws_loop())

        # Perform Login/Register or Auth
        if self.token:
            auth_res = await self.send_rpc({"action": "auth", "token": self.token, "client_version": "1.0.0"})
        else:
            auth_res = await self.send_rpc({
                "action": "login",
                "username": self.username,
                "password": self.password,
                "client_version": "1.0.0",
            })
            if auth_res.get("status") != "ok":
                # Register if user does not exist
                auth_res = await self.send_rpc({
                    "action": "register",
                    "username": self.username,
                    "password": self.password,
                    "client_version": "1.0.0",
                })

        if auth_res.get("status") == "ok":
            self.user_id = auth_res.get("user_id") or auth_res.get("data", {}).get("user_id")
            self.is_admin = auth_res.get("is_admin", False)
            self.roles = auth_res.get("roles", [])
            self.token = auth_res.get("token") or auth_res.get("data", {}).get("token", self.token)
            # Store advertised UDP port if returned
            if "udp_port" in auth_res:
                self.udp_port = auth_res["udp_port"]
            elif "data" in auth_res and "udp_port" in auth_res["data"]:
                self.udp_port = auth_res["data"]["udp_port"]
        else:
            await self.disconnect()
            raise RuntimeError(f"Authentication failed for {self.username}: {auth_res}")

        # Setup local UDP socket
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setblocking(False)
        self._udp_task = asyncio.create_task(self._udp_loop())

    async def disconnect(self):
        """Close client sessions cleanly."""
        self._running = False
        self.is_connected = False
        self.is_voice_active = False

        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        if self._udp_task and not self._udp_task.done():
            self._udp_task.cancel()

        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

        if self.udp_sock:
            try:
                self.udp_sock.close()
            except Exception:
                pass
            self.udp_sock = None

    async def send_rpc(self, payload: Dict[str, Any], timeout: float = 3.0) -> Dict[str, Any]:
        """Send JSON-RPC request and wait for matching response."""
        if not self.ws or not self.is_connected:
            raise RuntimeError("WebSocket is not connected")

        req_id = payload.get("id", f"req_{int(time.time()*1000)}_{self.user_id or 0}")
        payload["id"] = req_id

        await self.ws.send(json.dumps(payload))

        start = time.monotonic()
        while time.monotonic() - start < timeout:
            for item in reversed(self.received_events):
                if item.get("reply_to") == req_id or item.get("id") == req_id:
                    return item
            await asyncio.sleep(0.01)

        # Fallback to last event if response matched
        if self.received_events and "status" in self.received_events[-1]:
            return self.received_events[-1]

        return {"status": "timeout", "error": "RPC response timed out"}

    async def _ws_loop(self):
        """Background listener for WebSocket messages."""
        try:
            while self._running and self.ws and not self.ws.closed:
                msg_str = await self.ws.recv()
                if isinstance(msg_str, bytes):
                    msg_str = msg_str.decode('utf-8')
                data = json.loads(msg_str)
                self.received_events.append(data)
                await self.events_queue.put(data)

                # State sync updates
                if data.get("event") == "voice_state_update" and data.get("user_id") == self.user_id:
                    if "server_muted" in data:
                        self.is_server_muted = data["server_muted"]
                    if "server_deafened" in data:
                        self.is_server_deafened = data["server_deafened"]
                elif data.get("event") == "member_moved" and data.get("user_id") == self.user_id:
                    self.current_channel_id = data.get("to_channel_id")
                    if self.audio_gen:
                        self.audio_gen.channel_id = self.current_channel_id
                elif data.get("event") == "member_kicked" and data.get("user_id") == self.user_id:
                    self.is_connected = False
                    self.is_voice_active = False

        except WebSocketClosed as e:
            self.is_connected = False
            self.close_code = e.code
        except (asyncio.CancelledError, Exception):
            self.is_connected = False

    async def _udp_loop(self):
        """Background listener for UDP audio packets."""
        loop = asyncio.get_running_loop()
        while self._running and self.udp_sock:
            try:
                data = await loop.sock_recv(self.udp_sock, 4096)
                arr_time = time.time()
                self.bytes_received += len(data)
                self.packets_received += 1

                pkt = VoicePacket.decode(data)
                if pkt.packet_type == TYPE_VOICE:
                    self.received_voice_packets.append((pkt, arr_time))
                    await self.voice_packets_queue.put((pkt, arr_time))
                elif pkt.packet_type == TYPE_PONG:
                    await self.pong_packets_queue.put((pkt, arr_time))

            except (BlockingIOError, socket.error):
                await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.005)

    async def join_voice_channel(self, channel_id: int) -> Dict[str, Any]:
        """Join voice channel, parse dynamic UDP port, and send UDP handshake."""
        self.current_channel_id = channel_id
        res = await self.send_rpc({"action": "join_voice", "channel_id": channel_id})
        if res.get("status") == "ok":
            data = res.get("data", res)
            self.udp_token = data.get("udp_token")
            # Dynamic UDP port validation (F3)
            self.udp_port = data.get("udp_port", self.udp_port)
            self.audio_gen = AudioGenerator(
                sender_id=self.user_id or 1,
                channel_id=channel_id,
                frame_duration_ms=20,
            )
            # Send Handshake
            await self.send_udp_handshake()
            self.is_voice_active = True
        return res

    async def leave_voice_channel(self) -> Dict[str, Any]:
        """Leave voice channel."""
        res = await self.send_rpc({"action": "leave_voice", "channel_id": self.current_channel_id})
        self.current_channel_id = None
        self.is_voice_active = False
        return res

    async def send_udp_handshake(self):
        """Send Handshake packet (0x04) to register UDP endpoint."""
        if not self.udp_sock or self.user_id is None or self.current_channel_id is None:
            return
        token_payload = (self.udp_token or f"token_{self.user_id}").encode('utf-8')
        pkt = VoicePacket(
            packet_type=TYPE_HANDSHAKE,
            vad=False,
            energy_level=0,
            sender_id=self.user_id,
            channel_id=self.current_channel_id,
            sequence=0,
            timestamp=0,
            payload=token_payload,
        )
        await self.send_raw_udp(pkt.encode())

    async def send_raw_udp(self, data: bytes):
        """Send raw UDP datagram directly to SFU."""
        if not self.udp_sock:
            return
        loop = asyncio.get_running_loop()
        await loop.sock_sendto(self.udp_sock, data, (self.udp_host, self.udp_port))
        self.packets_sent += 1
        self.bytes_sent += len(data)

    async def send_voice_frame(
        self,
        is_speaking: bool = True,
        energy_level: Optional[int] = None,
        payload_size: int = 80,
    ) -> VoicePacket:
        """Send a single voice frame."""
        if not self.audio_gen:
            raise RuntimeError("Audio generator not initialized. Join voice channel first.")
        pkt = self.audio_gen.next_voice_packet(
            is_speaking=is_speaking,
            energy_level=energy_level,
            payload_size=payload_size,
        )
        await self.send_raw_udp(pkt.encode())
        return pkt

    async def stream_audio(
        self,
        duration_sec: float = 1.0,
        frame_ms: int = 20,
        is_speaking: bool = True,
    ) -> int:
        """Stream continuous audio frames."""
        count = int((duration_sec * 1000) / frame_ms)
        interval = frame_ms / 1000.0
        for _ in range(count):
            t0 = time.perf_counter()
            await self.send_voice_frame(is_speaking=is_speaking)
            spent = time.perf_counter() - t0
            sleep_t = max(0.0, interval - spent)
            if sleep_t > 0:
                await asyncio.sleep(sleep_t)
        return count

    async def send_ping_probe(self, channel_id: Optional[int] = None, seq: int = 1) -> VoicePacket:
        """Send Type 0x02 Ping probe to SFU."""
        ch_id = channel_id or self.current_channel_id or 101
        now_ts = int(time.time() * 1000) & 0xFFFFFFFF
        pkt = VoicePacket(
            packet_type=TYPE_PING,
            vad=False,
            energy_level=0,
            sender_id=self.user_id or 1,
            channel_id=ch_id,
            sequence=seq,
            timestamp=now_ts,
            payload=b'ping_probe',
        )
        await self.send_raw_udp(pkt.encode())
        return pkt

    async def wait_for_pong(self, timeout: float = 3.0) -> Tuple[VoicePacket, float]:
        """Wait for pong packet response."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                while not self.pong_packets_queue.empty():
                    return self.pong_packets_queue.get_nowait()
                await asyncio.sleep(0.005)
            except asyncio.CancelledError:
                break
        raise TimeoutError("Timed out waiting for UDP Pong response")

    async def wait_for_event(
        self,
        event_name: str,
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
        timeout: float = 3.0,
    ) -> Dict[str, Any]:
        """Wait for a specific WebSocket event."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                while not self.events_queue.empty():
                    evt = self.events_queue.get_nowait()
                    if evt.get("event") == event_name:
                        if predicate is None or predicate(evt):
                            return evt
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                break
        raise TimeoutError(f"Timed out waiting for event '{event_name}' on {self.username}")

    async def wait_for_voice_packet(
        self,
        sender_id: Optional[int] = None,
        timeout: float = 3.0,
    ) -> VoicePacket:
        """Wait for an inbound UDP voice packet."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                while not self.voice_packets_queue.empty():
                    pkt, arrival = self.voice_packets_queue.get_nowait()
                    if sender_id is None or pkt.sender_id == sender_id:
                        return pkt
                await asyncio.sleep(0.005)
            except asyncio.CancelledError:
                break
        raise TimeoutError(f"Timed out waiting for voice packet from sender {sender_id}")

