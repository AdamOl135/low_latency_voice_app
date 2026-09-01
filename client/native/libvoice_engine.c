#include "libvoice_engine.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define MINIAUDIO_IMPLEMENTATION
#include "miniaudio.h"

#define MAX_PEERS 32
#define RING_BUFFER_SIZE 32768
#define MAX_DEVICES 16
#define SAMPLES_PER_FRAME 960 // 20ms at 48kHz mono
#define BUFFER_SIZE_BYTES (SAMPLES_PER_FRAME * sizeof(int16_t)) // 1920 bytes

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
static bool g_mic_test_loopback = false;

static PeerStream g_peers[MAX_PEERS];
static OnSpeakingStateChangedCallback g_speaking_cb = NULL;
static OnAudioPacketReadyCallback g_packet_ready_cb = NULL;

static char g_input_device_id[128] = "default_input";
static char g_output_device_id[128] = "default_output";

// Circular buffer for captured hardware audio
static int16_t g_capture_ring[RING_BUFFER_SIZE];
static uint32_t g_capture_read_idx = 0;
static uint32_t g_capture_write_idx = 0;

static uint32_t g_hangover_ms_left = 0;

// miniaudio global context & devices
static ma_context g_ma_context;
static bool g_ma_context_initialized = false;
static ma_device g_capture_device;
static bool g_capture_device_initialized = false;
static ma_device g_playback_device;
static bool g_playback_device_initialized = false;

#ifdef _WIN32
#include <windows.h>
static CRITICAL_SECTION g_audio_cs;
static bool g_cs_initialized = false;

static void init_cs(void) {
    if (!g_cs_initialized) {
        InitializeCriticalSection(&g_audio_cs);
        g_cs_initialized = true;
    }
}

static void destroy_cs(void) {
    if (g_cs_initialized) {
        DeleteCriticalSection(&g_audio_cs);
        g_cs_initialized = false;
    }
}

static void enter_cs(void) {
    if (g_cs_initialized) EnterCriticalSection(&g_audio_cs);
}

static void leave_cs(void) {
    if (g_cs_initialized) LeaveCriticalSection(&g_audio_cs);
}

#else
#include <pthread.h>
static pthread_mutex_t g_audio_mutex;
static bool g_mutex_initialized = false;

static void init_cs(void) {
    if (!g_mutex_initialized) {
        pthread_mutexattr_t attr;
        pthread_mutexattr_init(&attr);
        pthread_mutexattr_settype(&attr, PTHREAD_MUTEX_RECURSIVE);
        pthread_mutex_init(&g_audio_mutex, &attr);
        pthread_mutexattr_destroy(&attr);
        g_mutex_initialized = true;
    }
}

static void destroy_cs(void) {
    if (g_mutex_initialized) {
        pthread_mutex_destroy(&g_audio_mutex);
        g_mutex_initialized = false;
    }
}

static void enter_cs(void) {
    if (g_mutex_initialized) pthread_mutex_lock(&g_audio_mutex);
}

static void leave_cs(void) {
    if (g_mutex_initialized) pthread_mutex_unlock(&g_audio_mutex);
}
#endif

// Forward declarations
void mix_audio_streams(int16_t* output_buffer, uint32_t frame_samples);
static void start_hardware_capture(void);
static void stop_hardware_capture(void);
static void start_hardware_playback(void);
static void stop_hardware_playback(void);

// miniaudio capture callback
static void ma_capture_callback(ma_device* pDevice, void* pOutput, const void* pInput, ma_uint32 frameCount) {
    (void)pOutput;
    if (!pInput || frameCount == 0 || !g_capturing) return;

    const int16_t* samples = (const int16_t*)pInput;
    ma_uint32 channels = (pDevice && pDevice->capture.channels > 0) ? pDevice->capture.channels : 1;

    enter_cs();
    if (channels <= 1) {
        for (ma_uint32 i = 0; i < frameCount; i++) {
            g_capture_ring[g_capture_write_idx] = samples[i];
            g_capture_write_idx = (g_capture_write_idx + 1) % RING_BUFFER_SIZE;
        }
    } else {
        // Multi-channel interface (e.g. Universal Audio Apollo Solo, stereo microphones)
        for (ma_uint32 i = 0; i < frameCount; i++) {
            int32_t mixed = 0;
            for (ma_uint32 c = 0; c < channels; c++) {
                mixed += (int32_t)samples[i * channels + c];
            }
            int32_t val = mixed / (int32_t)channels;
            if (val > 32767) val = 32767;
            if (val < -32768) val = -32768;
            g_capture_ring[g_capture_write_idx] = (int16_t)val;
            g_capture_write_idx = (g_capture_write_idx + 1) % RING_BUFFER_SIZE;
        }
    }
    leave_cs();
}

