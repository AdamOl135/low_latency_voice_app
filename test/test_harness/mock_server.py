"""High-Fidelity In-Process Mock Backend Server for Low-Latency Voice App.

Complies with:
- 20-byte UDP Binary Wire Protocol (Port 7878/udp)
- High-throughput SFU Selective Forwarding Unit
- WebSocket JSON-RPC Control Plane (Port 8080/tcp)
- Role-based permissions, Admin bootstrap, Moderation (gating, deafen, kick)
- In-band fast VAD speaking indicator propagation
- UDP Ping/Pong loopback probe
"""

import asyncio
import json
import socket
import struct
import time
from typing import Dict, Any, Set, Tuple, Optional, List
import websockets
from test.test_harness.audio_generator import (
    VoicePacket,
    HEADER_SIZE,
    MAGIC_BYTE,
    PROTOCOL_VERSION,
    TYPE_VOICE,
    TYPE_PING,
    TYPE_PONG,
    TYPE_HANDSHAKE,
)


class MockServerUser:
    def __init__(self, user_id: int, username: str, is_admin: bool = False, roles: Optional[List[str]] = None):
        self.user_id = user_id
        self.username = username
        self.is_admin = is_admin
        self.roles = roles or (["admin"] if is_admin else ["member"])
        self.token = f"token_{user_id}_{int(time.time())}"
        self.udp_token = f"udptoken_{user_id}"
        self.current_channel_id: Optional[int] = None
        self.server_muted = False
        self.server_deafened = False
        self.is_speaking = False
        self.energy_level = 0
        self.ws: Optional[websockets.ServerConnection] = None
        self.ws_connections: Set[websockets.ServerConnection] = set()
        self.udp_addr: Optional[Tuple[str, int]] = None


