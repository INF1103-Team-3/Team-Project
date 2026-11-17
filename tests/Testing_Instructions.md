# BiteFinder Testing Instructions

Run every command from the repository root, which contains `Dockerfile` and
`tests/`. These instructions assess the current BIS, BRNS and BRC application,
including its four-manager architecture and CLI/web behavior.

## 1. Recommended assessor run: offline tests inside Docker

Prerequisites: Docker Engine/Desktop with Linux containers. Building the image
needs internet access to download the base image and Python dependencies.
Running the tests does **not** need an AI provider account, API key, Google Maps,
SMTP, MongoDB server or an already running BiteFinder stack. No `.env` file is
required for this standalone assessment image.

```bash
docker build --target web-test --build-arg SEED_ACCOUNTS=no -t bitefinder-assessment .
docker run --rm --network none bitefinder-assessment python tests/run_tests.py offline
```

The existing `web-test` Docker target contains runtime and development packages,
including `httpx` and `mongomock`. Do not use the smaller runtime image for the
complete mocked web/storage suite: it does not install all test dependencies.

`--network none` disables external networking while retaining loopback for the
controlled local HTTP fixtures. `.dockerignore` excludes the real `.env` from
the image; do not add `--env-file`, credentials, a secrets mount or an application
data volume to this command. The container is disposable, uses its own data
locations and runs as the image's non-root application user. It does not attach
the normal application's saved MongoDB/BRC volumes.

The `offline` group runs these **13 test scripts**:

| Scripts | Coverage |
| --- | --- |
| `tests/bis/test_bis.py` | Profile/search input, travel limits, immutable updates, cuisine and Singapore-location validation using sample AI data |
| `tests/brns/test_brns.py` | Eligibility, scores, ranking, opening hours, dietary/halal rules, travel limits, repeat-search exclusion and provider fallback |
| `tests/brc/test_brc.py` | Official outlet verification, provider fallback, persistent dataset freshness and non-blocking background refresh |
| `tests/oop/test_oop_refactor.py` | Real manager/helper classes, four-manager workflow order, provider/strategy substitution, route/photo contracts and JSON persistence |
| `tests/refactor/test_cleanup.py` | Shared preference-review policy, AI failure behavior, corrupt persistence, atomic-write failures and injected BRC refresh lifecycle |
| `tests/refactor/test_access_levels.py` | Subsystem access boundaries, serialization lock release, public capabilities and encapsulated collaborators |
| `tests/launcher/test_launcher.py` | CLI/web selection, invalid/EOF input, readiness and failure paths without starting Docker/browser services |
| Three scripts in `tests/blackbox/` | Real CLI processes against temporary project copies and controlled local HTTP services |
| `tests/integration/test_bis_brns_integration.py` | The actual BIS-to-BRNS request contract and shared business rules |
| `tests/web/test_web_api.py` | FastAPI/BIS class integration, authentication, profiles, chat, search, routing, favorites and current web features with mocks |
| `tests/web/test_storage_contracts.py` | JSON/Mongo store substitution, missing/invalid records, passwords and migration validation using temporary JSON and mongomock |

The runner executes each script, prints PASS/FAIL, and returns a nonzero exit
code if **any** script fails. Function-test scripts display inputs, expected
outputs and actual results; unittest scripts display case names and summaries.
`Passed scripts: 13` and `Failed scripts: 0` indicate a successful Python run.
Individual case counts can increase as tests are added.

### Frontend feature tests inside Docker

The Python image does not include Node. Run the browser-module contracts in a
separate Node 22 container, from the same repository root:

```bash
docker run --rm --network none --mount "type=bind,source=${PWD},target=/work,readonly" --workdir /work node:22-alpine node --test tests/frontend/test_refresh.mjs
```

The `${PWD}` form works in Bash and PowerShell. Docker must be allowed to access
the checkout directory. Pull `node:22-alpine` first if the image is not cached:

