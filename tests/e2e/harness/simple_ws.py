"""Pure Python Zero-Dependency RFC 6455 WebSocket Client and Server Implementation.

Implemented on top of Python's standard `asyncio.StreamReader` and `asyncio.StreamWriter`.
Provides 100% standard library compliance without external packages (websockets/uvloop).
"""

import asyncio
import base64
import hashlib
import os
import struct
import urllib.parse
from typing import Optional, Union, Dict, Any, Callable, Tuple, Set

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


class WebSocketClosed(Exception):
    """Raised when the WebSocket connection is closed."""
    def __init__(self, code: int = 1000, reason: str = ""):
        self.code = code
        self.reason = reason
        super().__init__(f"WebSocket closed with code {code}: {reason}")


class WebSocketConnection:
    """Represents a duplex RFC 6455 WebSocket connection."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, is_client: bool):
        self.reader = reader
        self.writer = writer
        self.is_client = is_client
        self.closed = False
        self.close_code: Optional[int] = None
        self.close_reason: str = ""
        self._recv_lock = asyncio.Lock()

    async def send(self, data: Union[str, bytes]):
        """Send a text or binary frame."""
        if self.closed:
            raise WebSocketClosed(self.close_code or 1006, "Connection already closed")

        if isinstance(data, str):
            opcode = OPCODE_TEXT
            payload = data.encode('utf-8')
        else:
            opcode = OPCODE_BINARY
            payload = bytes(data)

        length = len(payload)
        header = bytearray()
        # FIN=1, RSV=0, Opcode
        header.append(0x80 | opcode)

        # MASK bit and payload length
        mask_bit = 0x80 if self.is_client else 0x00
        if length <= 125:
            header.append(mask_bit | length)
        elif length <= 65535:
            header.append(mask_bit | 126)
            header.extend(struct.pack('>H', length))
        else:
            header.append(mask_bit | 127)
            header.extend(struct.pack('>Q', length))

        if self.is_client:
            mask_key = os.urandom(4)
            header.extend(mask_key)
            masked_payload = bytearray(payload)
            for i in range(len(masked_payload)):
                masked_payload[i] ^= mask_key[i % 4]
            frame = bytes(header) + bytes(masked_payload)
        else:
            frame = bytes(header) + payload

        self.writer.write(frame)
        await self.writer.drain()

    async def recv(self) -> Union[str, bytes]:
        """Receive the next full message (text or binary)."""
        async with self._recv_lock:
            while not self.closed:
                frame_opcode, payload = await self._read_frame()
                if frame_opcode == OPCODE_TEXT:
                    return payload.decode('utf-8')
                elif frame_opcode == OPCODE_BINARY:
                    return payload
                elif frame_opcode == OPCODE_PING:
                    # Echo ping payload back in pong
                    await self._send_control(OPCODE_PONG, payload)
                elif frame_opcode == OPCODE_PONG:
                    continue
                elif frame_opcode == OPCODE_CLOSE:
                    self.closed = True
                    code = 1000
                    reason = ""
                    if len(payload) >= 2:
                        code = struct.unpack('>H', payload[:2])[0]
                        reason = payload[2:].decode('utf-8', errors='ignore')
                    self.close_code = code
                    self.close_reason = reason
                    # Send close response if we haven't already
                    try:
                        await self._send_control(OPCODE_CLOSE, payload[:2])
                        await self.writer.drain()
                        self.writer.close()
                    except Exception:
                        pass
                    raise WebSocketClosed(code, reason)

            raise WebSocketClosed(self.close_code or 1000, self.close_reason)

    async def _read_frame(self) -> Tuple[int, bytes]:
        """Read a single frame from the stream."""
        head = await self.reader.readexactly(2)
        b1, b2 = head[0], head[1]
        fin = bool(b1 & 0x80)
        opcode = b1 & 0x0F
        is_masked = bool(b2 & 0x80)
        length = b2 & 0x7F

        if length == 126:
            ext = await self.reader.readexactly(2)
            length = struct.unpack('>H', ext)[0]
        elif length == 127:
            ext = await self.reader.readexactly(8)
            length = struct.unpack('>Q', ext)[0]

        mask_key = None
        if is_masked:
            mask_key = await self.reader.readexactly(4)

        payload = await self.reader.readexactly(length) if length > 0 else b''

        if is_masked and mask_key:
            unmasked = bytearray(payload)
            for i in range(len(unmasked)):
                unmasked[i] ^= mask_key[i % 4]
            payload = bytes(unmasked)

        return opcode, payload

    async def _send_control(self, opcode: int, payload: bytes):
        """Send a control frame (PING, PONG, CLOSE)."""
        length = len(payload)
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        mask_bit = 0x80 if self.is_client else 0x00
        header.append(mask_bit | length)
        if self.is_client:
            mask_key = os.urandom(4)
            header.extend(mask_key)
            masked = bytearray(payload)
            for i in range(len(masked)):
                masked[i] ^= mask_key[i % 4]
            frame = bytes(header) + bytes(masked)
        else:
            frame = bytes(header) + payload
        self.writer.write(frame)
        await self.writer.drain()

    async def close(self, code: int = 1000, reason: str = ""):
        """Initiate clean close handshake."""
        if self.closed:
            return
        self.closed = True
        self.close_code = code
        self.close_reason = reason
        payload = struct.pack('>H', code) + reason.encode('utf-8')
        try:
            await self._send_control(OPCODE_CLOSE, payload)
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass


async def connect_ws(url: str, timeout: float = 5.0) -> WebSocketConnection:
    """Connect to a WebSocket server URL (e.g. ws://127.0.0.1:8085/ws)."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"

    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)

    # Generate Sec-WebSocket-Key
    raw_key = os.urandom(16)
    sec_key = base64.b64encode(raw_key).decode('ascii')
    expected_accept = base64.b64encode(hashlib.sha1((sec_key + GUID).encode('ascii')).digest()).decode('ascii')

    handshake = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {sec_key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )

    writer.write(handshake.encode('utf-8'))
    await writer.drain()

    # Read HTTP Response
    header_data = b""
    while b"\r\n\r\n" not in header_data:
        chunk = await asyncio.wait_for(reader.read(1024), timeout=timeout)
        if not chunk:
            raise ConnectionError("Server closed connection during handshake")
        header_data += chunk

    status_line = header_data.split(b"\r\n")[0].decode('utf-8', errors='ignore')
    if "101" not in status_line:
        raise ConnectionError(f"WebSocket upgrade rejected: {status_line}")

    return WebSocketConnection(reader, writer, is_client=True)


