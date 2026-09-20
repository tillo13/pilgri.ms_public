#!/usr/bin/env python3
"""
Pilgrims Smoke Test CLI Runner

Usage:
    # Local tests (pre-deploy)
    python -m tools.smoke_test local --quick      # Quick: ~20 tests
    python -m tools.smoke_test local              # Default: ~50 tests
    python -m tools.smoke_test local --full       # Full: ~100+ tests
    python -m tools.smoke_test local --depot      # Feature-specific

    # Deployed tests (post-deploy against live site)
    python -m tools.smoke_test deployed           # Test https://pilgri.ms
    python -m tools.smoke_test deployed --verbose # With details
"""

import sys
import argparse
from datetime import datetime

from . import TESTS, PASSED, FAILED, SKIPPED, reset_results, print_summary, FEATURE_TAGS, TEST_TIMEOUT

# Import test modules to register tests
from . import local
from . import deployed


def filter_tests(mode, tier_max, features=None):
    """Filter tests by mode, tier, and optional features."""
    filtered = []
    for test_func in TESTS:
        # Filter by mode
        if test_func._mode != mode:
            continue

        # Filter by tier
        if test_func._tier > tier_max:
            continue

        # Filter by features if specified
        if features:
            test_features = set(test_func._features)
            if not test_features.intersection(features):
                continue

        filtered.append(test_func)

    return filtered


def run_tests(tests, verbose=False):
    """Run a list of tests and return success status. Global 3-min safety cap."""
    start_time = datetime.now()
    for i, test_func in enumerate(tests):
        test_func()
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > 180:
            remaining = tests[i + 1:]
            for r in remaining:
                SKIPPED.append(f"{r._test_name} (global timeout)")
            print(f"\n  ⚠️  GLOBAL TIMEOUT: {elapsed:.0f}s elapsed, skipped {len(remaining)} remaining tests")
            break
    return len(FAILED) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Pilgrims Smoke Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.smoke_test local --quick     # Quick pre-deploy tests
  python -m tools.smoke_test local --full      # Comprehensive local tests
  python -m tools.smoke_test local --depot     # Only depot-related tests
  python -m tools.smoke_test deployed          # Test live production site
  python -m tools.smoke_test deployed --verbose
        """
    )

    # Mode: local or deployed
    parser.add_argument('mode', choices=['local', 'deployed'],
                        help="Test mode: 'local' for pre-deploy, 'deployed' for post-deploy")

    # Tier flags
    tier_group = parser.add_mutually_exclusive_group()
    tier_group.add_argument('--quick', action='store_true',
                            help="Tier 1 only: ~20 critical tests (~5 sec)")
    tier_group.add_argument('--full', action='store_true',
                            help="All tiers: ~100+ comprehensive tests")

    # Feature flags
    for feature in FEATURE_TAGS.keys():
        parser.add_argument(f'--{feature}', action='store_true',
                            help=f"Only run {feature}-related tests")

    # Modifiers
    parser.add_argument('--verbose', '-v', action='store_true',
                        help="Show detailed error messages")
    parser.add_argument('--list', action='store_true',
                        help="List matching tests without running them")

    args = parser.parse_args()

    # Determine tier max
    if args.quick:
        tier_max = 1
    elif args.full:
        tier_max = 3
    else:
        tier_max = 2  # Default

    # Collect feature filters
    features = set()
    for feature in FEATURE_TAGS.keys():
        if getattr(args, feature, False):
            features.add(feature)

    # Filter tests
    tests = filter_tests(args.mode, tier_max, features if features else None)

    if not tests:
        print(f"No tests found for mode='{args.mode}', tier<={tier_max}")
        if features:
            print(f"Features filter: {features}")
        return 1

    # List mode
    if args.list:
        print(f"\n📋 Tests matching criteria ({len(tests)} tests):")
        print("=" * 60)
        for t in tests:
            tier_icon = {1: "🔴", 2: "🟡", 3: "🟢"}.get(t._tier, "⚪")
            features_str = ", ".join(t._features) if t._features else "general"
            print(f"  {tier_icon} [{t._tier}] {t._test_name} ({features_str})")
        return 0

    # Reset results
    reset_results()

    # Header
    mode_label = "LOCAL (pre-deploy)" if args.mode == 'local' else "DEPLOYED (post-deploy)"
    tier_label = {1: "QUICK", 2: "DEFAULT", 3: "FULL"}[tier_max]

    print()
    print("=" * 60)
    print(f"🚀 PILGRIMS SMOKE TEST: {mode_label}")
    print(f"   Tier: {tier_label} | Tests: {len(tests)} | Timeout: {TEST_TIMEOUT}s/test")
    if features:
        print(f"   Features: {', '.join(features)}")
    print("=" * 60)
    print()

    # Group tests by tier for display
    start_time = datetime.now()
    global_timed_out = False
    for tier in range(1, tier_max + 1):
        if global_timed_out:
            break
        tier_tests = [t for t in tests if t._tier == tier]
        if tier_tests:
            tier_names = {1: "TIER 1: CRITICAL", 2: "TIER 2: DEFAULT", 3: "TIER 3: FULL"}
            print(f"\n{tier_names[tier]}")
            print("-" * 40)
            for test_func in tier_tests:
                test_func()
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed > 180:
                    print(f"\n  ⚠️  GLOBAL TIMEOUT: {elapsed:.0f}s elapsed, skipping remaining tests")
                    global_timed_out = True
                    break

    # Summary
    exit_code = print_summary(verbose=args.verbose)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
