#!/usr/bin/env bash
# ==============================================================================
# Low-Latency Voice App — Tailscale Mesh Setup Script
# Milestone 5: Zero-NAT Mesh VPN Network Provisioning for Ubuntu Server
# ==============================================================================
set -euo pipefail

echo "===================================================================="
echo "  Tailscale Mesh Network Setup for Low-Latency Voice Backend"
echo "===================================================================="

# 1. Require root or sudo privileges
if [ "$EUID" -ne 0 ]; then
    echo "[-] Please run as root or with sudo: sudo $0" >&2
    exit 1
fi

# 2. Check and Install Tailscale if not present
if ! command -v tailscale >/dev/null 2>&1; then
    echo "[+] Installing Tailscale repository and package..."
    curl -fsSL https://tailscale.com/install.sh | sh
    echo "[+] Tailscale installed successfully."
else
    echo "[+] Tailscale is already installed."
fi

# 3. Ensure tailscaled daemon is active and enabled on boot
echo "[+] Enabling and starting tailscaled service..."
systemctl enable --now tailscaled

# 4. Optimize UDP performance and buffer sizes for low-latency VoIP SFU
echo "[+] Tuning kernel UDP buffers for real-time Opus packet streams..."
sysctl -w net.core.rmem_max=26214400 >/dev/null 2>&1 || true
sysctl -w net.core.wmem_max=26214400 >/dev/null 2>&1 || true
sysctl -w net.core.rmem_default=1048576 >/dev/null 2>&1 || true
sysctl -w net.core.wmem_default=1048576 >/dev/null 2>&1 || true

# Persist sysctl parameters across reboots
SYSCTL_CONF="/etc/sysctl.d/99-voice-app-udp.conf"
cat <<EOF > "$SYSCTL_CONF"
# Low-Latency Voice App UDP Buffer Tuning
net.core.rmem_max = 26214400
net.core.wmem_max = 26214400
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
EOF
echo "[+] Persisted UDP tuning to ${SYSCTL_CONF}."

# 5. Authenticate / Up Tailscale
AUTH_KEY="${TAILSCALE_AUTH_KEY:-}"

if [ -n "$AUTH_KEY" ]; then
    echo "[+] Authenticating Tailscale with pre-authorized key..."
    tailscale up --auth-key="$AUTH_KEY" --ssh --accept-routes
else
    echo "[+] Bringing up Tailscale interactive login..."
    tailscale up --ssh --accept-routes || true
fi

# 6. Retrieve and display mesh network details
TS_IP=$(tailscale ip -4 2>/dev/null || echo "Pending authentication")
TS_NAME=$(tailscale status --json 2>/dev/null | grep -o '"HostName":"[^"]*"' | head -1 | cut -d'"' -f4 || hostname)

echo ""
echo "===================================================================="
echo "  TAILSCALE MESH NETWORK READY"
echo "===================================================================="
echo "  Host Name:       ${TS_NAME}"
echo "  Tailscale IPv4:  ${TS_IP}"
echo ""
echo "  To connect Flutter Desktop clients over Tailscale:"
echo "    - Control WebSocket: ws://${TS_IP}:8080/ws"
echo "    - Voice SFU UDP:     ${TS_IP}:7878"
echo "===================================================================="
