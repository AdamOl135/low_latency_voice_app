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
