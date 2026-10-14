"""Shared helpers for BiteFinder process-level black-box tests."""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_ROOT))

from reporting import show_case, show_summary


PLACE_NAMES = (
    "Near Cafe",
    "Far Cafe",
)


def search_request(**changes):
    """Return one valid BIS-to-BRNS request."""

    request = {
        "origin": {
            "query": "1.352,103.944",
            "label": "Tampines",
            "latitude": 1.352,
            "longitude": 103.944,
        },
        "mode": "walk",
        "max_distance_km": 2.0,
        "max_travel_minutes": None,
        "traffic_aware": False,
        "cuisine": "none",
        "budget_per_person": 10.0,
        "other_preferences": [],
        "dietary_requirements": [],
        "disliked_cuisines": [],
    }

    request.update(changes)

    return request


def places_response(extra=False):
    """Return fixed local restaurant data for black-box testing."""

    rows = [
        (
            PLACE_NAMES[0],
            1,
            1.353,
        ),
        (
            PLACE_NAMES[1],
            2,
            1.39,
        ),
    ]

    if extra:
        rows.extend(
            (
                name,
                number,
                1.353 + number * 0.0001,
            )
            for number, name
            in enumerate(
                (
                    "Third Cafe",
                    "Fourth Cafe",
                    "Fifth Cafe",
                    "Sixth Cafe",
                ),
                3,
            )
        )

    return {
        "places": [
            {
                "displayName": {
                    "text": name,
                },

                "id":
                    f"test-place-{number}",

                "formattedAddress":
                    f"{number} Test Road, Singapore",

                "postalAddress": {
                    "postalCode":
                        f"1234{number:02d}",
                },

                "nationalPhoneNumber":
                    f"61234{number:03d}",

                "rating":
                    4.2,

                "userRatingCount":
                    125,

                "servesVegetarianFood":
                    number == 2,

                "accessibilityOptions": {
                    "wheelchairAccessibleEntrance":
                        number == 1,
                },

                "location": {
                    "latitude":
                        latitude,

                    "longitude":
                        103.95,
                },

                "currentOpeningHours": {
                    "openNow":
                        True,

                    "periods": [
                        {
                            "open": {
                                "day": 0,
                                "hour": 0,
                            }
                        }
                    ],
                },

                "regularOpeningHours": {
                    "periods": [
                        {
                            "open": {
                                "day": 0,
                                "hour": 0,
                            }
                        }
                    ],
                },

                "types": [
                    "restaurant",
                ],

                "priceRange": {
                    "startPrice": {
                        "units": "5",
                    },

                    "endPrice": {
                        "units": "8",
                    },
                },
            }

            for name, number, latitude
            in rows
        ]
    }


def _read_request(connection):
    """Read one HTTP request sent to the local black-box service."""

    data = b""

    while b"\r\n\r\n" not in data:

        chunk = connection.recv(
            4096
        )

        if not chunk:
            break

        data += chunk

    head, _, body = data.partition(
        b"\r\n\r\n"
    )

    lines = (
        head.decode(
            "iso-8859-1"
        )
        .split("\r\n")
    )

    method, raw_path, _ = (
        lines[0].split()
    )

    path = raw_path.split(
        "?",
        1,
    )[0]

    headers = {}

    for line in lines[1:]:

        if ":" in line:

            name, value = line.split(
                ":",
                1,
            )

            headers[
                name.lower().strip()
            ] = value.strip()

    length = int(
        headers.get(
            "content-length",
            "0",
        )
        or 0
    )

    while len(body) < length:

        body += connection.recv(
            4096
        )

    parsed = None

    if length:

        parsed = json.loads(
            body[:length]
            .decode(
                "utf-8"
            )
        )

    return (
        method,
        path,
        parsed,
    )


def _send_json(
    connection,
    value,
    status="200 OK",
):
    """Send a JSON response to BiteFinder."""

    encoded = json.dumps(
        value
    ).encode(
        "utf-8"
    )

    response = (
        f"HTTP/1.1 {status}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(encoded)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode(
        "ascii"
    )

    connection.sendall(
        response + encoded
    )


