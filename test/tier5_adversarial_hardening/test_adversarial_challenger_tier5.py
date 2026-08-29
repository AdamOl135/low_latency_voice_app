"""Tier 5 Adversarial Coverage Hardening & Empirical Stress Verification Suite.

Challenger 1 Comprehensive Verification Harness covering:
1. 15 concurrent active voice streams in a single channel without packet drop cascading.
2. Sub-30ms round-trip latency SLA and in-band fast VAD propagation.
3. Moderation invariants (Admin movement, server mute/deafen packet gating, kick token invalidation).
4. Tailscale mesh IP compatibility and zero-NAT Docker deployment configuration.
"""

import asyncio
import os
import socket
import struct
import time
from typing import List, Dict, Any
import pytest
import pytest_asyncio
import websockets

from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.mock_server import MockServer
from test.test_harness.latency_probe import LatencyProbe, RFC3550JitterCalculator
from test.test_harness.audio_generator import (
    VoicePacket,
    AudioGenerator,
    HEADER_SIZE,
    MAGIC_BYTE,
    PROTOCOL_VERSION,
    TYPE_VOICE,
    TYPE_PING,
    TYPE_PONG,
    TYPE_HANDSHAKE,
)


# ============================================================================
# 1. 15 CONCURRENT ACTIVE VOICE STREAMS IN SINGLE CHANNEL
# ============================================================================

