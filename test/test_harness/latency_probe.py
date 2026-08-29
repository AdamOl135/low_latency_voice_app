"""High-Precision Latency Probe & RFC 3550 Jitter Calculator.

Provides:
- Nanosecond-precision UDP Ping/Pong probe (Type 0x02/0x03)
- Statistical aggregation: Min, Max, Mean, Median, P95, P99 RTT
- One-way latency estimation
- RFC 3550 Interarrival Jitter computation
- SLA verification for sub-30ms voice packet processing
"""

import asyncio
import socket
import struct
import time
import statistics
from typing import List, Dict, Optional, Tuple, Any
from test.test_harness.audio_generator import (
    VoicePacket,
    TYPE_PING,
    TYPE_PONG,
    TYPE_VOICE,
    MAGIC_BYTE,
    PROTOCOL_VERSION,
    SAMPLE_RATE,
)


class LatencyStats:
    """Statistical summary of latency and jitter measurements."""

    def __init__(self, rtt_samples_ms: List[float], jitter_ms: float = 0.0, packet_loss_rate: float = 0.0):
        self.count = len(rtt_samples_ms)
        self.samples = rtt_samples_ms
        self.jitter_ms = jitter_ms
        self.packet_loss_rate = packet_loss_rate

        if self.count > 0:
            self.min_ms = min(rtt_samples_ms)
            self.max_ms = max(rtt_samples_ms)
            self.mean_ms = statistics.mean(rtt_samples_ms)
            self.median_ms = statistics.median(rtt_samples_ms)
            sorted_samples = sorted(rtt_samples_ms)
            p95_idx = int(0.95 * (self.count - 1))
            p99_idx = int(0.99 * (self.count - 1))
            self.p95_ms = sorted_samples[p95_idx]
            self.p99_ms = sorted_samples[p99_idx]
            self.one_way_mean_ms = self.mean_ms / 2.0
        else:
            self.min_ms = 0.0
            self.max_ms = 0.0
            self.mean_ms = 0.0
            self.median_ms = 0.0
            self.p95_ms = 0.0
            self.p99_ms = 0.0
            self.one_way_mean_ms = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'count': self.count,
            'min_ms': round(self.min_ms, 3),
            'max_ms': round(self.max_ms, 3),
            'mean_ms': round(self.mean_ms, 3),
            'median_ms': round(self.median_ms, 3),
            'p95_ms': round(self.p95_ms, 3),
            'p99_ms': round(self.p99_ms, 3),
            'one_way_mean_ms': round(self.one_way_mean_ms, 3),
            'jitter_ms': round(self.jitter_ms, 3),
            'loss_rate_pct': round(self.packet_loss_rate * 100, 2),
        }

    def verify_sla(self, max_allowed_ms: float = 30.0) -> bool:
        """Verify latency is within the specified SLA threshold (default 30ms)."""
        if self.count == 0:
            return False
        return self.mean_ms < max_allowed_ms and self.p95_ms < max_allowed_ms


class RFC3550JitterCalculator:
    """Calculates interarrival jitter using the RFC 3550 specification algorithm:

    D(i, j) = (R_j - S_j) - (R_i - S_i)
    J(i) = J(i-1) + (|D(i-1, i)| - J(i-1)) / 16
    """

    def __init__(self, clock_rate_hz: int = SAMPLE_RATE):
        self.clock_rate_hz = clock_rate_hz
        self.last_transit_ms: Optional[float] = None
        self.jitter_ms: float = 0.0
        self.sample_count: int = 0

    def add_packet(self, sender_timestamp_samples: int, arrival_time_sec: float) -> float:
        """Update jitter given the sender's 48kHz timestamp and the local arrival wall clock."""
        # Convert sender timestamp from sample units to milliseconds
        sender_time_ms = (sender_timestamp_samples / self.clock_rate_hz) * 1000.0
        arrival_time_ms = arrival_time_sec * 1000.0
        transit_ms = arrival_time_ms - sender_time_ms

        if self.last_transit_ms is not None:
            d = abs(transit_ms - self.last_transit_ms)
            self.jitter_ms += (d - self.jitter_ms) / 16.0
        
        self.last_transit_ms = transit_ms
        self.sample_count += 1
        return self.jitter_ms

    def reset(self):
        self.last_transit_ms = None
        self.jitter_ms = 0.0
        self.sample_count = 0


