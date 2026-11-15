"""Select the terminal or browser entry point without owning domain rules."""


class BISLauncher:
    def __init__(self, io, cli_runner, web_launcher):
        self._io = io
        self._cli = cli_runner
        self._web = web_launcher

    def run(self, mode=None):
        while True:
            selected = mode or self._io.choose_interface()
            if selected == "exit":
                self._io.display_message("Goodbye!")
                return
            try:
                if selected == "cli":
                    return self._cli()
                self._io.display_message("Starting the web interface...")
                result = self._web.start()
                self._io.display_message("Open BiteFinder: " + result["url"])
                if not result["browser_opened"]:
                    self._io.display_message("Open this URL in your host browser.")
                return result
            except (OSError, RuntimeError) as error:
                self._io.display_message(str(error))
                if mode:
                    return
