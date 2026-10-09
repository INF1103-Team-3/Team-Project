# BiteFinder current code workflow

This guide describes the code as it currently runs. It follows halal data
preparation, the separate BRC checker, profile collection in BIS, and a live
search handed from BIS to BRNS. It also explains every runtime module and the
important data, configuration, test, and visualization files. The project
scope documents describe some planned capabilities; this guide distinguishes
those plans from executable behavior.

## 1. The three running paths

```text
OPTIONAL HALAL DIRECTORY PREPARATION          SEPARATE BRC CHECKER
BRC/halal_data_scrape.py                      BRC/restaurant_finder.py
  -> HalalFreak sitemap and area pages           -> BRC IO collects its own request
  -> BRC/data/HalalFreak_restaurants.json         -> Google Places and Routes
                                                  -> BRC AI enriches candidates
                                                  -> BRC Logic checks directory
                                                  -> BRC Data saves history

MAIN USER PATH
BIS/main.py
  -> BIS IO collects account, profile, and today's choices
  -> BIS AI interprets profile answers and each live search
  -> BIS Logic validates and protects confirmed choices
  -> BIS Data saves the profile and serializes one eight-field JSON request
  -> BRNS/main.py search(json)
       -> BRNS IO validates JSON and gathers Places/catalog candidates
       -> BRNS AI orders every candidate and suggests reason codes
       -> BRNS Logic verifies facts and creates matches/alternatives
       -> BRNS Data stores a small search summary
  -> BRNS IO prints results and, if chosen, a route

SHARED SUPPORT
shared/geocode_cache.py -> data/geocode_cache.json
shared/debug_log.py     -> logs/bitefinder.log
```

**Current integration boundary:** The HalalFreak directory belongs to BRC.
BIS does not read it, and BRNS does not call BRC or read its directory. The
official halal checker integration shown in project planning documents has
not been connected to the BIS → BRNS path. BRNS deliberately labels a halal
hint as **unofficial; not checked**. Its bundled catalog can contain a legacy
`certification` field, but BRNS Logic removes that field before returning a
restaurant. Therefore no current BIS search can turn a BRNS result into an
official halal claim.

### Entry points

| Command from the repository root | What it runs |
| --- | --- |
| `python BIS/main.py` | Interactive account, profile, and search chatbot. This is the normal user entry point. |
| `python BRC/halal_data_scrape.py` | Separate download/refresh of BRC's HalalFreak directory. It is not called by BIS or BRNS. |
| `python BRC/restaurant_finder.py` | Separate BRC restaurant checker with its own interactive questions and history. |
| `python BRNS/main.py < request.json` | Standalone BRNS adapter: reads one BIS-shaped JSON object from standard input, runs one search, and prints results. Normal BIS use calls `BRNS.main.search()` directly. |

Use the Python environment with the requirements installed. A root `.env`
supplies credentials and settings; `.env.example` shows the expected names.
Do not put actual credentials in documentation or version control.

## 2. Halal data preparation and the independent BRC path

### 2.1 Refreshing the halal directory

`BRC/halal_data_scrape.py` is a standalone scraper. Its `main()` connects
BRC's Python logging to the global log and calls `refresh()`. `refresh()` calls
`scrape_all()`, which reads the HalalFreak sitemap, selects area page URLs,
fetches each area, and parses establishment links. The parser extracts a
name, listed establishment type, optional six-digit postal code, area, and
profile URL. It de-duplicates by profile URL. One failing area is reported
and skipped; a failed sitemap stops the refresh. If the final list is empty,
the existing directory is retained instead of being overwritten.

The successful result is written atomically by
`BRC/data_manager.save_halal_directory()` to
`BRC/data/HalalFreak_restaurants.json`. That file and even its `BRC/data/`
directory may be absent before the first successful refresh. A scraped row
records the source's `Certified` label, but it is not consumed by the live
BIS → BRNS search.

### 2.2 How BRC uses the directory

`BRC/restaurant_finder.py` starts a **different** application. BRC IO asks
for a location, `halal`/`non-halal`/`vegetarian`, maximum walking minutes,
minimum rating, and maximum average spend. These become a `SearchRequest`
dataclass from `BRC/models.py`. BRC's `places_client.py` geocodes the area,
performs a Google Places text search (up to 20 candidates), gets walking
routes, and builds candidate records containing Google facts. Its
`BRC/ai_manager.py` sends the candidates to Gemini to estimate cuisine,
average price, likely allergens, and spicy options. It validates each AI item
and retries missing items; an unavailable AI detail is recorded as failed
rather than silently being treated as fact.

