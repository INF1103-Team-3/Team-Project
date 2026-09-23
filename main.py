"""Start the procedural BiteFinder CLI."""

import sys

from config import load_config
from debug import debug_log
from io_manager import run_cli


def main():
    config = load_config()
    debug_log("config_loaded")
    return run_cli(config, sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