// miniaudio playback callback
static void ma_playback_callback(ma_device* pDevice, void* pOutput, const void* pInput, ma_uint32 frameCount) {
    (void)pInput;
    if (!pOutput || frameCount == 0) return;
    int16_t* outBuf = (int16_t*)pOutput;
    ma_uint32 channels = (pDevice && pDevice->playback.channels > 0) ? pDevice->playback.channels : 1;

    if (!g_playing || g_local_deafened) {
        memset(outBuf, 0, frameCount * channels * sizeof(int16_t));
        return;
    }

    enter_cs();
    if (channels <= 1) {
        mix_audio_streams(outBuf, frameCount);
    } else {
        // Output device is stereo or multi-channel (e.g. Topping DX3Pro+ USB DAC, stereo headphones)
        // Mix mono stream first into temporary buffer, then duplicate across all output channels
        int16_t monoBuf[SAMPLES_PER_FRAME];
        uint32_t framesRemaining = frameCount;
        uint32_t frameOffset = 0;

        while (framesRemaining > 0) {
            uint32_t chunk = (framesRemaining > SAMPLES_PER_FRAME) ? SAMPLES_PER_FRAME : framesRemaining;
            mix_audio_streams(monoBuf, chunk);

            for (uint32_t f = 0; f < chunk; f++) {
                int16_t sample = monoBuf[f];
                for (ma_uint32 c = 0; c < channels; c++) {
                    outBuf[(frameOffset + f) * channels + c] = sample;
                }
            }

            frameOffset += chunk;
            framesRemaining -= chunk;
        }
    }
    leave_cs();
}

static ma_device_id* find_capture_device_id(const char* device_id, ma_device_info* pCaptureInfos, ma_uint32 captureCount) {
    if (!device_id || strcmp(device_id, "default_input") == 0 || strlen(device_id) == 0) {
        return NULL;
    }
    unsigned int devIdx = 0;
    if (sscanf(device_id, "dev_in_%u", &devIdx) == 1 || sscanf(device_id, "winmm_in_%u", &devIdx) == 1) {
        if (devIdx < captureCount) {
            return &pCaptureInfos[devIdx].id;
        }
    }
    for (ma_uint32 i = 0; i < captureCount; i++) {
        if (strcmp(pCaptureInfos[i].name, device_id) == 0) {
            return &pCaptureInfos[i].id;
        }
    }
    return NULL;
}

static ma_device_id* find_playback_device_id(const char* device_id, ma_device_info* pPlaybackInfos, ma_uint32 playbackCount) {
    if (!device_id || strcmp(device_id, "default_output") == 0 || strlen(device_id) == 0) {
        return NULL;
    }
    unsigned int devIdx = 0;
    if (sscanf(device_id, "dev_out_%u", &devIdx) == 1 || sscanf(device_id, "winmm_out_%u", &devIdx) == 1) {
        if (devIdx < playbackCount) {
            return &pPlaybackInfos[devIdx].id;
        }
    }
    for (ma_uint32 i = 0; i < playbackCount; i++) {
        if (strcmp(pPlaybackInfos[i].name, device_id) == 0) {
            return &pPlaybackInfos[i].id;
        }
    }
    return NULL;
}

