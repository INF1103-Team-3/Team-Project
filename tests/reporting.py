"""Colored teacher-facing reporting helpers for BiteFinder tests."""

import os
from pprint import pformat
import sys


COLORS = {
    "heading": "\033[1;36m",
    "rule": "\033[36m",
    "running": "\033[1;34m",
    "label": "\033[1;35m",
    "expected": "\033[33m",
    "actual": "\033[34m",
    "pass": "\033[1;32m",
    "fail": "\033[1;31m",
    "error": "\033[1;31m",
    "warning": "\033[1;33m",
    "command": "\033[32m",
    "muted": "\033[2m",
}
RESET = "\033[0m"


def colors_enabled():
    """Respect explicit test color settings, NO_COLOR, and terminal support."""
    setting = os.getenv("BITEFINDER_TEST_COLOR", "auto").strip().lower()
    if setting in {"always", "on", "true", "1"}:
        return True
    if setting in {"never", "off", "false", "0"} or "NO_COLOR" in os.environ:
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def style(value, role):
    """Return colored text for a semantic reporting role when enabled."""
    text = str(value)
    return f"{COLORS[role]}{text}{RESET}" if colors_enabled() else text


def show_case(case_id, function, purpose, test_input, expected, actual):
    """Print the input, expected output, actual output and result."""
    passed = actual == expected
    print("\n" + style("=" * 72, "rule"))
    print(style(case_id, "heading"))
    print(style("=" * 72, "rule"))
    print(f"{style('Function:', 'label')} {function}")
    print(f"{style('Purpose:', 'label')} {purpose}")
    print(style("\nInput:", "label"))
    print(pformat(test_input, sort_dicts=False))
    print(style("\nExpected output:", "expected"))
    print(pformat(expected, sort_dicts=False))
    print(style("\nActual output:", "actual"))
    print(pformat(actual, sort_dicts=False))
    print("\n" + style(
        f"Result: {'PASS' if passed else 'FAIL'}",
        "pass" if passed else "fail",
    ))
    return passed


def show_summary(group_name, total_tests, failures):
    """Print the final colored summary for one BiteFinder test group."""
    failed_count = len(failures)
    passed_count = total_tests - failed_count
    print("\n" + style("=" * 72, "rule"))
    print(style(f"{group_name.upper()} TEST SUMMARY", "heading"))
    print(style("=" * 72, "rule"))
    print(f"Tests run: {total_tests}")
    print(style(f"Passed: {passed_count}", "pass"))
    print(style(f"Failed: {failed_count}", "fail" if failures else "muted"))
    if failures:
        print(style("\nFailed tests:", "fail"))
        for test_name, error in failures:
            print(style(
                f"- {test_name}: {type(error).__name__}: {error}",
                "fail",
            ))


def show_group_start(group_name, description):
    """Print a colored heading before a group of tests starts."""
    print("\n" + style("#" * 72, "rule"))
    print(style(f"BITEFINDER - {group_name.upper()}", "heading"))
    print(style("#" * 72, "rule"))
    print(description)
