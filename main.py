"""Start the procedural BiteFinder CLI."""

from config import load_config
from debug import debug_log
from io_manager import run_cli


def main():
    config = load_config()
    debug_log("config_loaded")
    run_cli(config)


if __name__ == "__main__":
    main()