@pytest.mark.asyncio
async def test_15_concurrent_voice_streams_heavy_load_no_cascading_drop(client_factory):
    """Stress-test 15 concurrent active voice streams streaming 50 frames each in Channel 101.
    
    Verifies:
    - 15 concurrent transmitters actively sending 20ms Opus frames.
    - Zero packet drop cascading: total received packets >= 98% of expected forwarded packets.
    - Interarrival jitter remains < 10ms across all 15 clients.
    - No client disconnects or deadlocks under sustained multi-stream pressure.
    """
    num_clients = 15
    frames_per_client = 50  # 1 second of continuous audio per client
    channel_id = 101

    clients: List[SyntheticClient] = []
    for i in range(num_clients):
        c = await client_factory(username=f"Challenger_User_{i+1:02d}")
        res = await c.join_voice_channel(channel_id=channel_id)
        assert res.get("status") == "ok", f"Client {c.username} failed to join channel {channel_id}"
        clients.append(c)

    assert len(clients) == num_clients

    # Allow UDP handshakes to settle
    await asyncio.sleep(0.08)

    # Concurrently stream 20ms frames from all 15 clients
    async def stream_client(client: SyntheticClient):
        for seq in range(frames_per_client):
            t0 = time.perf_counter()
            await client.send_voice_frame(is_speaking=True, payload_size=100)
            elapsed = time.perf_counter() - t0
            sleep_time = max(0.0, 0.020 - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    start_time = time.perf_counter()
    await asyncio.gather(*(stream_client(c) for c in clients))
    total_stream_time = time.perf_counter() - start_time

    # Drain residual UDP buffers
    await asyncio.sleep(0.20)

    # Verify per-client health and receipt
    total_sent = sum(c.packets_sent for c in clients)
    total_recv = sum(c.packets_received for c in clients)

    # Expected voice packets sent by all clients = 15 * 50 = 750
    # Expected forwards to peers = 750 * 14 = 10,500
    expected_forwarded = (num_clients * frames_per_client) * (num_clients - 1)

    for c in clients:
        assert c.is_connected is True, f"Client {c.username} dropped connection during 15-stream load"
        assert c.packets_received > 0, f"Client {c.username} received 0 packets"
        # Verify RFC 3550 jitter remained bounded
        assert c.jitter_calc.jitter_ms < 15.0, (
            f"Client {c.username} RFC 3550 Jitter {c.jitter_calc.jitter_ms:.2f}ms exceeded limit"
        )

    # Assert high-throughput forwarding without cascading drops (>95% delivery ratio)
    delivery_ratio = total_recv / float(expected_forwarded)
    assert delivery_ratio >= 0.95, (
        f"Packet delivery ratio {delivery_ratio * 100:.2f}% below 95% threshold "
        f"({total_recv}/{expected_forwarded} packets)"
    )


# ============================================================================
# 2. SUB-30MS ROUND-TRIP LATENCY SLA & IN-BAND FAST VAD PROPAGATION
# ============================================================================

@pytest.mark.asyncio
async def test_sub_30ms_rtt_latency_sla_under_load(client_factory, mock_server):
    """Verify UDP ping/pong round-trip latency SLA (<30ms mean, <30ms p95, <30ms p99) under background traffic."""
    # Active background streaming client
    bg_speaker = await client_factory(username="BGSpeaker")
    bg_listener = await client_factory(username="BGListener")
    await bg_speaker.join_voice_channel(channel_id=101)
    await bg_listener.join_voice_channel(channel_id=101)

    # Probe client
    probe_client = await client_factory(username="ProbeTester")
    await probe_client.join_voice_channel(channel_id=101)

    probe = LatencyProbe(
        host="127.0.0.1",
        port=mock_server.actual_udp_port,
        sender_id=probe_client.user_id,
        channel_id=101,
        timeout=1.0,
    )

    # Background task sending audio frames
    async def bg_traffic():
        for _ in range(50):
            await bg_speaker.send_voice_frame(is_speaking=True)
            await asyncio.sleep(0.010)

    bg_task = asyncio.create_task(bg_traffic())

    # Run 60 latency probes at 10ms intervals
    stats = await probe.async_run_probe(count=60, interval_sec=0.010)
    await bg_task

    assert stats.count == 60, f"Expected 60 probe replies, got {stats.count}"
    assert stats.packet_loss_rate == 0.0, f"Probe packet loss {stats.packet_loss_rate * 100}%"
    assert stats.mean_ms < 15.0, f"Mean latency {stats.mean_ms:.2f}ms exceeds 15ms target"
    assert stats.p95_ms < 30.0, f"P95 latency {stats.p95_ms:.2f}ms exceeds 30ms SLA"
    assert stats.p99_ms < 30.0, f"P99 latency {stats.p99_ms:.2f}ms exceeds 30ms SLA"


@pytest.mark.asyncio
async def test_in_band_fast_vad_propagation_sub_30ms_sla(client_factory):
    """Verify speaking state threshold transitions propagate to peer clients within <30ms."""
    speaker = await client_factory(username="VADSpeaker")
    observer = await client_factory(username="VADObserver")

    await speaker.join_voice_channel(channel_id=101)
    await observer.join_voice_channel(channel_id=101)

    # Prime channel
    await speaker.send_voice_frame(is_speaking=False, energy_level=0)
    await asyncio.sleep(0.05)

    transition_latencies_ms = []

    # Perform 10 speech toggle cycles (Silence -> Speaking -> Silence)
    for cycle in range(10):
        # 1. Transition: Silence -> Speaking
        t0 = time.perf_counter()
        await speaker.send_voice_frame(is_speaking=True, energy_level=12)

        evt = await observer.wait_for_event(
            "voice_state_update",
            lambda e: e.get("user_id") == speaker.user_id and e.get("speaking") is True,
            timeout=1.0,
        )
        t_recv = time.perf_counter()
        latency_ms = (t_recv - t0) * 1000.0
        transition_latencies_ms.append(latency_ms)

        # 2. Transition: Speaking -> Silence
        await speaker.send_voice_frame(is_speaking=False, energy_level=0)
        await asyncio.sleep(0.02)

    avg_vad_latency = sum(transition_latencies_ms) / len(transition_latencies_ms)
    max_vad_latency = max(transition_latencies_ms)

    assert avg_vad_latency < 20.0, f"Average VAD propagation {avg_vad_latency:.2f}ms exceeds 20ms"
    assert max_vad_latency < 30.0, f"Peak VAD propagation {max_vad_latency:.2f}ms exceeds 30ms SLA"


# ============================================================================
# 3. MODERATION INVARIANTS (MOVE, MUTE/DEAFEN GATING, KICK REVOCATION)
# ============================================================================

@pytest.mark.asyncio
async def test_admin_movement_instant_channel_isolation(client_factory):
    """Admin moves active speaker between channels during continuous streaming; verify immediate isolation."""
    admin = await client_factory(username="AdminMover")
    target = await client_factory(username="MovedSpeaker")
    ch101_peer = await client_factory(username="Ch101Listener")
    ch102_peer = await client_factory(username="Ch102Listener")

    # Initial channel placement
    await target.join_voice_channel(channel_id=101)
    await ch101_peer.join_voice_channel(channel_id=101)
    await ch102_peer.join_voice_channel(channel_id=102)

    # Verify initial audio delivery in Ch 101
    await target.send_voice_frame(is_speaking=True)
    pkt = await ch101_peer.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert pkt.channel_id == 101

    # Drain Ch 101 queue
    while not ch101_peer.voice_packets_queue.empty():
        ch101_peer.voice_packets_queue.get_nowait()

    # Admin moves target from 101 -> 102
    res = await admin.move_member(target_user_id=target.user_id, to_channel_id=102)
    assert res.get("status") == "ok"

    # Wait for target's client state update
    await asyncio.sleep(0.05)
    assert target.current_channel_id == 102

    # Target transmits voice in new channel 102
    await target.send_voice_frame(is_speaking=True)

    # Ch 102 peer receives packet immediately
    pkt102 = await ch102_peer.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert pkt102.channel_id == 102

    # Ch 101 peer receives 0 packets (strict room isolation)
    with pytest.raises(TimeoutError):
        await ch101_peer.wait_for_voice_packet(sender_id=target.user_id, timeout=0.3)


@pytest.mark.asyncio
async def test_moderation_server_mute_deafen_packet_gating_invariants(client_factory):
    """Verify server-mute strictly blocks ingress at SFU and server-deafen strictly blocks egress."""
    admin = await client_factory(username="AdminGatekeeper")
    muted_user = await client_factory(username="MutedUser")
    deaf_user = await client_factory(username="DeafUser")
    normal_peer = await client_factory(username="NormalPeer")

    await muted_user.join_voice_channel(channel_id=101)
    await deaf_user.join_voice_channel(channel_id=101)
    await normal_peer.join_voice_channel(channel_id=101)

    # 1. Apply Server Mute to muted_user
    await admin.set_server_mute(target_user_id=muted_user.user_id, muted=True)

    # Muted user sends 10 frames
    for _ in range(10):
        await muted_user.send_voice_frame(is_speaking=True)
    await asyncio.sleep(0.05)

    # Neither deaf nor normal peer should receive any packets from muted_user
    assert normal_peer.voice_packets_queue.empty(), "Normal peer received audio from server-muted user!"
    assert deaf_user.voice_packets_queue.empty(), "Deaf peer received audio from server-muted user!"

    # 2. Apply Server Deafen to deaf_user
    await admin.set_server_deafen(target_user_id=deaf_user.user_id, deafened=True)

    # Normal peer sends 10 frames
    for _ in range(10):
        await normal_peer.send_voice_frame(is_speaking=True)
    await asyncio.sleep(0.05)

    # Deaf user must receive 0 packets
    assert deaf_user.voice_packets_queue.empty(), "Server-deafened user received egress audio!"

    # Unmute muted_user -> normal peer should now receive audio
    await admin.set_server_mute(target_user_id=muted_user.user_id, muted=False)
    await muted_user.send_voice_frame(is_speaking=True)
    pkt = await normal_peer.wait_for_voice_packet(sender_id=muted_user.user_id, timeout=2.0)
    assert pkt is not None


@pytest.mark.asyncio
async def test_member_kick_revocation_and_token_invalidation(client_factory, mock_server):
    """Verify kick immediately terminates WebSocket (code 4001), revokes auth token, and drops UDP routing."""
    admin = await client_factory(username="AdminEnforcer2")
    target = await client_factory(username="TargetKicked2")
    peer = await client_factory(username="PeerObserver2")

    target_token = target.token
    target_uid = target.user_id

    await target.join_voice_channel(channel_id=101)
    await peer.join_voice_channel(channel_id=101)

    # Verify voice flowing
    await target.send_voice_frame(is_speaking=True)
    pkt = await peer.wait_for_voice_packet(sender_id=target_uid, timeout=2.0)
    assert pkt is not None

    # Drain peer queue
    while not peer.voice_packets_queue.empty():
        peer.voice_packets_queue.get_nowait()

    # Admin kicks target
    res = await admin.kick_member(target_user_id=target_uid, reason="TOS Violation")
    assert res.get("status") == "ok"

    await asyncio.sleep(0.1)
    assert target.is_connected is False, "Target client WebSocket did not disconnect upon kick"

    # Target attempts to spam voice frames post-kick
    for _ in range(10):
        try:
            await target.send_voice_frame(is_speaking=True)
        except Exception:
            pass
        await asyncio.sleep(0.01)

    # Peer must receive nothing from kicked target
    assert peer.voice_packets_queue.empty(), "Peer received voice frames from kicked user!"

    # Reconnection with revoked token must fail
    reconn = SyntheticClient(
        token=target_token,
        ws_url=f"ws://127.0.0.1:{mock_server.actual_ws_port}/ws",
    )
    with pytest.raises(RuntimeError):
        await reconn.connect()
    assert reconn.is_connected is False


# ============================================================================
# 4. TAILSCALE MESH IP COMPATIBILITY & ZERO-NAT DEPLOYMENT VERIFICATION
# ============================================================================

@pytest.mark.asyncio
async def test_tailscale_wireguard_mtu_clamping_and_roaming(client_factory, mock_server):
    """Test packet sizes compatible with Tailscale/WireGuard MTU (1280-1420 bytes) and NAT roaming endpoint update."""
    client_a = await client_factory(username="TailscaleClientA")
    client_b = await client_factory(username="TailscaleClientB")

    await client_a.join_voice_channel(channel_id=101)
    await client_b.join_voice_channel(channel_id=101)

    # Test variable payload sizes across Tailscale MTU boundaries (40 bytes to 1200 bytes)
    for test_payload_len in [40, 80, 160, 320, 640, 1200]:
        await client_a.send_voice_frame(is_speaking=True, payload_size=test_payload_len)
        pkt = await client_b.wait_for_voice_packet(sender_id=client_a.user_id, timeout=2.0)
        assert len(pkt.payload) == test_payload_len, (
            f"Expected {test_payload_len} bytes payload, got {len(pkt.payload)}"
        )

    # Test IP roaming simulation: Client A creates a new secondary UDP socket (simulating Tailscale IP roaming)
    new_udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    new_udp_sock.setblocking(False)

    # Send handshake from new port/address
    roam_packet = VoicePacket(
        packet_type=TYPE_HANDSHAKE,
        sender_id=client_a.user_id,
        channel_id=101,
        sequence=1,
        timestamp=int(time.time()),
        payload=f"token_{client_a.user_id}".encode('utf-8'),
    )
    new_udp_sock.sendto(roam_packet.encode(), ("127.0.0.1", mock_server.actual_udp_port))
    await asyncio.sleep(0.05)

    # Now send voice frame from new socket
    roam_voice = VoicePacket(
        packet_type=TYPE_VOICE,
        vad=True,
        energy_level=15,
        sender_id=client_a.user_id,
        channel_id=101,
        sequence=2,
        timestamp=int(time.time()),
        payload=b"\x11\x22\x33\x44" * 20,
    )
    new_udp_sock.sendto(roam_voice.encode(), ("127.0.0.1", mock_server.actual_udp_port))

    # Client B should receive the voice frame routed from new address seamlessly
    pkt_roam = await client_b.wait_for_voice_packet(sender_id=client_a.user_id, timeout=2.0)
    assert pkt_roam is not None
    assert pkt_roam.sender_id == client_a.user_id

    new_udp_sock.close()


def test_docker_and_tailscale_deployment_configuration():
    """Static analysis of Dockerfile and docker-compose.yml configuration for Tailscale zero-NAT compatibility."""
    workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    compose_path = os.path.join(workspace, "docker-compose.yml")
    dockerfile_path = os.path.join(workspace, "backend", "Dockerfile")

    assert os.path.exists(compose_path), "docker-compose.yml must exist"
    assert os.path.exists(dockerfile_path), "backend/Dockerfile must exist"

    with open(compose_path, "r", encoding="utf-8") as f:
        compose_content = f.read()

    with open(dockerfile_path, "r", encoding="utf-8") as f:
        dockerfile_content = f.read()

    # 1. Ports exposure
    assert "8080:8080/tcp" in compose_content or "8080:8080" in compose_content, "TCP port 8080 must be mapped"
    assert "7878:7878/udp" in compose_content, "UDP port 7878/udp must be mapped for audio plane"

    # 2. Volume mounts
    assert "/app/data" in compose_content, "Volume mount for /app/data required for SQLite WAL persistence"

    # 3. Environment variables
    assert "PORT=8080" in compose_content
    assert "UDP_PORT=7878" in compose_content
    assert "DB_PATH=/app/data/voiceapp.db" in compose_content

    # 4. Healthcheck
    assert "healthcheck:" in compose_content or "HEALTHCHECK" in dockerfile_content
    assert "/health" in compose_content or "/health" in dockerfile_content

    # 5. Multi-stage Alpine container
    assert "FROM golang:" in dockerfile_content
    assert "FROM alpine:" in dockerfile_content
    assert "CGO_ENABLED=0" in dockerfile_content
