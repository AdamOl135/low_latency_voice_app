# Original User Request

## 2026-08-30T14:23:28Z

Fix critical voice communication bugs in a Discord-like voice/text chat application so that users in the same voice channel can hear each other, audio input is recognized correctly on both Windows and Linux, and the server defaults to `100.108.39.69:8085`.

Working directory: /home/adam/aiprojects/low_latency_voice_app
Integrity mode: development

## Requirements

### R1. Cross-Platform Audio Engine — Replace Windows-Only WinMM with miniaudio

The native C audio engine (`client/native/libvoice_engine.c`) currently implements audio capture and playback exclusively via the Windows Multimedia API (`waveIn*`/`waveOut*`). On Linux, all hardware functions are empty stubs — capture returns a synthetic 440 Hz sine wave, and playback does nothing. Microphone input is never read and speaker output never plays on Linux.

Replace the Windows-only WinMM backend with the `miniaudio` single-header library (`miniaudio.h`), which supports WASAPI (Windows), PulseAudio/PipeWire/ALSA (Linux), and CoreAudio (macOS). This must:
- Capture audio from the real hardware microphone on both Windows and Linux using `miniaudio`'s callback-driven device API, writing PCM samples into the existing `g_capture_ring` ring buffer.
- Play back mixed audio through real speakers/headphones on both Windows and Linux using `miniaudio`'s playback device, calling the existing `mix_audio_streams()` mixer in the playback callback.
- Preserve the existing device enumeration API (`voice_engine_get_input_devices`, `voice_engine_get_output_devices`, `voice_engine_set_input_device`, `voice_engine_set_output_device`).
- Remove the 440 Hz synthetic sine wave fallback in `voice_engine_capture_frame` — when hardware samples are temporarily unavailable, output silence (zero-filled buffer) instead.
- Implement proper thread synchronization for Linux (the current `enter_cs()`/`leave_cs()` are no-ops on non-Windows) using `pthread_mutex_t` or equivalent.
- Update `CMakeLists.txt` to download/include `miniaudio.h` and link appropriate platform libraries (e.g., `-ldl -lpthread -lm` on Linux).

### R2. Fix Backend UDP Session Scavenger Evicting Silent Listeners

The backend SFU's idle session scavenger (`server.go` cleanup loop) evicts UDP sessions after 60 seconds of inactivity based on `session.LastSeen`. However, `handlePing()` in `router.go` never updates `LastSeen` — only `handleVoice()` does. This means:
- A user who joins a voice channel but listens silently for >60s gets evicted from the SFU's channel routing table.
- After eviction, the silent user stops receiving forwarded audio from speaking peers.
- When the evicted user tries to speak, the SFU drops their packets with `ErrSessionNotFound`.

Fix `handlePing()` in `router.go` to look up the sender's session and call `session.Touch()` (or equivalent) to refresh `LastSeen` on every ping probe. This ensures listeners who send regular 1-second ping probes are never evicted.

### R3. Fix Hardcoded UDP Port `7878` in WebSocket Responses

In `backend/internal/control/handler.go`, the `handleAuth` (line 269) and `handleJoinVoice` (line 541) responses both return `"udp_port": 7878` as a hardcoded integer literal. If the server is configured to use a different UDP port (via `UDP_PORT` env var or `-udp-port` flag), clients receive the wrong port and send UDP datagrams into the void.

Replace the hardcoded `7878` with the actual configured UDP port from the `AuthService` (which already receives `*udpPort` at construction). The Hub or handler must have access to the configured UDP port and return it dynamically in all WebSocket responses that include `udp_port`.

### R4. Fix Client Settings Dialog Wrong Default Port and Ensure Default Server IP

In `client/lib/ui/dialogs/audio_settings_dialog.dart` line 412, the fallback port when parsing fails is `8080` instead of the correct `8085`. Fix this to use `AppConstants.defaultWsPort` (which is already `8085`).

Verify that `client/lib/core/constants.dart` has `defaultHost = '100.108.39.69'` and `defaultWsPort = 8085` (these are already correct, but confirm no other code overrides them).

### R5. Fix Inbound Audio Packet Re-Encoding Overhead

In `client/lib/state/voice_notifier.dart` line 138, received voice packets are decoded from UDP, then re-encoded with `packet.encode()` before being fed to the native engine via `feedInboundPacket()`. This creates unnecessary overhead and potential data corruption.

Instead, pass the original raw datagram bytes directly to `feedInboundPacket()` without the decode-then-re-encode round-trip. Store the raw bytes alongside the decoded packet in the inbound stream, or change `feedInboundPacket` to accept just the audio payload with sender metadata.

