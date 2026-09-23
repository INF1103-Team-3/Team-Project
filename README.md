# BiteFinder

BiteFinder is a procedural Python CLI that filters restaurant menu items against
hard requirements, then ranks qualifying restaurants with explained scores.
Requirements: [project specification](docs/BITEFINDER_SPEC.md).

Python 3.11+ is required. No third-party runtime or test packages are needed.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Enter a local profile name, then choose manual (`m`) or AI (`a`) search. Manual
search works without credentials. Confirm the interpreted requirements, review
up to five results, select a restaurant or reject the results, and search again.
Choose `p` to review/edit the active profile or reset learned preferences; `h`
shows its latest 10 history entries. Choose `q` to exit. EOF and Ctrl+C exit cleanly.

The starter data has three Saizeriya outlets in Singapore. Try manual search,
SGD 10, Italian cuisine, and leave walking, dietary, allergy and opening constraints
empty. Read [data provenance and limitations](docs/DATA.md) before extending it.
This is a small checked dataset, not broad restaurant coverage.

## Keys and configuration

Create an API key at [OpenRouter API Keys](https://openrouter.ai/settings/keys).
Set `OPENROUTER_API_KEY` and choose a JSON-capable model ID from
[OpenRouter's model catalog](https://openrouter.ai/models) for `OPENROUTER_MODEL`.
The model ID is not a credential. The integration uses the
[OpenRouter chat API](https://openrouter.ai/docs/quickstart) with JSON mode, a
20-second timeout, local schema validation, and at most one retry for malformed
interpretation. Network/HTTP failures return a readable error. Manual mode stays
available. Natural-language request text is sent to OpenRouter only in AI mode.

For an interactive Bash session, avoid putting the key itself in shell history:

```sh
read -rsp 'OpenRouter API key: ' OPENROUTER_API_KEY; echo
export OPENROUTER_API_KEY
read -rp 'OpenRouter model ID: ' OPENROUTER_MODEL
export OPENROUTER_MODEL
python main.py
```

The app reads environment variables only. It does not automatically load `.env`
or read `/run/codex-secrets`. Existing mounted credentials should be injected by
your container launcher; do not paste them into source code or chat. Safe variable
names are in `.env.example`. No Telegram key is needed for this CLI MVP.

For walking routes, create an account/key at the
[openrouteservice dashboard](https://openrouteservice.org/log-in/) and set
`OPENROUTESERVICE_API_KEY` using the same hidden-input pattern as above. The
[directions API](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/requests-and-return-types)
receives origin/destination coordinates when a confirmed search includes a
location. Route caches also remain local and ignored by Git.
`BITEFINDER_DATA_DIR` defaults to the repository `data` directory;
`BITEFINDER_LOG_DIR` defaults to `logs` relative to the working directory.

## Rules and persistence

A single meal must satisfy all hard requirements together. Unknown price excludes
an item when a budget is required. Unknown dietary/allergy evidence excludes it
when that constraint is required. Allergy claims also need verified exclusion of
cross-contact. No constraint is silently weakened. AI cannot provide restaurant
facts or override saved safety requirements. Unsupported interpretations must be
restated in manual mode. User confirmation is required because interpretation can
omit or misunderstand natural language.

Weekly local opening schedules support overnight hours and date exceptions.
Missing hours are unknown. Walking routes use openrouteservice's `foot-walking`
profile and require manual latitude/longitude. No straight-line substitute is used.
Successful routes are cached for one hour by exact origin/destination coordinates;
missing, expired or failed routes cannot pass a walking limit. A search makes at
most 10 uncached routing requests. Limits are applied to the provider's estimated
outdoor walking time; indoor access, entrances and unexpected closures may differ.
The routing service may snap coordinates to paths within 100 metres.

Ranking uses cuisine/food match (35), learned cuisine preference (25), walking
convenience (20), price (15), and variety (5). Individual contributions are shown.
Scores are ranking points, not probabilities or safety ratings. Tie-breaking uses
restaurant IDs. Repeated selections increase only bounded soft cuisine counts;
allergy and dietary requirements persist and are never learned away. The profile
editor lets you deliberately change them after reviewing the full replacement.
Cancelling or a failed save leaves the active profile unchanged. Saved cuisine and
food preferences fill empty search preferences; explicit search preferences take
precedence. Resetting learning preserves every explicit and safety preference.

Atomic JSON saves preserve existing files on failure. Corrupt history/profile
files are reported and not overwritten. The app supports one CLI process per data
directory; concurrent writes are not supported. Profiles and history contain user
preferences and location and remain local in ignored files. Debug logs contain only
controlled milestone codes and numeric counts, never user text or API responses.

## Structure

- `main.py`: startup; `io_manager.py`: input, display and orchestration.
- `ai_manager.py`, `prompts/`: API communication and interpretation prompt.
- `logic_manager.py`: hard constraints, opening status, ranking and soft learning.
- `data_manager.py`: JSON storage and restaurant loading; `schemas.py`: validation.
- `config.py`, `debug.py`: configuration and milestone logging.
- `routing_service.py`: pedestrian HTTP requests and route-cache validation.
- `data/`: sourced restaurant data; `tests/`: offline unit/integration tests.
- `legacy/streamlit_app.py`: preserved prototype, not the runnable MVP; its original
  database/recommender modules were absent from this checkout.

## Tests and Docker

```sh
python -m unittest discover -s tests -v
python -m compileall -q *.py tests

docker build -t bitefinder .
docker run --rm -it --env OPENROUTER_API_KEY --env OPENROUTER_MODEL \
  --env OPENROUTESERVICE_API_KEY bitefinder
```

All API tests use mocked responses. No live paid requests are required. The Docker
context explicitly excludes secrets and local user data. For persistent storage,
mount the project data directory at `/app/data` and logs at `/app/logs`.
Docker is unavailable in the current development container; image build/run have
not been verified. OpenRouter and openrouteservice live execution await
environment configuration.

## Troubleshooting and remaining work

- Missing key/model: set both variables or use manual search.
- No matches: examine exclusion counts and missing source evidence; constraints
  remain unchanged. Starter records have no verified allergy/dietary evidence or
  outlet-specific hours, so those hard constraints intentionally return no results.
- Damaged JSON: back up and repair the reported data file; originals are preserved.
- Failed saves: check directory permissions and free space.
- Malformed AI output: retry the request or switch to manual entry.

Next: broader verified data, live API/Docker validation, and controlled
AI-assisted source ingestion. Telegram and web
interfaces remain future enhancements under the CLI-first specification.