```bash
docker pull node:22-alpine
```

These tests import the real ES modules and their current cache-versioned URLs,
share the application's state object, provide a minimal DOM, and mock `fetch`.
They cover duplicate removal, the 200-venue seen-list cap, exhaustion/reset,
provider-error recovery, cancellation restoring previous results/controls,
and browser location parsing. A successful run reports `# fail 0` and exits 0.
They test behavior, not browser layout or actual map-provider rendering.

## 2. Coverage against the testing requirements

| Requirement | Concrete evidence in this suite |
| --- | --- |
| Automated core logic and important class behavior | The `offline` group exercises actual managers, validators, policies, workflows, routers, stores and sorters. `test_bis_search_workflow_orders_io_ai_logic_data` and `test_brns_workflow_orders_io_ai_logic_data` check the required workflow order. |
| No live AI API required | Sample responses in `bis/sample_inputs.py` and `brns/sample_inputs.py`; injected providers, patched HTTP calls, mock AI objects and loopback service fixtures. The Docker command above also denies external networking. Production AI behavior is not replaced with hardcoded success values. |
| Business rules, scoring and routing | BRNS match/alternative/reject cases cover budget, travel, cuisine, minimum rating, opening facts and official halal evidence. `test_outcome_policy_preserves_scoring_order_and_estimate_rejection` asserts the score and reason order; route-gateway tests check matrices, polyline/geometry and unknown route facts. |
| AI response validation and failures | Duplicate/missing/invalid recommendation IDs, invalid JSON, malformed provider output, fallback to another provider and complete provider failure. AI proposals cannot change confirmed choices or fabricate official certification. |
| Relevant new features | Web tests cover multi-origin/multi-cuisine merging, chat onboarding/negation, custom-cuisine validation, location enforcement, strict refresh/exhaustion, proposal tokens, user isolation and photo caching. BRC tests exercise seven-day freshness and refresh without blocking checks. Node tests cover client search cancellation. |
| Missing/corrupt persistence | BIS JSON/Mongo read-failure parity and `last_error`; BRNS corrupt history retained, wrong catalog shape rejected and failed atomic replacement cleaned up; BRC missing/malformed/wrong-shape raw/cleaned snapshots rejected and retained. Tests use temporary paths. |
| Docker execution and assessor instructions | The existing `web-test` image packages the Python suite; sections 1 and 4 distinguish isolated regressions from deployed-stack checks. CI defines container CLI/web jobs, but their existence is not proof of a successful current run. |

Mocks supply external evidence, not the business outcome being asserted. For
example, a stub supplies candidate facts or AI IDs/reasons, then the real Logic
Manager decides eligibility and score. `mongomock` exercises real repository
methods without requiring a MongoDB server. Black-box tests launch the actual
CLI entry points instead of substituting an entire successful application.

## 3. Focused runs and host execution

To investigate a failed Python group using the assessment image:

```bash
docker run --rm --network none bitefinder-assessment python tests/run_tests.py core
docker run --rm --network none bitefinder-assessment python tests/run_tests.py brns
docker run --rm --network none bitefinder-assessment python tests/run_tests.py brc
docker run --rm --network none bitefinder-assessment python tests/run_tests.py oop
docker run --rm --network none bitefinder-assessment python tests/run_tests.py web
```

`web` additionally includes the optional live-Mongo test, which reports a skip
when `MONGO_TEST_URI` is unset. `offline` excludes that optional script entirely.

For host development, install Python 3.11 dependencies and Node 22 or later:

```bash
python -m pip install -r requirements-dev.txt
python tests/run_tests.py offline
node --test tests/frontend/test_refresh.mjs
```

The runner supplies project import paths and removes live provider/Maps keys
from ordinary test subprocess environments. Application configuration can still
read a local `.env`, so the standalone Docker run is the recommended way to
verify external-network isolation. The live `api` group intentionally retains
credentials and is **not** part of this assessment run.

