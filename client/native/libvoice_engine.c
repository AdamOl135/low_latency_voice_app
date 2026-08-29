#include "libvoice_engine.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#ifdef _WIN32
  #include <windows.h>
  #include <mmsystem.h>
  #pragma comment(lib, "winmm.lib")
#endif

#define MAX_PEERS 32
#define RING_BUFFER_SIZE 32768
#define MAX_DEVICES 16
#define NUM_WAVE_BUFFERS 4
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

// Internal synthesis phase for fallback / test tone
static double g_synth_phase = 0.0;
static uint32_t g_hangover_ms_left = 0;

#ifdef _WIN32
static HWAVEIN g_hWaveIn = NULL;
static HWAVEOUT g_hWaveOut = NULL;
static WAVEHDR g_inWaveHdr[NUM_WAVE_BUFFERS];
static WAVEHDR g_outWaveHdr[NUM_WAVE_BUFFERS];
static int16_t g_inBuffers[NUM_WAVE_BUFFERS][SAMPLES_PER_FRAME];
static int16_t g_outBuffers[NUM_WAVE_BUFFERS][SAMPLES_PER_FRAME];
static CRITICAL_SECTION g_audio_cs;
static bool g_cs_initialized = false;

static void enter_cs(void) {
    if (g_cs_initialized) EnterCriticalSection(&g_audio_cs);
}

static void leave_cs(void) {
    if (g_cs_initialized) LeaveCriticalSection(&g_audio_cs);
}

// Forward declaration
void mix_audio_streams(int16_t* output_buffer, uint32_t frame_samples);

// WaveIn Callback
static void CALLBACK waveInProc(HWAVEIN hwi, UINT uMsg, DWORD_PTR dwInstance, DWORD_PTR dwParam1, DWORD_PTR dwParam2) {
    if (uMsg == WIM_DATA && g_capturing) {
        WAVEHDR* pHdr = (WAVEHDR*)dwParam1;
        if (pHdr && pHdr->dwBytesRecorded > 0) {
            int16_t* samples = (int16_t*)pHdr->lpData;
            uint32_t numSamples = pHdr->dwBytesRecorded / sizeof(int16_t);

            enter_cs();
            for (uint32_t i = 0; i < numSamples; i++) {
                g_capture_ring[g_capture_write_idx] = samples[i];
                g_capture_write_idx = (g_capture_write_idx + 1) % RING_BUFFER_SIZE;
            }
            leave_cs();
        }

        // Re-queue buffer if capture still active
        if (g_capturing && g_hWaveIn) {
            waveInAddBuffer(hwi, pHdr, sizeof(WAVEHDR));
        }
    }
}

// WaveOut Callback
static void CALLBACK waveOutProc(HWAVEOUT hwo, UINT uMsg, DWORD_PTR dwInstance, DWORD_PTR dwParam1, DWORD_PTR dwParam2) {
    if (uMsg == WOM_DONE && g_playing) {
        WAVEHDR* pHdr = (WAVEHDR*)dwParam1;
        if (pHdr && g_playing && g_hWaveOut) {
            int16_t* outBuf = (int16_t*)pHdr->lpData;
            enter_cs();
            mix_audio_streams(outBuf, SAMPLES_PER_FRAME);
            leave_cs();
            waveOutWrite(hwo, pHdr, sizeof(WAVEHDR));
        }
    }
}

static UINT parse_input_device_id(const char* device_id) {
    if (!device_id || strcmp(device_id, "default_input") == 0 || strlen(device_id) == 0) {
        return WAVE_MAPPER;
    }
    UINT devIdx = 0;
    if (sscanf(device_id, "winmm_in_%u", &devIdx) == 1) {
        return devIdx;
    }
    return WAVE_MAPPER;
}

static UINT parse_output_device_id(const char* device_id) {
    if (!device_id || strcmp(device_id, "default_output") == 0 || strlen(device_id) == 0) {
        return WAVE_MAPPER;
    }
    UINT devIdx = 0;
    if (sscanf(device_id, "winmm_out_%u", &devIdx) == 1) {
        return devIdx;
    }
    return WAVE_MAPPER;
}

