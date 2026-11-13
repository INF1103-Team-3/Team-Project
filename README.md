# BiteFinder

BiteFinder is an object-oriented restaurant discovery system for Singapore that
provides both an interactive command-line application and a web interface backed
by MongoDB. It combines saved preferences, today's request, restaurant facts,
route information, AI-assisted ranking, and official MUIS halal verification in
one guided workflow.

The system is designed for students, staff, office workers, visitors,
budget-conscious diners, Halal or vegetarian diners, public-transport users,
and anyone who wants recommendations supported by clear facts instead of a
single unexplained result.

## Features

- Create or resume an account with a password and six-digit email verification.
- Share account credentials, profiles, favorites, geocode cache, restaurant facts,
  and search history between the CLI and web UI through MongoDB.
- Save locations, budget, travel limits, dietary requirements, liked and
  disliked cuisines, and reusable special requests.
- Enter locations as Singapore postal codes, addresses, landmarks, or latitude
  and longitude.
- Search using walking, driving, or public transit distance and journey-time
  limits, including optional traffic-aware driving time.
- Describe requests naturally, including soft preferences such as `4.5 stars`
  and confirmed hard constraints such as `only Korean` or `at least 4.5 stars`.
- Use BIS AI to interpret free text while protecting confirmed user choices.
- Use Google Places and Routes for restaurant facts, opening hours, ratings,
  review counts, coordinates, distances, durations, and directions.
- Use BRNS AI to rank only the candidates found for the current search.
- Check halal candidates against cleaned MUIS records through BRC.
- Clearly distinguish official MUIS verification from unofficial Google halal
  indications.
- Show matches, alternatives, exclusions, cautions, and grounded reasons.
- Sort results by Google rating or travel distance.
- Display routes or email a selected Google Maps link to the verified account.
- Repeat the same search while preferring restaurants not previously returned.
- Retain an offline restaurant fallback while still requiring BRNS AI ranking.
- Share geocode caching and traceable operational logs across the application.

## How it works

```text
User
  -> BIS I/O: account, profile, commands, and today's choices
  -> BIS AI: interpret free text and produce structured search data
  -> BIS Logic: validate values and protect confirmed choices
  -> BIS Data: save the profile and serialize search JSON
  -> BRNS I/O: validate JSON and gather restaurant and route facts
  -> BRNS AI: rank current candidate IDs with controlled reason codes
  -> BRC when halal is requested: check candidates against MUIS data
  -> BRNS Logic: classify matches, alternatives, and exclusions
  -> BRNS Data: save restaurant facts and the validated search summary
  -> BIS and BRNS I/O: show results and post-search actions
```

**See [ProjectFlow.md](ProjectFlow.md) for the complete project workflow.** It
is the main flow reference for account setup, profile creation, BIS search,
BRNS recommendation and navigation, BRC halal verification, failures, result
actions, shared services, and Docker deployment.

The three applications have separate responsibilities:

- **BIS — BiteFinder Interaction System:** owns accounts, email verification,
  profiles, natural-language commands, search collection, and user interaction.
- **BRNS — BiteFinder Recommendation and Navigation System:** validates the BIS
  request, retrieves restaurant and route facts, ranks candidates, applies
  search rules, and prepares routes.
- **BRC — BiteFinder Restaurant Checker:** scrapes MUIS listings, builds the
  cleaned official halal database, caches cuisine tags, and checks restaurant
  objects or arrays against that database.

Each application keeps the four manager interfaces while BIS and BRNS use
object-oriented session, recommendation, validation, sorting and persistence
implementations behind compatibility façades:

| Manager | Responsibility |
| --- | --- |
| `io_manager.py` | Validate external input and present user-facing output |
| `ai_manager.py` | Build prompts, call providers, parse JSON, and validate AI output |
| `logic_manager.py` | Apply domain rules, scores, classifications, and routes |
| `data_manager.py` | Save, load, and query JSON records |

`main.py` coordinates the managers and decides whether processing continues or
returns safely to the user after a failure.

Production BIS, BRNS, and BRC classes live one per module inside functional
subpackages (`io/`, `ai/`, `logic/`, `data/`, `services/`) under
`BIS/classes/`, `BRNS/classes/`, and `BRC/classes/`.

## Detailed documentation

Each major project folder has its own README with its responsibilities,
workflow, files, data contracts, configuration, failure behavior, and relevant
test commands:

