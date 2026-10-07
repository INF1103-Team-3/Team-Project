# BiteFinder

BiteFinder currently contains two independent Python command-line applications
and a folder reserved for future work:

| Application | Purpose | Run from the repository root |
| --- | --- | --- |
| **BIS** — BiteFinder Interaction System | Sign up or resume an account and save food preferences | `python3 BIS/main.py` |
| **BRNS** — BiteFinder Recommendation & Navigation System | Find, rank, and route to restaurants | `python3 BRNS/main.py` |
| **BRC** — BiteFinder Restaurant Checker | Reserved for team members to add restaurant checking functionality | No command yet |

BIS profiles do not feed into BRNS searches yet. BRNS is based on the `main`
branch snapshot `43e91b6`; BIS comes from `bitefinder-chatbot-draft`. The
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
`requirements-dev.txt` adds `pycodestyle`.

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
The command collects today's search choices; restaurant results will be added
when BIS and BRNS are connected.

### BIS commands

| Command | What it does |
| --- | --- |
| `/help` | Show available commands |
| `/help [command]` | Explain a command, its accepted values, and examples |
| `/profile` | Show the saved profile |
| `/search` | Choose today's location, travel mode and distance, cuisine, budget, and other preferences |
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
distance. Search choices do not change your saved profile. Use `/help search`
for the full sequence.

### BIS AI and email settings

Signup uses fixed prompts and Python validation. AI can interpret preference
answers, but saved updates must still pass validation. To enable AI, set these
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
`OPENROUTER_API_KEY` setting. BRNS uses only `OPENROUTER_API_KEY`.

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
| `BIS/logs/bitefinder.log` | Operational logs, created on the first logged event |

Data and logs stay local. Use one BIS process per saved database. Set
`DEBUG=true` in the root `.env` to also display logs in the terminal. Logs include
travel distance and time; do not log API keys or verification codes.

Profiles use the current BIS schema only. The local user registry was reset for
this change, so sign up again to create a new profile. New users never import
another user's profile. Unreadable JSON or malformed account records block
writes so existing accounts are not overwritten.

## BRNS: restaurant search and routes

In the root `.env`, supply an `OPENROUTER_API_KEY` or `GEMINI_API_KEY` for request
interpretation. BRNS tries the configured model chain in order. For live Google
restaurant, geocoding,
and route data, also set `GOOGLE_MAPS_API_KEY` and `USE_LIVE_GOOGLE=true`.
Set `USE_LIVE_GOOGLE=false` to search the bundled restaurant catalog; AI
interpretation still needs an AI provider key. Cached locations may work
without a Maps key, while uncached locations need geocoding.

```bash
python3 BRNS/main.py
```

BRNS asks for a Singapore location, walking time or driving distance, budget,
meal time, dietary requirement, food preference, minimum rating, and optional
search text. It ranks matching restaurants, explains alternatives, and offers
a route or map link when coordinates are available. The current input supports
`none`, `halal`, and `vegetarian` dietary choices; it does not ask for allergies.

BRNS reads the root `.env` and keeps its data relative to `BRNS/`, regardless of
the working directory. The bundled catalog is at `BRNS/data/restaurants.json`.
Search history and API error logs are local runtime files ignored by Git.

## Code layout and development

Both applications have a `main.py` and separate `io_manager.py`,
`ai_manager.py`, `logic_manager.py`, and `data_manager.py` modules. BIS also has
`sources/` for its profile schema and prompts, and `support/` for configuration,
email delivery, and logging. BRNS has its own `config.py` and restaurant data.

To install the optional formatting checker and run it on BIS:

```bash
python3 -m pip install -r requirements-dev.txt
cd BIS
python3 -m pycodestyle *.py sources support
```
