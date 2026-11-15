# BRNS — BiteFinder Recommendation and Navigation System

BRNS receives validated search JSON from BIS, gathers restaurant/route facts,
asks AI to rank the current candidates, applies deterministic rules, coordinates
BRC halal verification, persists results and returns matches/alternatives.
It does not own account prompts, browser routes or user profiles.

## Runtime boundary

BIS calls `BRNSGatewayInterface` through `BRNSService` in
`classes/services/gateway/`. `runtime.py` builds CLI and headless web graphs.
The gateway exposes search, navigation, sorting, Maps links, user history and
model metadata. The HTTP gateway never calls BRNS directly.

With `BRC_SERVICE_URL` set, BRNS uses `BRCHTTPClient` through its verification
adapter. Without that variable, CLI composition can use in-process `BRC.main`.
Compose sets the URL to `http://brc:8000` for both CLI and API.

Direct BRNS CLI is an internal diagnostic path. From a POSIX host with a
prepared request JSON:

```bash
docker compose exec -T bis-brns python BRNS/main.py --internal < search_request.json
```

The `--internal` flag or `BITEFINDER_INTERNAL_CLI=1` is required. Normal users
start [BIS](../BIS/README.md) through `python main.py`.

## Manager and class ownership

| Area | Responsibility |
| --- | --- |
| `io_manager.py`, `classes/io/adapters/` | BIS request validation, presentation and external gateway delegation |
| `classes/io/gateways/google/` | Candidate retrieval and route gateway operations |
| `classes/io/gateways/verification/` | Focused BRC adapter and verification capability |
| `ai_manager.py`, `classes/ai/` | Ranking prompts, parsing/schema checks, provider objects and fallback routing |
| `logic_manager.py`, `classes/logic/evaluation/` | Candidate normalization, opening hours, factual grounding, outcome and enrichment policy |
| `classes/logic/sorting/` | Rating/distance strategies and registry |
| `data_manager.py`, `classes/data/` | Restaurant/history repositories, record mapping and request-local history scope |
| `classes/services/workflows/` | Recommendation pipeline, halal coordination and navigation |
| `classes/services/gateway/` | Headless subsystem contract and service |
| `classes/services/cli/`, `main.py` | Internal CLI and compatibility/bootstrap paths |

## BIS request contract

Each BRNS call takes exactly these fields:

| Field | Meaning |
| --- | --- |
| `origin` | `query`, `label`, Singapore `latitude` and `longitude` |
| `mode` | `walk`, `drive` or `transit` |
| `max_distance_km` | Distance limit or `null` |
| `max_travel_minutes` | Time limit or `null`; exactly one travel limit active |
| `traffic_aware` | Driving-time traffic option |
| `cuisine` | Supported cuisine or `none` |
| `budget_per_person` | Required positive SGD limit |
| `dietary_requirements` | Supported dietary values |
| `disliked_cuisines` | Cuisines to avoid |
| `other_preferences` | Confirmed free-text wishes and constraints |

Web multi-origin/multi-cuisine orchestration belongs to BIS. BRNS still
processes one origin and one cuisine target per call; it does not accept the
web transport's extra fields. See [DataFlowDiagram.md](../DataFlowDiagram.md)
for the full JSON example.

## Candidate preparation and AI

1. Validate the BIS request and provider configuration.
2. Load saved facts through Data and interpret them through Logic.
3. With `USE_LIVE_GOOGLE=true`, retrieve Places results and Routes matrices.
   `RestaurantEnricher` owns saved/live merge policy; outlet matching uses
   normalized name/address, while persistence uses Google place IDs.
4. With `USE_LIVE_GOOGLE=false`, use the active saved catalog (MongoDB or
   configured JSON). No catalog is shipped by default; saved route times are
   not claimed as current routes. Offline source selection still requires AI.
5. Prepare domain context through Logic, including rating/review confidence,
   constraints and previous names. AI returns candidate IDs and reason codes.

```json
{"recommendations": [{"id": 0, "reason_codes": ["within_budget", "within_route"]}]}
```

Every input ID must occur once. Unknown/duplicate/missing IDs and malformed
schemas are rejected. Provider fallback preserves the subsystem's configured
chain and deadline. `reason_codes` are validated and grounded against known
facts before presentation; model wording cannot invent official certification.

## Rules and outcomes

`RestaurantOutcomePolicy` owns match/alternative/reject decisions. Examples:

- Live candidates need confirmed opening evidence; disliked cuisines reject.
- Cuisine, price/range, rating floor and selected route limit are checked.
- Missing facts remain unknown; transit routes are not invented from speed estimates.
- Hard wishes can turn budget/travel issues into explicit advisories. Depending
  on the remaining checks, these can accompany matches or alternatives; the
  code does not promise every over-budget result is always an alternative.
- Official halal requires BRC evidence. Google halal indications remain
  unofficial. Missing vegetarian evidence produces an explicit uncertainty.
- AI order influences results while deterministic eligibility still applies.
  Previous results can be deprioritized for repeat searches.

The CLI uses configured display limits. The web gateway can supply per-call
limits without changing global configuration; BIS handles combined cuisine
limits and result annotations.

## BRC, navigation and presentation

`HalalVerificationCoordinator` runs only when halal is requested. It uses a
batch verification capability where available and validates returned MUIS
status/certification. If BRC fails, Google-indicated candidates remain visibly
unofficial; no failure creates official evidence.

`NavigationService.route_to()` requests directions and constructs a Google
Maps link from known coordinates. `RecommendationSorter` uses rating/distance
strategies without re-running AI or Places. CLI presentation delegates to
`common/recommendation_ui.py`; web presentation is returned through BIS IO.

## Storage and configuration

MongoDB `restaurants` stores facts keyed by `google_place_id`. Fields include
name, address, postal/contact data, Google rating/review count, cuisine/dietary
information, price range, weekly hours, accessibility, halal status and
coordinates. The shared record mapper preserves the JSON-format domain fields.
Missing new values can retain known saved values.

`search_history` stores request/summary metadata under request-local user
identity. BIS retrieves/deletes web history through `BRNSService`, not by
accessing the BRNS store directly. JSON mode uses the configured restaurant
and history paths. `BITEFINDER_AUTO_SEED` controls optional catalog seeding when
an external catalog exists and the Mongo collection is empty.

Configuration is in `config.py` and the root environment: `BITEFINDER_STORAGE`,
`MONGO_URI`, `MONGO_DATABASE`, `USE_LIVE_GOOGLE`, provider keys, Maps key,
`BRNS_AI_REQUEST_TIMEOUT_SECONDS`, `BRNS_AI_CHAIN_TIMEOUT_SECONDS`,
`BRC_SERVICE_URL` and endpoint overrides. See [root setup](../README.md).

Required provider/schema failures stop recommendation. BRNS JSON stores can
return empty collections for missing/corrupt files; Mongo failures raise explicit
unavailable errors. Web BIS can translate recognized no-open-restaurant errors
into empty results with a message. Those policies are distinct from successful
AI ranking.

## Tests

```powershell
docker compose exec bis-brns python tests/run_tests.py brns
docker compose exec bis-brns python tests/run_tests.py blackbox
docker compose exec bis-brns python tests/run_tests.py integration
docker compose exec bis-brns python tests/run_tests.py oop
docker compose --profile test run --rm web-test
```

Fixtures exercise the request boundary, ranking/reason validation, outcome
policy, enrichment, provider fallback, sorting, BRC isolation and persistence.
[ProjectFlow.md](../ProjectFlow.md) maps these stages to the complete application.