def _response_for(
    fixture,
    method,
    path,
    body,
):
    """Return the fixed response for one external-service request."""

    with fixture["lock"]:

        fixture["calls"].append(
            (
                path,
                body,
            )
        )

    if (
        path in (
            "/nearby",
            "/text",
        )
        and fixture[
            "places_failure"
        ]
    ):
        raise RuntimeError(
            "simulated Places service failure"
        )

    if (
        path == "/chat/completions"
        and fixture[
            "openrouter_failure"
        ]
    ):
        raise RuntimeError(
            "simulated AI provider failure"
        )
    if method == "GET":

        return {
            "results": [
                {
                    "geometry": {
                        "location": {
                            "lat":
                                1.352,

                            "lng":
                                103.944,
                        }
                    }
                }
            ]
        }

    if path == "/chat/completions":

        system = (
            body["messages"][0]
            ["content"]
        )

        user = (
            body["messages"][1]
            ["content"]
        )

        if (
            "Interpret today's restaurant wish"
            in system
        ):

            content = json.dumps(
                json.loads(
                    user
                )["confirmed_choices"]
            )

        elif (
            "Extract one profile travel limit"
            in system
        ):

            content = json.dumps(
                {
                    "value":
                        10,

                    "unit":
                        "km",
                }
            )

        elif (
            "Rank every supplied restaurant candidate"
            in system
        ):

            data = json.loads(
                user
            )

            content = json.dumps(
                {
                    "recommendations": [
                        {
                            "id":
                                item["id"],

                            "reason_codes":
                                [],
                        }

                        for item
                        in data["candidates"]
                    ]
                }
            )

            if fixture[
                "invalid_brns_ai"
            ]:

                content = (
                    '{"recommendations": "invalid"}'
                )

        elif (
            "Review this English"
            in system
        ):

            corrected = user.replace(
                "wesaten",
                "western",
            )

            content = json.dumps(
                {
                    "status":
                        (
                            "corrected"
                            if corrected != user
                            else "ok"
                        ),

                    "text":
                        corrected,
                }
            )

        elif (
            "You assist BiteFinder profile collection"
            in system
        ):

            profile_input = (
                json.loads(
                    user
                )
            )

            field = (
                profile_input[
                    "current_field"
                ]
            )

            vocabulary = (
                (
                    "punggol",
                    "sengkang",
                    "nex",
                )

                if field == "location"

                else (
                    "western",
                    "italian",
                )
            )

            values = [
                item

                for item
                in vocabulary

                if item
                in profile_input[
                    "user_message"
                ]
            ]

            content = json.dumps(
                {
                    "intent":
                        "profile_update",

                    "profile_updates": {
                        field:
                            values,
                    },

                    "location_action":
                        "add",
                }
            )

        else:

            content = "{}"

        return {
            "choices": [
                {
                    "message": {
                        "content":
                            content,
                    }
                }
            ]
        }

    if path in (
        "/nearby",
        "/text",
    ):

        return places_response(
            fixture[
                "six_matches"
            ]
        )

    if path == "/matrix":
        if fixture[
            "matrix_no_route"
        ]:

            destinations = (
                body.get(
                    "destinations",
                    [],
                )
                if isinstance(
                    body,
                    dict,
                )
                else []
            )

            return [
                {
                    "destinationIndex":
                        index,

                    "condition":
                        "ROUTE_NOT_FOUND",
                }

                for index
                in range(
                    len(destinations)
                )
            ]
        matrix = [
            {
                "destinationIndex":
                    index,

                "condition":
                    "ROUTE_EXISTS",

                "duration":
                    duration,

                "distanceMeters":
                    distance,
            }

            for index, duration, distance
            in (
                (
                    0,
                    "600s",
                    900,
                ),

                (
                    1,
                    "3600s",
                    5000,
                ),
            )
        ]

        if fixture[
            "six_matches"
        ]:

            matrix[1] = {
                "destinationIndex":
                    1,

                "condition":
                    "ROUTE_EXISTS",

                "duration":
                    "900s",

                "distanceMeters":
                    1500,
            }

            matrix.extend(
                {
                    "destinationIndex":
                        index,

                    "condition":
                        "ROUTE_EXISTS",

                    "duration":
                        "600s",

                    "distanceMeters":
                        900,
                }

                for index
                in range(
                    2,
                    6,
                )
            )

        return matrix

    if path == "/route":

        if fixture[
            "route_unavailable"
        ]:

            return {
                "routes": []
            }

        return {
            "routes": [
                {
                    "duration":
                        "600s",

                    "distanceMeters":
                        900,

                    "legs": [
                        {
                            "steps": [
                                {
                                    "navigationInstruction": {
                                        "instructions":
                                            "Head north"
                                    }
                                }
                            ]
                        }
                    ],
                }
            ]
        }

    return {
        "error":
            "not found",
    }


def _handle_connection(
    fixture,
    connection,
):
    """Handle one local service request."""

    try:

        (
            method,
            path,
            body,
        ) = _read_request(
            connection
        )

        response = _response_for(
            fixture,
            method,
            path,
            body,
        )

        _send_json(
            connection,
            response,
        )

    except Exception as error:

        _send_json(
            connection,
            {
                "error":
                    str(error),
            },
            status=(
                "500 Internal Server Error"
            ),
        )

    finally:

        connection.close()