For a **halal BRC search only**, `BRC/restaurant_finder.run_search()` loads
the scraped directory and passes an index to `BRC/logic_manager.py`. The
index groups rows by postal code. Logic extracts a postal code from a Google
address, compares normalized establishment names at the same postal code,
and sets a BRC certification status (`halal-certified`, `not-listed`, or
`unverified`). A missing directory or postal code means `unverified`, not an
official match. Logic also applies walk, rating, budget, AI-estimate, and
dietary flags, assigns accept/flag/reject, and scores each candidate. BRC
Data saves the processed records in `BRC/restaurant_history.json`; BRC IO
shows up to five accepted or flagged results.

This BRC certification check is **not** the future official BIS/BRNS checker.
Its source and name-matching behavior should not be assumed to apply to
BRNS output.

## 3. BIS startup, accounts, and saved profile

`BIS/main.py:main()` loads configuration using `BIS/support/config.py`,
validates required BIS AI settings, and starts `run_accounts()`. The account
loop loads saved users, lets a person sign up or resume by email, then starts
`run_session()`. `BIS/io_manager.py` owns prompts and terminal output.
`BIS/data_manager.py` owns the account files; `BIS/logic_manager.py` owns
rules; `BIS/ai_manager.py` owns OpenRouter calls. `BIS/main.py` coordinates
these calls.

On signup, BIS normalizes the email and username, creates a UUID user ID,
and saves a record with empty preferences. Unless `SMTP_BYPASS=true`, BIS IO
requests a verification challenge, `BIS/support/email_delivery.py` sends the
code, BIS Logic checks expiry/attempt rules and the submitted code, and BIS
Data persists the verified account and temporary verification state. The
verification code itself is never written to the operational log.

The profile fields, in collection order, are defined in
`BIS/sources/profile_schema.py`:

1. Saved location names.
2. Maximum walking distance in kilometres.
3. Maximum walking time in minutes.
4. Budget per person in SGD.
5. Dietary requirements (`halal`, `vegetarian`, both, or an empty list).
6. Liked cuisines.
7. Disliked cuisines.
8. Other preferences.

`None` means a field has not been answered. An empty list means the user
explicitly chose none. For travel, BIS Logic estimates the missing counterpart
using approximately 20 minutes per kilometre. The profile schema validates
types, finite numeric ranges, supported cuisines, allowed dietary choices,
and the exact set of account/profile fields. BIS Logic prevents a cuisine
from being both liked and disliked and handles add/replace/remove for saved
locations.

During profile collection, `BIS/io_manager.collect_action()` first recognizes
commands such as `/search`, `/edit`, `/profile`, `/reset`, `/logout`, and
`/quit`. Straightforward values can be parsed locally. Complex answers go
through `BIS/ai_manager.process()`, which asks OpenRouter for a structured
intent and profile update. `BIS/ai_manager.validate_response()` checks the
returned schema before `BIS/logic_manager.apply_updates()` can change the
profile. BIS asks for confirmation of AI-interpreted cuisines and extra
preferences. `BIS/data_manager.save_preferences()` validates and atomically
saves the final account. A failed interpretation or validation leaves the
previous preferences unchanged.

The account registry is `BIS/data/users.json`; verification challenges and
the first-search completion marker live in `BIS/data/profile_state.json`.
These are runtime data files, not code. When the final profile field is saved,
BIS automatically offers the first search. On later resume, a complete
profile triggers that automatic search only if its saved completion marker is
not set. A user can explicitly run `/search` again at any time.

## 4. BIS search: today's choices become a validated JSON request

The normal live call path is:

```text
BIS.main.run_search()
  -> BIS.io_manager.collect_search()
  -> BIS.ai_manager.interpret_search_request()
  -> BIS.logic_manager.validate_search_request()
  -> BIS.io_manager.confirm_search_request()
  -> BIS.data_manager.serialize_search_request()
  -> BRNS.main.search(json)
```

`collect_search()` asks for **today's** location, travel mode, travel distance,
cuisine, budget, optional saved or new other preferences, and a free-text
description of the desired meal. These choices do not overwrite the saved
profile. Dietary requirements and disliked cuisines are copied from that
profile. A walking search offers the saved walking distance as the Enter
default. Driving requires a fresh distance. Enter at the other-preferences
prompt means none; `all` includes every saved item.

