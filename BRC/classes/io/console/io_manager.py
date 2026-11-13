"""BRC IO Manager: terminal input, validation, and presentation."""

import json
import re
import sys
from pathlib import Path


NO_INPUT = object()
DEFAULT_RESTAURANTS_PATH = (
    Path(__file__).resolve().parents[2]
    / "BRNS" / "data" / "restaurants.json")


class IOManager:
    """Own all BRC user-facing terminal input and output."""

    def __init__(self, input_fn=input, out=None, err=None):
        self._input = input_fn
        self._out = out
        self._err = err

    def collect_interactive_input(self):
        self._print("\nBiteFinder Restaurant Checker")
        self._print("  1. Build or refresh the cleaned MUIS halal database")
        self._print(
            f"  2. Check the default restaurant file "
            f"({DEFAULT_RESTAURANTS_PATH})")
        self._print(
            "  3. Check a restaurant JSON file (one object or an array)")
        self._print("  4. Paste one restaurant JSON object")
        self._print(
            "  5. Check a file containing one restaurant JSON object")
        choice = self._ask_choice()
        if choice == "1":
            return NO_INPUT
        if choice == "2":
            return self.read_json_input(DEFAULT_RESTAURANTS_PATH)
        if choice == "3":
            return self.read_json_input(self._ask_path())
        if choice == "4":
            return self._ask_pasted_object()
        value = self.read_json_input(self._ask_path())
        if not isinstance(value, dict):
            raise ValueError(
                "The selected file must contain one restaurant object.")
        return value

    def _ask_choice(self):
        while True:
            choice = self._input("Choose 1–5 [Enter = 1]: ").strip() or "1"
            if choice in {"1", "2", "3", "4", "5"}:
                return choice
            self._print("Choose a number from 1 to 5.")

    def _ask_path(self):
        entered = self._input(
            "Restaurant JSON file path: ").strip().strip('"')
        if not entered:
            raise ValueError("Restaurant JSON file path cannot be empty.")
        return Path(entered).expanduser()

    def _ask_pasted_object(self):
        try:
            value = json.loads(
                self._input("Paste one restaurant JSON object: "))
        except json.JSONDecodeError as error:
            raise ValueError(
                "The pasted restaurant JSON is invalid.") from error
        if not isinstance(value, dict):
            raise ValueError(
                "Paste one restaurant JSON object, not an array.")
        return value

    @staticmethod
    def read_json_input(path=None):
        try:
            text = (
                Path(path).read_text(encoding="utf-8")
                if path else sys.stdin.read())
            return json.loads(text)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "Could not read restaurant JSON input.") from error

    @staticmethod
    def validate_restaurants(value):
        single = isinstance(value, dict)
        if not single and not isinstance(value, list):
            raise ValueError(
                "BRC requires one restaurant object or an array.")
        records = [value] if single else value
        if not records:
            raise ValueError("The restaurant array cannot be empty.")
        for number, record in enumerate(records, 1):
            if (not isinstance(record, dict)
                    or not str(record.get("name") or "").strip()):
                raise ValueError(f"Restaurant {number} needs a name.")
            has_address = str(record.get("address") or "").strip()
            has_postal = re.fullmatch(
                r"\d{6}", str(record.get("postal_code") or ""))
            if not has_address and not has_postal:
                raise ValueError(
                    f"Restaurant {number} needs an address or postal code.")
            if ("dietary" in record
                    and not isinstance(record["dietary"], list)):
                raise ValueError(
                    f"Restaurant {number} has invalid dietary data.")
        return records, single

    def display_record(self, record):
        self._print(json.dumps(record, ensure_ascii=False, indent=2))

    def display_list(self, records):
        self._print(json.dumps(list(records), ensure_ascii=False, indent=2))

    def display_result(self, result):
        if isinstance(result, list):
            self._print(f"Checked {len(result)} restaurant(s).")
        else:
            self._print("Checked 1 restaurant.")

    def display_status(self, message, error=False):
        stream = (
            (self._err or sys.stderr)
            if error else (self._out or sys.stdout))
        print(message, file=stream)

    def write_raw(self, text):
        (self._out or sys.stdout).write(text)

    def _print(self, text):
        print(text, file=self._out or sys.stdout)
