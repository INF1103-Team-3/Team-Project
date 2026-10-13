"""Procedural source checks for the INF1103 Part 1 submission constraints.

Run from the repository root:
    python tests/inf1103_compliance_check.py
"""

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLICATION_FOLDERS = ("BIS", "BRNS", "BRC", "shared")
REQUIRED_FUNCTIONS = {
    "io_manager.py": {"display_record", "display_list", "display_result"},
    "ai_manager.py": {
        "build_prompt", "call_api", "parse_response", "validate_response"},
    "logic_manager.py": {"evaluate", "score", "route"},
    "data_manager.py": {"save", "load", "query"},
}


def application_files():
    return [
        path for folder in APPLICATION_FOLDERS
        for path in (ROOT / folder).glob("*.py")
    ]


def defined_functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def check_procedural_source():
    failures = []
    for path in application_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes = [node.name for node in ast.walk(tree)
                   if isinstance(node, ast.ClassDef)]
        if classes:
            failures.append(f"{path.relative_to(ROOT)} defines classes: {classes}")
        if path.name == "io_manager.py":
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in {"input", "print"}:
                failures.append(
                    f"{path.relative_to(ROOT)}:{node.lineno} calls {node.func.id}()")
    return failures


def check_manager_functions():
    failures = []
    for area in ("BIS", "BRNS", "BRC"):
        for filename, required in REQUIRED_FUNCTIONS.items():
            path = ROOT / area / filename
            found = defined_functions(path)
            missing = sorted(required - found)
            if missing:
                failures.append(
                    f"{path.relative_to(ROOT)} is missing {', '.join(missing)}")
    return failures


def check_submission_files():
    failures = []
    if not (ROOT / "Dockerfile").is_file():
        failures.append("The repository root has no Dockerfile.")
    if not (ROOT / "requirements.txt").is_file():
        failures.append("The repository root has no requirements.txt.")
    return failures


def run():
    failures = (check_procedural_source() + check_manager_functions()
                + check_submission_files())
    if failures:
        sys.stderr.write("INF1103 compliance check failed:\n")
        for failure in failures:
            sys.stderr.write(f"  - {failure}\n")
        return 1
    sys.stdout.write(
        "INF1103 production-source check passed: procedural managers, "
        "required functions, IO boundaries, and root Docker files.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
