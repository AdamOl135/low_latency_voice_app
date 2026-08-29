"""Asynchronous Synthetic Client for Low-Latency Voice and Text Communication.

Simulates a real desktop client session:
- WebSocket JSON-RPC connection for auth, chat, channels, and moderation events
- UDP binary socket for voice streaming, in-band VAD, and ping/pong latency probes
- Event queues and async helpers for deterministic E2E assertions
"""

import asyncio
import json
import socket
import struct
import time
from typing import Dict, Any, List, Optional, Callable
import websockets
from test.test_harness.audio_generator import (
    VoicePacket,
    AudioGenerator,
    TYPE_VOICE,
    TYPE_PING,
    TYPE_PONG,
    TYPE_HANDSHAKE,
    SAMPLE_RATE,
)
from test.test_harness.latency_probe import RFC3550JitterCalculator


class SyntheticClient:
    """Simulates a complete desktop client communicating over WebSocket and UDP."""

    def __init__(
        self,
        username: str = "TestUser",
        password: str = "password123",
        token: Optional[str] = None,
        ws_url: str = "ws://127.0.0.1:8080/ws",
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

        # Networking
        self.ws: Optional[websockets.ClientConnection] = None
        self.udp_sock: Optional[socket.socket] = None
        self.audio_gen: Optional[AudioGenerator] = None
        self.jitter_calc = RFC3550JitterCalculator()

        # Background tasks
        self._ws_recv_task: Optional[asyncio.Task] = None
        self._udp_recv_task: Optional[asyncio.Task] = None
        self._running = False

        # Event Queues
        self.events_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.voice_packets_queue: asyncio.Queue[Tuple[VoicePacket, float]] = asyncio.Queue()
        self.received_events: List[Dict[str, Any]] = []
        self.received_voice_packets: List[Tuple[VoicePacket, float]] = []

        # Statistics
        self.packets_sent = 0
        self.packets_received = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        self.last_received_seq: Optional[int] = None
        self.out_of_order_count = 0
        self.sequence_gaps = 0

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self):
        """Establish WebSocket connection, register/auth, and setup background readers."""
        self._running = True
        self.ws = await websockets.connect(self.ws_url)
        self.is_connected = True
        self._ws_recv_task = asyncio.create_task(self._ws_loop())

        # Authenticate or Register
        if self.token:
            auth_res = await self.send_rpc({"action": "auth", "token": self.token, "client_version": "1.0.0"})
        else:
            auth_res = await self.send_rpc({
                "action": "login",
                "username": self.username,
                "password": self.password,
                "client_version": "1.0.0"
            })
            if auth_res.get("status") != "ok":
                # Try registering if login fails
                auth_res = await self.send_rpc({
                    "action": "register",
                    "username": self.username,
                    "password": self.password,
                    "client_version": "1.0.0"
                })

        if auth_res.get("status") == "ok":
            self.user_id = auth_res.get("user_id")
            self.is_admin = auth_res.get("is_admin", False)
            self.roles = auth_res.get("roles", [])
            self.token = auth_res.get("token", self.token)
            self.username = auth_res.get("username", self.username)
        else:
            self.is_connected = False
            self._running = False
            if self._ws_recv_task and not self._ws_recv_task.done():
                self._ws_recv_task.cancel()
            if self.ws:
                try:
                    await self.ws.close()
                except Exception:
                    pass
                self.ws = None
            raise RuntimeError(f"Authentication failed for {self.username}: {auth_res}")

        # Setup UDP socket
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setblocking(False)
        self._udp_recv_task = asyncio.create_task(self._udp_loop())

    async def disconnect(self):
        """Gracefully disconnect WebSocket and UDP sessions."""
        self._running = False
        self.is_connected = False
        self.is_voice_active = False

        if self._ws_recv_task and not self._ws_recv_task.done():
            self._ws_recv_task.cancel()
        if self._udp_recv_task and not self._udp_recv_task.done():
            self._udp_recv_task.cancel()

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
        """Send a JSON-RPC command over WebSocket and await corresponding response."""
        if not self.ws:
            raise RuntimeError("WebSocket is not connected")
        
        req_id = payload.get("id", f"req_{int(time.time() * 1000)}_{self.user_id or 0}")
        payload["id"] = req_id
        
        await self.ws.send(json.dumps(payload))
        
        # Poll events/responses for matching ID or general status response
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            try:
                # Check recent received events
                for item in reversed(self.received_events):
                    if item.get("id") == req_id or (item.get("reply_to") == req_id):
                        return item
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                break
        
        # If no explicit ID matched, return last status event if recent
        if self.received_events and "status" in self.received_events[-1]:
            return self.received_events[-1]
        
        return {"status": "timeout", "error": "RPC response timed out"}

    async def _ws_loop(self):
        """Background WebSocket event listener."""
        try:
            while self._running and self.ws:
                msg = await self.ws.recv()
                if isinstance(msg, bytes):
                    msg = msg.decode('utf-8')
                data = json.loads(msg)
                self.received_events.append(data)
                await self.events_queue.put(data)

                # Track voice states
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

        except (websockets.ConnectionClosed, websockets.ConnectionClosedError, asyncio.CancelledError):
            self.is_connected = False
        except Exception as e:
            self.is_connected = False

    async def _udp_loop(self):
        """Background UDP audio packet listener."""
        loop = asyncio.get_running_loop()
        while self._running and self.udp_sock:
            try:
                data = await loop.sock_recv(self.udp_sock, 2048)
                arrival_time = time.time()
                self.bytes_received += len(data)
                self.packets_received += 1

                pkt = VoicePacket.decode(data)
                self.received_voice_packets.append((pkt, arrival_time))
                await self.voice_packets_queue.put((pkt, arrival_time))

                # Track sequence and jitter
                if pkt.packet_type == TYPE_VOICE:
                    self.jitter_calc.add_packet(pkt.timestamp, arrival_time)
                    if self.last_received_seq is not None:
                        expected_seq = (self.last_received_seq + 1) & 0xFFFF
                        if pkt.sequence < expected_seq and (expected_seq - pkt.sequence < 30000):
                            self.out_of_order_count += 1
                        elif pkt.sequence > expected_seq:
                            self.sequence_gaps += (pkt.sequence - expected_seq)
                    self.last_received_seq = pkt.sequence

            except (BlockingIOError, socket.error):
                await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.005)

    # High-level actions
    async def join_voice_channel(self, channel_id: int) -> Dict[str, Any]:
        """Join a voice channel and perform UDP handshake."""
        self.current_channel_id = channel_id
        res = await self.send_rpc({"action": "join_voice", "channel_id": channel_id})
        if res.get("status") == "ok":
            self.udp_token = res.get("udp_token")
            self.udp_port = res.get("udp_port", self.udp_port)
            self.audio_gen = AudioGenerator(
                sender_id=self.user_id or 1,
                channel_id=channel_id,
                frame_duration_ms=20,
            )
            # Send UDP handshake packet
            await self.send_udp_handshake()
            self.is_voice_active = True
        return res

    async def leave_voice_channel(self) -> Dict[str, Any]:
        """Leave current voice channel."""
        res = await self.send_rpc({"action": "leave_voice", "channel_id": self.current_channel_id})
        self.current_channel_id = None
        self.is_voice_active = False
        return res

    async def send_udp_handshake(self):
        """Send Type 0x04 Handshake packet to register UDP endpoint with the SFU."""
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
        await self.send_raw_udp_packet(pkt.encode())

    async def send_raw_udp_packet(self, data: bytes):
        """Send raw UDP bytes to SFU."""
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
        """Generate and send the next 20ms voice packet."""
        if not self.audio_gen:
            raise RuntimeError("Audio generator not initialized. Join a voice channel first.")
        
        pkt = self.audio_gen.next_voice_packet(
            is_speaking=is_speaking,
            energy_level=energy_level,
            payload_size=payload_size,
        )
        await self.send_raw_udp_packet(pkt.encode())
        return pkt

    async def stream_audio(
        self,
        duration_sec: float = 1.0,
        frame_ms: int = 20,
        is_speaking: bool = True,
    ) -> int:
        """Stream continuous audio frames at real-time intervals."""
        count = int((duration_sec * 1000) / frame_ms)
        interval = frame_ms / 1000.0
        
        for _ in range(count):
            start = time.perf_counter()
            await self.send_voice_frame(is_speaking=is_speaking)
            elapsed = time.perf_counter() - start
            sleep_time = max(0.0, interval - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        return count

    async def send_chat_message(self, channel_id: int, content: str) -> Dict[str, Any]:
        """Send a text chat message."""
        return await self.send_rpc({
            "action": "send_chat",
            "channel_id": channel_id,
            "content": content,
        })

    async def get_chat_history(self, channel_id: int, limit: int = 50, before_id: Optional[int] = None) -> Dict[str, Any]:
        """Fetch chat history with cursor pagination."""
        req: Dict[str, Any] = {"action": "get_chat_history", "channel_id": channel_id, "limit": limit}
        if before_id is not None:
            req["before_id"] = before_id
        return await self.send_rpc(req)

    # Moderation commands
    async def move_member(self, target_user_id: int, to_channel_id: int) -> Dict[str, Any]:
        return await self.send_rpc({
            "action": "move_member",
            "target_user_id": target_user_id,
            "to_channel_id": to_channel_id,
        })

    async def set_server_mute(self, target_user_id: int, muted: bool = True) -> Dict[str, Any]:
        return await self.send_rpc({
            "action": "set_server_mute",
            "target_user_id": target_user_id,
            "muted": muted,
        })

    async def set_server_deafen(self, target_user_id: int, deafened: bool = True) -> Dict[str, Any]:
        return await self.send_rpc({
            "action": "set_server_deafen",
            "target_user_id": target_user_id,
            "deafened": deafened,
        })

    async def kick_member(self, target_user_id: int, reason: str = "Rule violation") -> Dict[str, Any]:
        return await self.send_rpc({
            "action": "kick_member",
            "target_user_id": target_user_id,
            "reason": reason,
        })

    # Assertions and Event Waiters
    async def wait_for_event(
        self,
        event_name: str,
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
        timeout: float = 3.0,
    ) -> Dict[str, Any]:
        """Wait for a specific WebSocket event matching the optional predicate."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                # Check unconsumed items in queue
                while not self.events_queue.empty():
                    evt = self.events_queue.get_nowait()
                    if evt.get("event") == event_name:
                        if predicate is None or predicate(evt):
                            return evt
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                break
        raise TimeoutError(f"Timed out waiting for event '{event_name}' on user {self.username}")

    async def wait_for_voice_packet(
        self,
        sender_id: Optional[int] = None,
        timeout: float = 3.0,
    ) -> VoicePacket:
        """Wait for an incoming UDP voice packet."""
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
