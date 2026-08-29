# E2E Test Infra: Low-Latency Voice and Text Communication App

## Test Philosophy
- **Opaque-Box & Requirement-Driven**: Tests interact with the backend and client endpoints exclusively through standard network protocols (WebSocket JSON-RPC on port 8080, UDP Voice on port 7878) and native binary outputs, without internal white-box mocks.
- **Methodology**: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Interaction Testing + Real-World 15-Client Concurrent Load Testing.
- **Strict SLA**: Packet processing latency <30ms, speaking state indicator propagation <30ms, 15 active voice streams without packet dropping or degradation.

## Feature Inventory & Test Coverage
| # | Feature | Source (Requirement) | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|----------------------|:------:|:------:|:------:|:------:|
| F01 | 3-Pane Dark-Mode Layout | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F02 | Channel Hierarchy Tree | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F03 | Real-Time Chat Stream | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F04 | Rich Text Input | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F05 | Voice HUD Dock | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F06 | Live Member Roster | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F07 | Audio Device Selection | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F08 | Local Mute & Deafen | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F09 | Push-to-Talk (PTT) | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F10 | Voice Activity Detection | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F11 | Media Extensibility | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F12 | Native Desktop Packaging | ORIGINAL_REQUEST §R1 | ✓ (5) | ✓ | ✓ | ✓ |
| F13 | Ultra-Low-Latency SFU | ORIGINAL_REQUEST §R2 | ✓ (5) | ✓ | ✓ | ✓ |
| F14 | Binary Wire Protocol | ORIGINAL_REQUEST §R2 | ✓ (5) | ✓ | ✓ | ✓ |
| F15 | Opus 10-20ms Frames | ORIGINAL_REQUEST §R2 | ✓ (5) | ✓ | ✓ | ✓ |
| F16 | In-Band Fast VAD (<30ms) | ORIGINAL_REQUEST §R2 | ✓ (5) | ✓ | ✓ | ✓ |
| F17 | Minimal Jitter Buffer | ORIGINAL_REQUEST §R2 | ✓ (5) | ✓ | ✓ | ✓ |
| F18 | 15-Client Voice Mixing | ORIGINAL_REQUEST §R2 | ✓ (5) | ✓ | ✓ | ✓ |
| F19 | Tailscale Mesh Resiliency | ORIGINAL_REQUEST §R2 | ✓ (5) | ✓ | ✓ | ✓ |
| F20 | Round-Trip Latency Measurement | ORIGINAL_REQUEST §R2 | ✓ (5) | ✓ | ✓ | ✓ |
| F21 | Role & Permission Model | ORIGINAL_REQUEST §R3 | ✓ (5) | ✓ | ✓ | ✓ |
| F22 | Server Creator Admin Grant | ORIGINAL_REQUEST §R3 | ✓ (5) | ✓ | ✓ | ✓ |
| F23 | Channel Movement Action | ORIGINAL_REQUEST §R3 | ✓ (5) | ✓ | ✓ | ✓ |
| F24 | Server-Side Mute Action | ORIGINAL_REQUEST §R3 | ✓ (5) | ✓ | ✓ | ✓ |
| F25 | Server-Side Deafen Action | ORIGINAL_REQUEST §R3 | ✓ (5) | ✓ | ✓ | ✓ |
| F26 | Member Kick Action | ORIGINAL_REQUEST §R3 | ✓ (5) | ✓ | ✓ | ✓ |
| F27 | Real-Time State Sync Broadcast | ORIGINAL_REQUEST §R3 | ✓ (5) | ✓ | ✓ | ✓ |
| F28 | Docker Containerization | ORIGINAL_REQUEST §R4 | ✓ (5) | ✓ | ✓ | ✓ |
| F29 | Docker Compose Deployment | ORIGINAL_REQUEST §R4 | ✓ (5) | ✓ | ✓ | ✓ |
| F30 | Tailscale Zero-NAT Networking | ORIGINAL_REQUEST §R4 | ✓ (5) | ✓ | ✓ | ✓ |

## Test Architecture & Directory Layout
```
test/
├── runner.py                     # Unified E2E Test Suite Runner
├── tier1_features/
│   ├── test_auth_roles.py        # T1.1: Registration, Login, Admin bootstrap, Tokens
│   ├── test_channels.py          # T1.2: Channel creation, categories, listing, hierarchy
│   ├── test_chat_messaging.py    # T1.3: Text chat send, receive, history pagination
│   ├── test_voice_protocol.py    # T1.4: UDP handshake, 20-byte framing, Opus forwarding
│   ├── test_voice_vad_sync.py    # T1.5: In-band VAD detection, speaking indicator broadcast
│   └── test_client_ui_build.py   # T1.6: Flutter desktop compilation & layout validation
├── tier2_boundaries/
│   ├── test_packet_boundaries.py # T2.1: 0-byte UDP, jumbo frames (>MTU), malformed headers
│   ├── test_jitter_bursts.py     # T2.2: Burst packet arrivals, out-of-order reordering
│   ├── test_chat_limits.py       # T2.3: 4000-char messages, rapid message flooding
│   └── test_rapid_channel_hops.py# T2.4: 50 channel switches per second stress
├── tier3_interactions/
│   ├── test_mod_channel_move.py  # T3.1: Admin moving member during active voice streaming
│   ├── test_mod_server_mute.py   # T3.2: Server-mute packet gating vs local mute
│   ├── test_mod_server_deafen.py # T3.3: Server-deafen egress packet suppression
│   ├── test_mod_kick_revocation.py# T3.4: Member kick during active streaming & token revocation
│   └── test_multi_client_state.py# T3.5: Concurrent state sync across mixed roles
├── tier4_latency_concurrency/
│   ├── test_sub_30ms_latency.py  # T4.1: High-precision nanosecond UDP loopback probe (<30ms)
│   ├── test_15_client_voice.py   # T4.2: 15 concurrent active voice streams in single channel
│   └── test_audio_degradation.py # T4.3: PESQ/SNR/Packet loss calculation under 15-stream load
└── test_harness/
    ├── synthetic_client.py       # Headless synthetic client simulating WebSocket + UDP
    ├── audio_generator.py        # 440Hz / 1kHz sine wave Opus frame generator
    └── latency_probe.py          # Nanosecond timestamp loopback & jitter calculator
```

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| S1 | 15-User Gaming Voice Session | F05, F06, F13, F14, F15, F16, F17, F18, F19, F20 | High |
| S2 | Moderated Community Channel | F02, F03, F06, F21, F22, F23, F24, F25, F26, F27 | High |
| S3 | Tailscale Remote Voice Mesh | F13, F14, F19, F20, F28, F29, F30 | High |
| S4 | Rapid Channel Hopping & Chat Stream | F02, F03, F04, F05, F06, F13, F23, F27 | Medium |

## Coverage Thresholds
- **Tier 1**: ≥5 tests per functional area (Total: 30+ tests)
- **Tier 2**: ≥10 boundary & corner tests
- **Tier 3**: ≥7 cross-feature interaction tests
- **Tier 4**: ≥4 realistic high-concurrency and latency SLA tests
- **Total Suite**: 50+ rigorous automated test cases