static void start_hardware_capture(void) {
    if (g_capture_device_initialized) return;
    if (!g_ma_context_initialized) {
        ma_context_config ctxConfig = ma_context_config_init();
        if (ma_context_init(NULL, 0, &ctxConfig, &g_ma_context) != MA_SUCCESS) {
            return;
        }
        g_ma_context_initialized = true;
    }

    ma_device_info* pPlaybackInfos = NULL;
    ma_uint32 playbackCount = 0;
    ma_device_info* pCaptureInfos = NULL;
    ma_uint32 captureCount = 0;
    ma_device_id* pTargetId = NULL;

    if (ma_context_get_devices(&g_ma_context, &pPlaybackInfos, &playbackCount, &pCaptureInfos, &captureCount) == MA_SUCCESS) {
        pTargetId = find_capture_device_id(g_input_device_id, pCaptureInfos, captureCount);
    }

    ma_device_config config = ma_device_config_init(ma_device_type_capture);
    config.capture.format = ma_format_s16;
    config.capture.channels = (g_config.channels > 0) ? g_config.channels : 1;
    config.sampleRate = (g_config.sample_rate > 0) ? g_config.sample_rate : 48000;
    config.dataCallback = ma_capture_callback;
    config.pUserData = NULL;
    if (pTargetId != NULL) {
        config.capture.pDeviceID = pTargetId;
    }

    if (ma_device_init(&g_ma_context, &config, &g_capture_device) == MA_SUCCESS) {
        g_capture_device_initialized = true;
        if (ma_device_start(&g_capture_device) != MA_SUCCESS) {
            ma_device_uninit(&g_capture_device);
            g_capture_device_initialized = false;
        }
    }
}

static void stop_hardware_capture(void) {
    if (!g_capture_device_initialized) return;
    ma_device_stop(&g_capture_device);
    ma_device_uninit(&g_capture_device);
    g_capture_device_initialized = false;
}

static void start_hardware_playback(void) {
    if (g_playback_device_initialized) return;
    if (!g_ma_context_initialized) {
        ma_context_config ctxConfig = ma_context_config_init();
        if (ma_context_init(NULL, 0, &ctxConfig, &g_ma_context) != MA_SUCCESS) {
            return;
        }
        g_ma_context_initialized = true;
    }

    ma_device_info* pPlaybackInfos = NULL;
    ma_uint32 playbackCount = 0;
    ma_device_info* pCaptureInfos = NULL;
    ma_uint32 captureCount = 0;
    ma_device_id* pTargetId = NULL;

    if (ma_context_get_devices(&g_ma_context, &pPlaybackInfos, &playbackCount, &pCaptureInfos, &captureCount) == MA_SUCCESS) {
        pTargetId = find_playback_device_id(g_output_device_id, pPlaybackInfos, playbackCount);
    }

    ma_device_config config = ma_device_config_init(ma_device_type_playback);
    config.playback.format = ma_format_s16;
    config.playback.channels = (g_config.channels > 0) ? g_config.channels : 1;
    config.sampleRate = (g_config.sample_rate > 0) ? g_config.sample_rate : 48000;
    config.dataCallback = ma_playback_callback;
    config.pUserData = NULL;
    if (pTargetId != NULL) {
        config.playback.pDeviceID = pTargetId;
    }

    if (ma_device_init(&g_ma_context, &config, &g_playback_device) == MA_SUCCESS) {
        g_playback_device_initialized = true;
        if (ma_device_start(&g_playback_device) != MA_SUCCESS) {
            ma_device_uninit(&g_playback_device);
            g_playback_device_initialized = false;
        }
    }
}

static void stop_hardware_playback(void) {
    if (!g_playback_device_initialized) return;
    ma_device_stop(&g_playback_device);
    ma_device_uninit(&g_playback_device);
    g_playback_device_initialized = false;
}

VOICE_API int32_t voice_engine_init(const AudioEngineConfig* config) {
    if (!config) return -1;

    init_cs();

    g_config = *config;
    if (g_config.sample_rate == 0) g_config.sample_rate = 48000;
    if (g_config.channels == 0) g_config.channels = 1;
    if (g_config.frame_duration_ms == 0) g_config.frame_duration_ms = 20;
    if (g_config.vad_threshold_db == 0.0f) g_config.vad_threshold_db = -45.0f;
    if (g_config.vad_hangover_ms == 0) g_config.vad_hangover_ms = 200;

    memset(&g_stats, 0, sizeof(AudioEngineStats));
    g_stats.input_level_db = -90.0f;
    g_mic_test_loopback = false;

    enter_cs();
    for (int i = 0; i < MAX_PEERS; i++) {
        g_peers[i].user_id = 0;
        g_peers[i].is_active = false;
        g_peers[i].is_speaking = false;
        g_peers[i].user_volume = 1.0f;
        g_peers[i].read_idx = 0;
        g_peers[i].write_idx = 0;
    }
    g_capture_read_idx = 0;
    g_capture_write_idx = 0;
    leave_cs();

    if (!g_ma_context_initialized) {
        ma_context_config ctxConfig = ma_context_config_init();
        if (ma_context_init(NULL, 0, &ctxConfig, &g_ma_context) == MA_SUCCESS) {
            g_ma_context_initialized = true;
        }
    }

    g_initialized = true;
    return 0;
}

