#!/usr/bin/env python3
"""Unified Requirement-Driven E2E Test Suite Runner for Low-Latency Voice App.

Supports running:
  - Tier 1: Feature Coverage (F1..F5 >= 5 tests each)
  - Tier 2: Boundary & Corner Cases (B1..B5 >= 5 tests each)
  - Tier 3: Cross-Feature Interactions (Pairwise combinations)
  - Tier 4: Real-World Application Scenarios (Multi-user, silent survival, reconnect)
  - All Tiers

Usage:
  python3 tests/e2e/runner.py --tier all
  python3 tests/e2e/runner.py --tier 1 -v
  python3 tests/e2e/runner.py --json-report test_results.json
"""

import argparse
import io
import json
import os
import sys
import time
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TIER_MODULES = {
    "1": [
        "tests.e2e.tier1_features.test_f1_audio_engine",
        "tests.e2e.tier1_features.test_f2_session_scavenger",
        "tests.e2e.tier1_features.test_f3_dynamic_udp_port",
        "tests.e2e.tier1_features.test_f4_client_settings",
        "tests.e2e.tier1_features.test_f5_inbound_raw_packet",
    ],
    "2": [
        "tests.e2e.tier2_boundaries.test_b1_audio_engine_boundaries",
        "tests.e2e.tier2_boundaries.test_b2_scavenger_boundaries",
        "tests.e2e.tier2_boundaries.test_b3_udp_port_boundaries",
        "tests.e2e.tier2_boundaries.test_b4_client_settings_boundaries",
        "tests.e2e.tier2_boundaries.test_b5_inbound_packet_boundaries",
    ],
    "3": [
        "tests.e2e.tier3_interactions.test_cross_feature_combinations",
    ],
    "4": [
        "tests.e2e.tier4_scenarios.test_real_world_scenarios",
    ],
}

TIER_NAMES = {
    "1": "Tier 1: Feature Coverage (F1..F5)",
    "2": "Tier 2: Boundary & Corner Cases (B1..B5)",
    "3": "Tier 3: Cross-Feature Interactions",
    "4": "Tier 4: Real-World Application Scenarios",
}


def run_tier(tier_key: str, verbose: bool = False):
    """Execute test modules for a specific tier."""
    modules = TIER_MODULES.get(tier_key, [])
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for mod_name in modules:
        try:
            mod = __import__(mod_name, fromlist=["*"])
            suite.addTests(loader.loadTestsFromModule(mod))
        except Exception as e:
            print(f"Error loading module {mod_name}: {e}", file=sys.stderr)

    stream = io.StringIO()
    runner = unittest.TextTestRunner(
        stream=stream,
        verbosity=2 if verbose else 1,
        resultclass=unittest.TextTestResult,
    )

    start_time = time.time()
    result = runner.run(suite)
    duration = time.time() - start_time

    output = stream.getvalue()
    return result, duration, output


def main():
    parser = argparse.ArgumentParser(description="Low-Latency Voice App 4-Tier E2E Test Suite Runner")
    parser.add_argument(
        "--tier",
        choices=["1", "2", "3", "4", "all"],
        default="all",
        help="Test tier to execute (1, 2, 3, 4, or all)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output with individual test method names",
    )
    parser.add_argument(
        "--json-report",
        type=str,
        default=None,
        help="Path to write JSON test report summary",
    )

    args = parser.parse_args()

    tiers_to_run = ["1", "2", "3", "4"] if args.tier == "all" else [args.tier]

    print("=" * 80)
    print("  LOW-LATENCY VOICE APP: 4-TIER E2E TEST SUITE RUNNER")
    print(f"  Tier Target: {args.tier.upper()} | Python: {sys.version.split()[0]}")
    print("=" * 80)

    total_start = time.time()
    tier_results = {}
    overall_success = True
    total_tests_run = 0
    total_failures = 0
    total_errors = 0

    for t in tiers_to_run:
        name = TIER_NAMES.get(t, f"Tier {t}")
        print(f"\n>> Running {name}...")
        result, duration, output = run_tier(t, verbose=args.verbose)

        passed = result.wasSuccessful()
        if not passed:
            overall_success = False

        total_tests_run += result.testsRun
        total_failures += len(result.failures)
        total_errors += len(result.errors)

        if args.verbose or not passed:
            print(output.strip())

        status_str = "PASSED" if passed else "FAILED"
        print(f"  [{status_str}] {name}: {result.testsRun} tests run ({len(result.failures)} failed, {len(result.errors)} errors) in {duration:.2f}s")

        tier_results[f"tier_{t}"] = {
            "name": name,
            "passed": passed,
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "duration_sec": round(duration, 3),
        }

    total_duration = time.time() - total_start

    print("\n" + "=" * 80)
    print("  E2E TEST SUITE SUMMARY")
    print("=" * 80)
    for t_key, res in tier_results.items():
        icon = "[PASS]" if res["passed"] else "[FAIL]"
        print(f"  {icon:<8} {res['name']:<48} {res['tests_run']:>3} tests [{res['duration_sec']:.2f}s]")
    print("-" * 80)
    overall_label = "ALL TIERS PASSED (100%)" if overall_success else "TEST SUITE FAILED"
    print(f"  Status: {overall_label} | Total: {total_tests_run} tests | Time: {total_duration:.2f}s")
    print("=" * 80)

    if args.json_report:
        report_data = {
            "timestamp": time.time(),
            "overall_passed": overall_success,
            "total_tests": total_tests_run,
            "total_failures": total_failures,
            "total_errors": total_errors,
            "total_duration_sec": round(total_duration, 3),
            "tiers": tier_results,
        }
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        print(f"  Saved JSON report to {args.json_report}")

    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()

