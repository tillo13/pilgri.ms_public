#!/usr/bin/env python3
"""
Pilgrims Smoke Test Package
===========================

Tiered, feature-aware testing system with local and deployed test modes.

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
import os
import signal

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# =============================================================================
# SHARED TEST REGISTRY & TRACKING
# =============================================================================

TESTS = []  # All registered tests
PASSED = []
FAILED = []
SKIPPED = []

# Feature tags for filtering
FEATURE_TAGS = {
    'crew': ['captain', 'scientist', 'aria', 'commander', 'replicate'],
    'depot': ['upgrade', 'shop', 'purchase', 'pricing', 'build_time'],
    'expeditions': ['expedition', 'discovery', 'travel', 'landmark'],
    'colony': ['infrastructure', 'building', 'solar', 'income'],
    'signal': ['signal', 'bond', 'fragment', 'origin_site'],
    'tech': ['tech', 'research', 'branch'],
    'api': ['api', 'endpoint', 'route'],
    'db': ['database', 'table', 'schema', 'postgres'],
    'config': ['config', 'catalog', 'pricing'],
    'blockchain': ['sepolia', 'wallet', 'tx', 'blockchain'],
}


# =============================================================================
# SHARED DECORATORS
# =============================================================================

# Per-test timeout (seconds) — prevents hanging on slow DB connections
TEST_TIMEOUT = 15


class TestTimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise TestTimeoutError("timed out")


def test(name, tier=2, features=None, mode='local'):
    """Register a test with name, tier level, feature tags, and mode (local/deployed)."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                # Set per-test timeout via SIGALRM
                old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(TEST_TIMEOUT)
                try:
                    result = func(*args, **kwargs)
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                if result is None or result is True:
                    PASSED.append(name)
                    print(f"  \u2705 {name}")
                    return True
                else:
                    FAILED.append((name, str(result)))
                    print(f"  \u274c {name}: {result}")
                    return False
            except TestTimeoutError:
                FAILED.append((name, f"TIMEOUT ({TEST_TIMEOUT}s)"))
                print(f"  \u23f1\ufe0f  {name}: TIMEOUT ({TEST_TIMEOUT}s)")
                return False
            except Exception as e:
                FAILED.append((name, str(e)))
                print(f"  \u274c {name}: {e}")
                return False
        wrapper._test_name = name
        wrapper._tier = tier
        wrapper._features = features or []
        wrapper._mode = mode
        TESTS.append(wrapper)
        return wrapper
    return decorator


def requires_web3(func):
    """Skip if web3 not available (venv not activated)."""
    def wrapper(*args, **kwargs):
        try:
            import web3
            return func(*args, **kwargs)
        except ImportError:
            name = getattr(func, '_test_name', func.__name__)
            SKIPPED.append(f"{name} (web3 not available)")
            print(f"  \u23ed\ufe0f  {name} (skipped - no venv)")
            return True
    wrapper._test_name = getattr(func, '_test_name', func.__name__)
    wrapper._tier = getattr(func, '_tier', 2)
    wrapper._features = getattr(func, '_features', [])
    wrapper._mode = getattr(func, '_mode', 'local')
    return wrapper


def requires_flask(func):
    """Skip if Flask context not available."""
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            return result
        except RuntimeError as e:
            if 'context' in str(e).lower():
                name = getattr(func, '_test_name', func.__name__)
                SKIPPED.append(f"{name} (needs Flask)")
                print(f"  \u23ed\ufe0f  {name} (skipped - needs Flask)")
                return True
            raise
    wrapper._test_name = getattr(func, '_test_name', func.__name__)
    wrapper._tier = getattr(func, '_tier', 2)
    wrapper._features = getattr(func, '_features', [])
    wrapper._mode = getattr(func, '_mode', 'local')
    return wrapper


# =============================================================================
# SHARED UTILITIES
# =============================================================================

def reset_results():
    """Reset test results for a fresh run."""
    global PASSED, FAILED, SKIPPED
    PASSED = []
    FAILED = []
    SKIPPED = []


def get_results():
    """Get current test results."""
    return {
        'passed': PASSED.copy(),
        'failed': FAILED.copy(),
        'skipped': SKIPPED.copy(),
    }


def print_summary(verbose=False):
    """Print test results summary."""
    print("\n" + "=" * 60)
    print("\U0001f4ca RESULTS")
    print("=" * 60)
    print(f"  \u2705 Passed:  {len(PASSED)}")
    print(f"  \u274c Failed:  {len(FAILED)}")
    print(f"  \u23ed\ufe0f  Skipped: {len(SKIPPED)}")

    if FAILED:
        print("\n\u274c FAILURES:")
        for name, error in FAILED:
            print(f"   \u2022 {name}")
            if verbose:
                print(f"     {error}")

    if SKIPPED and verbose:
        print("\n\u23ed\ufe0f  SKIPPED:")
        for name in SKIPPED:
            print(f"   \u2022 {name}")

    print("\n" + "=" * 60)

    if FAILED:
        print("\U0001f534 SOME TESTS FAILED")
        return 1
    else:
        print("\U0001f7e2 ALL TESTS PASSED")
        return 0
