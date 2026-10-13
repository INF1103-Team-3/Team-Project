"""Shared process-level BiteFinder fixture with fixed local HTTP responses."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __package__:
    from .friendly_test_report import run_friendly_suite
else:
    from friendly_test_report import run_friendly_suite


SOURCE = Path(__file__).resolve().parents[1]
PLACE_NAMES = ("Near Cafe", "Far Cafe")


def search_request(**changes):
    request = {
        "origin": {"query": "1.352,103.944", "label": "Tampines",
                   "latitude": 1.352, "longitude": 103.944},
        "mode": "walk", "max_distance_km": 2.0,
        "max_travel_minutes": None, "traffic_aware": False,
        "cuisine": "none", "budget_per_person": 10.0,
        "other_preferences": [], "dietary_requirements": [],
        "disliked_cuisines": [],
    }
    request.update(changes)
    return request


def places_response(extra=False):
    rows = [
        (PLACE_NAMES[0], 1, 1.353), (PLACE_NAMES[1], 2, 1.39),
    ]
    if extra:
        rows.extend((name, number, 1.353 + number * 0.0001)
                    for number, name in enumerate(
                        ("Third Cafe", "Fourth Cafe", "Fifth Cafe",
                         "Sixth Cafe"), 3))
    return {"places": [
        {"displayName": {"text": name},
         "id": f"test-place-{number}",
         "formattedAddress": f"{number} Test Road, Singapore",
         "postalAddress": {"postalCode": f"1234{number:02d}"},
         "nationalPhoneNumber": f"61234{number:03d}",
         "rating": 4.2, "userRatingCount": 125,
         "servesVegetarianFood": number == 2,
         "accessibilityOptions": {"wheelchairAccessibleEntrance": number == 1},
         "location": {"latitude": latitude, "longitude": 103.95},
         "currentOpeningHours": {
             "openNow": True,
             "periods": [{"open": {"day": 0, "hour": 0}}]},
         "regularOpeningHours": {
             "periods": [{"open": {"day": 0, "hour": 0}}]},
         "types": ["restaurant"],
         "priceRange": {"startPrice": {"units": "5"},
                        "endPrice": {"units": "8"}}}
        for name, number, latitude in rows
    ]}


def describe_http_call(path, body):
    """Name the service operation without printing request or account data."""
    method = "GET" if body is None else "POST"
    if path == "/chat/completions" and isinstance(body, dict):
        messages = body.get("messages") or []
        prompt = messages[0].get("content", "") if messages else ""
        purpose = next((label for marker, label in (
            ("Interpret today's restaurant wish", "BIS search interpretation"),
            ("Extract one profile travel limit", "BIS travel interpretation"),
            ("Correct an obvious typo in a short restaurant search menu answer",
             "BIS menu answer correction"),
            ("Rank every supplied restaurant candidate", "BRNS ranking"),
            ("Review this English", "BIS spelling review"),
            ("You assist BiteFinder profile collection", "BIS profile parsing"),
        ) if marker in prompt), "AI request")
        return f"{method} {path} [{purpose}]"
    purpose = {
        "/geocode": "Maps geocode", "/nearby": "Places nearby",
        "/text": "Places text search", "/matrix": "Routes matrix",
        "/route": "Directions route",
    }.get(path)
    return f"{method} {path}" + (f" [{purpose}]" if purpose else "")


class FixtureServer:
    """Fixed HTTP boundary; records each request without patching app code."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
        self.invalid_brns_ai = False
        self.six_matches = False
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, value):
                encoded = json.dumps(value).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                with fixture.lock:
                    fixture.calls.append((self.path.split("?", 1)[0], None))
                self.respond({"results": [{"geometry": {"location": {
                    "lat": 1.352, "lng": 103.944}}}]})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                body = json.loads(raw)
                with fixture.lock:
                    fixture.calls.append((self.path, body))
                if self.path == "/chat/completions":
                    system = body["messages"][0]["content"]
                    user = body["messages"][1]["content"]
                    if "Interpret today's restaurant wish" in system:
                        content = json.dumps(json.loads(user)["confirmed_choices"])
                    elif "Extract one profile travel limit" in system:
                        # Deliberately suggest km for bare "ten". BIS must still
                        # ask the user for a unit the user did not provide.
                        content = json.dumps({"value": 10, "unit": "km"})
                    elif "Rank every supplied restaurant candidate" in system:
                        data = json.loads(user)
                        content = json.dumps({"recommendations": [
                            {"id": item["id"], "reason_codes": []}
                            for item in data["candidates"]]})
                        if fixture.invalid_brns_ai:
                            content = '{"recommendations": "invalid"}'
                    elif "Review this English" in system:
                        corrected = user.replace("wesaten", "western")
                        content = json.dumps({
                            "status": "corrected" if corrected != user else "ok",
                            "text": corrected})
                    elif "You assist BiteFinder profile collection" in system:
                        profile_input = json.loads(user)
                        field = profile_input["current_field"]
                        vocabulary = (("punggol", "sengkang", "nex")
                                      if field == "location" else
                                      ("western", "italian"))
                        values = [item for item in vocabulary
                                  if item in profile_input["user_message"]]
                        content = json.dumps({
                            "intent": "profile_update",
                            "profile_updates": {field: values},
                            "location_action": "add"})
                    else:
                        content = "{}"
                    return self.respond({"choices": [{"message": {
                        "content": content}}]})
                if self.path in ("/nearby", "/text"):
                    return self.respond(places_response(fixture.six_matches))
                if self.path == "/matrix":
                    matrix = [
                        {"destinationIndex": index, "condition": "ROUTE_EXISTS",
                         "duration": duration, "distanceMeters": distance}
                        for index, duration, distance in (
                            (0, "600s", 900), (1, "3600s", 5000))]
                    if fixture.six_matches:
                        matrix[1] = {"destinationIndex": 1,
                                     "condition": "ROUTE_EXISTS",
                                     "duration": "900s", "distanceMeters": 1500}
                        matrix.extend({"destinationIndex": index,
                                       "condition": "ROUTE_EXISTS",
                                       "duration": "600s", "distanceMeters": 900}
                                      for index in range(2, 6))
                    return self.respond(matrix)
                if self.path == "/route":
                    return self.respond({"routes": [{
                        "duration": "600s", "distanceMeters": 900,
                        "legs": [{"steps": [{"navigationInstruction": {
                            "instructions": "Head north"}}]}]}]})
                self.send_error(404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def paths(self):
        with self.lock:
            return [path for path, _ in self.calls]

    def bodies(self, path):
        with self.lock:
            return [body for name, body in self.calls if name == path]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class BlackBoxFixture(unittest.TestCase):
    report_group = "Black box"

    def setUp(self):
        self.cli_calls = []
        self.observed_output = []
        self.temporary = tempfile.TemporaryDirectory(prefix="bitefinder-blackbox-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for folder in ("BIS", "BRNS", "BRC", "shared"):
            shutil.copytree(
                SOURCE / folder, self.root / folder,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", "data", "docs", ".gitignore"))
        (self.root / "BIS/data").mkdir()
        (self.root / "BRNS/data").mkdir()
        (self.root / "BRC/data").mkdir()
        (self.root / "data").mkdir()
        (self.root / "BRNS/data/restaurants.json").write_text("[]")
        self.fixture = FixtureServer()
        self.addCleanup(self.fixture.close)
        self.env = os.environ.copy()
        for name in tuple(self.env):
            if (name.startswith(("OPENROUTER_", "GEMINI_", "GROQ_", "SMTP_",
                                 "BITEFINDER_"))
                    or name in ("GOOGLE_MAPS_API_KEY", "AI_BYPASS",
                                "USE_LIVE_GOOGLE", "DEBUG")):
                self.env.pop(name)
        self.env.update({
            "NO_COLOR": "1", "AI_BYPASS": "false", "SMTP_BYPASS": "true",
            "USE_LIVE_GOOGLE": "true", "GEMINI_API_KEY": "",
            "OPENROUTER_API_KEY": "fixture-key",
            "OPENROUTER_MODEL": "fixture-model",
            "OPENROUTER_BASE_URL": self.fixture.base,
            "GOOGLE_MAPS_API_KEY": "fixture-key",
            "BITEFINDER_OPENROUTER_URL": self.fixture.base + "/chat/completions",
            "BITEFINDER_GEOCODE_URL": self.fixture.base + "/geocode",
            "BITEFINDER_TEXT_SEARCH_URL": self.fixture.base + "/text",
            "BITEFINDER_PLACES_URL": self.fixture.base + "/nearby",
            "BITEFINDER_MATRIX_URL": self.fixture.base + "/matrix",
            "BITEFINDER_ROUTES_URL": self.fixture.base + "/route",
            "NO_PROXY": "127.0.0.1,localhost",
        })

    def tearDown(self):
        if getattr(self, "_friendly_report", False):
            return
        cli, http = self.call_report()
        sys.stderr.write(f"\n    CLI calls: {cli}\n    HTTP calls: {http}\n")

    def call_report(self):
        """Describe observed calls without including inputs or account data."""
        cli_counts = Counter(self.cli_calls)
        cli = ", ".join(
            f"{name}/main.py" + (f" x{count}" if count > 1 else "")
            for name, count in cli_counts.items()) or "none"
        with self.fixture.lock:
            calls = list(self.fixture.calls)
        http = " -> ".join(
            describe_http_call(path, body) for path, body in calls) or "none"
        return cli, http

    def report_details(self):
        cli, http = self.call_report()
        return {
            "target_label": "Application", "target": cli,
            "observed_label": "Observed output excerpts",
            "observed": self.observed_output,
            "calls_label": "External calls",
            "calls": [] if http == "none" else http.split(" -> "),
            "no_calls": "None; no AI or Maps call was needed here.",
        }

    def run_cli(self, application, answers):
        self.cli_calls.append(application)
        content = answers if isinstance(answers, str) else "\n".join(answers) + "\n"
        try:
            completed = subprocess.run(
                [sys.executable, str(self.root / application / "main.py")],
                input=content, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, cwd=self.root, env=self.env,
                timeout=10, check=False)
        except subprocess.TimeoutExpired as error:
            self.fail(f"{application} hung after 10 seconds: {error.stdout!r}")
        self.assertEqual(completed.returncode, 0, completed.stdout)
        return completed.stdout

    def assert_shows(self, output, *snippets):
        for snippet in snippets:
            with self.subTest(expected=snippet):
                self.assertIn(snippet, output, output)
                line = next(line.strip() for line in output.splitlines()
                            if snippet in line)
                position = line.index(snippet)
                start = max(0, position - 55)
                end = min(len(line), position + len(snippet) + 55)
                excerpt = (("..." if start else "") + line[start:end]
                           + ("..." if end < len(line) else ""))
                excerpt = re.sub(r"[\w.+-]+@[\w.-]+", "<email>", excerpt)
                if excerpt not in self.observed_output:
                    self.observed_output.append(excerpt)

    def seed_complete_user(self):
        user_id = "blackbox-user"
        preferences = {
            "location": ["tampines"], "max_distance_km": 2.0,
            "max_travel_time_minutes": 40.0, "budget_per_person": 10.0,
            "dietary_requirements": [], "liked_cuisines": [],
            "disliked_cuisines": [], "other_preferences": [],
        }
        user = {"userID": user_id, "email": "tester@example.com",
                "email_verified": True, "username": "Tester",
                "preferences": preferences}
        (self.root / "BIS/data/users.json").write_text(json.dumps({user_id: user}))
        (self.root / "BIS/data/profile_state.json").write_text(json.dumps({
            "search": {user_id: {"completed": True}}}))
        return user

    def history(self):
        path = self.root / "BRNS/data/search_history.json"
        return json.loads(path.read_text()) if path.exists() else []


def run_blackbox_suite(test_case=None):
    """Run one black box class, or discover all three classes."""
    if test_case is None:
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(Path(__file__).parent),
            pattern="test_blackbox_*.py", top_level_dir=str(SOURCE))
        heading = "BiteFinder black box tests: BIS, BRNS, and BIS to BRNS"
    else:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(test_case)
        heading = ("BiteFinder black box tests: "
                   + {"BISBlackBoxTests": "BIS",
                      "BRNSBlackBoxTests": "BRNS",
                      "BISToBRNSBlackBoxTests": "BIS to BRNS"}.get(
                          test_case.__name__, test_case.__name__))
    run_friendly_suite(suite, heading)


if __name__ == "__main__":
    run_blackbox_suite()