## Acceptance Criteria

### Audio Communication (Critical)
- [ ] Two users connected to the same voice channel on the same network can hear each other speak in real time without audio drops.
- [ ] A user who joins a voice channel and listens silently for >120 seconds continues to hear all speaking peers without interruption.
- [ ] Audio capture on Linux reads from the real hardware microphone — no synthetic 440 Hz sine tone is generated or transmitted.
- [ ] Audio playback on Linux outputs received audio through real speakers/headphones.
- [ ] Audio capture and playback on Windows continue to work correctly after the miniaudio migration.

### Server Configuration
- [ ] The backend server defaults to listening on TCP port `8085` and UDP port `7878` as configured.
- [ ] The `join_voice` and `auth` WebSocket responses return the actual configured UDP port, not a hardcoded `7878`.
- [ ] The client defaults to connecting to `100.108.39.69:8085`.

### Build & Cross-Platform
- [ ] `cd backend && go test ./...` passes all unit tests.
- [ ] The native audio engine compiles on Linux (`cmake . && make` produces `libvoice_engine.so`).
- [ ] The native audio engine compiles on Windows (produces `voice_engine.dll`).
- [ ] The Flutter client builds for Linux: `cd client && flutter build linux`.

### Code Quality
- [ ] No hardcoded IP addresses or ports remain outside of `constants.dart` and `docker-compose.yml` default configurations.
- [ ] Thread synchronization is properly implemented for Linux in the native audio engine (no data races on `g_capture_ring` or `g_peers`).

## 2026-09-01T10:44:52Z

This is a single self-contained fix; keep it small and focused.

Create a GitHub Actions CI workflow for an existing Flutter voice chat application that automatically builds a ready-to-run Windows distribution zip (containing the Flutter `.exe`, the pre-built native `voice_engine.dll`, and all required runtime files) on every push, and commit + push all current uncommitted changes to the existing GitHub remote.

Working directory: /home/adam/aiprojects/low_latency_voice_app
Integrity mode: development

## Context

- The repository is a Flutter desktop + Go backend voice chat app at `/home/adam/aiprojects/low_latency_voice_app`
- Git remote is already configured: `origin https://github.com/AdamOl135/low_latency_voice_app.git`
- There are currently uncommitted changes (the voice communication fixes from the previous teamwork run) that need to be committed and pushed first
- The Flutter client is at `client/` and the native C audio engine is at `client/native/` (uses CMake, depends on `miniaudio.h` which is already in the `client/native/` directory)
- The app cannot be cross-compiled from Linux to Windows — the CI workflow must run on a Windows runner
- The native engine (`voice_engine.dll`) must be compiled from `client/native/libvoice_engine.c` using CMake on Windows and placed where the Flutter Windows build can find it (typically `client/build/windows/x64/runner/Release/` or bundled via the Flutter CMake integration)
- The Go backend at `backend/` does NOT need to be included in the Windows zip — it runs separately on the server

## Requirements

### R1. GitHub Actions CI Workflow for Windows Build

Create a GitHub Actions workflow file that runs on Windows, builds the Flutter client for Windows desktop (including compiling the native `voice_engine.dll` from `client/native/`), and uploads a zip artifact containing everything needed to run the app — a user should be able to extract the zip and double-click the `.exe` to launch the app without any build tools installed.

### R2. Git Commit and Push

Commit all current uncommitted changes (the voice communication fixes plus the new CI workflow) with a clear commit message, and push to the `origin` remote on the current branch. Use `git config` for the commit author if needed (use "Adam" as the name and any placeholder email).

## Acceptance Criteria

### CI Workflow
- [ ] A `.github/workflows/` YAML file exists that triggers on push events
- [ ] The workflow runs on `windows-latest` (or equivalent Windows runner)
- [ ] The workflow installs Flutter, enables Windows desktop support, and runs `flutter build windows` in the `client/` directory
- [ ] The workflow compiles `voice_engine.dll` from `client/native/` using CMake on Windows
- [ ] The built `voice_engine.dll` is placed where the Flutter exe can load it at runtime (same directory as the exe or in the Flutter bundle)
- [ ] The workflow produces a downloadable zip artifact containing the complete `build/windows/x64/runner/Release/` directory (or equivalent)
- [ ] The zip artifact name includes the commit SHA or a version identifier

### Git Push
- [ ] All uncommitted changes are committed with a descriptive commit message
- [ ] The commit is pushed to `origin` on the current branch
- [ ] `git status` shows a clean working tree after the push

