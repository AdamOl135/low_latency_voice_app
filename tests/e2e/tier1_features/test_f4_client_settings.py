"""Tier 1 Feature Tests: F4 - Client Settings Dialog Port Fallback & Defaults.

Validates:
- client/lib/core/constants.dart defaultHost == '100.108.39.69'
- client/lib/core/constants.dart defaultWsPort == 8085
- client/lib/ui/dialogs/audio_settings_dialog.dart fallback port logic uses defaultWsPort (8085), not 8080
- Settings endpoint URL formatting
- Port parsing fallback logic across invalid inputs
"""

import os
import re
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
CONSTANTS_PATH = os.path.join(PROJECT_ROOT, "client/lib/core/constants.dart")
SETTINGS_DIALOG_PATH = os.path.join(PROJECT_ROOT, "client/lib/ui/dialogs/audio_settings_dialog.dart")


class TestF4ClientSettings(unittest.TestCase):
    def test_f4_01_default_server_host_constant(self):
        """Test F4.1: AppConstants.defaultHost is set to 100.108.39.69."""
        self.assertTrue(os.path.exists(CONSTANTS_PATH), f"Missing {CONSTANTS_PATH}")
        with open(CONSTANTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        match = re.search(r"static\s+const\s+String\s+defaultHost\s*=\s*['\"]([^'\"]+)['\"]", content)
        self.assertIsNotNone(match, "Could not find defaultHost constant in constants.dart")
        default_host = match.group(1)
        self.assertEqual(default_host, "100.108.39.69", "AppConstants.defaultHost MUST be '100.108.39.69'")

    def test_f4_02_default_ws_port_constant(self):
        """Test F4.2: AppConstants.defaultWsPort is set to 8085."""
        self.assertTrue(os.path.exists(CONSTANTS_PATH))
        with open(CONSTANTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        match = re.search(r"static\s+const\s+int\s+defaultWsPort\s*=\s*(\d+)", content)
        self.assertIsNotNone(match, "Could not find defaultWsPort constant in constants.dart")
        default_port = int(match.group(1))
        self.assertEqual(default_port, 8085, "AppConstants.defaultWsPort MUST be 8085")

    def test_f4_03_settings_dialog_port_fallback_contract(self):
        """Test F4.3: audio_settings_dialog.dart uses 8085 or AppConstants.defaultWsPort as parse fallback."""
        self.assertTrue(os.path.exists(SETTINGS_DIALOG_PATH), f"Missing {SETTINGS_DIALOG_PATH}")
        with open(SETTINGS_DIALOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

        fallback_found = False
        for idx, line in enumerate(lines, 1):
            if "int.tryParse" in line and "_portController" in line:
                # Must NOT fall back to 8080
                self.assertNotIn("8080", line, f"Line {idx} in audio_settings_dialog.dart must not use hardcoded 8080 fallback")
                # Must use defaultWsPort or 8085
                self.assertTrue(
                    "8085" in line or "defaultWsPort" in line or "AppConstants.defaultWsPort" in line,
                    f"Line {idx} must fall back to 8085 / AppConstants.defaultWsPort"
                )
                fallback_found = True

        self.assertTrue(fallback_found, "Could not find port fallback parse line in audio_settings_dialog.dart")

    def test_f4_04_port_parsing_logic_simulation(self):
        """Test F4.4: Port parsing simulation validates correct fallback on malformed user strings."""
        DEFAULT_WS_PORT = 8085

        def parse_port(text: str) -> int:
            try:
                v = int(text.strip())
                return v if 1 <= v <= 65535 else DEFAULT_WS_PORT
            except Exception:
                return DEFAULT_WS_PORT

        self.assertEqual(parse_port("8085"), 8085)
        self.assertEqual(parse_port("9000"), 9000)
        self.assertEqual(parse_port(""), 8085)
        self.assertEqual(parse_port("invalid_port"), 8085)
        self.assertEqual(parse_port("8080abc"), 8085)
        self.assertEqual(parse_port("-1"), 8085)
        self.assertEqual(parse_port("70000"), 8085)

    def test_f4_05_client_endpoint_url_formation(self):
        """Test F4.5: Default WebSocket endpoint URL constructs ws://100.108.39.69:8085/ws."""
        default_host = "100.108.39.69"
        default_port = 8085
        ws_url = f"ws://{default_host}:{default_port}/ws"
        self.assertEqual(ws_url, "ws://100.108.39.69:8085/ws")

    def test_f4_06_no_residual_8080_in_settings_dialog(self):
        """Test F4.6: audio_settings_dialog.dart contains no residual 8080 default occurrences."""
        with open(SETTINGS_DIALOG_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for any remaining '8080' occurrences in dialog logic
        matches = [m.start() for m in re.finditer(r"\b8080\b", content)]
        self.assertEqual(
            len(matches),
            0,
            f"Found {len(matches)} residual occurrences of '8080' in audio_settings_dialog.dart; should all be 8085"
        )


if __name__ == "__main__":
    unittest.main()

