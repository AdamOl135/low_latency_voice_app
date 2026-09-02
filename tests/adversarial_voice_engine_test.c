#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <pthread.h>
#include <math.h>
#include <unistd.h>

#include "../client/native/libvoice_engine.h"

// Forward declaration of internal mixer
extern void mix_audio_streams(int16_t* output_buffer, uint32_t frame_samples);

#define SAMPLES_PER_FRAME 960
#define FRAME_BYTES 1920

// ============================================================================
// TEST 1: No Synthetic 440 Hz Tone & Complete Silence on Capture Underflow
// ============================================================================
void test_silence_on_underflow(void) {
    printf("[TEST 1] Testing silence on capture underflow (no 440 Hz synthetic tone)...\n");

    AudioEngineConfig config = {
        .sample_rate = 48000,
        .channels = 1,
        .frame_duration_ms = 20,
        .opus_bitrate = 48000,
        .vad_threshold_db = -45.0f,
        .vad_hangover_ms = 200
    };

    int32_t init_res = voice_engine_init(&config);
    assert(init_res == 0);

    uint8_t buffer[FRAME_BYTES];
    float level_db = 0.0f;
    bool is_speaking = true;
    uint8_t energy_level = 99;

    // Test 1a: Capture when engine capture is NOT started
    for (int i = 0; i < 50; i++) {
        memset(buffer, 0xFF, sizeof(buffer));
        int32_t ret = voice_engine_capture_frame(buffer, sizeof(buffer), &level_db, &is_speaking, &energy_level);
        assert(ret == FRAME_BYTES);
        for (int b = 0; b < FRAME_BYTES; b++) {
            if (buffer[b] != 0x00) {
                fprintf(stderr, "FAIL: Non-zero byte 0x%02X at offset %d when not capturing!\n", buffer[b], b);
                exit(1);
            }
        }
        assert(fabsf(level_db - (-90.0f)) < 0.001f);
        assert(is_speaking == false);
        assert(energy_level == 0);
    }

    // Test 1b: Capture when engine capture IS started but ring buffer has no mic data
    voice_engine_start_capture();
    for (int i = 0; i < 50; i++) {
        memset(buffer, 0xFF, sizeof(buffer));
        int32_t ret = voice_engine_capture_frame(buffer, sizeof(buffer), &level_db, &is_speaking, &energy_level);
        assert(ret == FRAME_BYTES);
        for (int b = 0; b < FRAME_BYTES; b++) {
            if (buffer[b] != 0x00) {
                fprintf(stderr, "FAIL: Non-zero byte 0x%02X at offset %d during capture underflow!\n", buffer[b], b);
                exit(1);
            }
        }
        assert(fabsf(level_db - (-90.0f)) < 0.001f);
        assert(is_speaking == false);
        assert(energy_level == 0);
    }

    // Test 1c: Local mute active during capture
    voice_engine_set_local_mute(true);
    for (int i = 0; i < 50; i++) {
        memset(buffer, 0xFF, sizeof(buffer));
        int32_t ret = voice_engine_capture_frame(buffer, sizeof(buffer), &level_db, &is_speaking, &energy_level);
        assert(ret == FRAME_BYTES);
        for (int b = 0; b < FRAME_BYTES; b++) {
            assert(buffer[b] == 0x00);
        }
        assert(fabsf(level_db - (-90.0f)) < 0.001f);
        assert(is_speaking == false);
        assert(energy_level == 0);
    }
    voice_engine_set_local_mute(false);

    voice_engine_stop_capture();
    voice_engine_destroy();
    printf("[TEST 1] PASS: All underflow frames are 100%% zeroed silence (-90.0 dBFS, energy 0, is_speaking=false).\n");
}