VOICE_API void voice_engine_destroy(void) {
    voice_engine_stop_capture();
    voice_engine_stop_playback();

    if (g_ma_context_initialized) {
        ma_context_uninit(&g_ma_context);
        g_ma_context_initialized = false;
    }

    g_mic_test_loopback = false;
    g_initialized = false;

    destroy_cs();
}

VOICE_API int32_t voice_engine_get_input_devices(AudioDeviceInfo* devices, int32_t max_count) {
    if (!devices || max_count < 1) return 0;
    int32_t count = 0;

    if (!g_ma_context_initialized) {
        ma_context_config ctxConfig = ma_context_config_init();
        if (ma_context_init(NULL, 0, &ctxConfig, &g_ma_context) == MA_SUCCESS) {
            g_ma_context_initialized = true;
        }
    }

    // Default Primary Device
    snprintf(devices[count].id, sizeof(devices[count].id), "default_input");
    snprintf(devices[count].name, sizeof(devices[count].name), "Default System Microphone");
    devices[count].is_default = true;
    count++;

    if (g_ma_context_initialized) {
        ma_device_info* pPlaybackInfos = NULL;
        ma_uint32 playbackCount = 0;
        ma_device_info* pCaptureInfos = NULL;
        ma_uint32 captureCount = 0;

        if (ma_context_get_devices(&g_ma_context, &pPlaybackInfos, &playbackCount, &pCaptureInfos, &captureCount) == MA_SUCCESS) {
            for (ma_uint32 i = 0; i < captureCount && count < max_count; i++) {
                snprintf(devices[count].id, sizeof(devices[count].id), "dev_in_%u", i);
                snprintf(devices[count].name, sizeof(devices[count].name), "%s", pCaptureInfos[i].name);
                devices[count].is_default = (pCaptureInfos[i].isDefault != 0);
                count++;
            }
        }
    }

    return count;
}

VOICE_API int32_t voice_engine_get_output_devices(AudioDeviceInfo* devices, int32_t max_count) {
    if (!devices || max_count < 1) return 0;
    int32_t count = 0;

    if (!g_ma_context_initialized) {
        ma_context_config ctxConfig = ma_context_config_init();
        if (ma_context_init(NULL, 0, &ctxConfig, &g_ma_context) == MA_SUCCESS) {
            g_ma_context_initialized = true;
        }
    }

    // Default Primary Device
    snprintf(devices[count].id, sizeof(devices[count].id), "default_output");
    snprintf(devices[count].name, sizeof(devices[count].name), "Default System Speakers");
    devices[count].is_default = true;
    count++;

    if (g_ma_context_initialized) {
        ma_device_info* pPlaybackInfos = NULL;
        ma_uint32 playbackCount = 0;
        ma_device_info* pCaptureInfos = NULL;
        ma_uint32 captureCount = 0;

        if (ma_context_get_devices(&g_ma_context, &pPlaybackInfos, &playbackCount, &pCaptureInfos, &captureCount) == MA_SUCCESS) {
            for (ma_uint32 i = 0; i < playbackCount && count < max_count; i++) {
                snprintf(devices[count].id, sizeof(devices[count].id), "dev_out_%u", i);
                snprintf(devices[count].name, sizeof(devices[count].name), "%s", pPlaybackInfos[i].name);
                devices[count].is_default = (pPlaybackInfos[i].isDefault != 0);
                count++;
            }
        }
    }

    return count;
}

