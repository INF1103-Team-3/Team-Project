# WEB-OOP: independent CLI and web entry points

This branch starts from OOP commit `c16badc` and selectively reuses
`frontend/index.html` and nginx infrastructure from web reference commit
`e604f76`. It does not merge the old procedural BIS/BRNS/BRC implementation.

## Start BiteFinder

From the repository root:

```powershell
python BIS/main.py
# or
python main.py
```

Choose CLI, start the web interface, or exit. Enter chooses CLI. Automation can
use `python main.py --cli` or `python main.py --web`. Importing BIS or FastAPI
never prompts, starts containers, or opens a browser.

JSON CLI and web API dependencies are combined in `requirements.txt` (with dev and test tools in `requirements-dev.txt`):

```powershell
python -m pip install -r requirements.txt
```

On the host, web selection runs Docker Compose if necessary, waits for API/Mongo
readiness through nginx, and opens `http://localhost:8080`. Existing services are
reused. Docker/Compose must already be installed. If launching from inside a
container, it checks the running web service and displays the host URL; it does
not require a Docker socket or open a browser in the container.

Explicit first build/update:

```powershell
docker compose -f docker-compose.web.yml up -d --build --wait web
```

The stack contains nginx, the FastAPI API, MongoDB, and the unchanged independent
BRC service. MongoDB has a named volume and is not published on a host port.
The website is bound to host loopback port 8080. No accounts or database records
are automatically imported at startup.

Start the optional CLI against the same Mongo database (it does not require the
API/nginx services to be running):

```powershell
docker compose -f docker-compose.web.yml --profile cli up -d --build bis-brns
docker compose -f docker-compose.web.yml exec bis-brns python main.py --cli
```

The original `docker-compose.yml` remains the independent JSON CLI/BRC stack.
Use it with the explicit `-f docker-compose.yml` option when choosing that mode.

Stop the web stack without deleting stored data:

```powershell
docker compose -f docker-compose.web.yml --profile cli down
```

Closing a browser or exiting the launcher does not stop shared containers.

## Configuration

Use an untracked `.env` file or environment variables; never put credentials in
HTML, source, images, or this document. Existing provider, Google Maps, and SMTP
variable names remain supported. The web login flow requires working SMTP
configuration and always verifies an actual challenge; an `@example.com` address
or CLI SMTP bypass setting does not bypass web authentication.

| Variable | Purpose |
| --- | --- |
| `BITEFINDER_STORAGE` | `json` by default for standalone CLI; `mongo` in the integrated stack. Selection happens once, with no automatic fallback. |
| `MONGO_URI` | Mongo connection; Compose supplies its internal service address. |
| `MONGO_DATABASE` | Database name, default `bitefinder`. |
| `BRC_SERVICE_URL` | Existing BRC HTTP boundary; Compose supplies its internal service address. |
| `BITEFINDER_WEB_URL` | Host-facing browser URL, default `http://localhost:8080`. |
| `BITEFINDER_WEB_READY_URL` | Optional internal readiness address for the launcher. |

For API-only host development, install `requirements.txt`, set
`BITEFINDER_STORAGE=mongo`, configure reachable Mongo and BRC endpoints, then run
`uvicorn web_api:app --host 127.0.0.1 --port 8000 --workers 1`. The Compose/nginx
route remains the supported same-origin browser setup.

## How requests use OOP

- `BISLauncher` coordinates selection; `LauncherIO` handles the launch menu.
- `web_api.py`, `BIS/web_routes.py`, and `BIS/web_dependencies.py` contain HTTP
  registrations and dependency/lifecycle wiring. They do not contain ranking,
  password policy, direct record writes, or duplicated OTP implementations.
- BIS `WebIOManager` validates/formats HTTP interactions and delegates to
  `BISApplicationService`, `WebAuthService`, `FavoriteService`, and existing
  managers. Each production class and request model has its own subsystem file.
- Existing BIS Logic and Data operations are shared with the CLI. Search uses
  the existing BIS AI interpretation and Logic validation before BRNS.
- BRNS web IO delegates validation/gateway operations to the existing IO manager
  and presents progress without printing terminal prompts. Recommendation and
  navigation use the existing OOP workflow/services and HTTP BRC adapter.
- An initial `/api/search` request returns the interpreted request plus a
  `confirmation_token`. The existing page displays an explicit confirmation.
  Submitting that one-use token runs recommendation against the exact stored
  request. Canceling does not run ranking or save history. Tokens expire after
  ten minutes and are bound to their authenticated owner, or to their opaque
  bearer possession for a guest search.
- Result limits and ranking weights remain those of the OOP base. There is no
  per-request mutation of global limits or monkey-patching of AI log functions.
  AI deadlines/history identity use context-local state. Searches are initially
  serialized per API worker with a bounded wait; the supplied image runs one
  worker. Multiworker scaling needs further concurrency/load verification.