def _serve(fixture):
    """Serve fixed responses until the fixture is closed."""

    while not fixture[
        "stop"
    ].is_set():

        try:

            connection, _ = (
                fixture[
                    "socket"
                ].accept()
            )

        except socket.timeout:

            continue

        except OSError:

            break

        threading.Thread(
            target=
                _handle_connection,

            args=(
                fixture,
                connection,
            ),

            daemon=True,
        ).start()


def start_fixture_server():
    """Start the local fake AI and Maps service."""

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    )

    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1,
    )

    server.bind(
        (
            "127.0.0.1",
            0,
        )
    )

    server.listen()

    server.settimeout(
        0.2
    )

    fixture = {
    "calls":
        [],

    "lock":
        threading.Lock(),

    "invalid_brns_ai":
        False,

    "places_failure":
        False,

    "matrix_no_route":
        False,

    "route_unavailable":
        False,

    "openrouter_failure":
        False,

    "six_matches":
        False,

        "socket":
            server,

        "port":
            server.getsockname()[1],

        "stop":
            threading.Event(),
    }

    fixture["thread"] = (
        threading.Thread(
            target=
                _serve,

            args=(
                fixture,
            ),

            daemon=True,
        )
    )

    fixture[
        "thread"
    ].start()

    return fixture


def close_fixture_server(
    fixture,
):
    """Stop the local fake service."""

    fixture[
        "stop"
    ].set()

    try:

        fixture[
            "socket"
        ].close()

    except OSError:

        pass

    fixture[
        "thread"
    ].join(
        timeout=2
    )


def fixture_base(
    fixture,
):
    """Return the fake service base URL."""

    return (
        f"http://127.0.0.1:"
        f"{fixture['port']}"
    )


def fixture_paths(
    fixture,
):
    """Return all external paths called by BiteFinder."""

    with fixture["lock"]:

        return [
            path

            for path, _
            in fixture["calls"]
        ]


def fixture_bodies(
    fixture,
    path,
):
    """Return request bodies recorded for one endpoint."""

    with fixture["lock"]:

        return [
            body

            for name, body
            in fixture["calls"]

            if name == path
        ]


def clear_fixture_calls(
    fixture,
):
    """Clear recorded HTTP requests."""

    with fixture["lock"]:

        fixture[
            "calls"
        ].clear()


def create_blackbox_context():
    """Create an isolated BiteFinder copy for one black-box test."""

    temporary = (
        tempfile.TemporaryDirectory(
            prefix=
                "bitefinder-blackbox-"
        )
    )

    root = Path(
        temporary.name
    )

    for folder in (
        "BIS",
        "BRNS",
        "BRC",
        "shared",
    ):

        shutil.copytree(
            ROOT / folder,
            root / folder,

            ignore=
                shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "data",
                    "docs",
                    ".gitignore",
                ),
        )

    (
        root
        / "BIS/data"
    ).mkdir()

    (
        root
        / "BRNS/data"
    ).mkdir()

    (
        root
        / "BRC/data"
    ).mkdir()

    (
        root
        / "data"
    ).mkdir()

    (
        root
        / "BRNS/data/restaurants.json"
    ).write_text(
        "[]",
        encoding="utf-8",
    )

    fixture = (
        start_fixture_server()
    )

    base = fixture_base(
        fixture
    )

    env = (
        os.environ.copy()
    )

    for name in tuple(
        env
    ):

        if (
            name.startswith(
                (
                    "OPENROUTER_",
                    "GEMINI_",
                    "GROQ_",
                    "SMTP_",
                    "BITEFINDER_",
                )
            )

            or name in (
                "GOOGLE_MAPS_API_KEY",
                "AI_BYPASS",
                "USE_LIVE_GOOGLE",
                "DEBUG",
                "BRC_SERVICE_URL",
            )
        ):

            env.pop(
                name,
                None,
            )

    env.update(
        {
            "NO_COLOR":
                "1",

            "AI_BYPASS":
                "false",

            "SMTP_BYPASS":
                "true",

            "USE_LIVE_GOOGLE":
                "true",

            "GEMINI_API_KEY":
                "",

            "OPENROUTER_API_KEY":
                "fixture-key",

            "OPENROUTER_MODEL":
                "fixture-model",

            "OPENROUTER_BASE_URL":
                base,

            "GOOGLE_MAPS_API_KEY":
                "fixture-key",

            "BITEFINDER_OPENROUTER_URL":
                (
                    base
                    + "/chat/completions"
                ),

            "BITEFINDER_GEOCODE_URL":
                (
                    base
                    + "/geocode"
                ),

            "BITEFINDER_TEXT_SEARCH_URL":
                (
                    base
                    + "/text"
                ),

            "BITEFINDER_PLACES_URL":
                (
                    base
                    + "/nearby"
                ),

            "BITEFINDER_MATRIX_URL":
                (
                    base
                    + "/matrix"
                ),

            "BITEFINDER_ROUTES_URL":
                (
                    base
                    + "/route"
                ),

            "NO_PROXY":
                "127.0.0.1,localhost",
        }
    )

    return {
        "temporary":
            temporary,

        "root":
            root,

        "fixture":
            fixture,

        "env":
            env,

        "observed_output":
            [],
    }


