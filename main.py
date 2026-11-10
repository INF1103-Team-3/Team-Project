"""Start the BiteFinder interaction system from the repository root."""

import sys
from pathlib import Path


def main(argv=None):
    """Launch BIS with the interactive CLI/web choice or explicit mode flags."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "BIS"))
    from BIS.main import main as bis_main

    return bis_main(argv)


if __name__ == "__main__":
    main()
