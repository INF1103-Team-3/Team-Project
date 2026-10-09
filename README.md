# BiteFinder

BiteFinder contains two connected Python command-line applications and a
folder reserved for future work:

| Application | Purpose | Run from the repository root |
| --- | --- | --- |
| **BIS** — BiteFinder Interaction System | Sign up or resume an account and save food preferences | `python3 BIS/main.py` |
| **BRNS** — BiteFinder Recommendation & Navigation System | Find, rank, and route to restaurants | `python3 BRNS/main.py` |
| **BRC** — BiteFinder Restaurant Checker | Reserved for team members to add restaurant checking functionality | No command yet |

BIS sends today's confirmed search as JSON to BRNS. The
[original project scope](ProjectInitialDetails.md) describes the intended
combined system, including allergy handling. The current CLIs do not implement
every feature in that scope.

## Install

Use Python 3.9 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.
The root `requirements.txt` covers both applications. The optional
`requirements-dev.txt` adds `pycodestyle` and the function graph tools.

To generate the function call PNGs on Windows, run these commands from the
repository root in PowerShell or Command Prompt:

```text
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe visualise_functions.py
```

Use the same Python executable for the install and the script. Pillow is
installed as `Pillow` but imported as `PIL`. The PNGs appear in
`function_graphs/`: `bis_to_brns.png` is the grouped manager flow,
`bis_to_brns_functions.png` shows the reachable function calls, and
`all_functions.png` covers every application function. `project_workflow.png`
shows the halal scraper and separate BRC checker alongside BIS, BRNS, and
their shared cache and log. Add `--trace` to run
BIS and capture a live session graph. The grouped flow shows
BIS IO → AI → Logic → Data (JSON) → BRNS IO → AI → Logic → Data.

Both applications read the same `.env` file at the repository root. If you do
not have one yet, copy `.env.example` to `.env` and edit the settings you need:

```bash
cp .env.example .env
```

Keep `.env` and API keys private. The root `.env` is ignored by Git.

## BIS: profiles and preferences

To use BIS locally without AI requests or verification emails, set
`AI_BYPASS=true` and `SMTP_BYPASS=true` in the root `.env`, then run:

```bash
python3 BIS/main.py
```

Choose **Sign up** to create an account with an email and username, or
**Resume by email** to continue an existing profile. Usernames accept 1–50
characters. BIS asks one preference question at a time and saves each account's
answers locally. When a profile becomes complete, BIS starts `/search` once.
An already complete profile starts it on the next resume if it has not run yet.
The command collects today's location and search limits, then asks one
optional question about what you want. Enter skips extra wishes; saved
special requests can be chosen by number or `all`, and a new request can be
entered in English. BIS checks new text and asks before using any AI wording
correction. BIS AI then proposes a search request. BIS Logic protects
confirmed choices and validates the proposal; you confirm it before BIS Data
serializes the request to JSON. Confirmed new special requests are saved for
future searches. BRNS receives that JSON for restaurant results.
AI may add wishes from your description but cannot remove selected preferences.
With `AI_BYPASS=true`, BIS shows the choices without calling AI or BRNS; this
is the chatbot test mode.

### BIS commands

| Command | What it does |
| --- | --- |
| `/help` | Show available commands |
| `/help [command]` | Explain a command, its accepted values, and examples |
| `/profile` | Show the saved profile |
| `/search` | Choose today's location and limits, describe your wishes, then confirm the interpreted search |
| `/edit` | Show how to change an answer |
| `/add-location` | Add areas to saved locations |
| `/remove-location` | Remove saved areas; at least one must remain |
| `/reset` | Clear preferences, keeping the account and username |
| `/logout` | Save and return to the account menu |
| `/quit` or `/exit` | Save and close the chatbot |

For example, type `/edit budget`, then enter `10` for a new budget in SGD.
Use `/help edit` for all editable fields and accepted answers. Editing replaces
an answer; `/add-location` keeps existing areas.

Dietary requirements are halal, vegetarian, both, or none. Cuisine answers use the
accepted list in [`BIS/sources/profile_schema.py`](BIS/sources/profile_schema.py);
spelling suggestions require confirmation. Travel accepts distance or time,
using **1 km ≈ 20 minutes of walking**. Both values are saved as an estimate,
not a calculated route. Other preferences are stored as a list; enter items
separated by commas, or `none` for an empty list.

