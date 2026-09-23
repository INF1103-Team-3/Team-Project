"""Command-line boundary for BiteFinder."""

from data_manager import load_json


def run_cli(config):
    restaurants, error = load_json(config["data_dir"] / "restaurants.json")
    print("BiteFinder CLI")
    print(error or f"Loaded {len(restaurants)} restaurant records.")
    if not restaurants:
        print("No verified restaurant data has been imported yet.")