class MockServer:
    """In-process mock Go SFU server for standalone E2E testing."""

    def __init__(self, host: str = "127.0.0.1", ws_port: int = 8080, udp_port: int = 7878):
        self.host = host
        self.ws_port = ws_port
        self.udp_port = udp_port

        self.users_by_id: Dict[int, MockServerUser] = {}
        self.users_by_name: Dict[str, MockServerUser] = {}
        self.users_by_token: Dict[str, MockServerUser] = {}
        self.users_by_udp_addr: Dict[Tuple[str, int], MockServerUser] = {}
        self.ws_to_user: Dict[websockets.ServerConnection, MockServerUser] = {}

        # Channels
        self.channels: Dict[int, Dict[str, Any]] = {
            101: {"id": 101, "name": "General Voice", "type": "voice", "category": "Voice Rooms"},
            102: {"id": 102, "name": "Gaming Lounge", "type": "voice", "category": "Voice Rooms"},
            201: {"id": 201, "name": "general-text", "type": "text", "category": "Text Channels"},
            202: {"id": 202, "name": "announcements", "type": "text", "category": "Text Channels"},
        }
        self.chat_history: Dict[int, List[Dict[str, Any]]] = {
            201: [],
            202: [],
        }

        self.next_user_id = 1
        self.next_msg_id = 1
        self._running = False
        self._ws_server = None
        self._udp_transport = None
        self._udp_protocol = None
        self.actual_ws_port = ws_port
        self.actual_udp_port = udp_port

    async def start(self):
        """Start both WebSocket server and UDP SFU socket."""
        self._running = True

        # Start WebSocket Server
        self._ws_server = await websockets.serve(
            self._handle_ws_connection,
            self.host,
            self.ws_port,
        )
        # Extract actual bound port (useful when port 0 is passed)
        for sock in self._ws_server.sockets:
            self.actual_ws_port = sock.getsockname()[1]
            break

        # Start UDP SFU Server
        loop = asyncio.get_running_loop()
        self._udp_transport, self._udp_protocol = await loop.create_datagram_endpoint(
            lambda: _UDPSFUProtocol(self),
            local_addr=(self.host, self.udp_port),
        )
        self.actual_udp_port = self._udp_transport.get_extra_info('sockname')[1]

    async def stop(self):
        """Stop mock backend services."""
        self._running = False
        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()
        if self._udp_transport:
            self._udp_transport.close()

    async def _handle_ws_connection(self, ws: websockets.ServerConnection):
        """Handle individual WebSocket client session."""
        current_user: Optional[MockServerUser] = None
        try:
            async for msg_str in ws:
                try:
                    req = json.loads(msg_str)
                except Exception:
                    continue

                action = req.get("action")
                req_id = req.get("id")

                resp = await self._process_action(action, req, ws, current_user)
                if resp is not None:
                    if req_id:
                        resp["reply_to"] = req_id
                    await ws.send(json.dumps(resp))

                # Update current_user context if auth or login succeeded
                if action in ("login", "register", "auth") and resp.get("status") == "ok":
                    uid = resp.get("user_id")
                    if uid in self.users_by_id:
                        current_user = self.users_by_id[uid]
                        current_user.ws = ws
                        current_user.ws_connections.add(ws)
                        self.ws_to_user[ws] = current_user

        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            if current_user:
                if ws in current_user.ws_connections:
                    current_user.ws_connections.remove(ws)
                if current_user.current_channel_id:
                    await self._broadcast_to_channel(
                        current_user.current_channel_id,
                        {"event": "user_left_voice", "user_id": current_user.user_id, "channel_id": current_user.current_channel_id}
                    )
                if ws in self.ws_to_user:
                    del self.ws_to_user[ws]
                if current_user.ws == ws:
                    current_user.ws = next(iter(current_user.ws_connections)) if current_user.ws_connections else None

    async def _process_action(
        self,
        action: str,
        req: Dict[str, Any],
        ws: websockets.ServerConnection,
        user: Optional[MockServerUser],
    ) -> Dict[str, Any]:
        """Dispatch WebSocket JSON-RPC actions."""
        if action == "register":
            username = req.get("username", f"User_{self.next_user_id}")
            # First user is automatically Admin (F22)
            is_admin = (len(self.users_by_id) == 0)
            roles = ["admin"] if is_admin else ["member"]
            
            new_user = MockServerUser(self.next_user_id, username, is_admin=is_admin, roles=roles)
            self.users_by_id[new_user.user_id] = new_user
            self.users_by_name[username] = new_user
            self.users_by_token[new_user.token] = new_user
            self.next_user_id += 1

            return {
                "status": "ok",
                "user_id": new_user.user_id,
                "username": new_user.username,
                "is_admin": new_user.is_admin,
                "roles": new_user.roles,
                "token": new_user.token,
            }

        elif action == "login":
            username = req.get("username", "")
            if username in self.users_by_name:
                u = self.users_by_name[username]
                return {
                    "status": "ok",
                    "user_id": u.user_id,
                    "username": u.username,
                    "is_admin": u.is_admin,
                    "roles": u.roles,
                    "token": u.token,
                }
            return {"status": "error", "error": "User not found"}

        elif action == "auth":
            token = req.get("token", "")
            if token in self.users_by_token:
                u = self.users_by_token[token]
                return {
                    "status": "ok",
                    "user_id": u.user_id,
                    "username": u.username,
                    "is_admin": u.is_admin,
                    "roles": u.roles,
                    "token": u.token,
                }
            return {"status": "error", "error": "Invalid session token"}

        elif action == "ping":
            return {
                "status": "ok",
                "action": "pong",
                "server_time": int(time.time()),
            }

        elif action == "list_channels":
            return {"status": "ok", "channels": list(self.channels.values())}

        elif action == "create_channel":
            if not user or not user.is_admin:
                return {"status": "error", "error": "Unauthorized: Admin role required"}
            name = req.get("name", "New Channel")
            ch_type = req.get("type", "voice")
            cat = req.get("category", "Voice Rooms" if ch_type == "voice" else "Text Channels")
            ch_id = 100 + len(self.channels) + 1
            new_ch = {"id": ch_id, "name": name, "type": ch_type, "category": cat}
            self.channels[ch_id] = new_ch
            if ch_type == "text":
                self.chat_history[ch_id] = []
            await self._broadcast_global({"event": "channel_created", "channel": new_ch})
            return {"status": "ok", "channel": new_ch}

        elif action == "join_voice":
            if not user:
                return {"status": "error", "error": "Unauthorized"}
            ch_id = req.get("channel_id")
            if ch_id not in self.channels or self.channels[ch_id]["type"] != "voice":
                return {"status": "error", "error": "Invalid voice channel"}

            # Leave previous channel if any
            if user.current_channel_id and user.current_channel_id != ch_id:
                await self._broadcast_to_channel(
                    user.current_channel_id,
                    {"event": "user_left_voice", "user_id": user.user_id, "channel_id": user.current_channel_id}
                )

            user.current_channel_id = ch_id
            await self._broadcast_to_channel(
                ch_id,
                {"event": "user_joined_voice", "user_id": user.user_id, "channel_id": ch_id, "username": user.username}
            )

            return {
                "status": "ok",
                "channel_id": ch_id,
                "udp_token": user.udp_token,
                "udp_port": self.actual_udp_port,
            }

        elif action == "leave_voice":
            if not user:
                return {"status": "error", "error": "Unauthorized"}
            ch_id = user.current_channel_id
            user.current_channel_id = None
            if ch_id:
                await self._broadcast_to_channel(
                    ch_id,
                    {"event": "user_left_voice", "user_id": user.user_id, "channel_id": ch_id}
                )
            return {"status": "ok"}

        elif action == "send_chat":
            if not user:
                return {"status": "error", "error": "Unauthorized"}
            ch_id = req.get("channel_id")
            content = req.get("content", "")
            if not content or len(content) > 4000:
                return {"status": "error", "error": "Message content exceeds limit"}

            msg = {
                "id": self.next_msg_id,
                "channel_id": ch_id,
                "sender_id": user.user_id,
                "sender_name": user.username,
                "content": content,
                "timestamp": int(time.time()),
            }
            self.next_msg_id += 1
            if ch_id not in self.chat_history:
                self.chat_history[ch_id] = []
            self.chat_history[ch_id].append(msg)

            await self._broadcast_global({
                "event": "chat_message",
                **msg
            })
            return {"status": "ok", "message_id": msg["id"]}

        elif action == "get_chat_history":
            ch_id = req.get("channel_id")
            limit = min(100, req.get("limit", 50))
            before_id = req.get("before_id")

            history = self.chat_history.get(ch_id, [])
            if before_id:
                history = [m for m in history if m["id"] < before_id]
            messages = history[-limit:]
            return {"status": "ok", "messages": messages}

        # Moderation Actions (F23, F24, F25, F26)
        elif action == "move_member":
            if not user or not user.is_admin:
                return {"status": "error", "error": "Permission denied"}
            target_id = req.get("target_user_id")
            to_ch_id = req.get("to_channel_id")
            if target_id not in self.users_by_id:
                return {"status": "error", "error": "Target user not found"}
            
            target = self.users_by_id[target_id]
            if not target.current_channel_id:
                return {"status": "error", "error": "Target user is not currently in a voice channel"}
            from_ch_id = target.current_channel_id
            target.current_channel_id = to_ch_id

            await self._broadcast_global({
                "event": "member_moved",
                "user_id": target.user_id,
                "from_channel_id": from_ch_id,
                "to_channel_id": to_ch_id,
            })
            return {"status": "ok"}

        elif action == "set_server_mute":
            if not user or not user.is_admin:
                return {"status": "error", "error": "Permission denied"}
            target_id = req.get("target_user_id")
            muted = req.get("muted", True)
            if target_id not in self.users_by_id:
                return {"status": "error", "error": "Target user not found"}
            
            target = self.users_by_id[target_id]
            target.server_muted = muted

            await self._broadcast_global({
                "event": "voice_state_update",
                "user_id": target.user_id,
                "server_muted": muted,
            })
            return {"status": "ok"}

        elif action == "set_server_deafen":
            if not user or not user.is_admin:
                return {"status": "error", "error": "Permission denied"}
            target_id = req.get("target_user_id")
            deafened = req.get("deafened", True)
            if target_id not in self.users_by_id:
                return {"status": "error", "error": "Target user not found"}
            
            target = self.users_by_id[target_id]
            target.server_deafened = deafened

            await self._broadcast_global({
                "event": "voice_state_update",
                "user_id": target.user_id,
                "server_deafened": deafened,
            })
            return {"status": "ok"}

        elif action == "kick_member":
            if not user or not user.is_admin:
                return {"status": "error", "error": "Permission denied"}
            target_id = req.get("target_user_id")
            reason = req.get("reason", "Kicked by administrator")
            if target_id == 1:
                return {"status": "error", "error": "Cannot kick server creator"}
            if target_id not in self.users_by_id:
                return {"status": "error", "error": "Target user not found"}
            
            target = self.users_by_id[target_id]
            was_in_channel = target.current_channel_id is not None
            # Revoke tokens and disconnect
            target.current_channel_id = None
            if target.token in self.users_by_token:
                del self.users_by_token[target.token]
            if target.udp_addr and target.udp_addr in self.users_by_udp_addr:
                del self.users_by_udp_addr[target.udp_addr]
            
            # Broadcast kick event
            await self._broadcast_global({
                "event": "member_kicked",
                "user_id": target.user_id,
                "reason": reason,
            })

            # Also broadcast voice evacuation if target was in a voice channel
            if was_in_channel:
                await self._broadcast_global({
                    "event": "voice_state_update",
                    "user_id": target.user_id,
                    "channel_id": None,
                    "is_speaking": False,
                    "speaking": False,
                    "energy": 0,
                })

            # Force close all target WebSockets with code 4001 and reason
            for ws_conn in list(target.ws_connections):
                try:
                    await ws_conn.close(code=4001, reason=reason)
                except Exception:
                    pass
            if target.ws and target.ws not in target.ws_connections:
                try:
                    await target.ws.close(code=4001, reason=reason)
                except Exception:
                    pass

            return {"status": "ok"}

        return {"status": "error", "error": f"Unknown action {action}"}

    async def _broadcast_global(self, event: Dict[str, Any]):
        """Broadcast JSON event to all connected WebSocket clients."""
        msg = json.dumps(event)
        for u in self.users_by_id.values():
            if u.ws:
                try:
                    await u.ws.send(msg)
                except Exception:
                    pass

    async def _broadcast_to_channel(self, channel_id: int, event: Dict[str, Any]):
        """Broadcast event to all users connected to a specific channel."""
        msg = json.dumps(event)
        for u in self.users_by_id.values():
            if u.current_channel_id == channel_id and u.ws:
                try:
                    await u.ws.send(msg)
                except Exception:
                    pass

    def handle_udp_packet(self, data: bytes, addr: Tuple[str, int]):
        """Process incoming UDP datagram in SFU router."""
        if len(data) < HEADER_SIZE:
            return

        try:
            pkt = VoicePacket.decode(data)
        except Exception:
            return

        if pkt.magic != MAGIC_BYTE or pkt.version != PROTOCOL_VERSION:
            return

        if len(pkt.payload) > 4076:
            return

        # Handle Handshake
        if pkt.packet_type == TYPE_HANDSHAKE:
            token_str = pkt.payload.decode('utf-8', errors='ignore')
            # Register user address
            for u in self.users_by_id.values():
                if u.user_id == pkt.sender_id or u.udp_token == token_str:
                    u.udp_addr = addr
                    self.users_by_udp_addr[addr] = u
                    break
            return

        # Handle Ping -> Immediate Pong
        if pkt.packet_type == TYPE_PING:
            pong_pkt = VoicePacket(
                packet_type=TYPE_PONG,
                vad=False,
                energy_level=0,
                sender_id=0,
                channel_id=pkt.channel_id,
                sequence=pkt.sequence,
                timestamp=pkt.timestamp,
                payload=pkt.payload,
            )
            if self._udp_transport:
                self._udp_transport.sendto(pong_pkt.encode(), addr)
            return

        # Handle Voice Packet (SFU Forwarding)
        if pkt.packet_type == TYPE_VOICE:
            sender = self.users_by_id.get(pkt.sender_id)
            if not sender or sender.token not in self.users_by_token:
                return

            if sender.current_channel_id is None or sender.current_channel_id != pkt.channel_id:
                return

            # Register address if not yet known
            if sender.udp_addr != addr:
                sender.udp_addr = addr
                self.users_by_udp_addr[addr] = sender

            # Server-mute gating (F24): Drop packets from server-muted sender
            if sender.server_muted:
                return

            # Update speaking state and broadcast if changed
            if sender.is_speaking != pkt.vad or abs(sender.energy_level - pkt.energy_level) >= 3:
                sender.is_speaking = pkt.vad
                sender.energy_level = pkt.energy_level
                asyncio.create_task(self._broadcast_to_channel(
                    sender.current_channel_id or pkt.channel_id,
                    {
                        "event": "voice_state_update",
                        "user_id": sender.user_id,
                        "channel_id": pkt.channel_id,
                        "speaking": pkt.vad,
                        "energy": pkt.energy_level,
                    }
                ))

            # Forward to other users in same channel (SFU selective forward)
            raw_bytes = data
            for peer in self.users_by_id.values():
                if (
                    peer.user_id != sender.user_id
                    and peer.current_channel_id == pkt.channel_id
                    and peer.udp_addr is not None
                    and not peer.server_deafened  # Deafen gating (F25)
                ):
                    if self._udp_transport:
                        self._udp_transport.sendto(raw_bytes, peer.udp_addr)


class _UDPSFUProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: MockServer):
        self.server = server

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        self.server.handle_udp_packet(data, addr)