VOICE_API int32_t voice_engine_set_input_device(const char* device_id) {
    if (!device_id) return -1;
    enter_cs();
    strncpy(g_input_device_id, device_id, sizeof(g_input_device_id) - 1);
    g_input_device_id[sizeof(g_input_device_id) - 1] = '\0';
    leave_cs();

    if (g_capturing) {
        stop_hardware_capture();
        start_hardware_capture();
    }
    return 0;
}

VOICE_API int32_t voice_engine_set_output_device(const char* device_id) {
    if (!device_id) return -1;
    enter_cs();
    strncpy(g_output_device_id, device_id, sizeof(g_output_device_id) - 1);
    g_output_device_id[sizeof(g_output_device_id) - 1] = '\0';
    leave_cs();

    if (g_playing) {
        stop_hardware_playback();
        start_hardware_playback();
    }
    return 0;
}

VOICE_API int32_t voice_engine_start_capture(void) {
    g_capturing = true;
    start_hardware_capture();
    return 0;
}

VOICE_API int32_t voice_engine_stop_capture(void) {
    g_capturing = false;
    stop_hardware_capture();
    g_stats.input_level_db = -90.0f;
    g_stats.is_speaking = false;
    return 0;
}

VOICE_API int32_t voice_engine_start_playback(void) {
    g_playing = true;
    start_hardware_playback();
    return 0;
}

VOICE_API int32_t voice_engine_stop_playback(void) {
    g_playing = false;
    stop_hardware_playback();
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
    if (muted) {
        g_stats.is_speaking = false;
    }
}

VOICE_API void voice_engine_set_local_deafen(bool deafened) {
    g_local_deafened = deafened;
}

VOICE_API void voice_engine_set_user_volume(uint32_t user_id, float volume_multiplier) {
    if (user_id == 0) return;
    enter_cs();
    for (int i = 1; i < MAX_PEERS; i++) {
        if (g_peers[i].is_active && g_peers[i].user_id == user_id) {
            g_peers[i].user_volume = volume_multiplier;
            leave_cs();
            return;
        }
    }

    // Allocate new peer slot (reserve slot 0 for mic test loopback)
    for (int i = 1; i < MAX_PEERS; i++) {
        if (!g_peers[i].is_active) {
            g_peers[i].user_id = user_id;
            g_peers[i].is_active = true;
            g_peers[i].user_volume = volume_multiplier;
            g_peers[i].read_idx = 0;
            g_peers[i].write_idx = 0;
            leave_cs();
            return;
        }
    }
    leave_cs();
}

VOICE_API void voice_engine_clear_peers(void) {
    enter_cs();
    g_mic_test_loopback = false;
    for (int i = 0; i < MAX_PEERS; i++) {
        g_peers[i].user_id = 0;
        g_peers[i].is_active = false;
        g_peers[i].is_speaking = false;
        g_peers[i].user_volume = 1.0f;
        g_peers[i].read_idx = 0;
        g_peers[i].write_idx = 0;
    }
    leave_cs();
}

VOICE_API void voice_engine_set_mic_test_loopback(bool enabled) {
    g_mic_test_loopback = enabled;
    if (enabled) {
        // Automatically start capture and playback if not already active
        if (!g_capturing) {
            voice_engine_start_capture();
        }
        if (!g_playing) {
            voice_engine_start_playback();
        }
    } else {
        // Clear loopback peer buffer
        enter_cs();
        g_peers[0].user_id = 0;
        g_peers[0].is_active = false;
        g_peers[0].is_speaking = false;
        g_peers[0].user_volume = 1.0f;
        g_peers[0].read_idx = 0;
        g_peers[0].write_idx = 0;
        leave_cs();
    }
}

VOICE_API bool voice_engine_is_mic_test_active(void) {
    return g_mic_test_loopback;
}

