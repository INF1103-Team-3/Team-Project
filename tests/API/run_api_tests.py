"""Master test runner for BiteFinder API testing suite.

Executes both AI keys/fallback chain tests and Google Maps Platform API tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
CURRENT_DIR = Path(__file__).resolve().parent

# Ensure project and test roots are in path
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_ROOT))

load_dotenv(ROOT / ".env")

from reporting import show_group_start, style


TEST_SCRIPTS = (
    ("AI Keys & Fallback Chain", CURRENT_DIR / "test_ai_keys_and_fallback.py"),
    ("Google Maps Platform API", CURRENT_DIR / "test_google_api.py"),
)


def run_test_script(name: str, script_path: Path) -> int:
    """Run one API test script as a subprocess preserving all environment keys."""
    relative = script_path.relative_to(ROOT)
    print("\n" + style("=" * 72, "rule"))
    print(style(f"Running API Test Suite: {name} ({relative})", "running"))
    print(style("=" * 72, "rule"), flush=True)

    # Pass the complete environment (including live API credentials)
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=ROOT,
        env=env,
    )

    status = "PASS" if result.returncode == 0 else "FAIL"
    role = "pass" if result.returncode == 0 else "fail"
    print("\n" + style(f"Suite Result: {name} — {status}", role))
    return result.returncode


def main() -> int:
    """Execute all API test suites and return overall status code."""
    show_group_start(
        "LIVE API & FALLBACK CHAIN TESTS",
        "Validates OpenRouter, Gemini, Groq, and Google Maps API keys, as well as\n"
        "AI multi-tier fallback cascade and Google offline fallback resilience.",
    )

    failed_suites = []
    for name, script_path in TEST_SCRIPTS:
        if not script_path.exists():
            print(style(f"\nError: Test script not found: {script_path}", "fail"))
            failed_suites.append(name)
            continue

        return_code = run_test_script(name, script_path)
        if return_code != 0:
            failed_suites.append(name)

    total = len(TEST_SCRIPTS)
    failed = len(failed_suites)
    passed = total - failed

    print("\n" + style("=" * 72, "rule"))
    print(style("OVERALL API TESTING SUMMARY", "heading"))
    print(style("=" * 72, "rule"))
    print(f"Suites executed: {total}")
    print(style(f"Passed suites:   {passed}", "pass"))
    print(style(f"Failed suites:   {failed}", "fail" if failed else "muted"))

    if failed_suites:
        print(style("\nFailed test suites:", "fail"))
        for suite in failed_suites:
            print(style(f"- {suite}", "fail"))
        return 1

    print("\n" + style("ALL API TESTS PASSED SUCCESSFULLY! [OK]", "pass"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