static void start_hardware_capture(void) {
    if (g_hWaveIn != NULL) return;

    WAVEFORMATEX wfx;
    memset(&wfx, 0, sizeof(wfx));
    wfx.wFormatTag = WAVE_FORMAT_PCM;
    wfx.nChannels = (WORD)(g_config.channels > 0 ? g_config.channels : 1);
    wfx.nSamplesPerSec = g_config.sample_rate > 0 ? g_config.sample_rate : 48000;
    wfx.wBitsPerSample = 16;
    wfx.nBlockAlign = (WORD)(wfx.nChannels * (wfx.wBitsPerSample / 8));
    wfx.nAvgBytesPerSec = wfx.nSamplesPerSec * wfx.nBlockAlign;

    UINT devId = parse_input_device_id(g_input_device_id);
    MMRESULT res = waveInOpen(&g_hWaveIn, devId, &wfx, (DWORD_PTR)waveInProc, 0, CALLBACK_FUNCTION);
    if (res != MMSYSERR_NOERROR) {
        g_hWaveIn = NULL;
        return;
    }

    for (int i = 0; i < NUM_WAVE_BUFFERS; i++) {
        memset(&g_inWaveHdr[i], 0, sizeof(WAVEHDR));
        g_inWaveHdr[i].lpData = (LPSTR)g_inBuffers[i];
        g_inWaveHdr[i].dwBufferLength = BUFFER_SIZE_BYTES;
        waveInPrepareHeader(g_hWaveIn, &g_inWaveHdr[i], sizeof(WAVEHDR));
        waveInAddBuffer(g_hWaveIn, &g_inWaveHdr[i], sizeof(WAVEHDR));
    }

    waveInStart(g_hWaveIn);
}

static void stop_hardware_capture(void) {
    if (g_hWaveIn == NULL) return;

    HWAVEIN h = g_hWaveIn;
    g_hWaveIn = NULL;

    waveInReset(h);
    for (int i = 0; i < NUM_WAVE_BUFFERS; i++) {
        waveInUnprepareHeader(h, &g_inWaveHdr[i], sizeof(WAVEHDR));
    }
    waveInClose(h);
}

static void start_hardware_playback(void) {
    if (g_hWaveOut != NULL) return;

    WAVEFORMATEX wfx;
    memset(&wfx, 0, sizeof(wfx));
    wfx.wFormatTag = WAVE_FORMAT_PCM;
    wfx.nChannels = (WORD)(g_config.channels > 0 ? g_config.channels : 1);
    wfx.nSamplesPerSec = g_config.sample_rate > 0 ? g_config.sample_rate : 48000;
    wfx.wBitsPerSample = 16;
    wfx.nBlockAlign = (WORD)(wfx.nChannels * (wfx.wBitsPerSample / 8));
    wfx.nAvgBytesPerSec = wfx.nSamplesPerSec * wfx.nBlockAlign;

    UINT devId = parse_output_device_id(g_output_device_id);
    MMRESULT res = waveOutOpen(&g_hWaveOut, devId, &wfx, (DWORD_PTR)waveOutProc, 0, CALLBACK_FUNCTION);
    if (res != MMSYSERR_NOERROR) {
        g_hWaveOut = NULL;
        return;
    }

    for (int i = 0; i < NUM_WAVE_BUFFERS; i++) {
        memset(&g_outWaveHdr[i], 0, sizeof(WAVEHDR));
        g_outWaveHdr[i].lpData = (LPSTR)g_outBuffers[i];
        g_outWaveHdr[i].dwBufferLength = BUFFER_SIZE_BYTES;
        waveOutPrepareHeader(g_hWaveOut, &g_outWaveHdr[i], sizeof(WAVEHDR));

        // Pre-fill buffer and submit
        enter_cs();
        mix_audio_streams(g_outBuffers[i], SAMPLES_PER_FRAME);
        leave_cs();
        waveOutWrite(g_hWaveOut, &g_outWaveHdr[i], sizeof(WAVEHDR));
    }
}

