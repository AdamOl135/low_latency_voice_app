"""High-Fidelity In-Process Go SFU and Control Plane Simulator for E2E Tests.

Simulates the exact Go backend contracts:
- Dynamic UDP port return in auth & join_voice (F3)
- Ping refreshes LastSeen timestamp to protect silent listeners from idle eviction (F2)
- 60-second idle session scavenger
- UDP selective forwarding across channel peers
- WebSocket JSON-RPC protocol and moderation invariants (F21-F27)
"""

import asyncio
import json
import socket
import time
from typing import Dict, Any, Optional, Set, Tuple, List
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
from tests.e2e.harness.simple_ws import SimpleWebSocketServer, WebSocketConnection, WebSocketClosed


class SFUSession:
    """Represents a client's UDP voice session in the SFU."""

    def __init__(self, user_id: int, channel_id: int, udp_addr: Optional[Tuple[str, int]] = None):
        self.user_id = user_id
        self.channel_id = channel_id
        self.udp_addr = udp_addr
        self.last_seen = time.time()
        self.is_speaking = False
        self.energy_level = 0
        self.is_muted = False
        self.is_deafened = False
        self.ssrc = 1000 + user_id

    def touch(self):
        """Update last_seen timestamp on active packet or ping."""
        self.last_seen = time.time()


class SFUUser:
    """Represents an authenticated user in the control plane."""

    def __init__(self, user_id: int, username: str, is_admin: bool = False, roles: Optional[List[str]] = None):
        self.user_id = user_id
        self.username = username
        self.is_admin = is_admin
        self.roles = roles or (["admin"] if is_admin else ["member"])
        self.token = f"token_{user_id}_{int(time.time()*1000)}"
        self.udp_token = f"udptoken_{user_id}"
        self.current_channel_id: Optional[int] = None
        self.server_muted = False
        self.server_deafened = False
        self.ws_conns: Set[WebSocketConnection] = set()


