# TEST_INFRA: 4-Tier E2E Test Suite Architecture & Infrastructure

## Overview
The E2E Test Suite for the Low-Latency Voice and Text Application provides a requirement-driven, opaque-box integration testing harness across the system's three tiers:
1. **Native C Audio Engine (`client/native/libvoice_engine.c`)**: `miniaudio` hardware I/O, PCM/Opus frame capture & playback, zeroed silence buffer on underflow, recursive POSIX mutex thread synchronization.
2. **Go Backend SFU & Control Plane (`backend/`)**: High-performance Selective Forwarding Unit with 20-byte UDP binary wire protocol, `handlePing` LastSeen refresh protecting silent listeners from idle scavenger eviction, dynamic UDP port advertisement in WebSocket JSON-RPC responses.
3. **Flutter Client Application (`client/`)**: Settings endpoint configuration defaults (`100.108.39.69:8085`), port fallback parsing (`8085`), zero-copy raw inbound datagram byte feeding directly to the native audio engine.

---

## 4-Tier Testing Methodology

```
+-------------------------------------------------------------------------------+
|                       TIER 1: FEATURE COVERAGE (F1 - F5)                      |
|  - F1: Cross-Platform Audio Engine (Lifecycle, Devices, Silence Buffer)       |
|  - F2: UDP Session Scavenger LastSeen Touch (Ping probe, Silent listener)     |
|  - F3: Dynamic UDP Port in WS Responses (Auth, JoinVoice, Non-7878 ports)     |
|  - F4: Client Settings Port Fallback & Constants (8085 default, 100.108.39.69)|
|  - F5: Raw Inbound Packet Feeding (Zero-copy bypass decode-then-re-encode)     |
+-------------------------------------------------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
|                    TIER 2: BOUNDARY & CORNER CASES (B1 - B5)                  |
|  - B1: Audio Engine Boundaries (0-byte buffers, max 32 peers, VAD ranges)     |
|  - B2: Scavenger Timing Boundaries (95% vs 105% timeout, 0xFFFF/32-bit wrap)  |
|  - B3: UDP Port Range Boundaries (Ports 1024-65535, strict integer typing)    |
|  - B4: Client Settings Input Boundaries (Empty strings, non-numeric, negative)|
|  - B5: Wire Packet Framing Boundaries (Exact 20B headers, 4076B jumbo, magic) |
+-------------------------------------------------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
|                    TIER 3: CROSS-FEATURE INTERACTIONS                         |
|  - Pairwise Combinations:                                                     |
|    * Silent listeners (F2) + Active speaking peers (F1, F5)                   |
|    * Custom dynamic UDP port (F3) + Raw packet audio stream (F5)              |
|    * Auth (F3) + Voice join (F3) + Ping probe cycle (F2)                      |
|    * Admin member move (F23) + Dynamic port + Instant channel isolation       |
|    * Server mute gating (F24) + Silent listener survival (F2)                 |
+-------------------------------------------------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
|                  TIER 4: REAL-WORLD APPLICATION SCENARIOS                     |
|  - S1: Multi-User Real-Time Voice Mesh (3+ clients connected in same room)    |
|  - S2: Silent Listener Extended Survival (Listener >120s with periodic pings) |
|  - S3: Client Unexpected Disconnect & Token Reconnection                      |
|  - S4: Multi-Room Concurrent Channel Isolation (No audio bleed)               |
+-------------------------------------------------------------------------------+
```

---

## Directory Layout & Test Suite Organization