Use `tests/run_tests.py` as the authoritative entry point. Some tests use explicit
`TESTS` registries and a custom teacher-facing reporter; unittest discovery alone
is not a substitute for running those scripts. With no group the runner selects
`core`, which is smaller than `offline`. `--help` lists all available groups.

## 4. Optional deployed-stack and real MongoDB checks

These are additional integration checks, **not required to execute core logic
without live AI**. They need Docker Compose 2.24+, running services and the
normal local setup described in [the root README](../README.md). The API/CLI
Compose services bind-mount the root `.env`; follow that setup without
replacing an existing environment file or using production credentials/data.

```bash
docker compose config -q
docker compose up -d --build --wait web bis-brns
docker compose exec -T bis-brns python tests/run_tests.py all
docker compose --profile test run --rm -e MONGO_TEST_URI=mongodb://mongodb:27017/ web-test
docker compose exec -T api python tests/web/smoke_stack.py
```

- `all` includes CLI/container deployment smoke tests and requires the BRC
  health endpoint. It excludes web tests and the opt-in live AI/Maps group;
  its name does not mean every test file in the repository.
- `web-test` runs the web group. With `MONGO_TEST_URI` it also creates and
  deletes a uniquely named `bitefinder_test_<uuid>` database to verify real
  persistence across clients. It does not reuse the application's user database.
- `smoke_stack.py` checks nginx delivery, BIS API routing, Mongo readiness, BRC
  health and unauthorized access. It does not make a paid recommendation call.
- Runtime BRC automatic warm-up can collect MUIS/OneMap data independently of
  these tests. To avoid that optional background network work in an assessment
  stack, set `BRC_AUTO_WARM=0` in its test environment before starting it.
- Docker/registry/package downloads need internet. None of the offline business
  tests requires live AI or Maps connectivity.

Stop the full stack while retaining saved named volumes:

```bash
docker compose --profile "*" down
```

Do not add `-v` to normal shutdown; it deletes saved named volumes. The isolated
`docker run --rm` commands in section 1 do not start this Compose stack.

## 5. Results, troubleshooting and verification status

Record the command, source revision/working-tree state, exit code and summary
when submitting assessment evidence. Keep failures visible; a skipped live
integration test is not a passing real-backend test.

| Symptom | Action |
| --- | --- |
| `ModuleNotFoundError` on the host | Install `requirements-dev.txt` in the Python environment actually running the command; preferably use the assessment image. |
| `mongomock` or `httpx` missing in a container | Build/run the `web-test` target, not only the `api` runtime target. |
| `all` fails to reach BRC | It is a deployment group. Start the Compose stack or use `offline` for isolated business/class tests. |
| Node tests use stale frontend state | Keep imports following `main.js`; do not hardcode an obsolete cache-version query that creates another state singleton. |
| `MONGO_TEST_URI` case skipped | Expected without a real Mongo service. Use section 4 to verify that extra requirement. |
| Image contains old code | Rebuild after source changes; these images copy source during the build. |
| Docker is unavailable | Host tests can verify logic, but do not claim the Docker requirement is proven. Run section 1 on an assessor/developer Docker host or obtain the current CI result. |

Audit snapshot, 17 November 2026: the offline Python group and Node suite are
checked against the current refactored working tree: **219 Python cases passed
in 13 scripts, and all 8 Node cases passed**. Python style checks passed.
The suites include the
shared `PreferenceReviewService`/`PreferenceValidationPolicy`, injected
`DatabaseRefreshService` and current frontend module graph. Explicitly registered
function tests are all included in their registries.

Docker was not installed in the audit environment. The Dockerfile, dependencies,
Compose wiring and CI commands were inspected, but this document **does not
claim a successful image build or container execution for this working tree**.
Run section 1 (and section 4 for deployment) to supply that evidence. Visual
browser behavior, production API accuracy, actual email delivery and complete
line/branch coverage are also not established by these offline tests.