// ============================================================================
// TEST 2: Soft Limiter & Mixer Behavior Under Extreme High-Amplitude Inputs
// ============================================================================
void test_soft_limiter_and_mixer(void) {
    printf("[TEST 2] Testing soft limiter & mixer under extreme high-amplitude inputs...\n");

    AudioEngineConfig config = {
        .sample_rate = 48000,
        .channels = 1,
        .frame_duration_ms = 20,
        .opus_bitrate = 48000,
        .vad_threshold_db = -45.0f,
        .vad_hangover_ms = 200
    };

    voice_engine_init(&config);
    voice_engine_start_playback();

    // Construct high-amplitude packets for 10 peers simultaneously
    // Each peer sending full-scale square wave: +32767
    uint8_t packet[20 + FRAME_BYTES];
    packet[0] = 0x56; // magic
    packet[1] = 0x01; // version
    packet[2] = 0x01; // type voice
    packet[3] = 0xF1; // vad=1, energy=15

    // Payload length = 1920 (0x0780)
    packet[14] = 0x07;
    packet[15] = 0x80;

    int16_t* pcm_payload = (int16_t*)(packet + 20);
    for (int s = 0; s < SAMPLES_PER_FRAME; s++) {
        pcm_payload[s] = 32767;
    }

    // Feed 10 peers with volume 2.0x -> unclipped sum would be 10 * 32767 * 2 = 655,340!
    for (uint32_t peer_id = 1; peer_id <= 10; peer_id++) {
        packet[4] = (peer_id >> 24) & 0xFF;
        packet[5] = (peer_id >> 16) & 0xFF;
        packet[6] = (peer_id >> 8) & 0xFF;
        packet[7] = peer_id & 0xFF;

        voice_engine_feed_inbound_packet(packet, sizeof(packet));
        voice_engine_set_user_volume(peer_id, 2.0f);
    }

    int16_t mixed_output[SAMPLES_PER_FRAME];
    memset(mixed_output, 0, sizeof(mixed_output));

    mix_audio_streams(mixed_output, SAMPLES_PER_FRAME);

    // Verify all mixed output samples are within [-32767, 32767] with no wrap-around/overflow
    for (int s = 0; s < SAMPLES_PER_FRAME; s++) {
        int16_t val = mixed_output[s];
        if (val < -32767 || val > 32767) {
            fprintf(stderr, "FAIL: Sample %d out of bounds: %d\n", s, val);
            exit(1);
        }
        // Because x > 1.0f, the cubic limiter should clamp y to 1.0f -> output is 32767
        if (val != 32767) {
            fprintf(stderr, "FAIL: Expected clamped output 32767, got %d\n", val);
            exit(1);
        }
    }

    // Now test with negative full scale: -32768
    for (int s = 0; s < SAMPLES_PER_FRAME; s++) {
        pcm_payload[s] = -32768;
    }
    for (uint32_t peer_id = 1; peer_id <= 10; peer_id++) {
        packet[4] = (peer_id >> 24) & 0xFF;
        packet[5] = (peer_id >> 16) & 0xFF;
        packet[6] = (peer_id >> 8) & 0xFF;
        packet[7] = peer_id & 0xFF;

        voice_engine_feed_inbound_packet(packet, sizeof(packet));
    }
    mix_audio_streams(mixed_output, SAMPLES_PER_FRAME);
    for (int s = 0; s < SAMPLES_PER_FRAME; s++) {
        int16_t val = mixed_output[s];
        // x < -1.0f -> y = -1.0f -> output is -32767
        if (val != -32767) {
            fprintf(stderr, "FAIL: Expected clamped negative output -32767, got %d\n", val);
            exit(1);
        }
    }

    // Test polynomial range [-1.0, 1.0]: smooth cubic compression
    // For x = 0.5 (pcm = 16384), y = 0.5 - (0.125)/3 = 0.5 - 0.0416667 = 0.458333 -> val ~ 15018
    voice_engine_clear_peers();
    for (int s = 0; s < SAMPLES_PER_FRAME; s++) {
        pcm_payload[s] = 16384;
    }
    packet[4] = 0; packet[5] = 0; packet[6] = 0; packet[7] = 42;
    voice_engine_feed_inbound_packet(packet, sizeof(packet));
    voice_engine_set_user_volume(42, 1.0f);

    mix_audio_streams(mixed_output, SAMPLES_PER_FRAME);
    for (int s = 0; s < SAMPLES_PER_FRAME; s++) {
        int16_t val = mixed_output[s];
        assert(val >= 15000 && val <= 15050);
    }

    voice_engine_clear_peers();
    voice_engine_stop_playback();
    voice_engine_destroy();
    printf("[TEST 2] PASS: Soft limiter prevents digital clipping and integer overflow across extreme multi-peer loads.\n");
}

