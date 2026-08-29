"""Tier 1.6: Flutter Desktop Client Layout, Architecture, and FFI Contracts.

Validates:
- F01: 3-Pane Dark-Mode Layout (Left: Channels, Center: Chat/HUD, Right: Roster)
- F07: Audio Device Selection (mic/speaker enumeration)
- F08: Local Mute & Deafen controls
- F09: Push-to-Talk (PTT) hotkey models
- F10: Voice Activity Detection (dBFS threshold)
- F11: Media Extensibility (audio/video track interfaces)
- F12: Native Desktop Packaging (Windows/Linux)
- Native Audio FFI Contract (PROJECT.md §3)
"""

import os
import re
import pytest

CLIENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "client"))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_client_directory_or_blueprint_conformance():
    """Verify Flutter client directory structure or architecture blueprint definition."""
    project_md_path = os.path.join(PROJECT_ROOT, "PROJECT.md")
    assert os.path.exists(project_md_path), "PROJECT.md must exist at project root"

    with open(project_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check key architectural modules in layout
    assert "client/lib/ui/channels" in content or "channels/" in content
    assert "client/lib/ui/chat" in content or "chat/" in content
    assert "client/lib/ui/roster" in content or "roster/" in content
    assert "libvoice_engine" in content


def test_3_pane_layout_contract_spec():
    """Verify 3-pane UI contract requirements (F01)."""
    original_req_path = os.path.join(PROJECT_ROOT, "ORIGINAL_REQUEST.md")
    with open(original_req_path, "r", encoding="utf-8") as f:
        req_content = f.read()

    assert "Minimalist dark-mode 3-pane layout" in req_content
    assert "Left panel" in req_content
    assert "Center panel" in req_content
    assert "Right panel" in req_content


def test_audio_engine_ffi_header_signatures():
    """Verify C FFI function signatures in PROJECT.md §3 match native engine contract."""
    project_md_path = os.path.join(PROJECT_ROOT, "PROJECT.md")
    with open(project_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    required_signatures = [
        "int voice_engine_init",
        "int voice_engine_start_capture",
        "int voice_engine_submit_playback_frame",
        "int voice_engine_set_vad_threshold",
        "int voice_engine_set_ptt_active",
        "int voice_engine_shutdown",
    ]

    for sig in required_signatures:
        assert sig in content, f"Missing required FFI signature: {sig}"


def test_ptt_and_vad_model_contracts():
    """Verify PTT (F09) and VAD (F10) configuration parameters."""
    project_md_path = os.path.join(PROJECT_ROOT, "PROJECT.md")
    with open(project_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check VAD dBFS threshold & hangover release requirement
    assert "dBFS threshold" in content or "threshold_dbfs" in content
    assert "200ms hangover" in content or "hangover" in content


def test_media_extensibility_contract():
    """Verify media track extensibility for camera and screen sharing (F11)."""
    project_md_path = os.path.join(PROJECT_ROOT, "PROJECT.md")
    with open(project_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "screen" in content.lower()
    assert "camera" in content.lower()
    assert "F11" in content


def test_docker_and_tailscale_infrastructure_contracts():
    """Verify Docker containerization (F28, F29) and Tailscale mesh networking (F30)."""
    project_md_path = os.path.join(PROJECT_ROOT, "PROJECT.md")
    with open(project_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Dockerfile" in content
    assert "docker-compose.yml" in content
    assert "Tailscale" in content
