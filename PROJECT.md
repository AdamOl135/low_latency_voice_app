# Project: Low Latency Voice App Bug Fixes

## Architecture
A low-latency, Discord-like voice/text chat application consisting of three distinct layers:
1. **Native C Audio Engine (`client/native/`)**: Cross-platform audio capture, playback, mixing, software VAD, and ring-buffered peer streaming using `miniaudio.h` with platform thread synchronization (`pthread_mutex_t` on POSIX, `CRITICAL_SECTION` on Windows).
2. **Go Backend SFU & Control Plane (`backend/`)**: High-performance Selective Forwarding Unit (SFU) handling binary UDP audio packet routing (Opus/PCM frames, VAD flags, energy levels, jitter calculation) and WebSocket JSON-RPC control plane (authentication, channel management, voice tokens, dynamic UDP port advertisement, presence).
3. **Flutter Client Application (`client/`)**: Cross-platform desktop/mobile client interacting with the Go backend over WebSocket (control/chat) and UDP (voice media streaming), and interfacing with the native C audio engine via `dart:ffi`.

```
+-------------------------------------------------------------------------+
|                              Flutter Client                             |
|  +--------------------------------+   +-------------------------------+ |
|  |     UI (Riverpod Notifiers)    |   |     WebSocket JSON-RPC        | |
|  +----------------+---------------+   +---------------+---------------+ |
|                   |                                   |                 |
|  +----------------v---------------+                   |                 |
|  |      VoiceClient (UDP Raw)     |                   |                 |
|  +----------------+---------------+                   |                 |
|                   |                                   |                 |
|  +----------------v---------------+                   |                 |
|  | AudioEngineService (dart:ffi)  |                   |                 |
+--+----------------+---------------+-------------------+-----------------+
                    |                                   |
         FFI Direct C Calls                     WebSocket TCP:8085
                    |                                   |
+-------------------v---------------+   +---------------v-----------------+
|      Native C Audio Engine        |   |         Go Backend Hub          |
|  - miniaudio hardware I/O (Linux) |   |  - Dynamic UDP port return      |
|  - POSIX pthread mutexes          |   |  - Session token auth           |
|  - Zeroed buffer on silence       |   +---------------+-----------------+
|  - Soft-limiter peer mixer        |                   |
+-------------------+---------------+        Internal Session Route       |
                    |                                   |                 |
         UDP Voice Media Datagrams                      |                 |
                    +===================================>                 |
                                        +---------------v-----------------+
                                        |         Go Backend SFU          |
                                        |  - Ping touches LastSeen        |
                                        |  - 60s idle session scavenger   |
                                        |  - UDP Audio Selective Forward  |
                                        +---------------------------------+
```

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Cross-Platform Audio Engine (miniaudio) | Replace Windows-only WinMM with `miniaudio.h` in `libvoice_engine.c`. Support Linux (PulseAudio/PipeWire/ALSA) & Windows (WASAPI). Real hardware mic capture into `g_capture_ring`, real playback from `mix_audio_streams()`, preserve device APIs, remove 440 Hz synthetic tone and output silence buffer on underflow, implement recursive `pthread_mutex_t` thread sync, update `CMakeLists.txt` for platform linking. | M1 | R1 |
| F2 | Backend UDP Session Scavenger LastSeen Touch | Fix `handlePing()` in `backend/internal/audio/router.go` to lookup session by `pkt.SenderID`/`srcAddr` and call `session.Touch()` / `UpdateAddr` to refresh `LastSeen` on every 1-second ping, preventing 60s eviction of silent listeners. | M2 | R2 |
| F3 | Backend Dynamic UDP Port in WS Responses | Add `UDPPort() int` to `auth.Service` / `AuthService` and update `handleAuth` (line 269) and `handleJoinVoice` (line 541) in `backend/internal/control/handler.go` to return the configured UDP port dynamically instead of hardcoded `7878`. | M2 | R3 |
| F4 | Client Settings Dialog Port Fallback & Defaults | Fix `client/lib/ui/dialogs/audio_settings_dialog.dart` line 412 fallback port from `8080` to `AppConstants.defaultWsPort` (`8085`). Verify default host `100.108.39.69` and port `8085` across client constants. | M3 | R4 |
| F5 | Client Inbound Packet Re-Encoding Optimization | Eliminate decode-then-re-encode round trip in `client/lib/state/voice_notifier.dart` by storing raw datagram bytes on `VoicePacket` and passing `rawBytes` directly to `feedInboundPacket()`. | M3 | R5 |
| F6 | E2E Integration Testing & Adversarial Hardening | Comprehensive test suite (Tiers 1-4 requirement-driven opaque-box tests, Tier 5 adversarial white-box tests) verifying multi-user audio streaming, silent listener survival >120s, dynamic UDP ports, Linux compilation, and thread safety. | E2E & M4 | Acceptance Criteria |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|--------------|--------|
| E2E | E2E Testing Track | Requirement-driven test harness and test cases (Tiers 1-4) published to `TEST_READY.md` | none | IN_PROGRESS |
| M1 | Native C Audio Engine | `client/native/libvoice_engine.c`, `miniaudio.h`, `CMakeLists.txt` — cross-platform miniaudio migration, thread safety, silence buffer | none | IN_PROGRESS |
| M2 | Go Backend SFU & Control | `backend/internal/audio/router.go`, `backend/internal/auth/service.go`, `backend/internal/control/handler.go`, `hub.go`, and backend tests | none | IN_PROGRESS |
| M3 | Flutter Client Fixes | `client/lib/ui/dialogs/audio_settings_dialog.dart`, `client/lib/services/voice_client.dart`, `client/lib/state/voice_notifier.dart`, `client/lib/services/audio_engine.dart` | none | IN_PROGRESS |
| M4 | Final Milestone: E2E Verification & Tier 5 Hardening | Pass 100% of E2E tests (Tiers 1-4) and adversarial coverage hardening (Tier 5) | E2E, M1, M2, M3 | PLANNED |