// ============================================================================
// TEST 3: High-Concurrency Multi-Threaded Stress Test (Thread Safety)
// ============================================================================
#define NUM_STRESS_THREADS 6
#define STRESS_ITERATIONS 5000

static volatile bool g_stress_running = true;

void* capture_worker(void* arg) {
    uint8_t buffer[FRAME_BYTES];
    float level_db;
    bool is_speaking;
    uint8_t energy;
    for (int i = 0; i < STRESS_ITERATIONS && g_stress_running; i++) {
        voice_engine_capture_frame(buffer, sizeof(buffer), &level_db, &is_speaking, &energy);
        usleep(100);
    }
    return NULL;
}

void* inbound_feed_worker(void* arg) {
    int worker_id = (int)(intptr_t)arg;
    uint8_t packet[20 + FRAME_BYTES];
    memset(packet, 0, sizeof(packet));
    packet[0] = 0x56;
    packet[1] = 0x01;
    packet[2] = 0x01;
    packet[3] = 0x11;
    packet[14] = 0x07;
    packet[15] = 0x80;

    for (int i = 0; i < STRESS_ITERATIONS && g_stress_running; i++) {
        uint32_t peer_id = (uint32_t)((worker_id * 5) + (i % 5) + 1);
        packet[4] = (peer_id >> 24) & 0xFF;
        packet[5] = (peer_id >> 16) & 0xFF;
        packet[6] = (peer_id >> 8) & 0xFF;
        packet[7] = peer_id & 0xFF;

        int16_t* pcm = (int16_t*)(packet + 20);
        for (int s = 0; s < SAMPLES_PER_FRAME; s++) {
            pcm[s] = (int16_t)((i * 17 + s) % 10000);
        }

        voice_engine_feed_inbound_packet(packet, sizeof(packet));
        usleep(150);
    }
    return NULL;
}

void* volume_and_controls_worker(void* arg) {
    for (int i = 0; i < STRESS_ITERATIONS && g_stress_running; i++) {
        uint32_t peer_id = (uint32_t)((i % 25) + 1);
        float vol = ((i % 20) / 10.0f); // 0.0 to 1.9
        voice_engine_set_user_volume(peer_id, vol);
        if (i % 50 == 0) {
            voice_engine_set_local_mute(i % 100 == 0);
        }
        if (i % 70 == 0) {
            voice_engine_set_local_deafen(i % 140 == 0);
        }
        if (i % 100 == 0) {
            voice_engine_set_mic_test_loopback(i % 200 == 0);
        }
        if (i % 250 == 0) {
            voice_engine_clear_peers();
        }
        usleep(200);
    }
    return NULL;
}

void* mixer_worker(void* arg) {
    int16_t output[SAMPLES_PER_FRAME];
    for (int i = 0; i < STRESS_ITERATIONS && g_stress_running; i++) {
        mix_audio_streams(output, SAMPLES_PER_FRAME);
        usleep(200);
    }
    return NULL;
}

