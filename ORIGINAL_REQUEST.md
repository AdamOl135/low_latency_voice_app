# Original User Request

## Initial Request — 2026-08-29T11:55:06+02:00

A self-hosted, ultra-low-latency voice and text communication application with a native Flutter desktop client (Windows and Ubuntu Linux) and a Dockerized backend engineered for Ubuntu Server with Tailscale VPN compatibility. The system is designed to be built in small, calculated, well-tested steps to ensure maximum audio accuracy and responsiveness.

Working directory: C:\Users\adaml\.gemini\antigravity\scratch\low_latency_voice_app
Integrity mode: development

## Requirements

### R1. Native Desktop Client (Flutter)
A native desktop client targeting Windows (.exe) and Ubuntu Linux (GTK/native executable) with zero web-wrapper dependencies:
- Minimalist dark-mode 3-pane layout:
  - Left panel: Server navigation and channel lists (separated into Voice and Text channels).
  - Center panel: Real-time text chat message stream and active voice channel HUD with controls.
  - Right panel: Live member roster with real-time presence and voice state indicators (speaking, muted, deafened).
- Voice interaction controls: Instant mute, deafen, push-to-talk / voice activity detection, and audio input/output device selection.
- Architecture structured to support future extension to camera and screen-sharing streams.

### R2. Ultra-Low-Latency Audio Architecture
A high-performance audio transport pipeline engineered to minimize talking latency to the absolute floor for channels of up to 15 concurrent users:
- Low-latency Opus encoding/decoding with optimized frame durations (10–20ms) and minimal-buffer jitter handling.
- Real-time voice state propagation (speaking indicators triggered with <30ms latency upon voice detection).
- Resilient packet handling across local networks and VPN meshes (Tailscale / WireGuard).

### R3. Server Management & Moderation
A server-side role and permission system with an initial Admin role (granted automatically to server creators):
- Member movement: Admins can move connected members between voice channels with immediate client-side sync.
- Moderation actions: Server-wide muting, server-wide deafening, and kicking members from the server.
- Real-time synchronization: Instant broadcast of moderation actions and channel states to all connected clients.

### R4. Containerized Self-Hosted Backend & VPN Networking
A lightweight, headless backend packaged for deployment via Docker and Docker Compose on an Ubuntu Server PC:
- Container configuration with all ports and volume mounts defined for clean host management.
- Native compatibility with Tailscale mesh networking without requiring complex public reverse-proxy gymnastics.
- Persistent storage for server configuration, channels, roles, and text chat history.

## Acceptance Criteria

### Audio Performance & Latency
- [ ] Automated loopback and round-trip audio latency tests confirm packet processing overhead under 30ms on local/VPN networks.
- [ ] Synthetic multi-client load test simulates 15 concurrent active voice streams in a single channel without packet drop cascading or audio degradation.
- [ ] Speaking indicator activation and deactivation state changes arrive at peer clients within 30ms of audio threshold crossing.

### Native Client & UI Verification
- [ ] Flutter desktop client compiles and executes cleanly as a native Windows executable and native Ubuntu Linux binary.
- [ ] 3-pane UI renders smoothly with responsive layout adjustments, displaying server list, channel hierarchy, text stream, and member roster.
- [ ] Input/output audio device selection and push-to-talk / voice activation controls function correctly.

### Moderation & State Synchronization
- [ ] Server creator receives Admin role with verified authorization flags.
- [ ] Action verification: Moving a user to another voice channel transfers their audio session immediately.
- [ ] Action verification: Server-muting/deafening a member suppresses their transmitted/received audio server-side and reflects across all client UIs.
- [ ] Action verification: Kicking a member immediately disconnects their WebSocket/voice sessions and revokes server access.

### Deployment & Infrastructure
- [ ] `docker compose up -d` boots the complete backend stack on Ubuntu Server without manual post-install intervention.
- [ ] Clients connected over a Tailscale network IP can discover, authenticate, exchange chat, and stream voice bidirectionally.

