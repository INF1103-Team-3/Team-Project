"""Deployment smoke tests for the BiteFinder Docker environment."""

import importlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_ROOT))


from reporting import show_case, show_summary


def test_running_inside_docker():
    """The deployment smoke test must run inside the submitted container."""

    test_input = {
        "docker_marker":
            "/.dockerenv",
    }

    expected = True

    actual = (
        Path(
            "/.dockerenv"
        ).exists()
    )

    show_case(
        "DEP-01: Test is running inside Docker",
        "Path.exists()",
        "Confirms that the deployment check is executing "
        "inside a Docker container rather than only on the host machine.",
        test_input,
        expected,
        actual,
    )

    assert actual is expected


def test_required_application_files_are_packaged():
    """The Docker image contains the required BiteFinder files."""

    required_files = [
        "main.py",
        "BIS/main.py",
        "BIS/logic_manager.py",
        "BRNS/main.py",
        "BRNS/logic_manager.py",
        "BRC/main.py",
        "shared/terminal_ui.py",
        "tests/bis/test_bis.py",
        "tests/brns/test_brns.py",
    ]

    test_input = {
        "required_files":
            required_files,
    }

    expected = {
        file_name: True
        for file_name
        in required_files
    }

    actual = {
        file_name:
            (
                ROOT /
                file_name
            ).exists()

        for file_name
        in required_files
    }

    show_case(
        "DEP-02: Required application and test files packaged",
        "Path.exists()",
        "Checks that the Docker image contains the BiteFinder "
        "modules and automated test scripts needed for assessment.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_bis_and_brns_modules_import_successfully():
    """The deployed Python environment can load BIS and BRNS."""

    modules = [
        "BIS.logic_manager",
        "BRNS.logic_manager",
    ]

    test_input = {
        "modules":
            modules,
    }

    expected = {
        "BIS.logic_manager":
            "imported",

        "BRNS.logic_manager":
            "imported",
    }

    actual = {}

    for module_name in modules:

        try:
            importlib.import_module(
                module_name
            )

            actual[
                module_name
            ] = "imported"

        except Exception as error:

            actual[
                module_name
            ] = (
                f"{type(error).__name__}: "
                f"{error}"
            )

    show_case(
        "DEP-03: BiteFinder modules import successfully",
        "importlib.import_module()",
        "Confirms that the deployed container has the dependencies "
        "and Python paths required to load BIS and BRNS.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def check_directory_writable(directory):
    """Write and remove a marker without changing stored application data."""

    marker = (
        directory /
        ".deployment_smoke_test"
    )

    try:
        marker.write_text(
            "BiteFinder deployment smoke test",
            encoding="utf-8",
        )

        return marker.exists()

    finally:

        if marker.exists():
            marker.unlink()


def test_persistent_data_directories_are_writable():
    """BIS and BRNS Docker data locations can be written successfully."""

    directories = {
        "BIS":
            ROOT / "BIS" / "data",

        "BRNS":
            ROOT / "BRNS" / "data",
    }

    test_input = {
        name: str(path)
        for name, path
        in directories.items()
    }

    expected = {
        "BIS": True,
        "BRNS": True,
    }

    actual = {
        name:
            check_directory_writable(
                path
            )

        for name, path
        in directories.items()
    }

    show_case(
        "DEP-04: Persistent data directories writable",
        "check_directory_writable()",
        "Confirms that BiteFinder can write to the BIS and BRNS "
        "data directories mounted by the Docker deployment.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_brc_service_is_reachable():
    """The BIS/BRNS container can reach the separate BRC service."""

    base_url = os.getenv(
        "BRC_SERVICE_URL",
        "http://brc:8000",
    ).rstrip("/")

    health_url = (
        base_url +
        "/health"
    )

    test_input = {
        "service":
            "BRC",

        "health_url":
            health_url,
    }

    expected = {
        "status": "ok",
    }

    try:
        with urllib.request.urlopen(
            health_url,
            timeout=5,
        ) as response:

            actual = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except Exception as error:

        actual = {
            "error":
                f"{type(error).__name__}: "
                f"{error}"
        }

    show_case(
        "DEP-05: BRC container reachable",
        "urllib.request.urlopen()",
        "Checks Docker service networking by calling the BRC "
        "health endpoint from the BIS/BRNS container.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def run_core_test_script(relative_path):
    """Run a core test file with live provider credentials removed."""

    environment = (
        os.environ.copy()
    )

    provider_keys = (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_API_KEYS",
        "OPENROUTER_API_KEYS_FILE",
        "GOOGLE_MAPS_API_KEY",
    )

    for key in provider_keys:

        environment.pop(
            key,
            None,
        )

    result = subprocess.run(
        [
            sys.executable,
            str(
                ROOT /
                relative_path
            ),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )

    output_lines = [
        line.strip()

        for line
        in result.stdout.splitlines()

        if line.strip()
    ]

    return {
        "exit_code":
            result.returncode,

        "summary":
            output_lines[-4:],
    }


def test_bis_core_tests_pass_without_api_credentials():
    """BIS automated tests run successfully without live AI credentials."""

    test_input = {
        "script":
            "tests/bis/test_bis.py",

        "live_api_credentials":
            "removed",
    }

    expected = {
        "exit_code": 0,
    }

    result = (
        run_core_test_script(
            "tests/bis/test_bis.py"
        )
    )

    actual = {
        "exit_code":
            result["exit_code"],
    }

    show_case(
        "DEP-06: BIS tests run without live AI",
        "subprocess.run()",
        "Runs the BIS automated test script inside Docker after "
        "removing live AI and Maps credentials.",
        test_input,
        expected,
        actual,
    )

    if result["summary"]:

        print(
            "BIS test summary:"
        )

        for line in result["summary"]:

            print(
                f"  {line}"
            )

    assert actual == expected


def test_brns_core_tests_pass_without_api_credentials():
    """BRNS automated tests run successfully without live AI credentials."""

    test_input = {
        "script":
            "tests/brns/test_brns.py",

        "live_api_credentials":
            "removed",
    }

    expected = {
        "exit_code": 0,
    }

    result = (
        run_core_test_script(
            "tests/brns/test_brns.py"
        )
    )

    actual = {
        "exit_code":
            result["exit_code"],
    }

    show_case(
        "DEP-07: BRNS tests run without live AI",
        "subprocess.run()",
        "Runs the BRNS automated test script inside Docker after "
        "removing live AI and Maps credentials.",
        test_input,
        expected,
        actual,
    )

    if result["summary"]:

        print(
            "BRNS test summary:"
        )

        for line in result["summary"]:

            print(
                f"  {line}"
            )

    assert actual == expected


TESTS = (
    test_running_inside_docker,
    test_required_application_files_are_packaged,
    test_bis_and_brns_modules_import_successfully,
    test_persistent_data_directories_are_writable,
    test_brc_service_is_reachable,
    test_bis_core_tests_pass_without_api_credentials,
    test_brns_core_tests_pass_without_api_credentials,
)


def run_tests():
    """Run all BiteFinder deployment smoke tests."""

    failures = []

    for test in TESTS:

        try:
            test()

        except Exception as error:

            failures.append(
                (
                    test.__name__,
                    error,
                )
            )

            print(
                f"\nFAILED: "
                f"{test.__name__}: "
                f"{error}"
            )

    show_summary(
        "Deployment",
        len(TESTS),
        failures,
    )

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    run_tests()