For a location, BIS accepts Singapore coordinates, a six-digit postal code,
an address, or a landmark. It checks the shared geocode cache first. If an
uncached landmark needs interpretation, BIS AI may produce a clean location
query; the original text is used if that AI call is unavailable. BIS Data
resolves coordinates directly, from the cache, or through Google Geocoding,
rejects coordinates outside the supported Singapore bounds, and remembers
successful aliases in the shared cache. BIS IO prints the found label and
coordinates and asks the user to confirm. Short invalid yes/no or walk/drive
answers can be sent to BIS AI for a typo suggestion, which is itself
confirmed by the user before use.

For every live `/search`, BIS AI interprets the free-text request even when
the other choices came from menus. For example, `chicken rice` can be added
to `other_preferences`. BIS Logic validates the complete proposed request.
It protects the already confirmed origin, travel mode, distance, cuisine,
budget, dietary requirements, and disliked cuisines. AI may add explicitly
mentioned other wishes but cannot remove a selected one. If it conflicts
with a protected choice, BIS asks for clarification and retries
interpretation. The full interpreted request is displayed for the user's
final yes/no confirmation before any BRNS search.

The BIS → BRNS JSON contract has **exactly eight top-level fields**:

```json
{
  "origin": {
    "query": "sengkang",
    "label": "sengkang",
    "latitude": 1.386812,
    "longitude": 103.891443
  },
  "mode": "walk",
  "max_distance_km": 10.0,
  "cuisine": "chinese",
  "budget_per_person": 10.0,
  "other_preferences": ["chicken rice"],
  "dietary_requirements": ["halal"],
  "disliked_cuisines": []
}
```

This is an example shape, not a user's saved record. The free-text sentence
is not an extra JSON field; only its validated wishes appear in
`other_preferences`. Account identifiers, email, verification state, and
profile-only fields do not cross the boundary. BIS Data serializes the
validated object with no NaN values. `BRNS/io_manager.accept_bis_json()`
validates the exact key sets again on receipt, including the origin object,
Singapore coordinate bounds, mode, supported cuisine, numeric limits, and
list fields.

`AI_BYPASS=true` is the BIS chatbot test mode: BIS parses/validates locally,
shows the choices, marks that test search complete, and skips BRNS entirely.
It is not the normal live recommendation path. BRNS retains a catalog
fallback when `USE_LIVE_GOOGLE=false`, but `BRNS.main.search()` still
requires a configured and successful AI recommendation in that mode.

## 5. BRNS search: IO → AI → Logic → Data

`BRNS/main.py:search()` starts or reuses the current shared trace ID and
coordinates four manager stages:

### Stage 1 — BRNS IO and its Places client

`BRNS/io_manager.accept_bis_json()` revalidates the BIS contract. BRNS checks
for an AI provider and, in live Google mode, a Maps key before spending a
Places request. `BRNS/io_manager.find_candidates()` converts the confirmed
origin into coordinates, loads the bundled catalog through
`BRNS/places_client.load_catalog()`, and asks
`BRNS/places_client.build_candidates()` to collect candidate facts. BRNS
Data does **not** find restaurants.

In live mode the client builds a Google Places text query from dietary
requirements, selected cuisine, and today's other preferences. If it gets
no usable text-search places, it tries generic nearby Places. It parses
names, addresses, coordinates, ratings, price ranges, Google place types,
and opening hours. A place can be enriched with bundled catalog facts only
when both normalized name **and** address match. Missing cuisine, price,
dietary, or spice data remain unknown; a Google starting price is kept as
`price_start`, not treated as a known average price. The client de-duplicates
names, asks Google Routes for a travel matrix for the selected mode, and
labels any missing route distance as an estimate. In catalog fallback mode,
it returns catalog rows without pretending that old catalog walking times
are routes from today's origin.

If a Places text search included `halal`, the resulting candidates receive
an `halal_hint` that eventually becomes `unofficial`. This only records how
the candidate was found; it is not a certificate check.

### Stage 2 — BRNS AI

