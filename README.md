# BiteFinder

BiteFinder is a procedural command-line application that helps people choose
restaurants in Singapore when several practical requirements must be considered
together. It combines saved preferences, today's request, restaurant facts,
route information, AI-assisted ranking, and official MUIS halal verification
in one guided workflow.

The system is designed for students, staff, office workers, visitors,
budget-conscious diners, Halal or vegetarian diners, public-transport users,
and anyone who wants recommendations supported by clear facts instead of a
single unexplained result.

## Features

- Create or resume an account using six-digit email verification.
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

Each application follows the procedural manager pattern:

| Manager | Responsibility |
| --- | --- |
| `io_manager.py` | Validate external input and present user-facing output |
| `ai_manager.py` | Build prompts, call providers, parse JSON, and validate AI output |
| `logic_manager.py` | Apply domain rules, scores, classifications, and routes |
| `data_manager.py` | Save, load, and query JSON records |

`main.py` coordinates the managers and decides whether processing continues or
returns safely to the user after a failure.

## Detailed documentation

Each major project folder has its own README with its responsibilities,
workflow, files, data contracts, configuration, failure behavior, and relevant
test commands:

| Area | Detailed guide |
| --- | --- |
| BIS account, profile, and search interaction | [BIS/README.md](BIS/README.md) |
| BRNS recommendation, routing, and result processing | [BRNS/README.md](BRNS/README.md) |
| BRC MUIS database and halal verification | [BRC/README.md](BRC/README.md) |
| Unit, integration, black box, and compliance tests | [tests/README.md](tests/README.md) |
| Static and live function visualizations | [project_overview/README.md](project_overview/README.md) |
| Shared logging, geocoding, terminal UI, and model discovery | [shared/README.md](shared/README.md) |
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
  main.py                    BIS orchestration and result-action loop
  io_manager.py              CLI input and display boundary
  ai_manager.py              BIS interpretation and model fallback chain
  logic_manager.py           profile and search-request rules
  data_manager.py            user, state, and search JSON persistence
  sources/                   prompts and profile schema
  support/                   configuration and SMTP verification

BRNS/                        restaurant recommendation and navigation
  README.md                  detailed BRNS search, ranking, and route guide
  main.py                    BRNS search, BRC handoff, sorting, and routing
  io_manager.py              BIS JSON, Google Places, Routes, and result display
  ai_manager.py              candidate ranking and provider fallback chain
  logic_manager.py           matching, alternatives, scores, and opening hours
  data_manager.py            restaurant facts and search history
  data/restaurants.json      saved facts and offline restaurant fallback

BRC/                         MUIS halal database and outlet checker
  README.md                  detailed BRC build and verification guide
  main.py                    database-build and restaurant-check workflows
  scraper.py                 raw MUIS and OneMap collection
  io_manager.py              scenario selection and JSON validation
  ai_manager.py              cuisine tagging and ambiguous outlet matching
  logic_manager.py           deterministic certification checks
  data_manager.py            raw, cleaned, cached, and checked JSON records

shared/                      geocode cache, model discovery, terminal UI, logs
  README.md                  shared-service contracts and design rules
tests/                       unit, integration, black box, email, and BRC tests
  README.md                  test layers, commands, isolation, and CI behavior
project_overview/            function-graph generators and local graph output
  README.md                  static and live visualization instructions
.github/workflows/tests.yml  host and Docker CI checks
Dockerfile                   `brc` and `bis-brns` image targets
docker-compose.yml           two-container deployment and persistent volumes
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
| `OPENROUTER_API_KEY` | OpenRouter model access for BIS and BRNS |
| `GROQ_API_KEY` | Optional Groq models appended to each application's fallback chain |
| `GEMINI_API_KEY` | Gemini fallback for BIS and BRNS, and the BRC provider |
| `GOOGLE_MAPS_API_KEY` | Geocoding, Places, route matrices, and directions |
| `USE_LIVE_GOOGLE=true` | Use current Google restaurant and route data |
| `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | Email verification and Maps-link delivery |
| `SMTP_BYPASS=true` | Skip SMTP delivery during local testing |
| `AI_BYPASS=true` | Test BIS profile interaction without AI or BRNS search |
| `DEBUG=true` | Mirror shared operational logs to the terminal |

`.env` is excluded from Git and the Docker build context. Never commit API keys
or SMTP credentials.

## Run the complete project with Docker Compose

The commands shown at the top of `docker-compose.yml` are the canonical way to
run BiteFinder:

```bash
docker compose up -d --build
docker compose exec bis-brns python main.py
```

The first command builds and starts two containers on `bitefinder-net`:

| Container | Runtime role |
| --- | --- |
| `bitefinder-brc` | Runs the BRC halal-checking HTTP service continuously and reports its health to Compose. |
| `bitefinder-bis-brns` | Remains running with an interactive terminal available; it contains BIS and BRNS. |

Compose waits for BRC to become healthy before starting the BIS/BRNS container.
The second command opens the root BiteFinder launcher inside that running
container. When the user exits BiteFinder, the container stays available, so
the command can be run again without rebuilding it.

Check container state at any time with:

```bash
docker compose ps
```

### First halal search

If the cleaned MUIS database does not exist, BRC prepares it automatically when
the first halal verification is requested. That first check may take longer
because BRC may need to scrape MUIS data and process uncached cuisine tags in
paced AI batches. Completed batches are saved in the
`bitefinder-brc-data` volume, so an interrupted or rate-limited build can
resume without retagging completed restaurants.

To build or refresh the BRC database manually, open its menu and choose option
`1`:

```bash
docker compose exec brc python -m BRC.main
```

### Container data and shutdown

`bitefinder-brc-data` preserves the raw and cleaned MUIS data, cuisine tags,
and restaurant-check caches. `bitefinder-bis-brns-data` preserves accounts,
profile state, restaurant facts, search history, the shared geocode cache, and
logs.

Stop both containers while keeping those named volumes:

```bash
docker compose down
```

Delete the containers and all saved named-volume data only when a complete
reset is intended:

```bash
docker compose down -v
```

BRNS sends halal checks to `http://brc:8000` over the Compose network. The BRC
port is available to the BIS/BRNS container but is not published to the host.
Both containers can still reach configured AI, Google, MUIS, OneMap, and SMTP
services on the internet.