For `/search`, BIS confirms your current location before asking the other
questions. Enter a Singapore postal code, address, landmark, or latitude and
longitude. Cached locations and coordinates work without a Maps key; uncached
addresses need `GOOGLE_MAPS_API_KEY` in the root `.env`. Walking searches offer
your saved walking distance as the default. Driving searches ask for a new
distance. Live search also requires a free-text description and confirmation
of the interpreted request. Search choices do not change your saved profile.
Use `/help search` for the full sequence.

### BIS AI and email settings

Signup uses fixed prompts and Python validation. AI can interpret preference
answers and is required for live `/search`; saved updates and search requests
must still pass validation. To enable AI, set these
values in the root `.env`:

```dotenv
AI_BYPASS=false
OPENROUTER_MODEL=your-model-slug
OPENROUTER_API_KEYS='["first-key", "second-key"]'
```

Keys rotate in order, including failed requests, and rotation resets on
launch. Alternatively, use `OPENROUTER_API_KEYS_FILE=secrets/openrouter_keys.json`
with a JSON list or comma/newline-separated key file. That relative path still
resolves from `BIS/`. The key list takes priority over the file, then the shared
`OPENROUTER_API_KEY` setting. BRNS uses `OPENROUTER_API_KEY` or
`GEMINI_API_KEY` according to its configured model chain.

To send verification codes, set `SMTP_BYPASS=false` and fill in the SMTP
settings in [`.env.example`](.env.example). Codes expire after ten
minutes and allow five attempts. SMTP bypass does not mark an email as
verified. Email format checks cannot prove that an inbox exists. Resuming an
already verified account uses email selection, not a password. Restart BIS
after changing its settings.

### BIS saved files

| Path | Purpose |
| --- | --- |
| `BIS/data/users.json` | Accounts keyed by user ID; username is outside preferences |
| `BIS/data/profile_state.json` | Email verification and first-search state |
| `data/geocode_cache.json` | Shared BIS, BRC, and BRNS geocode results, including successful /search lookups |
| `logs/bitefinder.log` | Shared BIS, BRNS, and BRC operational log, created on the first logged event |

Data and logs stay local. Use one BIS process per saved database. Each search
has a trace ID that connects its BIS and BRNS events in the shared log. Events
show the manager function, stage outcome, provider attempt, and candidate
counts without recording API keys, raw requests, addresses, or raw provider
text. It records the AI ID and reason-code list. When BRNS drops an unsupported
AI reason, the log includes the candidate ID
and name, rejected reason code, and facts used for the check. A search error
shows its trace ID so you can find the related lines. Set `DEBUG=true` in the
root `.env` to mirror the log to the terminal; standalone BRNS mirrors it to
stderr too.

Profiles use the current BIS schema only. The local user registry was reset for
this change, so sign up again to create a new profile. New users never import
another user's profile. Unreadable JSON or malformed account records block
writes so existing accounts are not overwritten.

## BRNS: restaurant search and routes

BIS sends BRNS the confirmed search request, including origin coordinates,
travel mode and distance, cuisine, budget, and dietary preferences. BRNS IO
validates it and gathers restaurant facts through Google Places. BRNS AI orders
all candidate IDs and supplies reason codes; Logic keeps only reasons supported
by candidate facts, applies the requirements, and creates matches and
alternatives; Data stores a validated search summary. A live search stops
without a valid BRNS AI recommendation, and can be retried.
For live Google restaurant and route data, set `GOOGLE_MAPS_API_KEY` and
`USE_LIVE_GOOGLE=true` in the root `.env`. The existing
`USE_LIVE_GOOGLE=false` catalog fallback remains available for local use, but
it still needs BRNS AI to produce a completed recommendation.

BRNS ranks candidates and explains alternatives. Halal results are labeled
unofficial until the restaurant checker is integrated. A route or map link
is offered when a result has coordinates. Standalone BRNS accepts one BIS
search JSON object on standard input instead of opening an interactive
questionnaire.

BRNS reads the root `.env` and keeps its data relative to `BRNS/`, regardless of
the working directory. The bundled catalog is at `BRNS/data/restaurants.json`.
Search history and the shared operational log are local runtime files ignored
by Git. Places and AI failures are recorded in that log.

## Code layout and development

Both applications have a `main.py` and separate `io_manager.py`,
`ai_manager.py`, `logic_manager.py`, and `data_manager.py` modules. BIS also has
`sources/` for its profile schema and prompts, and `support/` for configuration,
email delivery, and logging. BRNS has its own `config.py` and an IO-owned
`places_client.py` for Google Places, geocoding, and routing.

To install the optional formatting checker and run it on BIS:

```bash
python3 -m pip install -r requirements-dev.txt
cd BIS
python3 -m pycodestyle *.py sources support
```
