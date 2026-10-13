# BiteFinder Test Suite

This directory contains unit, integration, and black box tests for BIS, BRNS,
BRC, shared persistence, and email verification. The suite checks both valid
and invalid input and keeps external providers under controlled local fixtures
so results are repeatable.

## Run the tests

Install the application and development dependencies, then run the complete
suite from the project root:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Run the user friendly black box report:

```bash
python -m tests.blackbox_support
```

Run one file when working on a subsystem:

```bash
python -m unittest tests.test_brc_checker -v
python tests/test_blackbox_bis.py
python tests/test_blackbox_brns.py
python tests/test_blackbox_bis_to_brns.py
```

## Test layers

| Layer | What it proves | Provider behavior |
| --- | --- | --- |
| Unit | Individual manager rules, parsing, scoring, validation, and persistence. | Functions are supplied controlled inputs; no live provider is required. |
| Integration | Data passes across subsystem boundaries with the required JSON contract and call order. | External boundaries are replaced with deterministic test doubles. |
| Black box | A user can drive the real command line process and receive useful responses for correct and incorrect input. | Temporary local HTTP fixtures stand in for remote APIs. |
| Architecture compliance | The repository still follows the procedural four manager constraints and contains deployable/testable artifacts. | Static inspection only. |

## Test files

| File | Coverage |
| --- | --- |
| `test_unit_bis_logic.py` | BIS validation, profile choices, command interpretation, hard constraints, and search request preparation. |
| `test_unit_brns_ai.py` | BRNS model prompts, envelopes, fact grounding, model fallback, and response validation. |
| `test_unit_brns_logic.py` | Restaurant eligibility, ranking, price interpretation, ratings, travel limits, opening hours, and result explanations. |
| `test_unit_data_manager.py` | Account/profile persistence and safe data update behavior. |
| `test_bis_brns_integration.py` | The structured request and result contract between BIS and BRNS. |
| `test_brc_checker.py` | MUIS database cleanup, cuisine caching, restaurant verification, and BRC integration. |
| `test_email_verification.py` | Verification code generation, resend limits, attempt limits, expiry, SMTP behavior, and bypass configuration. |
| `test_blackbox_bis.py` | BIS command line conversations, profile creation, saved defaults, corrections, cancellation, and validation messages. |
| `test_blackbox_brns.py` | Standalone BRNS JSON input, search output, errors, and result structure. |
| `test_blackbox_bis_to_brns.py` | Full user input through BIS, the BRNS call, and returned restaurant presentation. |
| `blackbox_support.py` | Isolated fixture workspace, local HTTP services, subprocess runner, and friendly report entry point. |
| `friendly_test_report.py` | Colored scenario descriptions with expected and observed behavior and external call order. |
| `inf1103_compliance_check.py` | Static checks for the four manager architecture, procedural production code, entry points, Dockerfile, and requirements. |

## Friendly black box output

The friendly runner describes each scenario in user terms. For every test it
shows:

- the feature and behavior under test;
- the command or program called;
- representative input supplied to the process;
- the expected response or state;
- observed output excerpts; and
- the sequence of simulated external calls.

Color follows terminal support. Force or disable it with:

```bash
BITEFINDER_TEST_COLOR=always python -m tests.blackbox_support
BITEFINDER_TEST_COLOR=never python -m tests.blackbox_support
```

The standard `NO_COLOR` environment variable also disables color.

## Isolation and safety

Black box tests copy the necessary application files into temporary
directories. They strip real credentials, use temporary account and restaurant
data, and point network clients at a local fixture server. No test should send
real email, consume production AI quota, overwrite the working restaurant
database, or modify a user's saved profile.

Subprocesses have a finite timeout so a missing prompt response or stalled
workflow fails with diagnostic output instead of hanging indefinitely.

When adding a test that writes data, use the provided fixture paths or patch
the module path before the write. Never depend on test execution order or on a
file produced by another test.

## Writing new tests

Choose the narrowest layer that proves the requirement:

1. Use a unit test for a manager rule or parser.
2. Use an integration test for a contract between managers or subsystems.
3. Use a black box test when prompts, commands, process behavior, or user
   visible recovery is part of the requirement.

Give each test a descriptive docstring. For black box cases, add friendly
metadata so the report can state the input, expected output, observed output,
and calls made. Include a successful case, the important invalid inputs, and a
recovery case where the user can correct the problem.

## Architecture compliance check

Run the static course requirements check directly with:

```bash
python tests/inf1103_compliance_check.py
```

It verifies that production code in BIS, BRNS, BRC, and `shared` remains
procedural, input/output stays in IO managers, every manager exposes the
required operations, and deployment files are present. Dockerfiles and test
scripts may define classes because their framework or fixture responsibilities
are outside the production manager restriction.

## Docker and continuous integration

Run the same suite in the application image:

```bash
docker build -t bitefinder .
docker run --rm --entrypoint python bitefinder -m unittest discover -s tests -v
```

`.github/workflows/tests.yml` runs tests on pushes and pull requests using
Python 3.11, builds the Docker image, and repeats the suite inside the image.
This catches missing packaged files and dependency differences in addition to
normal host failures.

See [ProjectFlow.md](../ProjectFlow.md) for the runtime boundaries these tests
exercise.

