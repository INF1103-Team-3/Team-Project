# BiteFinder Automated Tests

This directory is the single current BiteFinder test suite. It contains
teacher-facing function tests, integration tests, process-level black-box
tests, controlled service fixtures, and Docker deployment smoke tests.

Tests print the function or workflow, purpose, input, expected output, actual
output, and a clear colored PASS or FAIL result. They use hardcoded AI replies
and local service fixtures rather than spending live API quota.

## Run in Docker

Build and start BiteFinder:

```bash
docker compose up -d --build
```

Run the complete suite:

```bash
docker compose exec bis-brns python tests/run_tests.py all
```

Run a smaller group by replacing `all` with one of the following names:

| Group | Coverage |
| --- | --- |
| `bis` | BIS validation, preferences, travel, cuisine, and structured AI interpretation |
| `brns` | BRNS eligibility, dietary rules, ranking, opening hours, missing-data handling, sorting, and AI fallback |
| `brc` | BRC MUIS halal verification and official restaurant outlet matching |
| `core` | BIS,BRNS and BRC function tests together; this is the default group |
| `blackbox` | Real BIS and BRNS processes with controlled HTTP fixtures |
| `integration` | BIS-to-BRNS JSON contract and shared rules |
| `deployment` | Image contents, writable volumes, imports, BRC networking, and core tests inside Docker |
| `api` | Live API key connectivity (OpenRouter, Gemini, Groq, Google Maps), AI multi-tier fallback chains, and Google Maps services |
| `all` | Every group above |

Examples:

```bash
docker compose exec bis-brns python tests/run_tests.py core
docker compose exec bis-brns python tests/run_tests.py brc
docker compose exec bis-brns python tests/run_tests.py blackbox
docker compose exec bis-brns python tests/run_tests.py integration
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
| `deployment/` | Smoke tests that verify the deployed Docker environment starts correctly and that the main services can import, communicate, and run basic checks |
| `API/` | Live validation tests for AI keys (OpenRouter, Gemini, Groq), multi-tier fallback cascades, and Google Maps Platform services |

## Isolation

The runner removes live AI and Google credentials from normal test subprocesses
and disables the Docker BRC adapter outside deployment tests. Black-box tests
use temporary project copies and local HTTP fixtures. They do not modify saved
accounts, restaurant data, or the shared application logs.

Deployment tests retain `BRC_SERVICE_URL` so they can verify that the BIS/BRNS
container reaches the BRC health endpoint over the Compose network.
