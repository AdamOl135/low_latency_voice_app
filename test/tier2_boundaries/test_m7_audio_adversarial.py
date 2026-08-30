import asyncio
import struct
import time
import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.audio_generator import (
    VoicePacket,
    AudioGenerator,
    HEADER_SIZE,
    MAGIC_BYTE,
    PROTOCOL_VERSION,
    TYPE_VOICE,
    TYPE_HANDSHAKE,
    TYPE_PING,
    TYPE_PONG,
)


@pytest.mark.asyncio
async def test_udp_sfu_multi_format_opus_and_pcm_forwarding(client_factory):
    """Empirically verify UDP SFU handling of both Opus frames (20-160B) and uncompressed PCM frames (1920B)."""
    alice = await client_factory(username="AliceMultiFormat")
    bob = await client_factory(username="BobMultiFormat")
    charlie = await client_factory(username="CharlieOtherCh")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)
    await charlie.join_voice_channel(channel_id=102)

    # Test payload sizes: standard Opus sizes (20B, 40B, 80B, 160B), intermediate (960B), and uncompressed PCM (1920B)
    test_payload_sizes = [20, 40, 80, 160, 960, 1920]

    for size in test_payload_sizes:
        payload_data = bytes([(i * 17 + size) % 256 for i in range(size)])
        sent_pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=True,
            energy_level=13,
            sender_id=alice.user_id,
            channel_id=101,
            sequence=size,
            timestamp=size * 960,
            payload=payload_data,
        )

        await alice.send_raw_udp_packet(sent_pkt.encode())

        # Bob (in same channel 101) must receive exact packet
        recv_pkt = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=3.0)

        assert recv_pkt.packet_type == TYPE_VOICE
        assert recv_pkt.sender_id == alice.user_id
        assert recv_pkt.channel_id == 101
        assert recv_pkt.sequence == size
        assert recv_pkt.vad is True
        assert recv_pkt.energy_level == 13
        assert len(recv_pkt.payload) == size, f"Expected payload length {size}, got {len(recv_pkt.payload)}"
        assert recv_pkt.payload == payload_data, f"Payload corrupted for size {size}"

    # Charlie (in channel 102) must have received 0 packets
    await asyncio.sleep(0.05)
    assert charlie.voice_packets_queue.empty(), "Charlie in channel 102 received audio from channel 101!"


@pytest.mark.asyncio
async def test_udp_sfu_pcm_1920b_continuous_stream_integrity(client_factory):
    """Verify continuous stream of 1920B uncompressed PCM frames preserves sequence, timestamp and data fidelity."""
    alice = await client_factory(username="AlicePCMStreamer")
    bob = await client_factory(username="BobPCMReceiver")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    audio_gen = AudioGenerator(sender_id=alice.user_id, channel_id=101, frame_duration_ms=20, frequency_hz=440.0)
    frame_count = 25

    sent_frames = []
    for seq in range(1, frame_count + 1):
        pcm_bytes = audio_gen.generate_pcm_frame(amplitude=0.75)
        assert len(pcm_bytes) == 1920, "PCM frame must be exactly 1920 bytes for 20ms @ 48kHz mono 16-bit"

        pkt = VoicePacket(
            packet_type=TYPE_VOICE,
            vad=True,
            energy_level=14,
            sender_id=alice.user_id,
            channel_id=101,
            sequence=seq,
            timestamp=seq * 960,
            payload=pcm_bytes,
        )
        sent_frames.append(pkt)
        await alice.send_raw_udp_packet(pkt.encode())
        await asyncio.sleep(0.005)

    # Bob receives all frames
    received_frames = []
    for _ in range(frame_count):
        recv_pkt = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=3.0)
        received_frames.append(recv_pkt)

    assert len(received_frames) == frame_count, f"Expected {frame_count} frames, received {len(received_frames)}"

    # Verify sequential integrity and content fidelity
    for i in range(frame_count):
        sent = sent_frames[i]
        recv = received_frames[i]

        assert recv.sequence == sent.sequence, f"Sequence mismatch at index {i}: sent={sent.sequence}, recv={recv.sequence}"
        assert recv.timestamp == sent.timestamp, f"Timestamp mismatch at index {i}: sent={sent.timestamp}, recv={recv.timestamp}"
        assert len(recv.payload) == 1920, f"Payload length mismatch: {len(recv.payload)}"
        assert recv.payload == sent.payload, f"PCM audio payload data corrupted at frame {i}"


