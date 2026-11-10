"""Check the running nginx/API/Mongo/BRC stack without paid service calls."""
import json
import urllib.error
import urllib.request


def main():
    for url, expected in (("http://web/api/health", "mongodb"),
                          ("http://brc:8000/health", "status")):
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.load(response)
            assert response.status == 200 and payload[expected]
    with urllib.request.urlopen("http://web/", timeout=5) as response:
        assert b"BiteFinder" in response.read()
    with urllib.request.urlopen("http://web/api/cuisines", timeout=5) as response:
        assert "japanese" in json.load(response)["cuisines"]
    try:
        urllib.request.urlopen("http://web/api/auth/me", timeout=5)
    except urllib.error.HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError("Unauthenticated profile access must be rejected")
    print("PASS: nginx frontend, API routing, Mongo readiness, BRC and authentication boundary")


if __name__ == "__main__":
    main()