---

## Interface Contracts

### C Audio Engine ↔ Flutter Dart FFI (`client/native/libvoice_engine.h` ↔ `client/lib/services/audio_engine.dart`)
- `VOICE_API bool voice_engine_init(const AudioEngineConfig* config)`
- `VOICE_API void voice_engine_destroy(void)`
- `VOICE_API int32_t voice_engine_get_input_devices(AudioDeviceInfo* devices, int32_t max_count)`
- `VOICE_API int32_t voice_engine_get_output_devices(AudioDeviceInfo* devices, int32_t max_count)`
- `VOICE_API bool voice_engine_set_input_device(const char* device_id)`
- `VOICE_API bool voice_engine_set_output_device(const char* device_id)`
- `VOICE_API bool voice_engine_start_capture(void)`
- `VOICE_API void voice_engine_stop_capture(void)`
- `VOICE_API bool voice_engine_start_playback(void)`
- `VOICE_API void voice_engine_stop_playback(void)`
- `VOICE_API uint32_t voice_engine_capture_frame(uint8_t* out_buffer, uint32_t max_len, float* out_level_db, bool* out_is_speaking, uint8_t* out_energy_level)`
- `VOICE_API void voice_engine_feed_inbound_packet(const uint8_t* packet_bytes, uint32_t length)`
- Struct `AudioDeviceInfo`: `char id[128]`, `char name[256]`, `bool is_default` (matches `AudioDeviceInfoC`).
- Struct `AudioEngineConfig`: `sample_rate (48000)`, `channels (1)`, `frame_duration_ms (20)`, `opus_bitrate (48000)`, `vad_threshold_db (-45.0)`, `vad_hangover_ms (200)` (matches `AudioEngineConfigC`).

### Flutter Client ↔ Go Backend SFU (UDP Audio Plane)
- 20-byte fixed binary header + audio payload:
  - `[0:1]` Magic `0x56`
  - `[1:2]` Version `0x01`
  - `[2:3]` Type: `0x01` Voice, `0x02` Ping, `0x03` Pong, `0x04` Handshake, `0x05` Leave
  - `[3:4]` Flags bitfield: Bit 0=Opus/PCM, Bit 1=VAD speaking, Bit 2=Muted, Bit 3=Deafened, Bit 4-7=Energy (0-15)
  - `[4:8]` Sender User ID (uint32 big-endian)
  - `[8:12]` Channel ID (uint32 big-endian)
  - `[12:14]` Sequence number (uint16 big-endian)
  - `[14:16]` Payload length (uint16 big-endian, 1920 for 20ms 48kHz mono PCM)
  - `[16:20]` Timestamp ms (uint32 big-endian)
  - `[20:N]` Audio payload

### Flutter Client ↔ Go Backend Control Plane (WebSocket JSON-RPC)
- WebSocket endpoint: `ws://<host>:<port>/ws` (default `ws://100.108.39.69:8085/ws`)
- `auth` response: `{"status": "ok", "action": "auth", "data": {..., "udp_port": <configured_udp_port>}}`
- `join_voice` response: `{"status": "ok", "action": "join_voice", "data": {..., "channel_id": <id>, "udp_token": "<token>", "udp_port": <configured_udp_port>, "ssrc": <ssrc>}}`

---

## Code Layout
- `client/native/`: Native C audio engine sources (`libvoice_engine.c`, `libvoice_engine.h`, `miniaudio.h`, `CMakeLists.txt`).
- `backend/`: Go backend source code (`cmd/server/main.go`, `internal/audio/`, `internal/auth/`, `internal/control/`, `internal/storage/`).
- `client/lib/`: Flutter Dart application (`core/`, `ffi/`, `models/`, `services/`, `state/`, `ui/`).
- `tests/e2e/`: E2E integration test harnesses and scripts.
- `.agents/`: Coordination metadata, briefings, progress logs, handoff reports.
