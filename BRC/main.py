"""Check restaurant JSON against an existing MUIS snapshot."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRC import ai_manager, data_manager, io_manager, logic_manager
from shared import debug_log


def check_json(value, snapshot: dict, ai: ai_manager.AIManager):
    """Return complete checked JSON in the same object/array shape."""
    records, single = io_manager.accept_check_input(value)
    debug_log.debug_log(f"Accepted {len(records)} restaurant records.", "INFO",
                        "BRC.io_manager.accept_check_input")
    if not records:
        return []
    proposals = ai.propose_muis_matches(records, snapshot)
    debug_log.debug_log(f"AI proposed {sum(bool(item) for item in proposals)} matches.",
                        "INFO", "BRC.ai_manager.propose_muis_matches")
    checked = logic_manager.check_muis_records(records, snapshot, proposals)
    debug_log.debug_log(
        f"Verified {sum(item.get('halal_certification') == 'official' for item in checked)} outlets.",
        "INFO", "BRC.logic_manager.check_muis_records")
    return checked[0] if single else checked


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check restaurant JSON with BRC.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    check = subcommands.add_parser("check")
    inputs = check.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", type=Path)
    inputs.add_argument("--stdin", action="store_true")
    outputs = check.add_mutually_exclusive_group()
    outputs.add_argument("--output", type=Path)
    outputs.add_argument("--stdout", action="store_true")
    check.add_argument("--snapshot", type=Path,
                       default=data_manager.MUIS_SNAPSHOT_PATH)
    args = parser.parse_args(argv)

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    debug_log.configure_python_logging()
    token = debug_log.start_trace()
    try:
        value = io_manager.read_check_input(args.input)
        snapshot = io_manager.load_check_snapshot(args.snapshot)
        debug_log.debug_log(
            f"Loaded MUIS snapshot with {len(snapshot['listings'])} listings.",
            "INFO", "BRC.io_manager.load_check_snapshot")
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ValueError("Set GEMINI_API_KEY before running the BRC checker.")
        ai = ai_manager.AIManager(
            api_key=key, model=os.getenv("BRC_GEMINI_MODEL", "gemini-3.5-flash-lite"))
        checked = check_json(value, snapshot, ai)
        if args.output:
            data_manager.save_checked_output(checked, args.output)
            debug_log.debug_log("Checked JSON saved.", "INFO",
                                "BRC.data_manager.save_checked_output")
        else:
            json.dump(checked, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
    except Exception as exc:
        debug_log.debug_log(f"Check stopped: {type(exc).__name__}.", "ERROR",
                            "BRC.main.check")
        print(f"BRC check failed: {exc}", file=sys.stderr)
        return 1
    finally:
        debug_log.end_trace(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
