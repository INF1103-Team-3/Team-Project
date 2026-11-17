# BRC — BiteFinder Restaurant Checker

BRC owns official MUIS outlet data and independent halal verification. It
collects MUIS listings, optionally geocodes through OneMap, builds a cleaned
outlet database and checks restaurant objects/batches against that evidence.
BRNS calls BRC when halal is requested; the browser/API does not call it directly.

## Deployment and service boundary

Compose runs `brc` as an independent HTTP service at `http://brc:8000` inside
`bitefinder-web`. Its port is not published to the host. The `brc-data` named
volume maps `/data`, including `/data/brc` and BRC's separate `/data/logs`.
Dockerfile symlinks `/app/BRC/data` and `/app/logs` into that volume.

| HTTP endpoint | Contract |
| --- | --- |
| `GET /health` | `{"status":"ok"}`; service liveness, not proof that data is ready |
| `GET /status` | `{"database_exists":true}` or `false` |
| `POST /check` | Restaurant JSON object or array; shape-preserving checked response |

Checks are serialized at the HTTP boundary. The BRNS adapter can use batch
checks. Request trace headers connect BRC work to upstream search logs.

## Four managers and class layout

| Area | Responsibility |
| --- | --- |
| `classes/io/console/` | Terminal input, JSON validation, progress and output |
| `classes/io/http/` | Independent HTTP server/handler and client adapter |
| `classes/io/scraping/`, `io/geocoding/` | MUIS collection, postal crawling and OneMap/no-geocoder implementations |
| `classes/ai/` | Prompt/schema handling, provider clients/fallback and AI errors |
| `classes/logic/` | Outlet identity, active certificates, deduplication and verification decisions |
| `classes/data/` | JSON persistence, caches and restaurant/MUIS models |
| `classes/services/` | `BRCApplication`, build/check jobs, cuisine/outlet workflow coordination and internal CLI |
| Root manager modules, `main.py`, `models.py`, `scraper.py` | Existing interfaces, re-exports and bootstrap compatibility |

`BaseBRCWorkflow` provides a shared job template; build and check workflows
specialize it. AI supplies proposals; deterministic MUIS/outlet evidence is
required before an official classification.

## Build and check behavior

`DataManager` persists cleaned snapshots across process restarts and caches parsed
reads by resolved path, nanosecond modification time and file size. A replacement
file invalidates that read cache; the cache is not the freshness decision.

The server starts background preparation when its cleaned database is absent,
unless `BRC_AUTO_WARM=0`. A check can also build missing data from a usable raw
snapshot or scrape. The first check may wait for that work even if `/health`
is already successful.

Builds reuse cache/keyword cuisine tags. **Compose sets
`BRC_BUILD_CUISINES_WITH_AI=0`**, so uncached cuisine batch AI is skipped in the
normal stack. Outside that override, optional AI batches can tag pending rows;
partial failures retain checkpoints for later attempts. Ambiguous outlet
matching can still call configured AI providers.

Exact matches and records without candidate outlets can skip AI. Final Logic
validates name/address/postal/unit and certificate evidence; an AI match alone
cannot grant official status. Missing or unavailable verification is not
reported as official.

## Dataset freshness and refresh ownership

`DatabaseRefreshService` owns warm-up, the refresh lock and periodic scheduling;
`BRCHTTPServer` owns the HTTP lifecycle and starts/stops that collaborator.
Data Manager reads the cleaned JSON and reports `missing`, `fresh` or `stale`
using the source snapshot timestamp validated by `MuisSnapshot`. The freshness
window is seven days; malformed or excessively future-dated timestamps are
not fresh. The file's modification time and `built_at` do not reset source age.

A missing/invalid database is built under the handler's serialized-check lock.
A stale but usable database stays available while one background job refreshes
it, without acquiring that check lock. Failed refreshes are logged and retain
the previous database. Fresh data skips the rebuild. `BRC_AUTO_WARM=0` disables
automatic warm-up and periodic refresh. `BRC_REFRESH_CHECK_INTERVAL_SECONDS`
defaults to 3600; a nonpositive interval disables the watcher but not initial
warm-up. The daemon watcher stops when the service stops; an already-running
refresh is not a cancellable job API. Explicit maintenance builds remain
available. `/health` is liveness; `/status` reports file existence, not freshness.

## Files and maintenance commands

Runtime files include raw `muis_establishments.json`, cleaned
`halal_restaurants.json`, cuisine/check caches, scrape progress, OneMap cache,
and the latest single/batch checked output. BRC does not migrate its evidence
into the application's Mongo collections.

Direct CLI execution is restricted to `--internal` or
`BITEFINDER_INTERNAL_CLI=1`. The following opens its maintenance menu:

```powershell
docker compose exec brc python -m BRC.main --internal
```

Choose build/refresh in that menu. To run a noninteractive build without input:

```powershell
docker compose exec -T brc python -m BRC.main --internal --stdout
```

`--input`, `--stdin`, `--output` and `--stdout` support explicit restaurant
checks and output selection. Builds and checks may use external services;
normal regression tests instead use controlled fixtures.

```powershell
docker compose logs --tail=100 brc
docker compose exec bis-brns python tests/run_tests.py brc
docker compose exec bis-brns python tests/run_tests.py oop
```

See [root operations](../README.md), [project flow](../ProjectFlow.md), and
[test isolation](../tests/README.md). Normal full shutdown is
`docker compose --profile "*" down`, which preserves BRC and Mongo data.
