"""BRC command-line adapter."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from BRC.classes.brc_application import BRCApplication
from BRC.classes.console_progress import ConsoleProgress
from BRC.classes.io_manager import NO_INPUT, IOManager
from BRC.classes.json_file import JsonFile
from shared import debug_log


class CommandLine:
    """Parse BRC command-line input and present it through IOManager."""

    def __init__(self, io=None):
        self._io = io or IOManager()

    def run(self, argv=None):
        arguments = list(sys.argv[1:] if argv is None else argv)
        if arguments[:1] == ["check"]:
            arguments = arguments[1:]
        interactive = not arguments
        parser = argparse.ArgumentParser(
            description="Build or use the BRC halal database.")
        inputs = parser.add_mutually_exclusive_group()
        inputs.add_argument("--input", type=Path)
        inputs.add_argument("--stdin", action="store_true")
        parser.add_argument("--output", type=Path)
        parser.add_argument("--stdout", action="store_true")
        args = parser.parse_args(arguments)

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        debug_log.configure_python_logging()
        token = debug_log.start_trace()
        progress = ConsoleProgress() if interactive else None
        try:
            if interactive:
                value = self._io.collect_interactive_input()
                self._io.display_status("", error=True)
            elif args.input or args.stdin:
                value = self._io.read_json_input(args.input)
            else:
                value = NO_INPUT
            app = BRCApplication(
                io=self._io,
                verbose=interactive,
                scrape_progress=progress)
            result = app.run(value, args.output)
            if args.stdout:
                self._io.write_raw(
                    JsonFile.format_json(result, compact_hours=True))
            elif value is NO_INPUT:
                self._io.display_status(
                    f"Built {len(result)} verified halal restaurant records.")
            else:
                self._io.display_result(result)
            return 0
        except Exception as error:
            debug_log.debug_log(
                f"BRC failed: {type(error).__name__}: {error}",
                "ERROR", "BRC.main")
            self._io.display_status(f"BRC failed: {error}", error=True)
            return 1
        finally:
            if progress:
                progress.finish()
            debug_log.end_trace(token)

    @classmethod
    def main(cls, argv=None):
        return cls().run(argv)