class SFUServer:
    """High-Fidelity SFU Server combining WebSocket control plane and UDP media plane."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        ws_port: int = 0,
        udp_port: int = 0,
        idle_timeout_sec: float = 60.0,
        scavenger_interval_sec: float = 0.5,
    ):
        self.host = host
        self.ws_port = ws_port
        self.udp_port = udp_port
        self.idle_timeout_sec = idle_timeout_sec
        self.scavenger_interval_sec = scavenger_interval_sec

        self.users_by_id: Dict[int, SFUUser] = {}
        self.users_by_name: Dict[str, SFUUser] = {}
        self.users_by_token: Dict[str, SFUUser] = {}
        self.sessions_by_user: Dict[int, SFUSession] = {}
        self.sessions_by_addr: Dict[Tuple[str, int], SFUSession] = {}

        self.channels: Dict[int, Dict[str, Any]] = {
            101: {"id": 101, "name": "General Voice", "type": "voice", "category": "Voice Rooms"},
            102: {"id": 102, "name": "Gaming Lounge", "type": "voice", "category": "Voice Rooms"},
            201: {"id": 201, "name": "general-text", "type": "text", "category": "Text Channels"},
            202: {"id": 202, "name": "announcements", "type": "text", "category": "Text Channels"},
        }
        self.chat_history: Dict[int, List[Dict[str, Any]]] = {201: [], 202: []}

        self.next_user_id = 1
        self.next_msg_id = 1
        self.running = False
        self.ws_server: Optional[SimpleWebSocketServer] = None
        self.udp_transport: Optional[asyncio.DatagramTransport] = None
        self.scavenger_task: Optional[asyncio.Task] = None

        self.actual_ws_port: int = 0
        self.actual_udp_port: int = 0

        # Telemetry
        self.evicted_sessions: List[Tuple[int, float]] = []
        self.forwarded_packets_count = 0
        self.dropped_muted_count = 0
        self.pings_received_count = 0

    async def start(self):
        """Start WebSocket server, UDP socket, and session scavenger loop."""
        self.running = True

        # Start WebSocket Server
        self.ws_server = SimpleWebSocketServer(self._handle_ws_client, self.host, self.ws_port)
        await self.ws_server.start()
        self.actual_ws_port = self.ws_server.bound_port

        # Start UDP Datagram Endpoint
        loop = asyncio.get_running_loop()
        self.udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: _SFUDatagramProtocol(self),
            local_addr=(self.host, self.udp_port),
        )
        self.actual_udp_port = self.udp_transport.get_extra_info('sockname')[1]

        # Start Idle Session Scavenger Loop
        self.scavenger_task = asyncio.create_task(self._scavenger_loop())

    async def stop(self):
        """Gracefully stop SFU server."""
        self.running = False
        if self.scavenger_task and not self.scavenger_task.done():
            self.scavenger_task.cancel()
        if self.ws_server:
            await self.ws_server.close()
        if self.udp_transport:
            self.udp_transport.close()

    async def _scavenger_loop(self):
        """Periodically evict sessions that exceeded idle_timeout_sec without a packet or ping."""
        while self.running:
            try:
                await asyncio.sleep(self.scavenger_interval_sec)
                now = time.time()
                evict_uids = []
                for uid, session in list(self.sessions_by_user.items()):
                    if (now - session.last_seen) > self.idle_timeout_sec:
                        evict_uids.append(uid)

                for uid in evict_uids:
                    sess = self.sessions_by_user.pop(uid, None)
                    if sess:
                        if sess.udp_addr in self.sessions_by_addr:
                            del self.sessions_by_addr[sess.udp_addr]
                        self.evicted_sessions.append((uid, now))
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _handle_ws_client(self, ws: WebSocketConnection):
        """Handle incoming WebSocket JSON-RPC connection."""
        current_user: Optional[SFUUser] = None
        try:
            while self.running and not ws.closed:
                msg_str = await ws.recv()
                if isinstance(msg_str, bytes):
                    msg_str = msg_str.decode('utf-8')
                try:
                    req = json.loads(msg_str)
                except Exception:
                    continue

                action = req.get("action")
                req_id = req.get("id")

                resp = await self._dispatch_action(action, req, ws, current_user)
                if resp is not None:
                    if req_id:
                        resp["reply_to"] = req_id
                    await ws.send(json.dumps(resp))

                # If login/register/auth succeeded, bind user
                if action in ("login", "register", "auth") and resp.get("status") == "ok":
                    uid = resp.get("user_id") or resp.get("data", {}).get("user_id")
                    if uid in self.users_by_id:
                        current_user = self.users_by_id[uid]
                        current_user.ws_conns.add(ws)

        except (WebSocketClosed, asyncio.CancelledError):
            pass
        finally:
            if current_user:
                current_user.ws_conns.discard(ws)
                if current_user.current_channel_id and len(current_user.ws_conns) == 0:
                    ch_id = current_user.current_channel_id
                    current_user.current_channel_id = None
                    await self._broadcast_channel(ch_id, {
                        "event": "user_left_voice",
                        "user_id": current_user.user_id,
                        "channel_id": ch_id,
                    })

    async def _dispatch_action(
        self,
        action: str,
        req: Dict[str, Any],
        ws: WebSocketConnection,
        user: Optional[SFUUser],
    ) -> Dict[str, Any]:
        """Process WebSocket JSON-RPC actions."""
        if action == "register":
            username = req.get("username", f"User_{self.next_user_id}")
            is_admin = (len(self.users_by_id) == 0)
            roles = ["admin"] if is_admin else ["member"]

            new_user = SFUUser(self.next_user_id, username, is_admin=is_admin, roles=roles)
            self.users_by_id[new_user.user_id] = new_user
            self.users_by_name[username] = new_user
            self.users_by_token[new_user.token] = new_user
            self.next_user_id += 1

            return {
                "status": "ok",
                "action": "register",
                "user_id": new_user.user_id,
                "username": new_user.username,
                "is_admin": new_user.is_admin,
                "roles": new_user.roles,
                "token": new_user.token,
                "udp_port": self.actual_udp_port,  # F3: Dynamic UDP port return
            }

        elif action == "login":
            username = req.get("username", "")
            if username in self.users_by_name:
                u = self.users_by_name[username]
                return {
                    "status": "ok",
                    "action": "login",
                    "user_id": u.user_id,
                    "username": u.username,
                    "is_admin": u.is_admin,
                    "roles": u.roles,
                    "token": u.token,
                    "udp_port": self.actual_udp_port,  # F3: Dynamic UDP port return
                }
            return {"status": "error", "error": "User not found"}

        elif action == "auth":
            token = req.get("token", "")
            if token in self.users_by_token:
                u = self.users_by_token[token]
                return {
                    "status": "ok",
                    "action": "auth",
                    "data": {
                        "user_id": u.user_id,
                        "username": u.username,
                        "is_admin": u.is_admin,
                        "roles": u.roles,
                        "token": u.token,
                        "udp_port": self.actual_udp_port,  # F3: Dynamic UDP port return
                    },
                    "user_id": u.user_id,
                    "udp_port": self.actual_udp_port,
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
                return {"status": "error", "error": "Unauthorized: Admin required"}
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
                old_ch = user.current_channel_id
                user.current_channel_id = None
                await self._broadcast_channel(old_ch, {
                    "event": "user_left_voice",
                    "user_id": user.user_id,
                    "channel_id": old_ch,
                })

            user.current_channel_id = ch_id

            # Create or update SFU session
            sess = self.sessions_by_user.get(user.user_id)
            if not sess:
                sess = SFUSession(user.user_id, ch_id)
                self.sessions_by_user[user.user_id] = sess
            else:
                sess.channel_id = ch_id
                sess.touch()

            await self._broadcast_channel(ch_id, {
                "event": "user_joined_voice",
                "user_id": user.user_id,
                "channel_id": ch_id,
                "username": user.username,
            })

            return {
                "status": "ok",
                "action": "join_voice",
                "data": {
                    "channel_id": ch_id,
                    "udp_token": user.udp_token,
                    "udp_port": self.actual_udp_port,  # F3: Dynamic UDP port return
                    "ssrc": sess.ssrc,
                },
                "channel_id": ch_id,
                "udp_token": user.udp_token,
                "udp_port": self.actual_udp_port,  # F3: Dynamic UDP port return
                "ssrc": sess.ssrc,
            }

        elif action == "leave_voice":
            if not user:
                return {"status": "error", "error": "Unauthorized"}
            ch_id = user.current_channel_id
            user.current_channel_id = None
            if ch_id:
                await self._broadcast_channel(ch_id, {
                    "event": "user_left_voice",
                    "user_id": user.user_id,
                    "channel_id": ch_id,
                })
            # Remove SFU session
            sess = self.sessions_by_user.pop(user.user_id, None)
            if sess and sess.udp_addr in self.sessions_by_addr:
                del self.sessions_by_addr[sess.udp_addr]
            return {"status": "ok"}

        elif action == "send_chat":
            if not user:
                return {"status": "error", "error": "Unauthorized"}
            ch_id = req.get("channel_id")
            content = req.get("content", "")
            if not content or len(content) > 4000:
                return {"status": "error", "error": "Message content exceeds 4000 limit"}

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

            await self._broadcast_global({"event": "chat_message", **msg})
            return {"status": "ok", "message_id": msg["id"]}

        elif action == "get_chat_history":
            ch_id = req.get("channel_id")
            limit = min(100, req.get("limit", 50))
            before_id = req.get("before_id")
            history = self.chat_history.get(ch_id, [])
            if before_id:
                history = [m for m in history if m["id"] < before_id]
            return {"status": "ok", "messages": history[-limit:]}

        # Moderation Actions
        elif action == "move_member":
            if not user or not user.is_admin:
                return {"status": "error", "error": "Permission denied"}
            target_id = req.get("target_user_id")
            to_ch_id = req.get("to_channel_id")
            target = self.users_by_id.get(target_id)
            if not target or not target.current_channel_id:
                return {"status": "error", "error": "Target user not in voice"}

            from_ch_id = target.current_channel_id
            target.current_channel_id = to_ch_id
            if target_id in self.sessions_by_user:
                self.sessions_by_user[target_id].channel_id = to_ch_id
                self.sessions_by_user[target_id].touch()

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
            target = self.users_by_id.get(target_id)
            if not target:
                return {"status": "error", "error": "Target not found"}

            target.server_muted = muted
            if target_id in self.sessions_by_user:
                self.sessions_by_user[target_id].is_muted = muted
                self.sessions_by_user[target_id].touch()

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
            target = self.users_by_id.get(target_id)
            if not target:
                return {"status": "error", "error": "Target not found"}

            target.server_deafened = deafened
            if target_id in self.sessions_by_user:
                self.sessions_by_user[target_id].is_deafened = deafened
                self.sessions_by_user[target_id].touch()

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
            target = self.users_by_id.get(target_id)
            if not target:
                return {"status": "error", "error": "Target not found"}

            target.current_channel_id = None
            if target.token in self.users_by_token:
                del self.users_by_token[target.token]
            sess = self.sessions_by_user.pop(target_id, None)
            if sess and sess.udp_addr in self.sessions_by_addr:
                del self.sessions_by_addr[sess.udp_addr]

            await self._broadcast_global({
                "event": "member_kicked",
                "user_id": target.user_id,
                "reason": reason,
            })

            # Force close target connections with code 4001
            for conn in list(target.ws_conns):
                asyncio.create_task(conn.close(code=4001, reason=reason))

            return {"status": "ok"}

        return {"status": "error", "error": f"Unknown action {action}"}

    async def _broadcast_global(self, event: Dict[str, Any]):
        """Broadcast event to all connected users."""
        msg = json.dumps(event)
        for u in self.users_by_id.values():
            for conn in list(u.ws_conns):
                try:
                    await conn.send(msg)
                except Exception:
                    pass

    async def _broadcast_channel(self, channel_id: int, event: Dict[str, Any]):
        """Broadcast event to users currently in channel."""
        msg = json.dumps(event)
        for u in self.users_by_id.values():
            if u.current_channel_id == channel_id:
                for conn in list(u.ws_conns):
                    try:
                        await conn.send(msg)
                    except Exception:
                        pass

    def handle_udp_datagram(self, data: bytes, addr: Tuple[str, int]):
        """Process inbound UDP packet in SFU router."""
        if len(data) < HEADER_SIZE:
            return

        try:
            pkt = VoicePacket.decode(data)
        except Exception:
            return

        if pkt.magic != MAGIC_BYTE or pkt.version != PROTOCOL_VERSION:
            return

        # 1. TypeHandshake (0x04)
        if pkt.packet_type == TYPE_HANDSHAKE:
            token_str = pkt.payload.decode('utf-8', errors='ignore')
            # Look up user
            for u in self.users_by_id.values():
                if u.user_id == pkt.sender_id or u.udp_token == token_str:
                    sess = self.sessions_by_user.get(u.user_id)
                    if not sess:
                        sess = SFUSession(u.user_id, pkt.channel_id, addr)
                        self.sessions_by_user[u.user_id] = sess
                    else:
                        sess.udp_addr = addr
                        sess.channel_id = pkt.channel_id
                        sess.touch()
                    self.sessions_by_addr[addr] = sess
                    break
            return

        # 2. TypePing (0x02) — CRITICAL F2 Requirement: handlePing TOUCHES LastSeen!
        if pkt.packet_type == TYPE_PING:
            self.pings_received_count += 1
            # Refresh session LastSeen by sender ID or source address
            sess = self.sessions_by_user.get(pkt.sender_id)
            if not sess:
                sess = self.sessions_by_addr.get(addr)
            if sess:
                sess.touch()
                if sess.udp_addr != addr:
                    sess.udp_addr = addr
                    self.sessions_by_addr[addr] = sess

            # Respond with Pong preserving timestamp and payload
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
            if self.udp_transport:
                self.udp_transport.sendto(pong_pkt.encode(), addr)
            return

        # 3. TypeVoice (0x01) — SFU Selective Forwarding
        if pkt.packet_type == TYPE_VOICE:
            sess = self.sessions_by_user.get(pkt.sender_id)
            if not sess:
                sess = self.sessions_by_addr.get(addr)
                if not sess or sess.user_id != pkt.sender_id:
                    # ErrSessionNotFound: dropped
                    return

            if sess.channel_id != pkt.channel_id:
                # ErrChannelMismatch: dropped
                return

            sess.touch()
            if sess.udp_addr != addr:
                sess.udp_addr = addr
                self.sessions_by_addr[addr] = sess

            # Ingress Server Mute Gating (F24)
            if sess.is_muted:
                self.dropped_muted_count += 1
                return

            # Update speaking state and broadcast if changed
            if sess.is_speaking != pkt.vad or abs(sess.energy_level - pkt.energy_level) >= 3:
                sess.is_speaking = pkt.vad
                sess.energy_level = pkt.energy_level
                asyncio.create_task(self._broadcast_channel(
                    pkt.channel_id,
                    {
                        "event": "voice_state_update",
                        "user_id": sess.user_id,
                        "channel_id": pkt.channel_id,
                        "speaking": pkt.vad,
                        "energy": pkt.energy_level,
                    }
                ))

            # Forward to channel peers (skipping server-deafened peers)
            raw_bytes = data
            for peer_uid, peer_sess in self.sessions_by_user.items():
                if (
                    peer_uid != sess.user_id
                    and peer_sess.channel_id == pkt.channel_id
                    and peer_sess.udp_addr is not None
                    and not peer_sess.is_deafened
                ):
                    if self.udp_transport:
                        self.udp_transport.sendto(raw_bytes, peer_sess.udp_addr)
                        self.forwarded_packets_count += 1


class _SFUDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: SFUServer):
        self.server = server

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        self.server.handle_udp_datagram(data, addr)