`BRNS/ai_manager.recommend_candidates()` creates a compact factual summary
of **every** candidate and sends the confirmed request plus those facts to
an AI provider. The configured chain currently tries direct Gemini models
first, then OpenRouter as a fallback. Calls have connection and response
timeouts, and provider failures are logged without raw provider bodies or
keys. The AI must return a list containing every candidate ID exactly once,
ordered by suitability, with up to four allowed reason codes per candidate.
The response is rejected if IDs are missing, duplicated, out of range, or
the JSON/reason-code schema is invalid. A search stops if no provider gives
a valid recommendation. This is why BRNS cannot complete a normal search
without AI, even though Logic independently checks the eventual facts.

The older `BRNS/ai_manager.call_ai()` prompt/parsing interface remains in
the file, but `BRNS.main.search()` does not call it. The active AI entry
point for BIS-driven searches is `recommend_candidates()`.

### Stage 3 — BRNS Logic

`BRNS/logic_manager.rank_restaurants()` checks the AI IDs again, normalizes
each candidate, and removes any legacy `certification` value. It validates
each AI reason against actual candidate fields and the request. For example,
`within_budget` requires a known numeric `avg_price` at or below the user's
budget; a `price_start` alone is insufficient. Unsupported factual reasons
are logged with the candidate ID and evidence, then dropped. Malformed
reason-code lists or invalid candidate IDs still stop the search.

`decide_outcome()` independently checks selected and disliked cuisines,
dietary evidence, budget, and route distance. A disliked cuisine rejects a
candidate. A known mismatch, unknown fact, unverified dietary status,
unverified budget, or estimated/unavailable route creates an alternative
with explanatory reasons. A candidate with all required facts verified
becomes a match. An unofficial halal hint remains an unverified dietary
fact. Logic retains AI order, returns at most five matches and five
alternatives, and counts rejected candidates as `hidden`. It does not
promote an AI reason into a fact merely because the model said it.

### Stage 4 — BRNS Data and return to BIS

`BRNS/data_manager.save_search_results()` appends a small validated summary
to `BRNS/data/search_history.json`: source (`live-google` or
`offline-catalog`), origin coordinates, mode, selected cuisine, and top
match names. A history write failure is logged as a warning and does not
erase the result. BRNS returns the result object to BIS. BIS marks the
search completed in `BIS/data/profile_state.json` only after BRNS returns
successfully, and `BRNS/io_manager.show_results()` prints matches followed
by alternatives, with labels for unknown prices, estimated travel, and
unofficial/unverified halal status.

If the user selects a numbered result for directions, BIS calls
`BRNS/main.py:route_to()`. BRNS IO uses the Places client for an on-demand
Directions request and builds a Google Maps link. When detailed directions
are unavailable, the link remains available. `BRNS/io_manager.show_route()`
prints the route or fallback link. Enter skips the route prompt.

On cancellation, AI failure, invalid data, or BRNS failure, BIS leaves the
search retryable and shows an error with the shared log trace ID. The
profile already saved before that attempt remains saved.

## 6. Shared files and operational boundaries

### Geocoding cache

`shared/geocode_cache.py` is the single durable cache for BIS, BRC, and
BRNS. It lowercases and trims text keys, validates finite latitude/longitude
pairs, and stores successful lookups in `data/geocode_cache.json`. Its
read-modify-write uses a lock file and atomic replacement; it uses `msvcrt`
on Windows and `fcntl` on Unix. BIS can store both the user's original
location text and the AI-cleaned query as aliases. BRC and BRNS use the
same lookup and remember functions. Cache entries are coordinates, not
restaurant search results.

### Global log

`shared/debug_log.py` writes to `logs/bitefinder.log`. BIS and BRNS call it
directly. BRC's existing Python `logging` calls are bridged into it by
`configure_python_logging()`. A search trace ID connects BIS and BRNS
events in one process; the CLI displays that ID when a search error occurs.
`DEBUG=true` mirrors operational events to the terminal. BRNS records
provider attempts, candidate counts, accepted AI order, rejected reason
details, and stage outcomes. The log should be treated as diagnostic data,
because candidate names and some restaurant facts appear in verbose lines.
It is not a source of restaurant or certification truth.

## 7. File-by-file reference

### BIS: chatbot and profile side

