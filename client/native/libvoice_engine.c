#include "libvoice_engine.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define MAX_PEERS 32
#define RING_BUFFER_SIZE 16384
#define MAX_DEVICES 16

typedef struct {
    uint32_t user_id;
    bool is_active;
    bool is_speaking;
    float user_volume;
    int16_t buffer[RING_BUFFER_SIZE];
    uint32_t read_idx;
    uint32_t write_idx;
} PeerStream;

static AudioEngineConfig g_config;
static AudioEngineStats g_stats;
static bool g_initialized = false;
static bool g_capturing = false;
static bool g_playing = false;

static bool g_local_muted = false;
static bool g_local_deafened = false;
static bool g_ptt_pressed = false;
static bool g_vad_mode = true;
static float g_vad_threshold = -45.0f;

static PeerStream g_peers[MAX_PEERS];
static OnSpeakingStateChangedCallback g_speaking_cb = NULL;
static OnAudioPacketReadyCallback g_packet_ready_cb = NULL;

static char g_input_device_id[128] = "default_input";
static char g_output_device_id[128] = "default_output";

VOICE_API int32_t voice_engine_init(const AudioEngineConfig* config) {
    if (!config) return -1;

    g_config = *config;
    if (g_config.sample_rate == 0) g_config.sample_rate = 48000;
    if (g_config.channels == 0) g_config.channels = 1;
    if (g_config.frame_duration_ms == 0) g_config.frame_duration_ms = 20;
    if (g_config.vad_threshold_db == 0.0f) g_config.vad_threshold_db = -45.0f;
    if (g_config.vad_hangover_ms == 0) g_config.vad_hangover_ms = 200;

    memset(&g_stats, 0, sizeof(AudioEngineStats));
    g_stats.input_level_db = -90.0f;

    for (int i = 0; i < MAX_PEERS; i++) {
        g_peers[i].user_id = 0;
        g_peers[i].is_active = false;
        g_peers[i].is_speaking = false;
        g_peers[i].user_volume = 1.0f;
        g_peers[i].read_idx = 0;
        g_peers[i].write_idx = 0;
    }

    g_initialized = true;
    return 0;
}

VOICE_API void voice_engine_destroy(void) {
    voice_engine_stop_capture();
    voice_engine_stop_playback();
    g_initialized = false;
}

VOICE_API int32_t voice_engine_get_input_devices(AudioDeviceInfo* devices, int32_t max_count) {
    if (!devices || max_count < 1) return 0;

    int32_t count = 0;
    
    // Default system microphone
    snprintf(devices[count].id, sizeof(devices[count].id), "default_input");
    snprintf(devices[count].name, sizeof(devices[count].name), "Default System Microphone (WASAPI/PulseAudio)");
    devices[count].is_default = true;
    count++;

    if (count < max_count) {
        snprintf(devices[count].id, sizeof(devices[count].id), "headset_mic");
        snprintf(devices[count].name, sizeof(devices[count].name), "Headset Microphone");
        devices[count].is_default = false;
        count++;
    }

    if (count < max_count) {
        snprintf(devices[count].id, sizeof(devices[count].id), "usb_mic");
        snprintf(devices[count].name, sizeof(devices[count].name), "USB Studio Microphone");
        devices[count].is_default = false;
        count++;
    }

    return count;
}

VOICE_API int32_t voice_engine_get_output_devices(AudioDeviceInfo* devices, int32_t max_count) {
    if (!devices || max_count < 1) return 0;

    int32_t count = 0;

    // Default system speakers
    snprintf(devices[count].id, sizeof(devices[count].id), "default_output");
    snprintf(devices[count].name, sizeof(devices[count].name), "Default System Speakers (WASAPI/PulseAudio)");
    devices[count].is_default = true;
    count++;

    if (count < max_count) {
        snprintf(devices[count].id, sizeof(devices[count].id), "headphones");
        snprintf(devices[count].name, sizeof(devices[count].name), "Headphones / Gaming Headset");
        devices[count].is_default = false;
        count++;
    }

    if (count < max_count) {
        snprintf(devices[count].id, sizeof(devices[count].id), "line_out");
        snprintf(devices[count].name, sizeof(devices[count].name), "Digital Line Out");
        devices[count].is_default = false;
        count++;
    }

    return count;
}

VOICE_API int32_t voice_engine_set_input_device(const char* device_id) {
    if (!device_id) return -1;
    strncpy(g_input_device_id, device_id, sizeof(g_input_device_id) - 1);
    return 0;
}

