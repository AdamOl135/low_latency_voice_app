# Project: Low-Latency Voice and Text Communication Application

## Architecture
A high-performance, self-hosted communication system composed of:
1. **Headless Go Backend**:
   - High-throughput UDP Selective Forwarding Unit (SFU) with zero-allocation `sync.Pool` packet router.
   - 20-byte binary UDP wire protocol with in-band VAD (<30ms speaking indicator propagation), 10-20ms Opus frame forwarding (20–160B), and uncompressed PCM frame forwarding (1920B/20ms @ 48kHz mono 16-bit). Expanded buffer size: `MaxPacketSize = 4096`, `MaxPayloadSize = 4076`.
   - WebSocket JSON-RPC control plane for real-time text chat, presence roster, channel tree, role-based authorization, and moderation (with WS Close Code 4001 kick lifecycle).
   - SQLite persistent storage in WAL mode for user accounts, channels, roles, server configuration, and chat message history.
2. **Native Flutter Desktop Client (Windows & Linux)**:
   - 3-Pane minimalist dark-mode layout (Left: Channels; Center: Chat Stream & Voice HUD; Right: Member Roster).
   - Clean Architecture state management (Riverpod) handling WebSocket control events, presence sync, voice states, speaking halo synchronization (<30ms), and clean kick handling without reconnect loops.
   - Native audio engine (`libvoice_engine` / `miniaudio` + `libopus` via Dart FFI / Audio Worker) with WASAPI / PipeWire backends, hardware device enumeration, PTT / VAD metering, and strict mic test loopback isolation to prevent self-echo.
   - Extensible media pipeline designed for future camera and screen sharing.
3. **Containerized Deployment & Mesh Networking**:
   - Multi-stage Docker packaging producing a lightweight (<20MB) Alpine container.
   - Docker Compose configuration with persistent volume mounts (`/app/data`).
   - Native Tailscale mesh IP (`100.x.y.z`) compatibility requiring zero public NAT traversal or reverse-proxy configuration.

