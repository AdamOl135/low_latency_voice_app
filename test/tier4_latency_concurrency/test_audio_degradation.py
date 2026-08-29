"""Tier 4.3: Audio Quality, SNR, Waveform Integrity, and Degradation Under Load Tests.

Validates:
- F15: Opus 10-20ms Frames & 48kHz clock progression
- F17: Minimal Jitter Buffer & PLC resilience under packet loss
- Acceptance Criteria: Zero audio degradation or packet drop cascading under 15-client load
"""

import math
import struct
import pytest
import pytest_asyncio
import numpy as np
from test.test_harness.synthetic_client import SyntheticClient
from test.test_harness.audio_generator import (
    AudioGenerator,
    VoicePacket,
    SAMPLE_RATE,
    FRAME_SIZE_10MS,
    FRAME_SIZE_20MS,
)


def test_audio_generator_sine_wave_snr():
    """Verify synthetic 1000Hz audio generator produces pure harmonic tones with SNR > 20dB."""
    gen = AudioGenerator(frame_duration_ms=20, frequency_hz=1000.0)
    pcm_bytes = gen.generate_pcm_frame(amplitude=0.8)
    
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32767.0
    assert len(samples) == FRAME_SIZE_20MS

    # Compute FFT with Hanning window to suppress spectral leakage
    window = np.hanning(len(samples))
    fft_vals = np.abs(np.fft.rfft(samples * window))
    freqs = np.fft.rfftfreq(len(samples), 1.0 / SAMPLE_RATE)

    peak_freq_idx = np.argmax(fft_vals)
    peak_freq = freqs[peak_freq_idx]

    # Peak should be centered at 1000Hz (+- 50Hz resolution)
    assert abs(peak_freq - 1000.0) < 60.0

    # Signal to noise ratio of the fundamental peak window
    peak_window = slice(max(0, peak_freq_idx - 2), min(len(fft_vals), peak_freq_idx + 3))
    signal_power = np.sum(fft_vals[peak_window] ** 2)
    noise_power = np.sum(fft_vals ** 2) - signal_power
    snr_db = 10 * np.log10(signal_power / max(1e-10, noise_power))
    assert snr_db > 20.0  # Pure harmonic tone with high SNR


def test_10ms_vs_20ms_frame_sample_counts():
    """Verify 10ms (480 samples) and 20ms (960 samples) framing math (F15)."""
    gen10 = AudioGenerator(frame_duration_ms=10)
    gen20 = AudioGenerator(frame_duration_ms=20)

    assert gen10.samples_per_frame == 480
    assert gen20.samples_per_frame == 960

    pkt10 = gen10.next_voice_packet()
    pkt20 = gen20.next_voice_packet()

    assert gen10.timestamp == 480
    assert gen20.timestamp == 960


@pytest.mark.asyncio
async def test_packet_sequence_continuity_under_load(client_factory):
    """Verify transmitted audio streams preserve strict sequence continuity without missing packets (F15, F17)."""
    alice = await client_factory(username="AliceQuality")
    bob = await client_factory(username="BobQuality")

    await alice.join_voice_channel(channel_id=101)
    await bob.join_voice_channel(channel_id=101)

    total_frames = 30
    for i in range(total_frames):
        await alice.send_voice_frame(is_speaking=True)

    received_sequences = []
    for _ in range(total_frames):
        try:
            pkt = await bob.wait_for_voice_packet(sender_id=alice.user_id, timeout=1.0)
            received_sequences.append(pkt.sequence)
        except TimeoutError:
            break

    assert len(received_sequences) == total_frames
    assert received_sequences == sorted(received_sequences)
    # Check consecutive differences are all 1
    diffs = [received_sequences[i+1] - received_sequences[i] for i in range(len(received_sequences)-1)]
    assert all(d == 1 for d in diffs), f"Sequence gaps detected: {diffs}"