def close_blackbox_context(
    context,
):
    """Clean up the temporary BiteFinder environment."""

    close_fixture_server(
        context[
            "fixture"
        ]
    )

    context[
        "temporary"
    ].cleanup()


def run_cli(
    context,
    application,
    answers,
):
    """Run BIS or BRNS exactly as a user-facing process."""

    content = (
        answers

        if isinstance(
            answers,
            str,
        )

        else (
            "\n".join(
                answers
            )
            + "\n"
        )
    )

    try:

        completed = (
            subprocess.run(
                [
                    sys.executable,

                    str(
                        context[
                            "root"
                        ]
                        / application
                        / "main.py"
                    ),
                ],

                input=
                    content,

                text=
                    True,

                stdout=
                    subprocess.PIPE,

                stderr=
                    subprocess.STDOUT,

                cwd=
                    context[
                        "root"
                    ],

                env=
                    context[
                        "env"
                    ],

                timeout=
                    10,

                check=
                    False,
            )
        )

    except subprocess.TimeoutExpired as error:

        raise AssertionError(
            f"{application} hung after 10 seconds: "
            f"{error.stdout!r}"
        ) from error

    if completed.returncode != 0:

        raise AssertionError(
            completed.stdout
        )

    return completed.stdout


def assert_shows(
    context,
    output,
    *snippets,
):
    """Check that the user-visible output contains expected text."""

    for snippet in snippets:

        if snippet not in output:

            raise AssertionError(
                f"Expected output to contain "
                f"{snippet!r}.\n\n"
                f"Actual output:\n"
                f"{output}"
            )

        line = next(
            line.strip()

            for line
            in output.splitlines()

            if snippet in line
        )

        position = (
            line.index(
                snippet
            )
        )

        start = max(
            0,
            position - 55,
        )

        end = min(
            len(line),
            position
            + len(snippet)
            + 55,
        )

        excerpt = (
            (
                "..."
                if start
                else ""
            )

            + line[
                start:end
            ]

            + (
                "..."
                if end < len(line)
                else ""
            )
        )

        excerpt = re.sub(
            r"[\w.+-]+@[\w.-]+",
            "<email>",
            excerpt,
        )

        if (
            excerpt
            not in context[
                "observed_output"
            ]
        ):

            context[
                "observed_output"
            ].append(
                excerpt
            )


def seed_complete_user(
    context,
):
    """Create one complete verified BIS user for black-box testing."""

    user_id = (
        "blackbox-user"
    )

    preferences = {
        "location": [
            "tampines"
        ],

        "max_distance_km":
            2.0,

        "max_travel_time_minutes":
            40.0,

        "budget_per_person":
            10.0,

        "dietary_requirements":
            [],

        "liked_cuisines":
            [],

        "disliked_cuisines":
            [],

        "other_preferences":
            [],
    }

    user = {
        "userID":
            user_id,

        "email":
            "tester@example.com",

        "email_verified":
            True,

        "username":
            "Tester",

        "preferences":
            preferences,
    }

    (
        context["root"]
        / "BIS/data/users.json"
    ).write_text(
        json.dumps(
            {
                user_id:
                    user,
            }
        ),

        encoding=
            "utf-8",
    )

    (
        context["root"]
        / "BIS/data/profile_state.json"
    ).write_text(
        json.dumps(
            {
                "search": {
                    user_id: {
                        "completed":
                            True,
                    }
                }
            }
        ),

        encoding=
            "utf-8",
    )

    return user


def history(
    context,
):
    """Read BRNS search history produced by a black-box test."""

    path = (
        context["root"]
        / "BRNS/data/search_history.json"
    )

    if not path.exists():

        return []

    return json.loads(
        path.read_text(
            encoding=
                "utf-8"
        )
    )


def run_blackbox_tests(
    test_functions,
    group_name,
):
    """Run one group of procedural black-box tests."""

    failures = []

    for test in test_functions:

        try:

            test()

        except Exception as error:

            failures.append(
                (
                    test.__name__,
                    error,
                )
            )

            print(
                f"\nFAILED: "
                f"{test.__name__}: "
                f"{error}"
            )

    show_summary(
        group_name,
        len(test_functions),
        failures,
    )

    if failures:

        raise SystemExit(1)