```
+-----------------------------------------------------------------------------------+
|                           Flutter Desktop Client                                  |
|  +-------------------+  +--------------------------------+  +------------------+  |
|  | Left: Server Tree |  | Center: Chat Stream & Voice HUD|  | Right: Roster    |  |
|  +-------------------+  +--------------------------------+  +------------------+  |
|  | Riverpod State    |  | Audio Engine (miniaudio+Opus)  |  | PTT / VAD Engine |  |
+--+--------+----------+--+---------------+----------------+--+---------+--------+--+
            |                             |                             |
      WebSocket JSON-RPC             UDP Binary Audio              UDP Voice / Ping
     (Port 8080/tcp)               (Port 7878/udp)               (Port 7878/udp)
            |                             |                             |
+-----------v-----------------------------v-----------------------------v-----------+
|                              Go Backend SFU Server                                |
|  +-------------------+  +--------------------------------+  +------------------+  |
|  | WebSocket Hub     |  | UDP Packet Router (SFU)        |  | Moderation Engine|  |
|  | (Auth, Chat, Sync)|  | (In-Band VAD, <0.2ms Forward)  |  | (Gating & Kick)  |  |
|  +---------+---------+  +---------------+----------------+  +---------+--------+  |
|            |                            |                             |           |
|  +---------v----------------------------v-----------------------------v--------+  |
|  |                        SQLite WAL Storage (/app/data)                       |  |
+--+-----------------------------------------------------------------------------+--+
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F01 | 3-Pane Dark-Mode Layout | Left channel tree, center chat/HUD, right live member roster | M3 | R1 |
| F02 | Channel Hierarchy Tree | Categorized Voice and Text channels with active voice badges | M3 | R1 |
| F03 | Real-Time Chat Stream | Virtualized sliver message list with cursor pagination and timestamps | M1, M3 | R1 |
| F04 | Rich Text Input | Text input with multi-line, enter-to-send, and rate limiting | M3 | R1 |
| F05 | Voice HUD Dock | Active voice channel status, ping/latency HUD, instant disconnect button | M3 | R1 |
| F06 | Live Member Roster | Real-time presence list grouped by role with speaking/mute/deafen badges | M3 | R1 |
| F07 | Audio Device Selection | Enumeration and selection of input (mic) and output (speakers/headphones) | M3 | R1 |
| F08 | Local Mute & Deafen | Client-side microphone toggle and audio output suppression | M3 | R1 |
| F09 | Push-to-Talk (PTT) | Configurable local and global hotkey capture with mouse button support | M3 | R1 |
| F10 | Voice Activity Detection | Energy-based VAD (dBFS threshold) with 200ms hangover release | M3 | R1 |
| F11 | Media Extensibility | Decoupled audio/video track architecture ready for screen/camera share | M3 | R1 |
| F12 | Native Desktop Packaging | Clean compilation for Windows (.exe) and Ubuntu Linux (GTK native) | M3 | R1 |
| F13 | Ultra-Low-Latency SFU | High-throughput UDP packet router with zero-allocation sync.Pool | M2 | R2 |
| F14 | Binary Wire Protocol | 20-byte binary header with magic, flags, SSRC, sequence, and timestamp | M2 | R2 |
| F15 | Opus 10-20ms Frames | Low-latency 48kHz VOIP Opus encoding and decoding | M2, M3 | R2 |
| F16 | In-Band Fast VAD | Embedded VAD bit and energy level in UDP header for <30ms speaking sync | M2, M3, M7 | R2, Follow-up R3 |
| F17 | Minimal Jitter Buffer | Adaptive low-latency ring buffer with packet loss concealment (PLC) | M2, M3 | R2 |
| F18 | 15-Client Voice Mixing | Efficient multi-stream selective forwarding without audio degradation | M2, M6 | R2 |
| F19 | Tailscale Mesh Resiliency | Direct UDP packet transmission compatible with Tailscale MTU and mesh IP | M2, M5 | R2 |
| F20 | Round-Trip Latency Measurement | In-band UDP ping/pong probe with sub-millisecond precision | M2, M6 | R2 |
| F21 | Role & Permission Model | Bitfield-based permission system (Admin, Moderator, Member) | M1, M4 | R3 |
| F22 | Server Creator Admin Grant | Automatic Admin role assignment to the first registered server creator | M1, M4 | R3 |
| F23 | Channel Movement Action | Admin moves connected member with immediate client-side audio migration | M4 | R3 |
| F24 | Server-Side Mute Action | Server-enforced suppression of incoming voice packets at UDP router | M4 | R3 |
| F25 | Server-Side Deafen Action | Server-enforced suppression of outgoing voice packets to target client | M4 | R3 |
| F26 | Member Kick Action | Immediate WebSocket disconnection (code 4001) and UDP session revocation | M4, M7 | R3, Follow-up R4 |
| F27 | Real-Time State Sync Broadcast | Instant WebSocket JSON-RPC event broadcast for all channel/user state changes | M1, M4, M7 | R3, Follow-up R4 |
| F28 | Docker Containerization | Lightweight multi-stage Alpine Dockerfile with minimal footprint | M5 | R4 |
| F29 | Docker Compose Deployment | One-command orchestration (`docker compose up -d`) with volume persistence | M5 | R4 |
| F30 | Tailscale Zero-NAT Networking | Direct binding to Tailscale mesh IP for seamless private VPN access | M5 | R4 |
| F31 | Multi-Format UDP SFU 4096B Buffer | Expand UDP SFU to 4096B packet buffer supporting Opus and PCM 1920B | M7 | Follow-up R1 |
| F32 | Mic Test Loopback Isolation & Echo Elimination | Isolate mic test loopback to Settings mode, zeroing slot 0 on join/close | M7 | Follow-up R2 |
| F33 | Full-Stack Kick Sync & Reconnect Prevention | WS close code 4001 handling, kick banner, and full peer state purging | M7 | Follow-up R4 |

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Core & Persistence & WebSocket RPC | Go server scaffold, SQLite WAL persistence, Auth, Roles, Channel tree, WebSocket JSON-RPC server, Chat messaging | none | DONE |
| M2 | Ultra-Low-Latency Audio SFU & Voice Protocol | UDP packet router, 20-byte binary header, Opus framing, in-band VAD (<30ms), minimal jitter buffer, latency probe | M1 | DONE |
| M3 | Flutter Desktop Client (UI, Audio I/O, Controls) | 3-Pane UI, Riverpod state, native audio engine (miniaudio+Opus via FFI), PTT/VAD, device selection, Windows/Linux build | M1, M2 | DONE |
| M4 | Moderation Engine & Real-Time Sync Invariants | Server-side role enforcement, Admin move, server-mute/deafen UDP packet gating, kick session revocation, broadcast | M1, M2, M3 | DONE |
| M5 | Containerization & Tailscale Deployment | Dockerfile, docker-compose.yml, volume mounts, Tailscale mesh networking support, deployment scripts | M1, M2, M4 | DONE |
| M6 | Final Integration, 100% E2E Verification & Hardening | Dual-track convergence: Execute 4-Tier E2E test suite (Tiers 1-4) until 100% pass + Tier 5 Adversarial Hardening | M1-M5, E2E | DONE |
| M7 | Follow-up Audio Multi-Format, Echo Elimination, VAD Sync & Kick Sync | Go SFU 4096B buffer expansion (R1), C/Flutter mic test isolation & self-echo elimination (R2), In-band fast VAD & green halo UI sync (R3), Full-stack kick synchronization & close code 4001 handling (R4) | M1-M6 | IN_PROGRESS |
| E2E | E2E Testing Suite Track | Independent requirement-driven 4-tier test harness, runner, latency measurement, 15-client concurrency stress test | none (Parallel) | DONE |

## Interface Contracts

### 1. UDP Voice Binary Wire Protocol (Port 7878/udp)
```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Magic (0x56) | Version (0x01)| Type (0x01-04)| Flags/VAD+Lvl |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           Sender ID                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          Channel ID                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|        Sequence Number        |         Payload Length        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           Timestamp                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Audio Payload (Opus 20..160B or PCM 1920B) ...       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```
- `Magic`: Fixed byte `0x56` ('V')
- `Version`: `0x01`
- `Type`: `0x01` = Voice Packet, `0x02` = Ping, `0x03` = Pong, `0x04` = Voice Handshake
- `Flags/VAD`: Bit 0 = VAD (1=speaking, 0=silent), Bits 1-3 = Reserved, Bits 4-7 = Energy Level (0-15)
- `Sender ID`: 32-bit uint user identifier
- `Channel ID`: 32-bit uint active voice channel
- `Sequence Number`: 16-bit uint incrementing sequence
- `Payload Length`: 16-bit uint byte count of payload (`MaxPayloadSize = 4076`, `MaxPacketSize = 4096`)
- `Timestamp`: 32-bit uint sample timestamp (48kHz clock)

### 2. WebSocket Control Plane JSON-RPC (Port 8080/tcp)
- **Authentication**: `{"action": "auth", "token": "<session_token>", "client_version": "1.0.0"}` -> `{"status": "ok", "user_id": 1, "is_admin": true, "roles": ["admin"]}`
- **Channel Join**: `{"action": "join_voice", "channel_id": 101}` -> `{"status": "ok", "udp_token": "<token>", "udp_port": 7878}`
- **Send Text Message**: `{"action": "send_chat", "channel_id": 201, "content": "Hello!"}` -> broadcast `{"event": "chat_message", "id": 55, "channel_id": 201, "sender_id": 1, "sender_name": "Admin", "content": "Hello!", "timestamp": 1724930000}`
- **Move Member**: `{"action": "move_member", "target_user_id": 2, "to_channel_id": 102}` -> broadcast `{"event": "member_moved", "user_id": 2, "from_channel_id": 101, "to_channel_id": 102}`
- **Server Mute / Deafen**: `{"action": "set_server_mute", "target_user_id": 2, "muted": true}` -> broadcast `{"event": "voice_state_update", "user_id": 2, "server_muted": true}`
- **Kick Member**: `{"action": "kick_member", "target_user_id": 2, "reason": "Rule violation"}` -> WebSocket close code `4001` on target client + token/session purge + broadcast `{"event": "member_kicked", "user_id": 2}` and `{"event": "voice_state_update", "user_id": 2, "channel_id": null}`
- **Client Kick Reaction**: Close code 4001 detected -> cancel reconnection loop -> disconnect voice/chat -> show "Kicked by administrator" banner without wiping credentials.
- **Peer Kick Reaction**: Global `member_kicked` event -> purge target from `members`, `voiceStates`, `voiceOccupants`, and speaking/volume tracking.

### 3. Native Audio FFI Interface (`libvoice_engine`)
```c
int voice_engine_init(uint32_t sample_rate, uint32_t frame_size_ms, uint32_t channels);
int voice_engine_start_capture(const char* input_device_id, void (*on_encoded_frame)(const uint8_t* data, uint32_t len, uint8_t vad_flag, uint8_t energy));
int voice_engine_submit_playback_frame(uint32_t ssrc, const uint8_t* opus_data, uint32_t len, uint32_t timestamp);
int voice_engine_set_vad_threshold(float threshold_dbfs);
int voice_engine_set_ptt_active(int active);
void voice_engine_clear_peers(void); // Resets all peers i=0..MAX_PEERS-1 and g_mic_test_loopback=false
int voice_engine_shutdown(void);
```

## Code Layout
```
low_latency_voice_app/
├── .agents/                      # Agent orchestration metadata only
├── backend/                      # Headless Go Backend
│   ├── cmd/
│   │   └── server/               # Main application entry point (main.go)
│   ├── internal/
│   │   ├── audio/                # UDP SFU router, 4096B packet pooling, jitter buffer
│   │   ├── auth/                 # Session tokens, password hashing, admin bootstrap
│   │   ├── control/              # WebSocket JSON-RPC hub, kick close code 4001, event broadcast
│   │   ├── model/                # Data structures (User, Channel, Message, Role)
│   │   ├── moderation/           # Permission checks, mute/deafen gating, kick
│   │   └── storage/              # SQLite WAL database repository, token revocation
│   ├── go.mod
│   ├── go.sum
│   └── Dockerfile                # Multi-stage Alpine container build
├── client/                       # Flutter Desktop Application
│   ├── lib/
│   │   ├── main.dart             # App entry point
│   │   ├── core/                 # Constants, theme (dark-mode), router
│   │   ├── audio/                # Dart FFI bindings to libvoice_engine & isolates
│   │   ├── models/               # Client-side data models
│   │   ├── services/             # WebSocket client (code 4001 handler), UDP voice client
│   │   ├── state/                # Riverpod providers (auth, channels, roster, voice, settings)
│   │   └── ui/                   # 3-Pane Desktop Layout
│   │       ├── channels/         # Left: Server tree & channel lists (green halo speaking badge)
│   │       ├── chat/             # Center: Text chat stream & message input
│   │       ├── voice/            # Center: Active voice HUD & controls
│   │       ├── roster/           # Right: Live member presence roster (green halo speaking badge)
│   │       └── dialogs/          # Settings (mic test dispose cleanup), Audio Device selection, Admin mod
│   ├── native/                   # C Native Audio Engine (libvoice_engine with clean loopback isolation)
│   │   ├── src/
│   │   ├── CMakeLists.txt
│   │   └── include/
│   ├── pubspec.yaml
│   └── windows/ / linux/         # Native desktop platform runners
├── docker-compose.yml            # Production deployment config
├── scripts/                      # Deployment and build scripts
└── test/                         # E2E Test Suite & Synthetic Load Harness
    ├── e2e_runner/               # Standalone test runner
    ├── tier1_features/           # Feature coverage tests (voice protocol, VAD sync)
    ├── tier2_boundaries/         # Boundary and corner tests
    ├── tier3_interactions/       # Cross-feature interaction tests (mod kick revocation, multi-client state)
    ├── tier4_latency_concurrency/# 15-Client load & <30ms latency harness
    └── test_harness/             # Mock clients, audio sine generator, UDP probes
```
