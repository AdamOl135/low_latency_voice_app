#!/usr/bin/env bash
# ==============================================================================
# Low-Latency Voice App — Release Packaging Script
# Cleans old zip archives and generates release zip packages for current version
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

VERSION=$(grep -E '^version:' client/pubspec.yaml | head -n 1 | awk '{print $2}' | cut -d'+' -f1)
if [ -z "$VERSION" ]; then
    VERSION="1.0.0"
fi

echo "===================================================================="
echo "  Packaging Low-Latency Voice App (Version: v${VERSION})"
echo "  Root: ${SCRIPT_DIR}"
echo "===================================================================="

# 1. Clean old zip archives and dist
echo "[1/4] Cleaning old zip files..."
find . -maxdepth 3 -name "*.zip" -type f -exec rm -vf {} +
rm -rf dist
mkdir -p dist

# 2. Build Windows 11 Desktop Release (.zip with .exe and .dll)
echo "[2/4] Building Windows 11 Release ZIP (.exe + .dll + assets)..."
python3 scripts/build_windows_dist.py

# 3. Build Linux x64 Client Bundle
echo "[3/4] Packaging Linux Client Bundle..."
CLIENT_BUNDLE_DIR="client/build/linux/x64/debug/bundle"

if [ -d "$CLIENT_BUNDLE_DIR" ]; then
    if [ -f "client/native/build/libvoice_engine.so" ]; then
        cp -p "client/native/build/libvoice_engine.so" "${CLIENT_BUNDLE_DIR}/lib/"
    fi

    CLIENT_STAGE="dist/low_latency_voice_app-v${VERSION}-linux-x64"
    rm -rf "$CLIENT_STAGE"
    mkdir -p "$CLIENT_STAGE"
    cp -r "${CLIENT_BUNDLE_DIR}"/* "$CLIENT_STAGE/"
    
    cat << 'RUNNER_EOF' > "$CLIENT_STAGE/run.sh"
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_LIBRARY_PATH="${SCRIPT_DIR}/lib:${LD_LIBRARY_PATH:-}"
exec "${SCRIPT_DIR}/low_latency_voice_app" "$@"
RUNNER_EOF
    chmod +x "$CLIENT_STAGE/run.sh" "$CLIENT_STAGE/low_latency_voice_app"

    cat << README_EOF > "$CLIENT_STAGE/README.txt"
Low-Latency Voice & Text Desktop Client
Version: v${VERSION}
Platform: Ubuntu Linux x64

Usage:
  ./run.sh
or
  LD_LIBRARY_PATH=./lib ./low_latency_voice_app

Configuration:
  Connect to backend via WebSocket: ws://<SERVER_IP>:8085/ws
  Voice UDP SFU Endpoint: <SERVER_IP>:7878/udp
README_EOF

    (cd dist && zip -r "low_latency_voice_app-v${VERSION}-linux-x64.zip" "low_latency_voice_app-v${VERSION}-linux-x64")
    rm -rf "$CLIENT_STAGE"
    echo "[+] Created dist/low_latency_voice_app-v${VERSION}-linux-x64.zip"
fi

# 4. Package Backend Server Stack
echo "[4/4] Packaging Backend Deployment Stack..."
BACKEND_STAGE="dist/low_latency_voice_app-v${VERSION}-backend"
rm -rf "$BACKEND_STAGE"
mkdir -p "$BACKEND_STAGE"

cp -r backend "$BACKEND_STAGE/"
cp -r scripts "$BACKEND_STAGE/"
cp docker-compose.yml "$BACKEND_STAGE/"
cp PROJECT.md "$BACKEND_STAGE/"
cp ORIGINAL_REQUEST.md "$BACKEND_STAGE/"

cat << README_BK_EOF > "$BACKEND_STAGE/README.txt"
Low-Latency Voice & Text App — Backend Server Deployment Package
Version: v${VERSION}

Deployment:
1. Ensure Docker and Docker Compose are installed.
2. Run deployment script:
   ./scripts/deploy.sh up
   
Ports:
- HTTP/WebSocket Control Plane: 8085/tcp
- UDP Voice SFU Audio Plane:    7878/udp
README_BK_EOF

(cd dist && zip -r "low_latency_voice_app-v${VERSION}-backend.zip" "low_latency_voice_app-v${VERSION}-backend")
rm -rf "$BACKEND_STAGE"
echo "[+] Created dist/low_latency_voice_app-v${VERSION}-backend.zip"

echo ""
echo "===================================================================="
echo "  ALL RELEASE PACKAGES READY"
echo "===================================================================="
ls -lh dist/*.zip
echo "===================================================================="
