"""Main test runner for BiteFinder automated tests."""

import os
import subprocess
import sys
from pathlib import Path

from reporting import show_group_start


TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent


TEST_GROUPS = {
    "bis": [
        TESTS_DIR / "bis" / "test_bis.py",
    ],

    "brns": [
        TESTS_DIR / "brns" / "test_brns.py",
    ],

    "core": [
        TESTS_DIR / "bis" / "test_bis.py",
        TESTS_DIR / "brns" / "test_brns.py",
    ],

    "deployment": [
        TESTS_DIR / "deployment" / "smoke.py",
    ],

    "all": [
        TESTS_DIR / "bis" / "test_bis.py",
        TESTS_DIR / "brns" / "test_brns.py",
        TESTS_DIR / "deployment" / "smoke.py",
    ],
}


GROUP_DESCRIPTIONS = {
    "bis":
        "Tests BIS input validation, preference handling, "
        "search preparation and hardcoded AI interpretation.",

    "brns":
        "Tests BRNS restaurant filtering, recommendation rules, "
        "dietary checks, ranking and hardcoded AI recommendations.",

    "core":
        "Runs the BIS and BRNS core function tests without "
        "calling a live AI API.",

    "deployment":
        "Checks that BiteFinder and its automated tests work "
        "inside the submitted Docker environment.",

    "all":
        "Runs all BiteFinder core and deployment tests.",
}


def safe_test_environment():
    """Return an environment without live API credentials."""

    environment = os.environ.copy()

    # Make the project root and tests folder importable
    existing_pythonpath = environment.get(
        "PYTHONPATH",
        "",
    )

    paths = [
        str(ROOT),
        str(TESTS_DIR),
    ]

    if existing_pythonpath:
        paths.append(
            existing_pythonpath
        )

    environment["PYTHONPATH"] = os.pathsep.join(
        paths
    )

    live_api_keys = (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_API_KEYS",
        "OPENROUTER_API_KEYS_FILE",
        "GOOGLE_MAPS_API_KEY",
    )

    for key in live_api_keys:
        environment.pop(
            key,
            None,
        )

    return environment


def running_inside_docker():
    """Return True when the test runner is executing inside Docker."""

    return Path(
        "/.dockerenv"
    ).exists()


def run_test_file(test_file):
    """Run one BiteFinder test script and return its exit code."""

    if not test_file.exists():

        print(
            f"\nERROR: Test file not found: "
            f"{test_file.relative_to(ROOT)}"
        )

        return 1

    print("\n" + "-" * 72)

    print(
        f"Running: "
        f"{test_file.relative_to(ROOT)}"
    )

    print("-" * 72)

    result = subprocess.run(
        [
            sys.executable,
            str(test_file),
        ],
        cwd=ROOT,
        env=safe_test_environment(),
    )

    return result.returncode


def run_group(group_name):
    """Run every test script belonging to the selected group."""

    scripts = TEST_GROUPS[
        group_name
    ]

    show_group_start(
        group_name,
        GROUP_DESCRIPTIONS[
            group_name
        ],
    )

    if group_name in (
        "deployment",
        "all",
    ):

        if not running_inside_docker():

            print()
            print(
                "Deployment tests must be run "
                "inside the BiteFinder Docker container."
            )

            print()
            print(
                "Start Docker with:"
            )

            print(
                "docker compose up -d --build"
            )

            print()
            print(
                "Then run:"
            )

            print(
                "docker compose exec bis-brns "
                "python tests/run_tests.py deployment"
            )

            return 1

    failed_scripts = []

    for script in scripts:

        exit_code = run_test_file(
            script
        )

        if exit_code != 0:

            failed_scripts.append(
                script
            )

    print("\n" + "=" * 72)

    print(
        f"{group_name.upper()} GROUP SUMMARY"
    )

    print("=" * 72)

    print(
        f"Test scripts run: "
        f"{len(scripts)}"
    )

    print(
        f"Passed scripts: "
        f"{len(scripts) - len(failed_scripts)}"
    )

    print(
        f"Failed scripts: "
        f"{len(failed_scripts)}"
    )

    if failed_scripts:

        print()
        print(
            "Failed scripts:"
        )

        for script in failed_scripts:

            print(
                f"- "
                f"{script.relative_to(ROOT)}"
            )

        return 1

    return 0


def show_usage():
    """Display the available BiteFinder test commands."""

    print(
        "BiteFinder automated test runner"
    )

    print()

    print(
        "Usage:"
    )

    print(
        "  python tests/run_tests.py"
    )

    print(
        "  python tests/run_tests.py bis"
    )

    print(
        "  python tests/run_tests.py brns"
    )

    print(
        "  python tests/run_tests.py core"
    )

    print(
        "  python tests/run_tests.py deployment"
    )

    print(
        "  python tests/run_tests.py all"
    )


def main():
    """Read the requested test group and run it."""

    if len(sys.argv) == 1:

        group_name = "core"

    elif len(sys.argv) == 2:

        group_name = (
            sys.argv[1]
            .strip()
            .lower()
        )

    else:

        show_usage()

        raise SystemExit(2)

    if group_name not in TEST_GROUPS:

        print(
            f"Unknown test group: "
            f"{group_name}"
        )

        print()

        show_usage()

        raise SystemExit(2)

    exit_code = run_group(
        group_name
    )

    raise SystemExit(
        exit_code
    )


if __name__ == "__main__":
    main()