VOICE_API float voice_engine_get_input_level_db(void) {
    return g_stats.input_level_db;
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

    if (sender_id == 0) return;

    uint16_t payload_len = ((uint16_t)packet_bytes[14] << 8) | ((uint16_t)packet_bytes[15]);
    if (length < (uint32_t)(20 + payload_len)) return;

    // Buffer inbound audio into peer stream
    enter_cs();
    PeerStream* peer = NULL;
    for (int i = 1; i < MAX_PEERS; i++) { // Reserve index 0 for mic test loopback
        if (g_peers[i].is_active && g_peers[i].user_id == sender_id) {
            peer = &g_peers[i];
            break;
        }
    }
    if (!peer) {
        for (int i = 1; i < MAX_PEERS; i++) {
            if (!g_peers[i].is_active) {
                g_peers[i].user_id = sender_id;
                g_peers[i].is_active = true;
                g_peers[i].user_volume = 1.0f;
                g_peers[i].read_idx = 0;
                g_peers[i].write_idx = 0;
                peer = &g_peers[i];
                break;
            }
        }
    }

    if (peer) {
        peer->is_speaking = vad;
        const uint8_t* payload = packet_bytes + 20;
        uint32_t samples_to_write = payload_len / sizeof(int16_t);
        if (samples_to_write > SAMPLES_PER_FRAME) samples_to_write = SAMPLES_PER_FRAME;
        const int16_t* pcm_in = (const int16_t*)payload;

        for (uint32_t s = 0; s < samples_to_write; s++) {
            peer->buffer[peer->write_idx] = pcm_in[s];
            peer->write_idx = (peer->write_idx + 1) % RING_BUFFER_SIZE;
        }
    }
    leave_cs();

    if (g_speaking_cb) {
        g_speaking_cb(sender_id, vad, energy);
    }
}

