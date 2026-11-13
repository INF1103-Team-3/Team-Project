# BRC — BiteFinder Restaurant Checker

BRC manages Singapore MUIS halal restaurant verification. It scrapes official
MUIS listings, cleans and geocodes records via OneMap, tags cuisines using AI,
and verifies restaurant objects or batches against the cleaned halal database.

## Deployment Role

In [docker-compose.yml](../docker-compose.yml), BRC runs as an always-on
background HTTP container (`brc`, image target `brc`) reachable inside the
`bitefinder-web` network at `http://brc:8000`. Runtime MUIS files and AI caches
are persisted in the `brc-data` Docker volume (`/data/brc` -> `/app/BRC/data`).

## Files

| Path | Responsibility |
| --- | --- |
| `main.py` | Compatibility entrypoint (`BRCApplication.run_once`, `CommandLine.main`) |
| `scraper.py` | MUIS establishment scraping and OneMap postal geocoding utilities |
| `models.py` | Re-exported domain models (`Address`, `Certificate`, `HalalOutlet`, `RestaurantRecord`, `CheckedRestaurant`, `model_constants`) |
| `io_manager.py`, `ai_manager.py`, `logic_manager.py`, `data_manager.py` | Compatibility façades over OOP managers |
| `classes/` | Granular OOP packages: `io/` (`console/`, `http/{server,client}/`, `geocoding/{contracts,providers}/`, `scraping/`), `ai/` (`workflows/`, `providers/{contracts,fallback,clients}/`, `errors/`), `logic/`, `data/` (`storage/`, `caches/`, `models/{common,muis,restaurant}/`), and `services/` (`workflows/{contracts}/`, `cli/`) |

## HTTP Service Endpoints

Exposed on internal port `8000` (`BRC_PORT`):

- `GET /health` -> `{"status": "ok"}`
- `GET /status` -> `{"database_exists": true|false}`
- `POST /check` -> accepts a restaurant JSON object or list and checks official MUIS certification

## Run & Test

```powershell
# Build or refresh the MUIS database manually inside the brc container
# (direct CLI execution requires --internal or BITEFINDER_INTERNAL_CLI=1)
docker compose exec brc python -m BRC.main --internal

# Run BRC automated unit tests
docker compose exec bis-brns python tests/run_tests.py brc
```
