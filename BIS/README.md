# BIS — BiteFinder Interaction System

BIS owns user interaction, accounts, email verification, profiles, chat and
search requests. Both CLI and web use BIS; recommendation and navigation are
accessed through the headless `BRNSService` boundary. See the
[root README](../README.md), [project flow](../ProjectFlow.md), and
[data flow](../DataFlowDiagram.md) for deployment and end-to-end context.

## Entry points

From the repository root:

```powershell
python main.py
python BIS/main.py
python main.py --cli
python main.py --web
```

Without a flag, `BISLauncher` offers CLI, Web, or Exit; Enter chooses CLI.
The web launcher starts/reuses Compose on the host and attempts to open
`http://localhost:8080`. Inside a container it checks readiness and displays
the host URL. Importing the launcher does not start either interface.

Docker is the documented full-stack setup:

```powershell
docker compose up -d --build
docker compose exec bis-brns python main.py --cli
```

The interactive CLI defaults to MongoDB unless `BITEFINDER_STORAGE` is already
set. The web runtime requires MongoDB. Explicit JSON mode is available for
CLI/testing, but is not an automatic database-outage fallback.

## Code ownership

| Path | Responsibility |
| --- | --- |
| `main.py` | Launcher and CLI manager/session composition; compatibility entry points |
| `runtime.py` | Web composition root, Mongo repositories, BIS web services, and BRNS gateway wiring |
| `io_manager.py`, `classes/io/cli/io_manager.py` | Terminal collection, validation, confirmation and presentation |
| `classes/io/web/web_io_manager.py` | HTTP payload/result formatting and authentication delegation |
| `classes/io/web/models/` | Pydantic auth, preference and search request schemas |
| `classes/io/contracts/` | Focused session, search and web IO capabilities |
| `ai_manager.py`, `classes/ai/` | Prompt/response handling, provider contracts, clients and fallback routing |
| `logic_manager.py`, `classes/logic/` | Profile/search decisions, midpoint and cuisine-merge policy, validation and password hashing |
| `data_manager.py`, `classes/data/` | Account, credential and state stores, JSON/Mongo implementations, serialization and optional sync/import tools |
| `classes/services/cli/` | `InteractionSession`, `BISSearchWorkflow` and result interaction |
| `classes/services/web/` | `BISApplicationService`, `BISChatbotService`, authentication, favorites and runtime lifecycle |
| `classes/services/launcher/` | Mode selection and web-stack startup |
| `sources/` | Canonical profile vocabulary, value validation, questions and prompt text |
| `support/email_verification/classes/` | Separate challenge, SMTP delivery, service and capability contracts |

The four manager modules remain identifiable. Supporting classes are grouped
by layer, one production class per file; compatibility modules still contain
some implementation helpers as well as delegates.

## Accounts and verification

Signup collects username, email and a confirmed password of **8–128 characters**.
Login/resume verifies the stored password. Existing accounts without credentials
use enrollment. `PasswordHasher` stores PBKDF2-SHA256 salt/hash data separately
from the domain user record; web profile responses never include credentials.

With `SMTP_BYPASS=false`, authentication sends a six-digit challenge with
expiry, resend cooldown and a failed-attempt window. Verification consumes the
challenge. Web authentication then returns a bearer token backed by an
expiring session digest.

**`SMTP_BYPASS=true` bypasses delivery and OTP in both CLI and web.** The web
shortcut can complete legacy credential enrollment and mark the account
verified. It is for testing; it does not prove ownership of an email inbox.
Do not describe it as a CLI-only setting or an email-domain exception.

## Profiles and CLI commands

A domain user has `userID`, email, verification flag, username and nested
`preferences`. Preference fields are location, maximum distance/time, budget,
dietary requirements, liked cuisines, disliked cuisines and other preferences.
An incomplete field can be `null`; a completed list can be empty where allowed.
Liked/disliked conflicts are rejected. Profile distance/time estimates use
20 walking minutes per kilometre; live navigation belongs to BRNS.

