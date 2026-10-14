"""Main colored test runner for BiteFinder automated tests."""

import os
import subprocess
import sys
from pathlib import Path

from reporting import show_group_start, style


TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

BIS_TEST = TESTS_DIR / "bis" / "test_bis.py"
BRNS_TEST = TESTS_DIR / "brns" / "test_brns.py"
BRC_TEST = TESTS_DIR / "brc" / "test_brc.py"
BLACKBOX_TESTS = (
    TESTS_DIR / "blackbox" / "test_blackbox_bis.py",
    TESTS_DIR / "blackbox" / "test_blackbox_brns.py",
    TESTS_DIR / "blackbox" / "test_blackbox_bis_to_brns.py",
)
INTEGRATION_TEST = TESTS_DIR / "integration" / "test_bis_brns_integration.py"
DEPLOYMENT_TEST = TESTS_DIR / "deployment" / "smoke.py"
API_AI_TEST = TESTS_DIR / "API testing" / "test_ai_keys_and_fallback.py"
API_GOOGLE_TEST = TESTS_DIR / "API testing" / "test_google_api.py"
API_TESTS = (
    API_AI_TEST,
    API_GOOGLE_TEST,
)

TEST_GROUPS = {
    "bis": (BIS_TEST,),
    "brns": (BRNS_TEST,),
    "brc": (BRC_TEST,),

    "core": (
        BIS_TEST,
        BRNS_TEST,
        BRC_TEST,
    ),

    "blackbox": BLACKBOX_TESTS,

    "integration": (INTEGRATION_TEST,),

    "deployment": (DEPLOYMENT_TEST,),

    "api": API_TESTS,

    "all": (
        BIS_TEST,
        BRNS_TEST,
        BRC_TEST,
        *BLACKBOX_TESTS,
        INTEGRATION_TEST,
        DEPLOYMENT_TEST,
    ),
}

GROUP_DESCRIPTIONS = {
    "bis": (
        "Tests BIS input validation, preference handling, search preparation "
        "and hardcoded AI interpretation."
    ),
    "brns": (
        "Tests BRNS restaurant filtering, recommendation rules, dietary "
        "checks, ranking and hardcoded AI recommendations."
    ),
    "brc": (
        "Tests MUIS halal verification and official outlet matching."
    ),
    "core": (
        "Runs the BIS and BRNS core function tests without calling a live "
        "AI API."
    ),
    "blackbox": (
        "Runs the real BIS and BRNS command-line programs against controlled "
        "local service fixtures."
    ),
    "integration": (
        "Verifies the structured BIS to BRNS request boundary and shared "
        "business rules."
    ),
    "deployment": (
        "Checks that BiteFinder and its automated tests work inside the "
        "submitted Docker environment."
    ),
    "api": (
        "Validates live API key connectivity (OpenRouter, Gemini, Groq, "
        "Google Maps), AI fallback cascades, and Google Maps services."
    ),
    "all": "Runs every BiteFinder core, black-box, integration and deployment test.",
}


def safe_test_environment(use_brc_service=False, is_api_test=False):
    """Return an importable test environment; retains credentials only for API tests."""
    environment = os.environ.copy()
    paths = [str(ROOT), str(TESTS_DIR)]
    if environment.get("PYTHONPATH"):
        paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(paths)

    if not is_api_test:
        for key in (
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "OPENROUTER_API_KEY",
            "OPENROUTER_API_KEYS",
            "OPENROUTER_API_KEYS_FILE",
            "GOOGLE_MAPS_API_KEY",
        ):
            environment.pop(key, None)
    if not use_brc_service:
        environment.pop("BRC_SERVICE_URL", None)
    return environment


def running_inside_docker():
    """Return True when the test runner is executing inside Docker."""
    return Path("/.dockerenv").exists()


def run_test_file(test_file):
    """Run one BiteFinder test script and return its exit code."""
    relative = test_file.relative_to(ROOT)
    if not test_file.exists():
        print(style(f"\nERROR: Test file not found: {relative}", "error"))
        return 1

    print("\n" + style("-" * 72, "rule"))
    print(style(f"Running: {relative}", "running"))
    print(style("-" * 72, "rule"), flush=True)

    is_api = "API testing" in str(test_file)
    result = subprocess.run(
        [sys.executable, str(test_file)],
        cwd=ROOT,
        env=safe_test_environment(
            use_brc_service=(test_file == DEPLOYMENT_TEST),
            is_api_test=is_api,
        ),
    )
    status = "PASS" if result.returncode == 0 else "FAIL"
    role = "pass" if result.returncode == 0 else "fail"
    print(style(f"Completed: {relative} — {status}", role))
    return result.returncode


def run_group(group_name):
    """Run every test script belonging to the selected group."""
    scripts = TEST_GROUPS[group_name]
    show_group_start(group_name, GROUP_DESCRIPTIONS[group_name])

    if group_name in {"deployment", "all"} and not running_inside_docker():
        print(style(
            "\nDeployment tests must run inside the BiteFinder Docker container.",
            "warning",
        ))
        print("\nStart Docker with:")
        print(style("  docker compose up -d --build", "command"))
        print("\nThen run:")
        print(style(
            f"  docker compose exec bis-brns python tests/run_tests.py {group_name}",
            "command",
        ))
        return 1

    failed_scripts = [
        script for script in scripts if run_test_file(script) != 0
    ]

    print("\n" + style("=" * 72, "rule"))
    print(style(f"{group_name.upper()} GROUP SUMMARY", "heading"))
    print(style("=" * 72, "rule"))
    print(f"Test scripts run: {len(scripts)}")
    print(style(
        f"Passed scripts: {len(scripts) - len(failed_scripts)}",
        "pass",
    ))
    print(style(
        f"Failed scripts: {len(failed_scripts)}",
        "fail" if failed_scripts else "muted",
    ))

    if failed_scripts:
        print(style("\nFailed scripts:", "fail"))
        for script in failed_scripts:
            print(style(f"- {script.relative_to(ROOT)}", "fail"))
        return 1
    return 0


def show_usage():
    """Display the available BiteFinder test commands."""
    print(style("BiteFinder automated test runner", "heading"))
    print("\nUsage:")
    for group in ("bis", "brns", "core", "blackbox", "integration",
                  "deployment", "all"):
        print(style(f"  python tests/run_tests.py {group}", "command"))
    print("\nWith no group, the runner uses core.")
    print("Set BITEFINDER_TEST_COLOR=always or never to override color detection.")


def main():
    """Read the requested test group and run it."""
    if len(sys.argv) == 1:
        group_name = "core"
    elif len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        show_usage()
        return
    elif len(sys.argv) == 2:
        group_name = sys.argv[1].strip().lower()
    else:
        show_usage()
        raise SystemExit(2)

    if group_name not in TEST_GROUPS:
        print(style(f"Unknown test group: {group_name}\n", "error"))
        show_usage()
        raise SystemExit(2)
    raise SystemExit(run_group(group_name))


if __name__ == "__main__":
    main()
