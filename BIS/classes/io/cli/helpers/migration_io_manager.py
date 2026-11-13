"""CLI output for explicitly requested storage migrations."""
import json


class MigrationIOManager:
    def display(self, counts, applied=False):
        print(json.dumps({"mode": "applied" if applied else "dry-run", "records": counts}, indent=2))

    def error(self, message):
        print("Migration stopped: " + message)
