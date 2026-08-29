#ifndef LIBVOICE_ENGINE_H
#define LIBVOICE_ENGINE_H

#include <stdint.h>
#include <stdbool.h>

#ifdef _WIN32
  #define VOICE_API __declspec(dllexport)
#else
  #define VOICE_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

// Audio Device Info Descriptor
typedef struct {
    char id[128];
    char name[256];
    bool is_default;
} AudioDeviceInfo;

// Audio Engine Configuration
typedef struct {
    uint32_t sample_rate;       // Default 48000 Hz
    uint32_t channels;          // 1 (Mono)
    uint32_t frame_duration_ms; // 10 or 20 ms
    uint32_t opus_bitrate;      // Default 48000 bps
    float vad_threshold_db;     // Default -45.0 dBFS
    uint32_t vad_hangover_ms;   // Default 200 ms
} AudioEngineConfig;

// Audio Statistics & Telemetry
typedef struct {
    float input_level_db;
    bool is_speaking;
    uint32_t packets_sent;
    uint32_t packets_received;
    uint32_t packets_lost;
    float current_jitter_ms;
} AudioEngineStats;

// Callbacks
typedef void (*OnSpeakingStateChangedCallback)(uint32_t user_id, bool is_speaking, float energy_level);
typedef void (*OnAudioPacketReadyCallback)(const uint8_t* data, uint32_t length);

// Lifecycle Functions
VOICE_API int32_t voice_engine_init(const AudioEngineConfig* config);
VOICE_API void voice_engine_destroy(void);

// Device Enumeration & Selection
VOICE_API int32_t voice_engine_get_input_devices(AudioDeviceInfo* devices, int32_t max_count);
VOICE_API int32_t voice_engine_get_output_devices(AudioDeviceInfo* devices, int32_t max_count);
VOICE_API int32_t voice_engine_set_input_device(const char* device_id);
VOICE_API int32_t voice_engine_set_output_device(const char* device_id);

// Audio Stream Control
VOICE_API int32_t voice_engine_start_capture(void);
VOICE_API int32_t voice_engine_stop_capture(void);
VOICE_API int32_t voice_engine_start_playback(void);
VOICE_API int32_t voice_engine_stop_playback(void);

// Mode & Parameter Controls
VOICE_API void voice_engine_set_ptt_state(bool is_pressed);
VOICE_API void voice_engine_set_vad_mode(bool enabled, float threshold_db);
VOICE_API void voice_engine_set_local_mute(bool muted);
VOICE_API void voice_engine_set_local_deafen(bool deafened);
VOICE_API void voice_engine_set_user_volume(uint32_t user_id, float volume_multiplier);

// Microphone Testing & Real-time Feedback
VOICE_API void voice_engine_set_mic_test_loopback(bool enabled);
VOICE_API bool voice_engine_is_mic_test_active(void);
VOICE_API float voice_engine_get_input_level_db(void);

// Frame Capture & Inbound Processing
VOICE_API int32_t voice_engine_capture_frame(
    uint8_t* out_buffer,
    uint32_t max_len,
    float* out_level_db,
    bool* out_is_speaking,
    uint8_t* out_energy_level
);
VOICE_API void voice_engine_feed_inbound_packet(const uint8_t* packet_bytes, uint32_t length);

// Callbacks & Telemetry
VOICE_API void voice_engine_register_callbacks(
    OnSpeakingStateChangedCallback on_speaking,
    OnAudioPacketReadyCallback on_packet_ready
);
VOICE_API void voice_engine_get_stats(AudioEngineStats* stats);

#ifdef __cplusplus
}
#endif

#endif // LIBVOICE_ENGINE_H