| Area | Detailed guide |
| --- | --- |
| BIS account, profile, and search interaction | [BIS/README.md](BIS/README.md) |
| BRNS recommendation, routing, and result processing | [BRNS/README.md](BRNS/README.md) |
| BRC MUIS database and halal verification | [BRC/README.md](BRC/README.md) |
| Web API ASGI app, routes, and composition boundary | [http_gateway/README.md](http_gateway/README.md) |
| Browser UI static frontend assets | [frontend/README.md](frontend/README.md) |
| Function, integration, black-box, and deployment tests | [tests/README.md](tests/README.md) |
| Static and live function visualizations | [project_overview/README.md](project_overview/README.md) |
| Common infrastructure (logging, geocoding, UI, storage, nginx) | [common/README.md](common/README.md) |
| End-to-end data states, AI payloads, and file storage | [DataFlowDiagram.md](DataFlowDiagram.md) |

Start with this root README for setup and operation. Use
[ProjectFlow.md](ProjectFlow.md) to follow the whole application from the user
through BIS, BRNS, and BRC. Use [DataFlowDiagram.md](DataFlowDiagram.md) to see
how user and provider data becomes validated AI payloads and stored JSON. Open
the relevant folder README when implementing, testing, or troubleshooting one
subsystem.

The current project statement is in
[ProjectInitialDetails.md](ProjectInitialDetails.md).

## Repository structure