## Follow-up — 2026-08-30T01:17:05+02:00

Resolve voice audio transmission, eliminate local self-echo loopback, synchronize peer speaking indicators, and implement real-time member kick synchronization in the low-latency Discord-like voice application.

Working directory: c:/Users/adaml/.gemini/antigravity/scratch/low_latency_voice_app
Integrity mode: development

## Requirements

### R1. UDP SFU Datagram Buffer & Multi-Format Audio Forwarding
Expand the Go backend UDP SFU packet buffer (`MaxPacketSize = 4096` bytes, `MaxPayloadSize = 4076` bytes) and update the packet buffer pool so that both compressed Opus frames (20–160 bytes) and uncompressed PCM audio frames (1920 bytes / 20ms @ 48kHz mono) are received, decoded without payload length mismatch errors, and selectively forwarded to all peer sessions in the same voice channel.

### R2. Local Audio Self-Echo Elimination & Clean Mic Test Isolation
Ensure the client audio engine (`libvoice_engine.c`, `audio_engine.dart`, and `settings_notifier.dart`) isolates mic test loopback exclusively to Settings test mode. Joining a voice channel or closing the settings dialog must guarantee `g_mic_test_loopback` and `g_peers[0]` are cleared and disabled so users never hear their own voice looped back into their headphones/speakers.

### R3. In-Band Fast VAD & Peer Speaking Indicator Synchronization
Ensure that when any connected member in a voice channel speaks, their in-band VAD bit and energy level are transmitted in the UDP audio header, processed by the SFU, and received by all channel peers. Peers must immediately display the green speaking indicator halo ring around the speaking user's avatar in both the Channel Occupants tree and Member Roster (<30ms latency).

### R4. Member Kick Real-Time State Synchronization & Disconnect Handling
Implement end-to-end kick synchronization across the full stack according to the user design choice:
1. **Backend**: Disconnect the kicked client with WebSocket close code 4001, revoke UDP tokens, remove active voice states, and broadcast `member_kicked` and voice channel evacuation events.
2. **Kicked Client**: Detect close code 4001 in `WebSocketService`, prevent automatic reconnect loops, disconnect the user from voice channels and chat, and present a clear 'Kicked' notification/banner explaining they were kicked by an administrator without clearing their credential state completely.
3. **Peer Clients**: Upon receiving `member_kicked`, immediately remove the kicked member from the active Member Roster, purge them from `voiceStates`, remove them from `voiceOccupants` in the Channel Tree, and clear their speaking/volume entries.

## Acceptance Criteria

### Audio & Voice Communication
- [ ] Users connected to the same voice channel hear all other speaking peers in real time without audio drops.
- [ ] Users in a voice channel do not hear their own voice looped back.
- [ ] When a peer speaks, their avatar displays the green speaking glow/halo in the left channel occupant list and the right member roster.
- [ ] In-band VAD energy levels and speaking states update responsively for all peers in the voice channel.

### Moderation & Kick Synchronization
- [ ] Kicking a member immediately terminates their active WebSocket connection (close code 4001) and revokes their UDP voice session.
- [ ] The kicked client disconnects from voice and chat channels and displays an informative 'Kicked' notification without initiating auto-reconnect loops.
- [ ] All other connected clients immediately reflect the member's removal from the member roster and voice channel occupants tree in real time.

### Verification & Testing
- [ ] All Go backend unit and integration tests pass (`cd backend && go test ./...`).
- [ ] All Flutter client unit and state tests pass (`cd client && flutter test`).
- [ ] All end-to-end multi-client test suites pass (`pytest test/tier1_features/test_voice_protocol.py test/tier1_features/test_voice_vad_sync.py test/tier3_interactions/test_mod_kick_revocation.py test/tier3_interactions/test_multi_client_state.py`).

