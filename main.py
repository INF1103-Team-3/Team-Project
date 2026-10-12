"""Start the BiteFinder interaction system from the repository root."""

import sys
from pathlib import Path


def main():
    """Launch the existing BIS command-line application."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "BIS"))
    from BIS.main import main as bis_main

    bis_main()


if __name__ == "__main__":
    main()