| Command | Action |
| --- | --- |
| `/help` / `/help [command]` | Show help without leaving the active prompt |
| `/profile` | Display saved profile |
| `/search` | Collect and confirm today's search |
| `/edit` | Replace a profile field |
| `/add-location` / `/remove-location` | Change saved locations |
| `/reset` | Clear preferences while retaining identity |
| `/password` | Change the account password |
| `/color on` / `/color off` | Save terminal color preference |
| `/logout` | Return to account selection |
| `/quit` / `/exit` | Save and close |

Recognized natural-language commands can map to these allowed actions. CLI
profile free text may be interpreted by AI; typed/local validation paths also
exist. Declined corrections are not applied. EOF and Ctrl+C close cleanly.

## CLI search

`BISSearchWorkflow` collects one origin, travel mode, one active time/distance
limit, driving traffic preference when applicable, one cuisine or `none`,
budget, dietary restrictions, dislikes and special wishes. It delegates AI
interpretation, confirmed-choice validation, preference recording and results
interaction to the corresponding collaborators.

The ten-field search JSON is validated again by BRNS. Results can be inspected,
sorted, routed, emailed as a Maps link, refined, or repeated with previous
results supplied. `AI_BYPASS=true` is a CLI test path that skips BRNS search.

## Web search, chat and saved actions

The browser enters through `http_gateway/`, whose handlers use BIS web IO.
`BISApplicationService` calls the injected BRNS gateway, rather than reaching
into BRC or recommendation persistence directly.

- The form supports multiple Singapore origins; Logic computes the midpoint.
- Multiple cuisines trigger separate BRNS calls and Logic-owned merge/deduplication.
  Custom cuisine terms are handled through the web search preparation policy.
- Direct `/api/search` is the default. `confirm_only=true` returns a stored,
  expiring proposal token. Submitting `confirmation_token` consumes that saved
  request once. The normal form currently submits a direct search.
- `/api/chat` supports onboarding, incremental filter edits, missing-field
  questions and explicit search confirmation. On AI failure it can use
  deterministic parsing; not every chat turn calls an AI provider.
- Profile form saves and supported chat profile saves are explicit actions.
  Guest users can search/chat but must authenticate for owned profile writes,
  favorites and history deletion.
- Web results include input origins, cuisine breakdown, matches, alternatives,
  exclusions and model metadata. Favorites and history are scoped by user ID.

## Persistence and configuration

Normal CLI/web accounts and credentials share MongoDB `users` and
`web_credentials`; web repositories also manage sessions, proposals and
favorites. Shared storage does not mean every CLI menu exposes every web action.
JSON CLI mode uses `BIS/data/users.json`, `profile_state.json` and
`credentials.json`. `CliUserFileSync` is optional and is not injected by the
current CLI/web roots; do not assume automatic JSON-to-Mongo mirroring.

Configuration comes from the root environment. Relevant names include
`BITEFINDER_STORAGE`, `MONGO_URI`, `MONGO_DATABASE`, provider keys,
`OPENROUTER_API_KEYS`, `OPENROUTER_API_KEYS_FILE`, `OPENROUTER_MODEL`,
`OPENROUTER_BASE_URL`, `OPENROUTER_TIMEOUT_SECONDS`, `GOOGLE_MAPS_API_KEY`,
`SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
`SMTP_FROM_EMAIL`, `SMTP_BYPASS`, `VERIFICATION_ATTEMPT_RESET_MINUTES`,
`AI_BYPASS` and `DEBUG`. See [the root template](../.env.example).

Mongo connection errors are explicit; no alternate store is selected silently.
Invalid BIS JSON account data is retained and writes are blocked. Geocoding
uses `LocationGateway` and `common.geocode_cache`. Operational messages use the
container's `logs/bitefinder.log`; trace IDs connect downstream requests.

## Tests

```powershell
docker compose exec bis-brns python tests/run_tests.py bis
docker compose exec bis-brns python tests/run_tests.py blackbox
docker compose exec bis-brns python tests/run_tests.py integration
docker compose exec bis-brns python tests/run_tests.py oop
docker compose exec bis-brns python tests/run_tests.py launcher
docker compose --profile test run --rm web-test
```

Normal tests use temporary data and controlled AI/Maps/SMTP collaborators.
The web suite covers auth, passwords, profile ownership, chat, multi-origin and
multi-cuisine search, proposals, favorites, history and error paths. See
[tests/README.md](../tests/README.md) for host prerequisites and live Mongo checks.
