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
| `classes/ai/` | Prompt/schema handling, optional cuisine and outlet workflows, provider clients/fallback and errors |
| `classes/logic/` | Outlet identity, active certificates, deduplication and verification decisions |
| `classes/data/` | JSON persistence, caches and restaurant/MUIS models |
| `classes/services/` | `BRCApplication`, workflow template and concrete build/check jobs, internal CLI |
| Root manager modules, `main.py`, `models.py`, `scraper.py` | Existing interfaces, re-exports and bootstrap compatibility |

`BaseBRCWorkflow` provides a shared job template; build and check workflows
specialize it. AI supplies proposals; deterministic MUIS/outlet evidence is
required before an official classification.

## Build and check behavior

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