class LatencyProbe:
    """Standalone high-precision UDP Ping probe."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7878,
        sender_id: int = 9999,
        channel_id: int = 101,
        timeout: float = 1.0,
    ):
        self.host = host
        self.port = port
        self.sender_id = sender_id
        self.channel_id = channel_id
        self.timeout = timeout
        self.seq = 0

    def ping_once(self, sock: Optional[socket.socket] = None) -> Optional[float]:
        """Send a single ping and return RTT in milliseconds, or None if timed out."""
        own_sock = False
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            own_sock = True

        send_ns = time.perf_counter_ns()
        payload = struct.pack('>Q', send_ns)

        pkt = VoicePacket(
            packet_type=TYPE_PING,
            vad=False,
            energy_level=0,
            sender_id=self.sender_id,
            channel_id=self.channel_id,
            sequence=self.seq,
            timestamp=int((time.time() * 48000)) & 0xFFFFFFFF,
            payload=payload,
        )
        self.seq = (self.seq + 1) & 0xFFFF

        try:
            sock.sendto(pkt.encode(), (self.host, self.port))
            data, _ = sock.recvfrom(2048)
            recv_ns = time.perf_counter_ns()

            resp = VoicePacket.decode(data)
            if resp.packet_type == TYPE_PONG and len(resp.payload) >= 8:
                orig_send_ns = struct.unpack('>Q', resp.payload[:8])[0]
                rtt_ms = (recv_ns - orig_send_ns) / 1_000_000.0
                return rtt_ms
            return None
        except (socket.timeout, BlockingIOError, OSError):
            return None
        finally:
            if own_sock:
                sock.close()

    def run_probe(self, count: int = 20, interval_sec: float = 0.01) -> LatencyStats:
        """Run multiple consecutive pings and compute statistical breakdown."""
        samples: List[float] = []
        lost_count = 0
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)

        try:
            for _ in range(count):
                rtt = self.ping_once(sock)
                if rtt is not None:
                    samples.append(rtt)
                else:
                    lost_count += 1
                if interval_sec > 0:
                    time.sleep(interval_sec)
        finally:
            sock.close()

        loss_rate = (lost_count / count) if count > 0 else 1.0
        return LatencyStats(rtt_samples_ms=samples, packet_loss_rate=loss_rate)

    async def async_ping_once(self, sock: Optional[socket.socket] = None) -> Optional[float]:
        """Asynchronously send a ping and await pong response."""
        loop = asyncio.get_running_loop()
        own_sock = False
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            own_sock = True

        send_ns = time.perf_counter_ns()
        payload = struct.pack('>Q', send_ns)

        pkt = VoicePacket(
            packet_type=TYPE_PING,
            vad=False,
            energy_level=0,
            sender_id=self.sender_id,
            channel_id=self.channel_id,
            sequence=self.seq,
            timestamp=int((time.time() * 48000)) & 0xFFFFFFFF,
            payload=payload,
        )
        self.seq = (self.seq + 1) & 0xFFFF

        try:
            await loop.sock_sendto(sock, pkt.encode(), (self.host, self.port))
            data = await asyncio.wait_for(loop.sock_recv(sock, 2048), timeout=self.timeout)
            recv_ns = time.perf_counter_ns()

            resp = VoicePacket.decode(data)
            if resp.packet_type == TYPE_PONG and len(resp.payload) >= 8:
                orig_send_ns = struct.unpack('>Q', resp.payload[:8])[0]
                rtt_ms = (recv_ns - orig_send_ns) / 1_000_000.0
                return rtt_ms
            return None
        except (asyncio.TimeoutError, OSError):
            return None
        finally:
            if own_sock:
                sock.close()

    async def async_run_probe(self, count: int = 20, interval_sec: float = 0.01) -> LatencyStats:
        """Asynchronously run multiple consecutive pings."""
        samples: List[float] = []
        lost_count = 0
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)

        try:
            for _ in range(count):
                rtt = await self.async_ping_once(sock)
                if rtt is not None:
                    samples.append(rtt)
                else:
                    lost_count += 1
                if interval_sec > 0:
                    await asyncio.sleep(interval_sec)
        finally:
            sock.close()

        loss_rate = (lost_count / count) if count > 0 else 1.0
        return LatencyStats(rtt_samples_ms=samples, packet_loss_rate=loss_rate)
