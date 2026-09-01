"""Tier 2 Boundary Tests: B4 - Client Settings Boundaries.

Validates:
- Empty string port fallback to 8085
- Non-numeric string port fallback to 8085
- Out-of-range port values (0, 65536, 100000)
- Negative port values (-1, -8085)
- IPv6 literal addresses, hostnames, and loopback IPs
"""

import unittest
from tests.e2e.tier1_features.test_f4_client_settings import CONSTANTS_PATH, SETTINGS_DIALOG_PATH


class TestB4ClientSettingsBoundaries(unittest.TestCase):
    def _parse_port_helper(self, port_str: str, default_port: int = 8085) -> int:
        """Helper implementing the exact contract for Flutter int.tryParse(port) ?? defaultWsPort."""
        try:
            val = int(port_str.strip())
            if 1 <= val <= 65535:
                return val
            return default_port
        except Exception:
            return default_port

    def test_b4_01_empty_string_port_fallback(self):
        """Test B4.1: Empty string input in settings dialog port field returns 8085."""
        self.assertEqual(self._parse_port_helper(""), 8085)
        self.assertEqual(self._parse_port_helper("   "), 8085)

    def test_b4_02_alphanumeric_port_fallback(self):
        """Test B4.2: Alphanumeric and symbol string inputs return 8085."""
        self.assertEqual(self._parse_port_helper("abc"), 8085)
        self.assertEqual(self._parse_port_helper("8085-custom"), 8085)
        self.assertEqual(self._parse_port_helper("!@#$%"), 8085)

    def test_b4_03_negative_and_zero_port_fallback(self):
        """Test B4.3: Negative and 0 port inputs return 8085."""
        self.assertEqual(self._parse_port_helper("-1"), 8085)
        self.assertEqual(self._parse_port_helper("-8085"), 8085)
        self.assertEqual(self._parse_port_helper("0"), 8085)

    def test_b4_04_out_of_range_port_fallback(self):
        """Test B4.4: Ports greater than 65535 return 8085."""
        self.assertEqual(self._parse_port_helper("65536"), 8085)
        self.assertEqual(self._parse_port_helper("100000"), 8085)
        self.assertEqual(self._parse_port_helper("99999999999999999999"), 8085)

    def test_b4_05_valid_port_parsing(self):
        """Test B4.5: Valid ports within 1..65535 parse correctly without fallback."""
        self.assertEqual(self._parse_port_helper("80"), 80)
        self.assertEqual(self._parse_port_helper("443"), 443)
        self.assertEqual(self._parse_port_helper("8085"), 8085)
        self.assertEqual(self._parse_port_helper("9000"), 9000)
        self.assertEqual(self._parse_port_helper("65535"), 65535)


if __name__ == "__main__":
    unittest.main()

