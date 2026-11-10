"""Minimal launch-menu IO; no application, AI, or database initialization."""


class LauncherIO:
    def __init__(self, read=input, write=print):
        self._read, self._write = read, write

    def display_message(self, message):
        self._write(message)

    def choose_interface(self):
        self.display_message("BiteFinder\n1. Use the CLI\n2. Start the web interface\n0. Exit")
        while True:
            try:
                value = self._read("Choose an option [1]: ")
                if value is None:
                    return "exit"
                value = value.strip()
            except (EOFError, KeyboardInterrupt):
                return "exit"
            choice = {"": "cli", "1": "cli", "2": "web", "0": "exit"}.get(value)
            if choice:
                return choice
            self.display_message("Choose 1, 2, or 0.")