void test_high_concurrency_stress(void) {
    printf("[TEST 3] Testing high-concurrency thread safety (%d threads, %d iterations)...\n",
           NUM_STRESS_THREADS, STRESS_ITERATIONS);

    AudioEngineConfig config = {
        .sample_rate = 48000,
        .channels = 1,
        .frame_duration_ms = 20,
        .opus_bitrate = 48000,
        .vad_threshold_db = -45.0f,
        .vad_hangover_ms = 200
    };

    voice_engine_init(&config);
    voice_engine_start_capture();
    voice_engine_start_playback();

    g_stress_running = true;
    pthread_t threads[NUM_STRESS_THREADS];

    pthread_create(&threads[0], NULL, capture_worker, NULL);
    pthread_create(&threads[1], NULL, capture_worker, NULL);
    pthread_create(&threads[2], NULL, inbound_feed_worker, (void*)(intptr_t)1);
    pthread_create(&threads[3], NULL, inbound_feed_worker, (void*)(intptr_t)2);
    pthread_create(&threads[4], NULL, volume_and_controls_worker, NULL);
    pthread_create(&threads[5], NULL, mixer_worker, NULL);

    for (int i = 0; i < NUM_STRESS_THREADS; i++) {
        pthread_join(threads[i], NULL);
    }

    voice_engine_stop_capture();
    voice_engine_stop_playback();
    voice_engine_destroy();

    printf("[TEST 3] PASS: Multi-threaded stress test completed cleanly with zero deadlocks or crashes.\n");
}

// ============================================================================
// TEST 4: Device Enumeration & Selection APIs
// ============================================================================
void test_device_enumeration(void) {
    printf("[TEST 4] Testing device enumeration & device selection APIs...\n");

    AudioEngineConfig config = {
        .sample_rate = 48000,
        .channels = 1,
        .frame_duration_ms = 20,
        .opus_bitrate = 48000,
        .vad_threshold_db = -45.0f,
        .vad_hangover_ms = 200
    };

    voice_engine_init(&config);

    AudioDeviceInfo in_devs[16];
    AudioDeviceInfo out_devs[16];

    int32_t in_count = voice_engine_get_input_devices(in_devs, 16);
    int32_t out_count = voice_engine_get_output_devices(out_devs, 16);

    printf("  Discovered %d input devices, %d output devices.\n", in_count, out_count);
    assert(in_count >= 1);
    assert(out_count >= 1);

    // Primary default input and output must exist
    assert(strcmp(in_devs[0].id, "default_input") == 0);
    assert(in_devs[0].is_default == true);
    assert(strcmp(out_devs[0].id, "default_output") == 0);
    assert(out_devs[0].is_default == true);

    // Test selection of default and custom device IDs
    assert(voice_engine_set_input_device("default_input") == 0);
    assert(voice_engine_set_output_device("default_output") == 0);
    assert(voice_engine_set_input_device("dev_in_0") == 0);
    assert(voice_engine_set_output_device("dev_out_0") == 0);
    assert(voice_engine_set_input_device("non_existent_device_id") == 0);
    assert(voice_engine_set_output_device("non_existent_device_id") == 0);
    assert(voice_engine_set_input_device(NULL) == -1);
    assert(voice_engine_set_output_device(NULL) == -1);

    // Boundary: 0 max_count
    assert(voice_engine_get_input_devices(in_devs, 0) == 0);
    assert(voice_engine_get_output_devices(out_devs, 0) == 0);
    assert(voice_engine_get_input_devices(NULL, 16) == 0);
    assert(voice_engine_get_output_devices(NULL, 16) == 0);

    voice_engine_destroy();
    printf("[TEST 4] PASS: Device enumeration and device selection APIs operate correctly.\n");
}

int main(void) {
    printf("================================================================\n");
    printf("  NATIVE C AUDIO ENGINE ADVERSARIAL STRESS & VERIFICATION SUITE \n");
    printf("================================================================\n");

    test_silence_on_underflow();
    test_soft_limiter_and_mixer();
    test_high_concurrency_stress();
    test_device_enumeration();

    printf("================================================================\n");
    printf("  ALL NATIVE AUDIO ENGINE ADVERSARIAL TESTS PASSED (100%%)      \n");
    printf("================================================================\n");
    return 0;
}

