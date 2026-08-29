#!/usr/bin/env python3
"""Unified E2E Test Suite Runner for Low-Latency Voice App.

Supports running:
  - Tier 1: Feature Coverage (Auth, Roles, Channels, Chat, UDP Voice, Fast VAD)
  - Tier 2: Boundaries (0-byte, Jumbo frames, Jitter bursts, 4000-char chat, Channel hops)
  - Tier 3: Interactions (Admin move during stream, Server mute/deafen gating, Kick revocation)
  - Tier 4: Concurrency & SLA (<30ms latency probe, 15 concurrent voice streams)
  - All Tiers

Usage:
  python test/runner.py --tier 1
  python test/runner.py --tier 4
  python test/runner.py --tier all
  python test/runner.py --verbose --json-report test_results.json
"""

import os
import sys
import argparse
import time
import json
import subprocess
from typing import List, Dict, Any, Tuple


TIER_DIRECTORIES = {
    "1": "test/tier1_features",
    "2": "test/tier2_boundaries",
    "3": "test/tier3_interactions",
    "4": "test/tier4_latency_concurrency",
}

TIER_NAMES = {
    "1": "Tier 1: Feature Coverage Tests",
    "2": "Tier 2: Boundary & Corner Tests",
    "3": "Tier 3: Cross-Feature Interaction Tests",
    "4": "Tier 4: Latency SLA & 15-Client Concurrency Tests",
}


def run_tier(tier_key: str, extra_args: List[str] = None) -> Tuple[int, float, str]:
    """Execute pytest for a specific tier directory."""
    tier_dir = TIER_DIRECTORIES.get(tier_key)
    if not tier_dir:
        print(f"Unknown tier: {tier_key}", file=sys.stderr)
        return 1, 0.0, ""

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        tier_dir,
        "-q",
        "--tb=short",
    ]
    if extra_args:
        cmd.extend(extra_args)

    start_time = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - start_time

    output = (res.stdout or "") + "\n" + (res.stderr or "")
    return res.returncode, duration, output.strip()


def main():
    parser = argparse.ArgumentParser(description="Low-Latency Voice App E2E Test Suite Runner")
    parser.add_argument(
        "--tier",
        choices=["1", "2", "3", "4", "all"],
        default="all",
        help="Test tier to execute (1, 2, 3, 4, or all)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output with test names",
    )
    parser.add_argument(
        "--json-report",
        type=str,
        default=None,
        help="Path to write JSON test report summary",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Target server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--ws-url",
        type=str,
        default=None,
        help="Target WebSocket URL (e.g. ws://127.0.0.1:8080/ws)",
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        default=None,
        help="Target UDP Port (e.g. 7878)",
    )

    args, unknown = parser.parse_known_args()

    # Pass environment variables if configured
    if args.ws_url:
        os.environ["VOICE_WS_URL"] = args.ws_url
    if args.udp_port:
        os.environ["VOICE_UDP_PORT"] = str(args.udp_port)
    os.environ["VOICE_UDP_HOST"] = args.host

    extra_pytest_args = []
    if args.verbose:
        extra_pytest_args.append("-v")
    if unknown:
        extra_pytest_args.extend(unknown)

    tiers_to_run = ["1", "2", "3", "4"] if args.tier == "all" else [args.tier]

    print("=" * 80)
    print("  LOW-LATENCY VOICE & TEXT APP - 4-TIER E2E TEST SUITE RUNNER")
    print(f"  Target: {args.host} | Tier: {args.tier.upper()} | Python: {sys.version.split()[0]}")
    print("=" * 80)

    total_start = time.time()
    tier_results = {}
    overall_success = True

    for t in tiers_to_run:
        name = TIER_NAMES.get(t, f"Tier {t}")
        print(f"\n>> Running {name} ({TIER_DIRECTORIES[t]})...")
        ret_code, duration, output = run_tier(t, extra_pytest_args)
        
        status = "PASSED" if ret_code == 0 else "FAILED"
        if ret_code != 0:
            overall_success = False

        print(output)
        print(f"[{status}] {name} completed in {duration:.2f}s (Exit code: {ret_code})")

        tier_results[f"tier_{t}"] = {
            "name": name,
            "directory": TIER_DIRECTORIES[t],
            "passed": (ret_code == 0),
            "exit_code": ret_code,
            "duration_sec": round(duration, 3),
            "output_snippet": output[-500:] if len(output) > 500 else output,
        }

    total_duration = time.time() - total_start
    print("\n" + "=" * 80)
    print("  E2E TEST SUITE SUMMARY")
    print("=" * 80)
    for t_key, res in tier_results.items():
        status_icon = "[PASS]" if res["passed"] else "[FAIL]"
        print(f"  {status_icon:<8}  {res['name']:<55} [{res['duration_sec']:.2f}s]")
    print("-" * 80)
    overall_status_str = "ALL TIERS PASSED (100%)" if overall_success else "TEST SUITE FAILED"
    print(f"  Status: {overall_status_str} | Total Time: {total_duration:.2f}s")
    print("=" * 80)

    if args.json_report:
        report_data = {
            "timestamp": time.time(),
            "overall_passed": overall_success,
            "total_duration_sec": round(total_duration, 3),
            "tiers": tier_results,
        }
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        print(f"  Saved JSON report to {args.json_report}")

    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