| File | Role and main calls |
| --- | --- |
| `BIS/main.py` | Program entry and coordinator. `main` loads settings; `run_accounts` selects an account; `run_session` dispatches commands; `save_update` validates/saves profile changes; `run_search` performs the BIS → BRNS handoff and optional route. |
| `BIS/io_manager.py` | All BIS terminal prompts and displays. Handles account selection, email verification interaction, profile answer collection, search location/mode/distance/cuisine/budget/other wishes, clarification and confirmation, result selection, and command parsing. It does not save records. |
| `BIS/ai_manager.py` | OpenRouter adapter, API-key rotation, response parsing/schema checking, profile answer interpretation, location extraction, short search-choice typo suggestions, and interpretation of every live search. It does not decide whether a proposed update is allowed. |
| `BIS/logic_manager.py` | Pure profile/search decisions: travel conversion, preference updates and conflicts, local answer parsing, email challenge policy, Singapore coordinate checks, and the protected eight-field search validation. |
| `BIS/data_manager.py` | Validated account and state persistence with atomic writes; email lookup/registration; shared geocode lookup and Google Geocoding; successful location caching; exact JSON serialization for BRNS. |
| `BIS/sources/profile_schema.py` | Canonical account and preference keys, cuisine/dietary vocabulary, numeric ranges, normalization, exact-schema validation, and verification constants. BRNS imports the supported cuisine list from here. |
| `BIS/sources/prompts.py` | Profile questions, labels, command/help text, AI system prompt, and command/intent tables. |
| `BIS/support/config.py` | Loads root `.env`, OpenRouter, Maps, SMTP, debug, and bypass settings; validates the required BIS AI configuration. |
| `BIS/support/email_delivery.py` | Validates SMTP settings and sends email verification codes over TLS. |
| `BIS/sources/__init__.py`, `BIS/support/__init__.py` | Package markers; no runtime decision logic. |
| `BIS/data/users.json` | Local saved accounts and preferences. Runtime data; do not use as a source of code behavior. |
| `BIS/data/profile_state.json` | Verification and automatic-search state per user. Runtime data. |
| `BIS/data/.gitkeep` | Keeps the data directory present in version control. |
| `BIS/.gitignore` | BIS-specific ignore rules for local/runtime material. |

### BRNS: restaurant search and navigation side

| File | Role and main calls |
| --- | --- |
| `BRNS/main.py` | `search` coordinates IO → AI → Logic → Data, reuses BIS trace IDs, and returns validated results. `route_to` builds an optional route. `main` is the standalone JSON-on-stdin entry. |
| `BRNS/io_manager.py` | Validates the exact BIS JSON contract, collects candidate facts through `places_client`, requests routes, and displays results/routes. It does not ask new user questions during a search. |
| `BRNS/places_client.py` | Google Geocoding, Places text/nearby search, place parsing, catalog enrichment, route matrix, route estimates, on-demand directions, Maps links, and shared geocode cache access. This is an IO-side API client, not the Data Manager. |
| `BRNS/ai_manager.py` | Provider chain, HTTP calls, factual candidate summaries, JSON/recommendation validation, and AI ordering/reason suggestions. `recommend_candidates` is the active search function; the older `call_ai` interface is not used by `BRNS.main.search`. |
| `BRNS/logic_manager.py` | Normalizes candidate facts, strips legacy certification claims, validates AI reasons, applies cuisine/dietary/budget/route rules, and divides results into matches, alternatives, and hidden rejects. |
| `BRNS/data_manager.py` | Reads/writes BRNS JSON files and stores a compact approved search summary. Its catalog loader exists, but current candidate gathering calls the Places client's catalog loader. |
| `BRNS/config.py` | Root `.env` settings, live/catalog switch, Google endpoints, AI provider order, display limits, and data paths. |
| `BRNS/data/restaurants.json` | Bundled candidate catalog. Used for matching enrichment in live mode and as candidate fallback when `USE_LIVE_GOOGLE=false`. Legacy certification text is not returned as official BRNS evidence. |
| `BRNS/data/search_history.json` | Locally generated compact BRNS search history. |
| `BRNS/.gitignore` | Ignores local BRNS runtime files such as search history. |

### BRC: separate checker and halal preparation