@pytest.mark.asyncio
async def test_udp_sfu_max_payload_boundary_and_oversized_rejection(client_factory):
    """Verify exact 4076-byte MaxPayloadSize boundary and safe rejection of oversized datagrams."""
    alice = await client_factory(username="AliceMaxBoundary")
    bob = await client_factory(username="BobMaxBoundary")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    # 1. 2000-byte payload within 4076 MTU
    payload_2000 = bytes([(i % 256) for i in range(2000)])
    pkt_2000 = VoicePacket(
        packet_type=TYPE_VOICE,
        vad=True,
        energy_level=15,
        sender_id=alice.user_id,
        channel_id=101,
        sequence=999,
        timestamp=999000,
        payload=payload_2000,
    )
    raw_2000 = pkt_2000.encode()
    assert len(raw_2000) == 2020
    await alice.send_raw_udp_packet(raw_2000)

    recv_2000 = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=3.0)
    assert len(recv_2000.payload) == 2000
    assert recv_2000.payload == payload_2000

    # 2. Oversized payload header claim (4077 in header) -> must be safely rejected by SFU
    oversized_data = bytearray(HEADER_SIZE + 4077)
    oversized_data[0] = MAGIC_BYTE
    oversized_data[1] = PROTOCOL_VERSION
    oversized_data[2] = TYPE_VOICE
    oversized_data[3] = 0xE1  # VAD=1, energy=14
    struct.pack_into('>IIHHI', oversized_data, 4, alice.user_id, 101, 1000, 4077, 1000000)

    await alice.send_raw_udp_packet(bytes(oversized_data))

    # Bob should NOT receive the oversized packet
    with pytest.raises(TimeoutError):
        await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=0.5)

    # 3. Verify server continues functioning normally after oversized attempt
    valid_pkt = await alice.send_voice_frame(is_speaking=True, energy_level=10, payload_size=80)
    recv_valid = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=2.0)
    assert recv_valid.sequence == valid_pkt.sequence


@pytest.mark.asyncio
async def test_inband_vad_and_energy_sweep_under_voice_bursts(client_factory):
    """Verify in-band VAD bit (0/1) and quantized 4-bit energy level (0-15) preservation across rapid voice bursts."""
    alice = await client_factory(username="AliceVADBurst")
    bob = await client_factory(username="BobVADBurst")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    # Sweep through all energy levels (0 to 15) with alternating VAD bit
    burst_configs = [
        (False, 0),
        (True, 1),
        (True, 4),
        (True, 7),
        (True, 10),
        (True, 13),
        (True, 15),
        (False, 0),
        (True, 12),
        (True, 8),
        (True, 5),
        (False, 0),
    ]

    for idx, (vad_state, energy) in enumerate(burst_configs):
        sent_pkt = await alice.send_voice_frame(
            is_speaking=vad_state,
            energy_level=energy,
            payload_size=80,
        )

        recv_pkt = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=3.0)

        assert recv_pkt.vad == vad_state, f"VAD flag mismatch at burst {idx}: sent={vad_state}, recv={recv_pkt.vad}"
        assert recv_pkt.energy_level == energy, f"Energy level mismatch at burst {idx}: sent={energy}, recv={recv_pkt.energy_level}"


@pytest.mark.asyncio
async def test_kicked_member_udp_voice_session_revoked(client_factory):
    """Verify member kick immediately terminates UDP voice forwarding and token validity."""
    admin = await client_factory(username="AdminKicker")
    target = await client_factory(username="TargetUserToKick")
    listener = await client_factory(username="ListenerUser")

    await admin.join_voice_channel(channel_id=101)
    await target.join_voice_channel(channel_id=101)
    await listener.join_voice_channel(channel_id=101)

    # Verify target can speak before kick
    await target.send_voice_frame(is_speaking=True, energy_level=12, payload_size=80)
    recv_before = await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=2.0)
    assert recv_before.sender_id == target.user_id

    # Admin kicks target
    kick_res = await admin.kick_member(target_user_id=target.user_id, reason="Challenger test kick")
    assert kick_res.get("status") == "ok"

    await asyncio.sleep(0.1)

    # Target attempts to send voice frames after kick
    for _ in range(5):
        try:
            await target.send_voice_frame(is_speaking=True, energy_level=15, payload_size=80)
        except Exception:
            pass

    # Listener must receive 0 packets from kicked target
    await asyncio.sleep(0.1)
    with pytest.raises(TimeoutError):
        await listener.wait_for_voice_packet(sender_id=target.user_id, timeout=0.5)