class SimpleWebSocketServer:
    """Lightweight pure Python WebSocket Server."""

    def __init__(self, handler: Callable[[WebSocketConnection], Any], host: str = "127.0.0.1", port: int = 0):
        self.handler = handler
        self.host = host
        self.port = port
        self.server: Optional[asyncio.Server] = None
        self.bound_port: int = 0
        self.active_connections: Set[WebSocketConnection] = set()

    async def start(self):
        self.server = await asyncio.start_server(self._accept_client, self.host, self.port)
        for sock in self.server.sockets:
            self.bound_port = sock.getsockname()[1]
            break

    async def _accept_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        header_data = b""
        while b"\r\n\r\n" not in header_data:
            chunk = await reader.read(1024)
            if not chunk:
                writer.close()
                return
            header_data += chunk

        lines = header_data.decode('utf-8', errors='ignore').split("\r\n")
        sec_key = ""
        for line in lines:
            if line.lower().startswith("sec-websocket-key:"):
                sec_key = line.split(":", 1)[1].strip()
                break

        if not sec_key:
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        accept_val = base64.b64encode(hashlib.sha1((sec_key + GUID).encode('ascii')).digest()).decode('ascii')
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_val}\r\n\r\n"
        )
        writer.write(response.encode('utf-8'))
        await writer.drain()

        ws = WebSocketConnection(reader, writer, is_client=False)
        self.active_connections.add(ws)
        try:
            await self.handler(ws)
        except (WebSocketClosed, asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self.active_connections.discard(ws)
            if not ws.closed:
                await ws.close()

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for ws in list(self.active_connections):
            await ws.close()