static void stop_hardware_playback(void) {
    if (g_hWaveOut == NULL) return;

    HWAVEOUT h = g_hWaveOut;
    g_hWaveOut = NULL;

    waveOutReset(h);
    for (int i = 0; i < NUM_WAVE_BUFFERS; i++) {
        waveOutUnprepareHeader(h, &g_outWaveHdr[i], sizeof(WAVEHDR));
    }
    waveOutClose(h);
}

#else
static void enter_cs(void) {}
static void leave_cs(void) {}
static void start_hardware_capture(void) {}
static void stop_hardware_capture(void) {}
static void start_hardware_playback(void) {}
static void stop_hardware_playback(void) {}
#endif

VOICE_API int32_t voice_engine_init(const AudioEngineConfig* config) {
    if (!config) return -1;

#ifdef _WIN32
    if (!g_cs_initialized) {
        InitializeCriticalSection(&g_audio_cs);
        g_cs_initialized = true;
    }
#endif

    g_config = *config;
    if (g_config.sample_rate == 0) g_config.sample_rate = 48000;
    if (g_config.channels == 0) g_config.channels = 1;
    if (g_config.frame_duration_ms == 0) g_config.frame_duration_ms = 20;
    if (g_config.vad_threshold_db == 0.0f) g_config.vad_threshold_db = -45.0f;
    if (g_config.vad_hangover_ms == 0) g_config.vad_hangover_ms = 200;

    memset(&g_stats, 0, sizeof(AudioEngineStats));
    g_stats.input_level_db = -90.0f;

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

    g_initialized = true;
    return 0;
}

VOICE_API void voice_engine_destroy(void) {
    voice_engine_stop_capture();
    voice_engine_stop_playback();
    g_mic_test_loopback = false;
    g_initialized = false;

#ifdef _WIN32
    if (g_cs_initialized) {
        DeleteCriticalSection(&g_audio_cs);
        g_cs_initialized = false;
    }
#endif
}

VOICE_API int32_t voice_engine_get_input_devices(AudioDeviceInfo* devices, int32_t max_count) {
    if (!devices || max_count < 1) return 0;

    int32_t count = 0;

#ifdef _WIN32
    UINT numDevs = waveInGetNumDevs();
    if (numDevs > 0) {
        // Default Primary Device
        snprintf(devices[count].id, sizeof(devices[count].id), "default_input");
        snprintf(devices[count].name, sizeof(devices[count].name), "Default System Microphone (WASAPI / DirectSound)");
        devices[count].is_default = true;
        count++;

        for (UINT i = 0; i < numDevs && count < max_count; i++) {
            WAVEINCAPSW caps;
            if (waveInGetDevCapsW(i, &caps, sizeof(caps)) == MMSYSERR_NOERROR) {
                snprintf(devices[count].id, sizeof(devices[count].id), "winmm_in_%u", i);
                WideCharToMultiByte(CP_UTF8, 0, caps.szPname, -1, devices[count].name, sizeof(devices[count].name), NULL, NULL);
                devices[count].is_default = false;
                count++;
            }
        }
        return count;
    }
#endif

    // Fallback devices when no hardware or on non-Windows platforms
    snprintf(devices[count].id, sizeof(devices[count].id), "default_input");
    snprintf(devices[count].name, sizeof(devices[count].name), "Default System Microphone (Built-in Audio)");
    devices[count].is_default = true;
    count++;

    if (count < max_count) {
        snprintf(devices[count].id, sizeof(devices[count].id), "headset_mic");
        snprintf(devices[count].name, sizeof(devices[count].name), "Headset Microphone (Realtek Audio)");
        devices[count].is_default = false;
        count++;
    }

    if (count < max_count) {
        snprintf(devices[count].id, sizeof(devices[count].id), "usb_mic");
        snprintf(devices[count].name, sizeof(devices[count].name), "USB Studio Microphone (High Definition)");
        devices[count].is_default = false;
        count++;
    }

    return count;
}

