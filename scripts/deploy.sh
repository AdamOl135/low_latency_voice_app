#!/usr/bin/env bash
# ==============================================================================
# Low-Latency Voice App — Ubuntu Server Automated Deployment Script
# Milestone 5: Containerized Backend Deployment with Docker Compose
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "===================================================================="
echo "  Deploying Low-Latency Voice & Text Backend Stack"
echo "  Target: Ubuntu Server / Docker Compose"
echo "  Root: ${SCRIPT_DIR}"
echo "===================================================================="

# 1. Check prerequisites
command -v docker >/dev/null 2>&1 || {
    echo "[-] Error: Docker is not installed. Please install Docker first." >&2
    exit 1
}

DOCKER_COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    echo "[-] Error: Neither 'docker compose' nor 'docker-compose' found." >&2
    exit 1
fi

# 2. Ensure data directory exists with appropriate permissions
DATA_DIR="${SCRIPT_DIR}/data"
if [ ! -d "$DATA_DIR" ]; then
    echo "[+] Creating persistent data directory: ${DATA_DIR}"
    mkdir -p "$DATA_DIR"
    chmod 755 "$DATA_DIR"
fi

# 3. Handle arguments (e.g. stop, logs, status, rebuild)
ACTION="${1:-up}"

case "$ACTION" in
    stop)
        echo "[+] Stopping voice backend stack..."
        $DOCKER_COMPOSE_CMD down
        echo "[+] Stack stopped."
        exit 0
        ;;
    logs)
        $DOCKER_COMPOSE_CMD logs -f voice-backend
        exit 0
        ;;
    status)
        $DOCKER_COMPOSE_CMD ps
        exit 0
        ;;
    rebuild)
        echo "[+] Rebuilding container images..."
        $DOCKER_COMPOSE_CMD build --no-cache
        ;;
    up|"")
        ;;
    *)
        echo "Usage: $0 [up|stop|logs|status|rebuild]"
        exit 1
        ;;
esac

# 4. Build and boot containerized stack
echo "[+] Starting services with Docker Compose..."
$DOCKER_COMPOSE_CMD up -d --build

# 5. Wait for backend healthcheck
echo "[+] Waiting for healthcheck probe on http://127.0.0.1:8085/health..."
MAX_RETRIES=30
COUNT=0
HEALTHY=false

while [ $COUNT -lt $MAX_RETRIES ]; do
    if curl -s -f http://127.0.0.1:8085/health >/dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    COUNT=$((COUNT + 1))
    sleep 1
done

if [ "$HEALTHY" = true ]; then
    echo "[+] Backend is HEALTHY and listening for connections!"
else
    echo "[-] Warning: Health check did not respond within ${MAX_RETRIES}s. Inspecting logs:"
    $DOCKER_COMPOSE_CMD logs --tail=50 voice-backend
    exit 1
fi

# 6. Display active network endpoints
echo ""
echo "===================================================================="
echo "  DEPLOYMENT SUCCESSFUL"
echo "===================================================================="
echo "  HTTP/WebSocket Control Plane:  ws://0.0.0.0:8085/ws"
echo "  UDP Voice SFU Audio Plane:     0.0.0.0:7878/udp"
echo "  Persistent Storage Directory:  ${DATA_DIR}"

if command -v tailscale >/dev/null 2>&1; then
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "")
    if [ -n "$TS_IP" ]; then
        echo "  Tailscale Mesh IP:             ${TS_IP}"
        echo "  Tailscale WebSocket URL:       ws://${TS_IP}:8085/ws"
        echo "  Tailscale Voice UDP:           ${TS_IP}:7878/udp"
    fi
fi
echo "===================================================================="