- `/api/active-model` truthfully describes the configured chain, not another
  user's in-flight model. The completed response includes the actual successful
  model reported by that request's BRNS pipeline.

The existing frontend design and routes are retained. Dynamic text is escaped
before insertion into HTML, and bookmark keys are passed as data rather than
interpolated JavaScript. This first integration
supports one origin and one supported cuisine. Multi-origin, multiple/custom
cuisine search splitting, and an increased result cap from the reference web
branch are intentionally not imported. Their controls are disabled or validated
with an explicit error; saved older selections must be revised before searching.

### Explicit API compatibility differences

The frontend now handles the search-confirmation response before rendering
results. Registration/login always require an OTP; existing CLI accounts are
not assigned web credentials merely by knowing an email address. Profile reads
and writes require the authenticated owner, rather than accepting a public user
ID. Bearer headers are supported; tokens in query strings are not accepted.
Database failures return 503 instead of empty success. Profile values use the
existing BIS validators; arbitrary numeric text is not silently rewritten into
new preference wording. These changes are covered by adapter tests and retain
the OOP business decisions underneath the website.

## Accounts and persistence

CLI and API use the same Mongo user IDs and strict domain user/preferences
schema when configured for Mongo. JSON and Mongo share `BaseUserStore` account
operations; the JSON error and serialization policies remain intact. Web
credentials are in a separate collection, never in profile responses or CLI
JSON. Sessions store token digests and have explicit expiry checks as well as
Mongo TTL cleanup. A CLI-only identity acquires a web password only after OTP
ownership proof. Existing web passwords retain their PBKDF2 format.

Mongo collections used here: `users`, `profile_state`, `web_credentials`,
`sessions`, `favorites`, `search_proposals`, `restaurants`, and `search_history`.
The profile-state record is keyed by section and user ID. Shared search history
uses request-local user identity; the CLI and API reload their records rather
than syncing whole JSON files. Existing anonymous JSON summaries remain
unattributed when imported; migration does not guess their owner.

Mongo outages produce explicit unavailable responses, without writing to JSON
or returning fabricated empty success. Corrupt/missing JSON continues to follow
the original JSON store policies. BRC's authoritative MUIS records and existing
geocode cache are not migrated.

## Explicit migration

Migration is optional and must target a database you select. Stop writes and
back up the selected database before applying. Default execution validates
approved JSON files and prints counts without connecting to Mongo:

```powershell
python migrate_to_mongo.py --database bitefinder --users BIS/data/users.json --states BIS/data/profile_state.json
```

Apply only after reviewing those counts and existing-record conflicts:

```powershell
python migrate_to_mongo.py --database bitefinder --confirm-database bitefinder --apply --users BIS/data/users.json --states BIS/data/profile_state.json
```

Optional `--restaurants` and `--history` accept the current JSON arrays. Inputs
must satisfy the current schemas; restaurant rows need unique Google place IDs.
The tool preserves IDs, uses stable history/state keys, refuses conflicting
records, and uses insert-only updates so reruns do not overwrite changes. It
imports current BIS JSON exports, not arbitrary dumps of the old procedural
web branch's Mongo schema. Old web collection exports need an explicit schema
conversion before import; old sessions are not carried across.

On standalone Mongo, the whole import is not a multi-collection transaction.
After a connection failure it may be partially applied; fix the cause and rerun
idempotently. Rollback uses the backup of the explicitly selected database;
never delete Docker volumes as a recovery shortcut. No migration was run on
real user data during development.

## Tests

Core/CLI tests remain independent of web dependencies:

```powershell
python tests/run_tests.py core
python tests/run_tests.py blackbox
python tests/run_tests.py integration
python tests/run_tests.py launcher
```

For web, dev, and repository contracts:

```powershell
python -m pip install -r requirements-dev.txt
python tests/run_tests.py web
```

The normal web suite uses `mongomock`, injected AI/SMTP/BRC collaborators, and
temporary files. It does not call paid/live providers, open a browser, start
Docker, or modify a real database. `MONGO_TEST_URI` enables one additional test
that uses and removes only a freshly generated `bitefinder_test_<uuid>` database.
A mock pass is not a real Mongo/container verification result.

Container checks:

```powershell
docker compose -f docker-compose.web.yml --profile test run --rm -e MONGO_TEST_URI=mongodb://mongodb:27017/ web-test
docker compose -f docker-compose.web.yml exec -T api python tests/web/smoke_stack.py
```

The original CI workflow retains its CLI/container suite. `web-tests.yml` adds
web-stack build/readiness, web contracts with isolated real Mongo, and an
nginx-to-API HTTP smoke path plus BRC health. These checks do not
execute paid searches. Actual browser rendering/manual form review remains a
separate check from the HTTP smoke script.

Nginx's response read timeout is 2100 seconds to allow the existing initial BRC
warm-up/client timeout; connection setup is bounded to five seconds. A first
halal search can therefore take longer than subsequent cached searches. Errors
and proxy failures remain failures, not successful empty results.