VOICE_API int32_t voice_engine_capture_frame(
    uint8_t* out_buffer,
    uint32_t max_len,
    float* out_level_db,
    bool* out_is_speaking,
    uint8_t* out_energy_level
) {
    if (!out_buffer || max_len < SAMPLES_PER_FRAME * sizeof(int16_t)) return 0;

    int16_t* pcm_out = (int16_t*)out_buffer;
    uint32_t frame_samples = SAMPLES_PER_FRAME; // 20ms at 48kHz

    // If capturing is not active and mic test is not active, output silence
    if (!g_capturing && !g_mic_test_loopback) {
        memset(pcm_out, 0, frame_samples * sizeof(int16_t));
        if (out_level_db) *out_level_db = -90.0f;
        if (out_is_speaking) *out_is_speaking = false;
        if (out_energy_level) *out_energy_level = 0;
        g_stats.input_level_db = -90.0f;
        g_stats.is_speaking = false;
        return (int32_t)(frame_samples * sizeof(int16_t));
    }

    // If locally muted, capture silence and speaking is false
    if (g_local_muted) {
        memset(pcm_out, 0, frame_samples * sizeof(int16_t));
        if (out_level_db) *out_level_db = -90.0f;
        if (out_is_speaking) *out_is_speaking = false;
        if (out_energy_level) *out_energy_level = 0;
        g_stats.input_level_db = -90.0f;
        g_stats.is_speaking = false;
        return (int32_t)(frame_samples * sizeof(int16_t));
    }

    // Attempt to dequeue live hardware samples from capture ring buffer
    bool has_hardware_samples = false;
    enter_cs();
    uint32_t available = (g_capture_write_idx >= g_capture_read_idx) 
        ? (g_capture_write_idx - g_capture_read_idx)
        : (RING_BUFFER_SIZE - g_capture_read_idx + g_capture_write_idx);

    if (available >= frame_samples) {
        for (uint32_t i = 0; i < frame_samples; i++) {
            pcm_out[i] = g_capture_ring[g_capture_read_idx];
            g_capture_read_idx = (g_capture_read_idx + 1) % RING_BUFFER_SIZE;
        }
        has_hardware_samples = true;
    }
    leave_cs();

    if (!has_hardware_samples) {
        // When hardware samples are unavailable, zero the buffer, set level to -90.0 dBFS, speaking = false, energy = 0
        memset(pcm_out, 0, frame_samples * sizeof(int16_t));
        g_hangover_ms_left = 0;
        g_stats.input_level_db = -90.0f;
        g_stats.is_speaking = false;
        g_stats.packets_sent++;
        if (out_level_db) *out_level_db = -90.0f;
        if (out_is_speaking) *out_is_speaking = false;
        if (out_energy_level) *out_energy_level = 0;
        return (int32_t)(frame_samples * sizeof(int16_t));
    }

    // Process real hardware samples
    double sum_sq = 0.0;
    for (uint32_t i = 0; i < frame_samples; i++) {
        int16_t s = pcm_out[i];
        sum_sq += ((double)s) * ((double)s);
    }

    double rms = sqrt(sum_sq / (double)frame_samples);
    float dbfs = -90.0f;
    if (rms > 0.0) {
        dbfs = (float)(20.0 * log10(rms / 32768.0));
    }
    if (dbfs < -90.0f) dbfs = -90.0f;
    if (dbfs > 0.0f) dbfs = 0.0f;

    // VAD & PTT Determination
    bool speaking = false;
    if (g_vad_mode) {
        if (dbfs >= g_vad_threshold) {
            speaking = true;
            g_hangover_ms_left = g_config.vad_hangover_ms;
        } else if (g_hangover_ms_left >= 20) {
            speaking = true;
            g_hangover_ms_left -= 20;
        } else {
            speaking = false;
            g_hangover_ms_left = 0;
        }
    } else {
        // Push to talk mode
        speaking = g_ptt_pressed;
    }

    // Energy Level (0-15)
    float normalized = (dbfs + 60.0f) / 60.0f;
    if (normalized < 0.0f) normalized = 0.0f;
    if (normalized > 1.0f) normalized = 1.0f;
    uint8_t energy = (uint8_t)(normalized * 15.0f + 0.5f);

    g_stats.input_level_db = dbfs;
    g_stats.is_speaking = speaking;
    g_stats.packets_sent++;

    if (out_level_db) *out_level_db = dbfs;
    if (out_is_speaking) *out_is_speaking = speaking;
    if (out_energy_level) *out_energy_level = energy;

    // If mic test loopback is enabled, route frame to internal peer buffer (index 0) for real-time audio self-monitoring
    if (g_mic_test_loopback) {
        enter_cs();
        PeerStream* loop_peer = &g_peers[0];
        loop_peer->user_id = 999999;
        loop_peer->is_active = true;
        loop_peer->user_volume = 1.0f;
        for (uint32_t s = 0; s < frame_samples; s++) {
            loop_peer->buffer[loop_peer->write_idx] = pcm_out[s];
            loop_peer->write_idx = (loop_peer->write_idx + 1) % RING_BUFFER_SIZE;
        }
        leave_cs();
    }

    return (int32_t)(frame_samples * sizeof(int16_t));
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

// Internal Software Audio Mixer with Soft-Clipping Limiter (supports chunked processing for arbitrary frame_samples)
void mix_audio_streams(int16_t* output_buffer, uint32_t frame_samples) {
    if (!output_buffer || frame_samples == 0 || g_local_deafened) {
        if (output_buffer) memset(output_buffer, 0, frame_samples * sizeof(int16_t));
        return;
    }

    uint32_t samples_remaining = frame_samples;
    uint32_t out_offset = 0;

    while (samples_remaining > 0) {
        uint32_t chunk = (samples_remaining > SAMPLES_PER_FRAME) ? SAMPLES_PER_FRAME : samples_remaining;
        float mix_accumulator[SAMPLES_PER_FRAME];
        memset(mix_accumulator, 0, chunk * sizeof(float));

        for (int i = 0; i < MAX_PEERS; i++) {
            if (!g_peers[i].is_active) continue;
            if (i == 0 && !g_mic_test_loopback) continue;

            float gain = g_peers[i].user_volume;
            for (uint32_t s = 0; s < chunk; s++) {
                if (g_peers[i].read_idx != g_peers[i].write_idx) {
                    int16_t pcm = g_peers[i].buffer[g_peers[i].read_idx];
                    g_peers[i].read_idx = (g_peers[i].read_idx + 1) % RING_BUFFER_SIZE;
                    mix_accumulator[s] += ((float)pcm) * gain;
                }
            }
        }

        // Smooth continuous cubic soft limiter without threshold discontinuities
        for (uint32_t s = 0; s < chunk; s++) {
            float x = mix_accumulator[s] / 32768.0f;
            float y;
            if (x >= 1.5f) {
                y = 1.0f;
            } else if (x <= -1.5f) {
                y = -1.0f;
            } else {
                y = x - (4.0f / 27.0f) * (x * x * x);
            }
            output_buffer[out_offset + s] = (int16_t)(y * 32767.0f);
        }

        out_offset += chunk;
        samples_remaining -= chunk;
    }
}