| File | Role and main calls |
| --- | --- |
| `BRC/halal_data_scrape.py` | Standalone HalalFreak sitemap/area scraper and directory refresh. |
| `BRC/restaurant_finder.py` | Separate BRC CLI coordinator: collect BRC request, fetch Places, enrich with AI, check directory and rules, save/display results. |
| `BRC/io_manager.py` | BRC prompts, validation at the CLI boundary, restaurant formatting, warnings, and history/summary displays. |
| `BRC/places_client.py` | BRC's Google Geocoding, Places, walking matrix, hours/price parsing, directions links, and shared geocode cache use. Independent of `BRNS/places_client.py`. |
| `BRC/ai_manager.py` | Gemini enrichment of BRC candidates with estimated cuisine, price, allergens, and spice fields; validates each returned item and retries missing ones. Independent of BRNS AI. |
| `BRC/logic_manager.py` | BRC certification matching using directory postal codes and names; accept/flag/reject rules, scoring, and summaries. |
| `BRC/data_manager.py` | BRC history load/save/filter, corrupt-file quarantine, and HalalFreak directory load/save/timestamp. |
| `BRC/models.py` | BRC `SearchRequest` dataclass with its own five input fields. This is not the BIS → BRNS JSON contract. |
| `BRC/restaurant_history.json` | BRC processed restaurant history. Separate from BRNS search history. |
| `BRC/data/HalalFreak_restaurants.json` | Generated directory after a successful scrape; may not yet exist locally. Read by BRC only. |
| `BRC/requirements.txt` | Extra dependencies for BRC's Gemini SDK, dotenv, requests, and HTML scraper. |
| `BRC/.gitkeep` | Keeps the BRC directory present in version control. |

### Shared and repository-level files

| File | Role |
| --- | --- |
| `shared/geocode_cache.py` | One geocode store and cross-platform lock for all three applications. |
| `shared/debug_log.py` | One operational log, BIS/BRNS trace IDs, optional terminal mirror, and BRC Python-logging bridge. |
| `data/geocode_cache.json` | Shared successful text-to-coordinate lookups; runtime data. |
| `data/geocode_cache.lock` | Lock file used during cache writes; runtime data. |
| `logs/bitefinder.log` | Shared diagnostic log; runtime data. |
| `.env.example` | Safe example of environment variable names and defaults; copy to local `.env` and fill credentials there. |
| `.env` | Local credentials and settings; ignored by Git and not part of the program's documented source. |
| `.gitignore` | Root rules for secrets, local data/logs, generated graphs, and other files that should not be committed. |
| `requirements.txt` | Core BIS/BRNS Python packages (`python-dotenv`, `requests`). |
| `requirements-dev.txt` | Core packages plus style, call-graph, and Pillow tooling. |
| `tests/test_bis_brns_integration.py` | Automated regression checks for request shape, manager order, AI validation, evidence-based reasons, logging, routes, cancellation, test mode, and the BIS → BRNS handoff. |
| `visualise_functions.py` | Generates static call-graph PNGs and `project_workflow.png`, a diagram of the separate halal/BRC and BIS → BRNS paths; has an optional live BIS trace mode. |
| `function_graphs/*.png` | Generated visualizations, not runtime inputs. |
| `README.md` | Setup, CLI commands, settings, and high-level usage. |
| `ProjectFlow.md`, `ProjectInitialDetails.md`, `BIS/docs/ProjectInitialDetails.md`, `BIS/docs/Team Project Framework Brief.pdf` | Project briefs/design references. Their desired behavior may be broader than today's running code. |
| `AI_REQUIRED_SEARCH_PLAN.md`, `CLI_OUTPUT_CLEANUP_PLAN.md` | Local planning notes. They are not imported or executed and are not part of the runtime flow. |

## 8. One concrete trace to remember

For a user seeking chicken rice near Sengkang, the decisive sequence is:

1. BIS IO confirms the geocoded origin and collects `walk`, a distance,
   `chinese`, a budget, today's optional preferences, and `chicken rice`.
2. BIS AI proposes the structured search, usually adding `chicken rice` to
   `other_preferences`. BIS Logic checks that confirmed choices stayed fixed.
3. The user confirms the summary. BIS Data serializes the eight-field JSON.
4. BRNS IO validates it, asks Google Places for candidates, enriches with
   catalog facts, and gets route distances.
5. BRNS AI orders every candidate and proposes reason codes. BRNS Logic
   removes claims that cannot be supported by candidate facts. A low
   `price_start` alone never proves `within_budget`.
6. BRNS Logic returns matches or clearly labeled alternatives; BRNS Data
   stores the compact summary; BIS prints results and optionally a route.

At no point in that path is the BRC HalalFreak directory consulted. Halal
information shown by BRNS remains explicitly unofficial or unverified until
the separate official checker integration is implemented.