VOICE_API int32_t voice_engine_set_output_device(const char* device_id) {
    if (!device_id) return -1;
    strncpy(g_output_device_id, device_id, sizeof(g_output_device_id) - 1);
    return 0;
}

VOICE_API int32_t voice_engine_start_capture(void) {
    g_capturing = true;
    return 0;
}

VOICE_API int32_t voice_engine_stop_capture(void) {
    g_capturing = false;
    return 0;
}

VOICE_API int32_t voice_engine_start_playback(void) {
    g_playing = true;
    return 0;
}

VOICE_API int32_t voice_engine_stop_playback(void) {
    g_playing = false;
    return 0;
}

VOICE_API void voice_engine_set_ptt_state(bool is_pressed) {
    g_ptt_pressed = is_pressed;
}

VOICE_API void voice_engine_set_vad_mode(bool enabled, float threshold_db) {
    g_vad_mode = enabled;
    g_vad_threshold = threshold_db;
}

VOICE_API void voice_engine_set_local_mute(bool muted) {
    g_local_muted = muted;
}

VOICE_API void voice_engine_set_local_deafen(bool deafened) {
    g_local_deafened = deafened;
}

VOICE_API void voice_engine_set_user_volume(uint32_t user_id, float volume_multiplier) {
    for (int i = 0; i < MAX_PEERS; i++) {
        if (g_peers[i].is_active && g_peers[i].user_id == user_id) {
            g_peers[i].user_volume = volume_multiplier;
            return;
        }
    }

    // Allocate new peer slot
    for (int i = 0; i < MAX_PEERS; i++) {
        if (!g_peers[i].is_active) {
            g_peers[i].user_id = user_id;
            g_peers[i].is_active = true;
            g_peers[i].user_volume = volume_multiplier;
            return;
        }
    }
}

VOICE_API void voice_engine_feed_inbound_packet(const uint8_t* packet_bytes, uint32_t length) {
    if (!packet_bytes || length < 20) return;

    g_stats.packets_received++;

    // Parse UDP wire header
    uint8_t magic = packet_bytes[0];
    if (magic != 0x56) return;

    uint8_t flags = packet_bytes[3];
    bool vad = (flags & 0x01) != 0;
    float energy = (float)((flags & 0xF0) >> 4) / 15.0f;

    uint32_t sender_id = ((uint32_t)packet_bytes[4] << 24) |
                         ((uint32_t)packet_bytes[5] << 16) |
                         ((uint32_t)packet_bytes[6] << 8)  |
                         ((uint32_t)packet_bytes[7]);

    if (g_speaking_cb) {
        g_speaking_cb(sender_id, vad, energy);
    }
}

VOICE_API void voice_engine_register_callbacks(
    OnSpeakingStateChangedCallback on_speaking,
    OnAudioPacketReadyCallback on_packet_ready
) {
    g_speaking_cb = on_speaking;
    g_packet_ready_cb = on_packet_ready;
}

VOICE_API void voice_engine_get_stats(AudioEngineStats* stats) {
    if (stats) {
        *stats = g_stats;
    }
}

// Internal Software Audio Mixer with Soft-Clipping Limiter
void mix_audio_streams(int16_t* output_buffer, uint32_t frame_samples) {
    if (!output_buffer || frame_samples == 0 || g_local_deafened) {
        if (output_buffer) memset(output_buffer, 0, frame_samples * sizeof(int16_t));
        return;
    }

    float mix_accumulator[960];
    uint32_t samples = frame_samples > 960 ? 960 : frame_samples;
    memset(mix_accumulator, 0, samples * sizeof(float));

    for (int i = 0; i < MAX_PEERS; i++) {
        if (!g_peers[i].is_active) continue;

        float gain = g_peers[i].user_volume;
        for (uint32_t s = 0; s < samples; s++) {
            if (g_peers[i].read_idx != g_peers[i].write_idx) {
                int16_t pcm = g_peers[i].buffer[g_peers[i].read_idx];
                g_peers[i].read_idx = (g_peers[i].read_idx + 1) % RING_BUFFER_SIZE;
                mix_accumulator[s] += ((float)pcm) * gain;
            }
        }
    }

    // Cubic polynomial soft limiter to prevent digital clipping
    for (uint32_t s = 0; s < samples; s++) {
        float x = mix_accumulator[s] / 32768.0f;
        float y;
        if (x > 1.0f) {
            y = 1.0f;
        } else if (x < -1.0f) {
            y = -1.0f;
        } else {
            y = x - (x * x * x) / 3.0f;
        }
        output_buffer[s] = (int16_t)(y * 32767.0f);
    }
}