## Work inside the application container

Open a shell in the already running BIS/BRNS container:

```bash
docker compose exec bis-brns sh
```

The shell starts in `/app`. From there, choose the operation needed:

```bash
# Start the complete BiteFinder CLI.
python main.py

# Run the complete automated test suite without the Docker BRC adapter.
env -u BRC_SERVICE_URL python -m unittest discover -s tests -v

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

Normal tests use temporary project copies and local fixture servers. They do
not call live AI, Google, SMTP, or the running BRC service. Unsetting
`BRC_SERVICE_URL` disables the Compose HTTP adapter during tests so the suite
can exercise the BRC source modules directly.

Run every test:

```bash
docker compose exec bis-brns env -u BRC_SERVICE_URL \
  python -m unittest discover -s tests -v
```

Run the readable BIS, BRNS, and combined black box report:

```bash
docker compose exec bis-brns env -u BRC_SERVICE_URL \
  python -m tests.blackbox_support
```

Run one black box boundary:

```bash
docker compose exec bis-brns env -u BRC_SERVICE_URL \
  python tests/test_blackbox_bis.py
docker compose exec bis-brns env -u BRC_SERVICE_URL \
  python tests/test_blackbox_brns.py
docker compose exec bis-brns env -u BRC_SERVICE_URL \
  python tests/test_blackbox_bis_to_brns.py
```

Run email tests or the INF1103 source check:

```bash
docker compose exec bis-brns env -u BRC_SERVICE_URL \
  python tests/test_email_verification.py
docker compose exec bis-brns env -u BRC_SERVICE_URL \
  python tests/inf1103_compliance_check.py
```

GitHub Actions builds the application image and runs the complete suite inside
that image for every push and pull request.

## Saved data and logs

| Path | Purpose |
| --- | --- |
| `BIS/data/users.json` | Accounts and profile preferences |
| `BIS/data/profile_state.json` | Email, search, and display state |
| `BRNS/data/restaurants.json` | Saved restaurant facts and offline fallback |
| `BRNS/data/search_history.json` | Validated search summaries |
| `BRC/data/muis_establishments.json` | Raw MUIS snapshot |
| `BRC/data/halal_restaurants.json` | Cleaned official halal database |
| `BRC/data/cuisine_tags_cache.json` | Resumable cuisine tags |
| `BRC/data/checked_restaurants_cache.json` | Previous restaurant checks |
| `data/geocode_cache.json` | Shared successful geocoding results |
| `logs/bitefinder.log` | Shared BIS, BRNS, and BRC operational log |

Docker stores these runtime files under the `bis-brns-data` and `brc-data`
named volumes. Local runtime files and secrets are ignored by Git.

Each search receives a trace ID. Logs record manager stages, provider attempts,
candidate counts, rejected reason codes, and error types without logging API
keys or raw provider responses.

Follow the application logs from the host:

```bash
# BIS and BRNS file log
docker compose exec bis-brns tail -f logs/bitefinder.log

# BRC file log
docker compose exec brc tail -f logs/bitefinder.log

# BRC container output and service errors
docker compose logs -f brc
```

## Function visualizations

Function visualization is optional development tooling rather than part of the
deployed application image. Setup and generation instructions are kept in
[project_overview/README.md](project_overview/README.md). Generated PNGs and
live-session call data remain below `project_overview/function_graphs/`.
