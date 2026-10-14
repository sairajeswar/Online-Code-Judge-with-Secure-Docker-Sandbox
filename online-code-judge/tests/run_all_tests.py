"""Comprehensive test runner: executes verdict tests, fork-bomb & infinite-loop
adversarial tests, and the 200 concurrent submission load test."""

import asyncio
import sys
import os
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from tests.test_verdicts import TestVerdicts
from tests.test_forkbomb_infinite_loop import TestAdversarialResilience
from tests.test_load_200 import run_200_concurrent_load_test


def run_unit_and_adversarial_tests():
    print("=======================================================")
    print("[1] RUNNING UNIT & ADVERSARIAL RESILIENCE SUITE")
    print("=======================================================")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestVerdicts))
    suite.addTests(loader.loadTestsFromTestCase(TestAdversarialResilience))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


def main():
    success = run_unit_and_adversarial_tests()
    if not success:
        print("[!] Unit/adversarial tests failed! Aborting load test.")
        sys.exit(1)

    print("\n=======================================================")
    print("[2] RUNNING 200 CONCURRENT SUBMISSION LOAD TEST")
    print("=======================================================")
    load_metrics = asyncio.run(run_200_concurrent_load_test(num_workers=20))

    if load_metrics["mismatches"] == 0:
        print("[SUCCESS] ALL TESTS PASSED! Proof verified successfully.")
    else:
        print("[!] Load test completed with mismatches.")
        sys.exit(1)


if __name__ == "__main__":
    main()