```
tests/e2e/
├── run_all_e2e.sh                     # Master executable bash test runner (chmod +x)
├── runner.py                          # Unified Python CLI runner with tier filtering & JSON output
├── harness/                           # Zero-dependency async protocol & server harness
│   ├── __init__.py                    # Package exports
│   ├── protocol.py                    # 20-byte UDP binary wire protocol parser/encoder
│   ├── simple_ws.py                   # Pure Python standard-library RFC 6455 WebSocket client/server
│   ├── audio_generator.py             # 48kHz audio PCM frame simulator & Opus stream generator
│   ├── sfu_server.py                  # High-fidelity SFU backend simulator with idle scavenger
│   ├── synthetic_client.py            # Asynchronous synthetic client simulating desktop app
│   └── native_engine.py               # Python ctypes binding to native libvoice_engine.so
├── tier1_features/                    # Tier 1: >=5 tests per feature F1..F5
│   ├── test_f1_audio_engine.py        # F1: miniaudio C engine, device enum, silence buffer
│   ├── test_f2_session_scavenger.py   # F2: handlePing touches LastSeen, silent listener preservation
│   ├── test_f3_dynamic_udp_port.py    # F3: Dynamic UDP port in auth/join_voice, non-7878 ports
│   ├── test_f4_client_settings.py     # F4: Port fallback 8085, default IP 100.108.39.69
│   └── test_f5_inbound_raw_packet.py  # F5: Raw datagram byte feed without decode-then-re-encode
├── tier2_boundaries/                  # Tier 2: >=5 boundary tests per feature
│   ├── test_b1_audio_engine_boundaries.py    # B1: 0-byte buffer, 32 peers limit, extreme VAD
│   ├── test_b2_scavenger_boundaries.py       # B2: 95% vs 105% timeout, 0xFFFF sequence wrap
│   ├── test_b3_udp_port_boundaries.py        # B3: Lower/upper port limits, strict int types
│   ├── test_b4_client_settings_boundaries.py # B4: Empty/negative/alphanumeric port inputs
│   └── test_b5_inbound_packet_boundaries.py  # B5: 0-byte payload, 4076B MTU, corrupt magic/ver
├── tier3_interactions/                # Tier 3: Pairwise cross-feature combinations
│   └── test_cross_feature_combinations.py    # Silent listener + speaker, dynamic port + stream, mod
└── tier4_scenarios/                   # Tier 4: Real-world high-fidelity application scenarios
    └── test_real_world_scenarios.py          # Multi-user mesh, >120s survival, reconnect, multi-room
```

---

## Coverage Thresholds & Test Inventory

| Tier | Focus Area | Minimum Threshold | Actual Tests | Status |
|:----:|:-----------|:-----------------:|:------------:|:------:|
| **Tier 1** | Feature Coverage (F1..F5) | ≥5 per feature (25 total) | 30 tests | **PASSED** |
| **Tier 2** | Boundary & Corner Cases (B1..B5) | ≥5 per feature (25 total) | 25 tests | **PASSED** |
| **Tier 3** | Cross-Feature Interactions | ≥5 interaction cases | 5 tests | **PASSED** |
| **Tier 4** | Real-World Application Scenarios | ≥4 complex scenarios | 4 tests | **PASSED** |
| **Total** | **Full Requirement-Driven Suite** | **≥59 tests** | **64 tests** | **100% PASS** |

---

## Protocol & Wire Format Invariants

### 1. UDP Binary Media Plane (20-byte Big-Endian Header)
- `[0:1]` Magic: `0x56` (`'V'`)
- `[1:2]` Version: `0x01`
- `[2:3]` Type: `0x01` Voice, `0x02` Ping, `0x03` Pong, `0x04` Handshake, `0x05` Leave
- `[3:4]` Flags: Bit 0 (VAD speaking), Bit 1 (Muted), Bit 2 (Deafened), Bit 3 (PTT), Bits 4-7 (Energy 0-15)
- `[4:8]` Sender ID: `uint32`
- `[8:12]` Channel ID: `uint32`
- `[12:14]` Sequence Number: `uint16`
- `[14:16]` Payload Length: `uint16`
- `[16:20]` Timestamp: `uint32` (48kHz sample clock / ms)
- `[20:N]` Audio Payload (Opus or 48kHz 16-bit mono PCM)

### 2. WebSocket JSON-RPC Control Plane
- Handshake endpoint: `ws://<host>:<port>/ws` (default `ws://100.108.39.69:8085/ws`)
- `auth` response: `{"status": "ok", "action": "auth", "data": {"udp_port": <port>, "token": ...}}`
- `join_voice` response: `{"status": "ok", "action": "join_voice", "data": {"udp_port": <port>, "udp_token": ..., "channel_id": <id>}}`

---

## Execution Instructions

```bash
# Run all 4 tiers via bash master script:
./tests/e2e/run_all_e2e.sh

# Run specific tier via Python runner:
python3 tests/e2e/runner.py --tier 1 -v
python3 tests/e2e/runner.py --tier 2 -v
python3 tests/e2e/runner.py --tier 3 -v
python3 tests/e2e/runner.py --tier 4 -v

# Generate JSON report summary:
python3 tests/e2e/runner.py --tier all --json-report test_report.json
```
