"""Launch-menu and web startup checks without Docker, browser, or external IO."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from BIS.classes.io.cli.helpers.launcher_io import LauncherIO
from BIS.classes.services.launcher.bis_launcher import BISLauncher
from BIS.classes.services.launcher.web_interface_launcher import WebInterfaceLauncher


class LauncherTests(unittest.TestCase):
    def test_enter_cli_and_invalid_entries(self):
        answers = iter(["bad", ""])
        messages = []
        menu = LauncherIO(lambda _prompt: next(answers), messages.append)
        self.assertEqual(menu.choose_interface(), "cli")
        self.assertIn("Choose 1, 2, or 0.", messages)

    def test_explicit_cli_skips_prompt_and_web_dependencies(self):
        menu = SimpleNamespace(choose_interface=Mock(), display_message=Mock())
        cli = Mock(return_value="cli")
        web = SimpleNamespace(start=Mock())
        self.assertEqual(BISLauncher(menu, cli, web).run("cli"), "cli")
        menu.choose_interface.assert_not_called()
        web.start.assert_not_called()

    def test_exit_does_not_start_any_services(self):
        menu = LauncherIO(lambda _p: "0", lambda _m: None)
        cli, web = Mock(), SimpleNamespace(start=Mock())
        BISLauncher(menu, cli, web).run()
        cli.assert_not_called()
        web.start.assert_not_called()

    def test_eof_exits(self):
        self.assertEqual(LauncherIO(Mock(side_effect=EOFError), lambda _m: None).choose_interface(), "exit")

    @staticmethod
    def ready_response():
        response = io.BytesIO(json.dumps({"mongodb": True}).encode())
        response.status = 200
        return response

    def test_already_running_reuses_stack_and_opens_host_browser(self):
        runner, browser = Mock(), Mock(return_value=True)
        launcher = WebInterfaceLauncher(runner=runner, browser=browser,
                  opener=lambda *_a, **_k: self.ready_response(), in_container=False)
        self.assertTrue(launcher.start()["browser_opened"])
        runner.assert_not_called()
        browser.assert_called_once()

    def test_container_never_runs_docker_or_opens_a_browser(self):
        runner, browser = Mock(), Mock()
        launcher = WebInterfaceLauncher(runner=runner, browser=browser,
                  opener=lambda *_a, **_k: self.ready_response(), in_container=True)
        self.assertFalse(launcher.start()["browser_opened"])
        runner.assert_not_called()
        browser.assert_not_called()

    def test_docker_failure_is_explained(self):
        launcher = WebInterfaceLauncher(runner=Mock(side_effect=FileNotFoundError),
                  opener=Mock(side_effect=OSError), in_container=False)
        with self.assertRaisesRegex(RuntimeError, "Check Docker"):
            launcher.start()

    def test_root_and_bis_entry_points_exit_without_loading_optional_services(self):
        import os
        import subprocess
        environment = os.environ.copy()
        environment.update(BITEFINDER_STORAGE="mongo", MONGO_URI="mongodb://unavailable.invalid:27017/")
        for relative in ("main.py", "BIS/main.py"):
            result = subprocess.run([sys.executable, str(ROOT / relative)],
                                    input="0\n", text=True, capture_output=True,
                                    env=environment, cwd=ROOT, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Start the web interface", result.stdout)
            self.assertIn("Goodbye", result.stdout)
            self.assertNotIn("MongoDB", result.stdout)

    def test_browser_failure_still_returns_running_web_url(self):
        launcher = WebInterfaceLauncher(browser=Mock(side_effect=OSError),
                  opener=lambda *_a, **_k: self.ready_response(), in_container=False)
        self.assertEqual(launcher.start(), {"url": "http://localhost:8080", "browser_opened": False})

    def test_readiness_timeout_is_bounded(self):
        times = iter([0, 1])
        launcher = WebInterfaceLauncher(runner=Mock(), opener=Mock(side_effect=OSError),
                  clock=lambda: next(times), sleep=Mock(), timeout=.1, in_container=False)
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            launcher.start()


if __name__ == "__main__":
    unittest.main(verbosity=2)
