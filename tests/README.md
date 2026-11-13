# BiteFinder Automated Tests

This directory is the single current BiteFinder test suite. It contains
teacher-facing function tests, integration tests, process-level black-box
tests, controlled service fixtures, and Docker deployment smoke tests.

Teacher-facing function/black-box tests print inputs, expectations and results;
unittest suites report individual cases and summaries. Normal groups use sample
AI and local fixtures; the explicitly selected `api` group makes live calls.

## Run in Docker

Build and start BiteFinder:

```bash
docker compose up -d --build
```

Run the standard CLI/container suite (`all` excludes `web` and live `api` tests):

```bash
docker compose exec bis-brns python tests/run_tests.py all
```

Run a smaller group by replacing `all` with one of the following names:

| Group | Coverage |
| --- | --- |
| `bis` | BIS validation, preferences, travel, cuisine, and structured AI interpretation |
| `brns` | BRNS eligibility, dietary rules, ranking, opening hours, missing-data handling, sorting, and AI fallback |
| `brc` | BRC MUIS halal verification and official restaurant outlet matching |
| `core` | `bis`, `brns`, `brc`, `oop`, and `launcher` test suites together; default group |
| `blackbox` | Real BIS and BRNS processes with controlled HTTP fixtures |
| `integration` | BIS-to-BRNS JSON contract and shared rules |
| `oop` | BIS/BRNS manager contracts, OOP classes, AI fallback, email verification, password stores, and sorting strategies |
| `launcher` | CLI/Web launcher menu and container readiness checks without Docker or browser IO |
| `web` | FastAPI API integration, storage/password/migration contracts, and optional live MongoDB (`MONGO_TEST_URI`) |
| `deployment` | Image contents, writable container paths, imports, BRC networking, and core tests inside Docker |
| `api` | Live API key connectivity (OpenRouter, Gemini, Groq, Google Maps), AI multi-tier fallback chains, and Google Maps services |
| `all` | Standard CLI/container groups: `bis`, `brns`, `brc`, `blackbox`, `integration`, `oop`, `launcher`, `deployment`; run `web` separately |

Examples:

```bash
docker compose exec bis-brns python tests/run_tests.py core
docker compose exec bis-brns python tests/run_tests.py brc
docker compose exec bis-brns python tests/run_tests.py blackbox
docker compose exec bis-brns python tests/run_tests.py integration

# Web + isolated live MongoDB tests and nginx -> api smoke check
docker compose --profile test run --rm -e MONGO_TEST_URI=mongodb://mongodb:27017/ web-test
docker compose exec -T api python tests/web/smoke_stack.py
```

## Color controls

Color is enabled automatically for an interactive terminal and disabled for
redirected output. Override detection with:

```bash
docker compose exec -e BITEFINDER_TEST_COLOR=always bis-brns python tests/run_tests.py all
docker compose exec -e BITEFINDER_TEST_COLOR=never bis-brns python tests/run_tests.py all
```

The standard `NO_COLOR` environment variable also disables color.

## Directory map

| Path | Purpose |
| --- | --- |
| `run_tests.py` | Group selection, safe environment, subprocess execution, and colored script summary |
| `reporting.py` | Colored case details and PASS/FAIL summaries |
| `bis/` | BIS function tests and fixed inputs |
| `brns/` | BRNS function tests and fixed restaurant/search inputs |
| `brc/` | BRC halal-verification and official outlet-matching tests |
| `blackbox/` | End-to-end CLI tests that run BIS and BRNS as real processes using controlled local HTTP services instead of live APIs |
| `integration/` | Tests that BIS output can be passed correctly into BRNS and that shared request fields and business rules remain consistent |
| `oop/` | Structural and behavioral OOP refactor contract tests |
| `launcher/` | Tests for `BISLauncher`, `LauncherIO`, and `WebInterfaceLauncher` |
| `web/` | FastAPI route, auth, chatbot, credential-store, and live MongoDB tests plus `smoke_stack.py` |
| `deployment/` | Smoke tests that verify the deployed Docker environment starts correctly and that the main services can import, communicate, and run basic checks |
| `API/` | Live validation tests for AI keys (OpenRouter, Gemini, Groq), multi-tier fallback cascades, and Google Maps Platform services |

## Isolation

The runner removes live AI and Google credentials from normal test subprocesses
and disables the Docker BRC adapter outside deployment tests. Black-box tests
use temporary project copies and local HTTP fixtures. They do not modify saved
accounts, restaurant data, or the shared application logs.

Deployment tests retain `BRC_SERVICE_URL` so they can verify that the BIS/BRNS
container reaches the BRC health endpoint over the Compose network.

## Host execution and dependencies

From the repository root, use Python 3.11 and install development requirements:

```powershell
python -m pip install -r requirements-dev.txt
python tests/run_tests.py core
python tests/run_tests.py blackbox
python tests/run_tests.py integration
python tests/run_tests.py web
```

`requirements-dev.txt` includes runtime requirements plus mongomock/httpx and
the development tools. The web-test Docker target installs it; the normal API
image installs runtime dependencies. `deployment` and the `all` group require
the Docker/BRC environment, so use the focused groups for host-only verification.

Web tests cover password length, CLI/web credentials, OTP/bypass paths, profile
ownership, multi-origin/multi-cuisine search, chatbot state/negation/onboarding,
proposal tokens, favorites/history, storage and error handling. Their mocked
composition test does not replace a browser test or a complete live search.

`MONGO_TEST_URI` enables an additional test using only a newly generated
`bitefinder_test_<uuid>` database and deleting that database afterward. Without
it, that case is skipped. The nginx/API/BRC smoke script requires the running
stack and verifies HTTP boundaries rather than paid AI/Maps behavior.

## CI, live checks and shutdown

`.github/workflows/tests.yml` runs the CLI/container suite;
`.github/workflows/web-tests.yml` builds the web stack, runs web tests with an
isolated real Mongo database, and checks HTTP smoke paths. A workflow definition
is not evidence that the current commit's CI run succeeded; inspect GitHub's run.

Live `api` checks are opt-in, retain service credentials and can consume quota
or write cache entries. Read [API/README.md](API/README.md) and use an appropriate
test environment rather than assuming they have normal-suite isolation.

```powershell
docker compose --profile "*" down
```

This stops all profiles and retains named data volumes. CI teardown uses `-v`
for its disposable stack; do not copy that flag into normal saved-data shutdown.