```text
BIS/                         account, profile, search-input, and email workflow
  README.md                  detailed BIS workflow and manager documentation
  main.py                    BIS compatibility façade, CLI/web launcher, and wiring
  runtime.py                 web runtime composition boundary (`build_web_runtime`)
  classes/                   nested by layer (`io/`, `ai/`, `logic/`, `data/`, `services/`) with contracts, fallback, validators, stores, and models
  io_manager.py              CLI input and display boundary
  ai_manager.py              BIS interpretation and model fallback chain
  logic_manager.py           profile and search-request rules
  data_manager.py            user, state, credential, and search persistence
  sources/                   prompts and profile schema
  support/                   configuration and SMTP verification façades
    email_verification/classes/  `contracts/`, `delivery/`, `challenge/`, `service/`

BRNS/                        restaurant recommendation and navigation
  README.md                  detailed BRNS search, ranking, and route guide
  main.py                    BRNS compatibility façade and gated internal CLI (`--internal`)
  runtime.py                 headless `BRNSService` gateway wiring for BIS CLI and web
  classes/                   nested by layer (`io/`, `ai/`, `logic/`, `data/`, `services/`) with adapters, gateways, fallback, evaluation, sorting, and stores
  io_manager.py              BIS JSON, Google Places, Routes, and internal result display
  ai_manager.py              candidate ranking and provider fallback chain
  logic_manager.py           matching, alternatives, scores, and opening hours
  data_manager.py            restaurant facts and search history

BRC/                         MUIS halal database and outlet checker
  README.md                  detailed BRC build, HTTP service, and check guide
  main.py                    database-build and restaurant-check workflows (gated internal CLI)
  scraper.py                 raw MUIS and OneMap collection
  classes/                   nested by layer (`io/`, `ai/`, `logic/`, `data/`, `services/`) with HTTP server/client, geocoding, scraping, AI fallback, models, and caches
  io_manager.py              scenario selection and JSON validation
  ai_manager.py              cuisine tagging and ambiguous outlet matching
  logic_manager.py           deterministic certification checks
  data_manager.py            raw, cleaned, cached, and checked JSON records

http_gateway/                FastAPI ASGI app, routes, and composition boundary
  README.md                  web backend API and runtime dependency guide
  main.py                    FastAPI ASGI entrypoint (`uvicorn http_gateway.main:app`)
  routes.py                  `/api/*` FastAPI route registrations (BIS IO only)
  dependencies.py            delegates `build_runtime()` to `BIS.runtime.build_web_runtime()`

frontend/                    static browser UI served by nginx
  README.md                  frontend ES-module architecture and nginx proxy notes
  index.html                 single-page UI entry point
  css/                       compiled Tailwind and custom styles
  js/                        API client, auth, chat, filter, map, results modules

common/                      geocode cache, model discovery, UI, storage, nginx
  README.md                  common-infrastructure contracts and design rules
  recommendation_ui.py       shared terminal recommendation and route cards
  storage_dependencies.py    shared lazy `MongoConnection` factory
  nginx.conf                 nginx reverse-proxy configuration
  migrate_to_mongo.py        optional JSON-to-MongoDB import CLI
tests/                       function, integration, black-box, web, and Docker tests
  README.md                  test groups, commands, isolation, and color controls
project_overview/            function-graph generators and local graph output
  README.md                  static and live visualization instructions
.github/workflows/tests.yml  host and Docker CI checks
Dockerfile                   `brc`, `bis-brns`, `api`, `web`, and `web-test` targets
docker-compose.yml           MongoDB, mongo-express, BRC, API, nginx web, CLI stack
requirements.txt             runtime CLI, web API, and MongoDB dependencies
requirements-dev.txt         test, lint, and visualization development tools
main.py                      repository-root BIS launcher
ProjectFlow.md               complete project and decision flow
DataFlowDiagram.md           data transformations, AI payloads, and file stores
ProjectInitialDetails.md     problem, users, AI use, and business rules
```

## Requirements

The application is designed to run through Docker Compose. The host requires:

- Docker Desktop or Docker Engine.
- Docker Compose 2.24 or newer.
- At least one supported AI provider key for BIS and BRNS.
- A Gemini key when building or using BRC AI workflows.
- A Google Maps Platform key for live Places, geocoding, and routes.
- Gmail or another SMTP account when email verification is enabled.

Python and application packages are installed in the images. A host Python
installation is not required to run BiteFinder or its automated tests.

## Configure the environment

Create the local environment file on macOS or Linux:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Open `.env` and configure the services needed for your run. The full list and
comments are in [`.env.example`](.env.example).

| Setting | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | OpenRouter model access for BIS, BRNS, and BRC |
| `GROQ_API_KEY` | Optional Groq models appended to each application's fallback chain |
| `GEMINI_API_KEY` | Gemini models used independently by BIS, BRNS, and BRC |
| `GOOGLE_MAPS_API_KEY` | Geocoding, Places, route matrices, and directions |
| `USE_LIVE_GOOGLE=true` | Use current Google restaurant and route data |
| `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | Email verification and Maps-link delivery |
| `SMTP_BYPASS=true` | Skip SMTP delivery during local CLI testing (never bypasses web OTP auth) |
| `AI_BYPASS=true` | Test BIS profile interaction without AI or BRNS search |
| `BITEFINDER_STORAGE` | `mongo` (default in Compose and `run_cli()`) or `json` |
| `MONGO_URI` | MongoDB connection string (Compose supplies `mongodb://mongodb:27017/`) |
| `MONGO_DATABASE` | MongoDB database name (default `bitefinder`) |
| `DEBUG=true` | Mirror shared operational logs to the terminal |

`.env` is excluded from Git and the Docker build context. Never commit API keys
or SMTP credentials.

## Run MongoDB, the Web Server, and the CLI with Docker Compose

[docker-compose.yml](docker-compose.yml) orchestrates the full BiteFinder stack on
the `bitefinder-web` bridge network:

| Service | Port on host | Role |
| --- | --- | --- |
| `mongodb` | `127.0.0.1:27017` | MongoDB 7.0 database storing accounts, credentials, state, favorites, restaurants, search history, and geocode cache (`mongo-data` volume) |
| `mongo-express` (`dev` profile) | `http://localhost:8081` | Optional web admin UI to inspect MongoDB collections |
| `brc` | internal `8000` | Always-on MUIS halal verification HTTP service (`brc-data` volume) |
| `api` | internal `8000` | FastAPI backend (`uvicorn http_gateway.main:app`) wired strictly through BIS (`BIS.runtime`) to MongoDB and BRC |
| `web` | `http://localhost:8080` | nginx webserver serving `frontend/` and proxying `/api/` -> `api:8000` (`/docs` and `/openapi.json` disabled by default) |
| `bis-brns` | — | Interactive CLI & test container backed by the same MongoDB database |
| `web-test` (`test` profile) | — | Ephemeral container runner for `tests/run_tests.py web` |

### Start MongoDB and the web stack

Build and start MongoDB, BRC, FastAPI (`api`), nginx (`web`),
and the CLI container (`bis-brns`) (add `--profile dev` to include `mongo-express`):

```powershell
docker compose up -d --build
```

Or wait specifically until the webserver is healthy at `http://localhost:8080`:

```powershell
docker compose up -d --build --wait web
```

Then open in your browser:
- **BiteFinder Web UI:** `http://localhost:8080`
- **API health check:** `http://localhost:8080/api/health` (`{"status":"ok","mongodb":true}`)
- **Mongo Express DB UI (when started with `--profile dev`):** `http://localhost:8081`

### Launch interactively via `main.py`

If Python dependencies are installed locally (`pip install -r requirements.txt`),
the root launcher can start/reuse the Docker Compose web stack or run CLI directly:

```powershell
python main.py          # interactive menu: 1 = CLI, 2 = Web, 0 = Exit
python main.py --web    # ensure MongoDB/BRC/API/web are running and open http://localhost:8080
python main.py --cli    # start CLI directly (defaults to MongoDB on 127.0.0.1:27017)
```

### Run the CLI inside Docker (sharing MongoDB with the web UI)

```powershell
docker compose exec bis-brns python main.py --cli
```

Do not add `-T` to interactive CLI commands because it disables the TTY used for
prompts and ANSI colors. Exiting the CLI leaves `mongodb`, `web`, and other
background services running.

### Run the FastAPI webserver on the host (optional local development)

When `mongodb` (and optionally `brc`) are running via Docker Compose (`mongodb`
is published on `127.0.0.1:27017`):

```powershell
python -m pip install -r requirements.txt
$env:BITEFINDER_STORAGE = "mongo"
$env:MONGO_URI = "mongodb://127.0.0.1:27017/"
$env:MONGO_DATABASE = "bitefinder"
uvicorn http_gateway.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Inspect MongoDB collections directly using `mongosh` inside the `mongodb` container:

```powershell
docker compose exec mongodb mongosh --quiet --eval "db.getSiblingDB('bitefinder').getCollectionNames()"
```

Check container status at any time with:

```powershell
docker compose ps
```

### Test Docker networking

Check external internet access from the `bis-brns` or `brc` containers:

```powershell
docker compose exec bis-brns python -c "import urllib.request; r=urllib.request.urlopen('https://www.google.com/generate_204', timeout=10); print('Internet working, HTTP', r.status)"
docker compose exec brc python -c "import urllib.request; r=urllib.request.urlopen('https://www.google.com/generate_204', timeout=10); print('Internet working, HTTP', r.status)"
```

Verify internal service reachability across `bitefinder-web`:

```powershell
docker compose exec bis-brns python -c "import urllib.request; print(urllib.request.urlopen('http://brc:8000/health', timeout=5).read().decode())"
docker compose exec bis-brns python -c "import urllib.request; print(urllib.request.urlopen('http://api:8000/api/health', timeout=5).read().decode())"
```

Successful external checks print `Internet working, HTTP 204`. Service health
checks return `{"status": "ok"}` (BRC) and `{"status":"ok","mongodb":true}` (API).

Inspect container logs and shared BiteFinder trace logs with:

```powershell
docker compose logs --tail=100 brc
docker compose logs --tail=100 api
docker compose exec bis-brns tail -n 100 logs/bitefinder.log
```

If a transferred Windows checkout reports an entrypoint `bad interpreter` or
`exec format` error, rebuild after confirming Git uses LF endings:

```powershell
git ls-files --eol Dockerfile docker-compose.yml
docker compose down
docker compose up -d --build
```

Both files should show `w/lf`. The repository enforces LF through
`.gitattributes`, and the Docker build removes stray carriage returns from the
generated entrypoint.

### First halal search

If the cleaned MUIS database does not exist, BRC prepares it automatically when
started or on the first halal verification request. Completed batches are saved
in the `brc-data` volume so interrupted builds can resume without retagging.

To build or refresh the BRC database manually:

```powershell
docker compose exec brc python -m BRC.main --internal
```

### Container data, named volumes, and shutdown

- `mongo-data`: persistent MongoDB database backing (`users`, `web_credentials`,
  `profile_state`, `favorites`, `search_proposals`, `sessions`, `restaurants`,
  `search_history`, `geocode_cache`).
- `brc-data`: MUIS snapshots, cleaned halal database, and AI cuisine/check caches.
- `application-data`: container-local scratch directories and operational logs (`logs/bitefinder.log`).

Stop containers while keeping all MongoDB and BRC volumes:

```powershell
docker compose down
```

Delete containers **and** all saved MongoDB/BRC volumes (destructive reset):

```powershell
docker compose down -v
```

BRC listens on `http://brc:8000` over `bitefinder-web` and is not published to the host.
The FastAPI backend listens on `http://api:8000` internally and is exposed to the browser via nginx at `http://localhost:8080/api/`.

## Work inside the application container

Open a shell in the already running BIS/BRNS container:

```powershell
docker compose exec bis-brns sh
```

The shell starts in `/app`. From there, choose the operation needed:

```bash
# Start the complete BiteFinder CLI.
python main.py

# Run the complete automated test suite.
python tests/run_tests.py all

# Follow the BIS and BRNS application log. Press Ctrl+C to stop following it.
tail -f logs/bitefinder.log

# Leave the container shell without stopping the containers.
exit
```

Opening a shell is optional. Every command can also be executed directly with
`docker compose exec`, as shown in the following sections.

## Use the CLI

After signup or resume, incomplete profiles continue from the first unanswered
field. A complete profile enters the command loop.

| Command | Action |
| --- | --- |
| `/help` or `/help [command]` | Show commands or detailed help |
| `/profile` | Show the saved account profile |
| `/search` | Collect and confirm today's restaurant search |
| `/edit` | Choose a profile field to replace |
| `/add-location` | Add a saved location |
| `/remove-location` | Remove a saved location while retaining at least one |
| `/reset` | Clear profile preferences while retaining the account |
| `/password` | Change your account password |
| `/color off` or `/color on` | Save the user's terminal-color preference |
| `/logout` | Return to the account menu |
| `/quit` or `/exit` | Save and close BiteFinder |

Natural messages such as `search for a restaurant`, `show my profile`, or
`color off` can be interpreted as the equivalent supported command. `/help`
and color commands also work while another prompt is active.

The search summary shows location, travel limit, specific cuisine, budget,
dietary restrictions, disliked cuisines, and special requests. Pressing Enter
confirms the summary. After results, the menu can show details, sort, route,
email a Maps link, reveal alternatives, change today's choices, repeat the same
search, or return to commands.

## Run the tests

Normal tests use hardcoded AI replies, temporary project copies, and local
fixture servers. They do not call live AI, Google, or SMTP services. The runner
disables the BRC HTTP adapter except for deployment tests that intentionally
check communication between the containers.

Run every test:

```powershell
docker compose exec bis-brns python tests/run_tests.py all
```

The runner colors headings, expected and actual values, PASS results, and FAIL
results in an interactive terminal. Set `BITEFINDER_TEST_COLOR=always` or
`never` with `docker compose exec -e` to override automatic detection; see the
[test guide](tests/README.md) for examples.

Run only the BIS and BRNS function tests:

```powershell
docker compose exec bis-brns python tests/run_tests.py core
```

Run all process-level black-box tests:

```powershell
docker compose exec bis-brns python tests/run_tests.py blackbox
```

Run the BIS-to-BRNS integration tests, web/MongoDB tests, or Docker checks:

```powershell
docker compose exec bis-brns python tests/run_tests.py integration
docker compose exec bis-brns python tests/run_tests.py deployment
docker compose --profile test run --rm -e MONGO_TEST_URI=mongodb://mongodb:27017/ web-test
docker compose exec -T api python tests/web/smoke_stack.py
```

For local host testing outside Docker, install `pip install -r requirements-dev.txt`.

GitHub Actions builds the application images and runs the core, black-box,
deployment, and web/Mongo test suites on push and pull request.

## Saved data and logs

| Store / Path | Purpose |
| --- | --- |
| MongoDB `bitefinder.users` | Accounts and profile preferences |
| MongoDB `bitefinder.web_credentials` | Password hashes synced across CLI and Web |
| MongoDB `bitefinder.profile_state` | Email verification, first-search, and display state |
| MongoDB `bitefinder.favorites` | User bookmarked restaurants |
| MongoDB `bitefinder.search_proposals` | One-use search confirmation tokens |
| MongoDB `bitefinder.sessions` | Web bearer auth sessions |
| MongoDB `bitefinder.restaurants` | Saved restaurant facts and offline catalog |
| MongoDB `bitefinder.search_history` | Validated per-user search summaries |
| MongoDB `bitefinder.geocode_cache` | Shared normalized geocode aliases |
| `BRC/data/muis_establishments.json` | Raw MUIS snapshot (`brc-data` volume) |
| `BRC/data/halal_restaurants.json` | Cleaned official halal database (`brc-data` volume) |
| `BRC/data/cuisine_tags_cache.json` | Resumable cuisine tags (`brc-data` volume) |
| `BRC/data/checked_restaurants_cache.json` | Previous restaurant checks (`brc-data` volume) |
| `logs/bitefinder.log` | Shared BIS, BRNS, and BRC operational log |

Docker persists MongoDB collections in `mongo-data`, BRC files in `brc-data`,
and container logs in `application-data` / `brc-data`. Workspace `data/`
directories are not stored on the host.

Each search receives a trace ID. Logs record manager stages, provider attempts,
candidate counts, rejected reason codes, and error types without logging API
keys or raw provider responses.

Follow the application logs from the host:

```powershell
# BIS and BRNS file log
docker compose exec bis-brns tail -n 100 -f logs/bitefinder.log

# FastAPI API container output
docker compose logs -f api

# BRC container output and service errors
docker compose logs -f brc
```

## Function visualizations

Function visualization is optional development tooling rather than part of the
deployed application image. Setup and generation instructions are kept in
[project_overview/README.md](project_overview/README.md). Generated PNGs and
live-session call data remain below `project_overview/function_graphs/`.