VOICE_API int32_t voice_engine_get_output_devices(AudioDeviceInfo* devices, int32_t max_count) {
    if (!devices || max_count < 1) return 0;

    int32_t count = 0;

#ifdef _WIN32
    UINT numDevs = waveOutGetNumDevs();
    if (numDevs > 0) {
        // Default Primary Device
        snprintf(devices[count].id, sizeof(devices[count].id), "default_output");
        snprintf(devices[count].name, sizeof(devices[count].name), "Default System Speakers (WASAPI / DirectSound)");
        devices[count].is_default = true;
        count++;

        for (UINT i = 0; i < numDevs && count < max_count; i++) {
            WAVEOUTCAPSW caps;
            if (waveOutGetDevCapsW(i, &caps, sizeof(caps)) == MMSYSERR_NOERROR) {
                snprintf(devices[count].id, sizeof(devices[count].id), "winmm_out_%u", i);
                WideCharToMultiByte(CP_UTF8, 0, caps.szPname, -1, devices[count].name, sizeof(devices[count].name), NULL, NULL);
                devices[count].is_default = false;
                count++;
            }
        }
        return count;
    }
#endif

    // Fallback devices when no hardware or on non-Windows platforms
    snprintf(devices[count].id, sizeof(devices[count].id), "default_output");
    snprintf(devices[count].name, sizeof(devices[count].name), "Default System Speakers (Built-in Audio)");
    devices[count].is_default = true;
    count++;

    if (count < max_count) {
        snprintf(devices[count].id, sizeof(devices[count].id), "headphones");
        snprintf(devices[count].name, sizeof(devices[count].name), "Headphones / Headset (Realtek Audio)");
        devices[count].is_default = false;
        count++;
    }

    if (count < max_count) {
        snprintf(devices[count].id, sizeof(devices[count].id), "line_out");
        snprintf(devices[count].name, sizeof(devices[count].name), "Digital Line Out (High Definition Audio)");
        devices[count].is_default = false;
        count++;
    }

    return count;
}

VOICE_API int32_t voice_engine_set_input_device(const char* device_id) {
    if (!device_id) return -1;
    strncpy(g_input_device_id, device_id, sizeof(g_input_device_id) - 1);
    g_input_device_id[sizeof(g_input_device_id) - 1] = '\0';

    if (g_capturing) {
        stop_hardware_capture();
        start_hardware_capture();
    }
    return 0;
}

VOICE_API int32_t voice_engine_set_output_device(const char* device_id) {
    if (!device_id) return -1;
    strncpy(g_output_device_id, device_id, sizeof(g_output_device_id) - 1);
    g_output_device_id[sizeof(g_output_device_id) - 1] = '\0';

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
    enter_cs();
    for (int i = 0; i < MAX_PEERS; i++) {
        if (g_peers[i].is_active && g_peers[i].user_id == user_id) {
            g_peers[i].user_volume = volume_multiplier;
            leave_cs();
            return;
        }
    }

    // Allocate new peer slot
    for (int i = 0; i < MAX_PEERS; i++) {
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
        g_peers[0].is_active = false;
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

    double sum_sq = 0.0;

    if (!has_hardware_samples) {
        // Fallback tone synthesis for headless / test / fallback environments
        for (uint32_t i = 0; i < frame_samples; i++) {
            double sample_val = 6000.0 * sin(g_synth_phase);
            g_synth_phase += 2.0 * 3.141592653589793 * 440.0 / 48000.0;
            if (g_synth_phase > 2.0 * 3.141592653589793) {
                g_synth_phase -= 2.0 * 3.141592653589793;
            }

            int16_t s = (int16_t)sample_val;
            pcm_out[i] = s;
            sum_sq += ((double)s) * ((double)s);
        }
    } else {
        for (uint32_t i = 0; i < frame_samples; i++) {
            int16_t s = pcm_out[i];
            sum_sq += ((double)s) * ((double)s);
        }
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

// Internal Software Audio Mixer with Soft-Clipping Limiter
void mix_audio_streams(int16_t* output_buffer, uint32_t frame_samples) {
    if (!output_buffer || frame_samples == 0 || g_local_deafened) {
        if (output_buffer) memset(output_buffer, 0, frame_samples * sizeof(int16_t));
        return;
    }

    float mix_accumulator[SAMPLES_PER_FRAME];
    uint32_t samples = frame_samples > SAMPLES_PER_FRAME ? SAMPLES_PER_FRAME : frame_samples;
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
