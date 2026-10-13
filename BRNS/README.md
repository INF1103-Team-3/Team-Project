# BRNS — BiteFinder Recommendation and Navigation System

BRNS accepts one confirmed BIS search request, gathers restaurant and route
facts, requires AI to rank the current candidate set, applies deterministic
business rules, optionally checks halal candidates through BRC, saves validated
facts, and returns matches and alternatives.

BRNS normally runs inside BIS. It can also run independently by reading one
search JSON object from standard input:

```bash
python BRNS/main.py < search_request.json
```

## Responsibilities

BRNS owns:

- validation of the BIS-to-BRNS JSON boundary;
- live Google Places text and nearby searches;
- Google Routes distance and duration matrices;
- walking, driving, traffic-aware driving, and transit route retrieval;
- normalization and enrichment using saved restaurant facts;
- AI ordering of every current candidate identifier;
- grounding of AI reason codes in known restaurant facts;
- hard and soft requirement evaluation;
- confidence-adjusted rating comparisons using review counts;
- open-now checks using Singapore time and weekly hours;
- classification into matches, alternatives, and exclusions;
- BRC handoff for halal searches;
- result sorting, Google Maps links, and selected-result routes;
- restaurant-fact upserts and search-history persistence.

BRNS does not collect an interactive profile or ask the user search questions.
BIS owns that interaction and passes a complete request.

## Manager flow

```text
BIS JSON
  -> BRNS I/O: validate request and gather current candidates
  -> BRNS AI: return every candidate ID once in ranked order
  -> BRC when halal is requested: add official or unofficial evidence
  -> BRNS Logic: validate reasons and classify each candidate
  -> BRNS Data: save facts and a validated search summary
  -> BRNS I/O: display results or return them to BIS
```

`main.py` coordinates the stages and stops the search when input, candidate
retrieval, or AI ranking cannot be completed safely.

## Files

| Path | Purpose |
| --- | --- |
| `main.py` | Search orchestration, BRC verification, result sorting, selected-result routing, and standalone entry point |
| `io_manager.py` | BIS request boundary, Google Places and Routes clients, saved-record enrichment, and restaurant/result displays |
| `ai_manager.py` | Provider/model chain, ranking prompt, JSON parsing, schema validation, and grounded reason-code contract |
| `logic_manager.py` | Hard and soft requirements, scoring, matches, alternatives, exclusions, opening hours, sorting, and required interfaces |
| `data_manager.py` | Restaurant schema conversion, upserts, search-history summaries, and generic save/load/query functions |
| `config.py` | Root environment loading, endpoints, provider chain, display limits, and data paths |
| `data/restaurants.json` | Saved live facts and offline restaurant fallback |
| `data/search_history.json` | Validated search summaries; ignored by Git |

## Accepted request contract

`io_manager.accept_bis_json()` accepts a JSON object with only the supported
search fields. The request contains:

| Field | Meaning |
| --- | --- |
| `origin` | Confirmed label, Singapore latitude, and longitude |
| `mode` | `walk`, `drive`, or `transit` |
| `max_distance_km` | Active distance limit or `null` |
| `max_travel_minutes` | Active time limit or `null` |
| `traffic_aware` | Boolean used only by supported driving-time searches |
| `cuisine` | Supported cuisine or `none` |
| `budget_per_person` | Positive SGD maximum |
| `dietary_requirements` | `halal`, `vegetarian`, both, or neither |
| `disliked_cuisines` | Cuisines that must be rejected |
| `other_preferences` | Confirmed soft and hard natural-language requests |

The boundary rejects extra or missing fields, invalid types and ranges,
overseas coordinates, incompatible limit combinations, and unsupported modes
before Places or BRNS AI is called.

## Candidate sources

### Live Google mode

With `USE_LIVE_GOOGLE=true`, BRNS requires `GOOGLE_MAPS_API_KEY` and:

1. Builds a nearby-search radius from the active travel limit.
2. Uses the complete special-request wording in Google text search when useful.
3. Retrieves restaurant names, addresses, place IDs, types, coordinates,
   ratings, review counts, price data, accessibility, and opening information.
4. Merges saved fields by Google place ID where live data is missing.
5. Requests a route matrix for the selected mode.
6. Excludes live candidates without usable current opening evidence.

### Offline restaurant mode

With `USE_LIVE_GOOGLE=false`, BRNS loads `data/restaurants.json`. Offline mode
is a demonstration and outage fallback; it does not remove the BRNS AI
requirement. Saved route data is cleared rather than presented as a current
verified route.

## BRNS AI contract

Before spending a Places request, BRNS checks that at least one provider is
configured. The provider chain can use direct Gemini, OpenRouter, and optional
Groq models from separate credential pools.

The ranking prompt receives:

- the validated search request;
- one factual summary for each candidate;
- minimum and preferred rating interpretation;
- hard cuisine and hard-preference flags;
- confidence-adjusted rating values;
- previously returned restaurant names for repeat searches.

The AI must return:

```json
{
  "recommendations": [
    {"id": 0, "reason_codes": ["within_budget", "within_route"]}
  ]
}
```

Every supplied ID must appear exactly once. Duplicate, missing, unknown, or
wrongly typed IDs invalidate the response. Reason codes are limited to the
documented set and are checked again by Logic against candidate facts.

Supported reason codes include cuisine match, verified budget and route fit,
rating evidence, vegetarian options, unofficial halal indication, and spicy
options. An unsupported claim is dropped and logged with the candidate facts.

## Recommendation rules

`logic_manager.rank_restaurants()` normalizes each candidate and calls
`decide_outcome()`.

Important rules include:

- disliked cuisines reject a candidate;
- `only`, `must`, `exclusively`, `minimum`, and `at least` can create hard
  requirements after BIS confirmation;
- hard cuisine and minimum-rating requirements are enforced;
- when hard special requests exist, budget and travel limits can be relaxed
  only into clearly labelled alternatives;
- official halal is accepted only after BRC verification;
- a Google halal indication remains unofficial;
- vegetarian matches require supported dietary facts;
- price checks use the known restaurant range rather than assuming a starting
  price proves the entire meal fits;
- rating quality combines stars and review count by shrinking small samples
  toward a 4/5 prior;
- live candidates must be open at the current Singapore day and time;
- missing transit routes are never replaced with speed estimates;
- repeat searches prefer suitable unseen restaurants but still return every AI
  ranked candidate to Logic.

Results contain separate `matches`, `alternatives`, hidden/excluded counts,
travel metadata, requested dietary requirements, and optional halal
verification details.

## BRC integration

When halal is not requested, BRNS does not call BRC.

When halal is requested:

1. BRNS follows the validated AI recommendation order.
2. Each candidate is shaped as one BRC restaurant object.
3. BRC checks it against the cleaned MUIS database.
4. A verified certificate and matching outlet set
   `halal_certification` to `official`.
5. An unverified Google-indicated candidate stays `unofficial`.
6. A candidate with neither accepted MUIS nor Google evidence is excluded.
7. If BRC fails or times out, remaining Google-indicated candidates may
   continue only as visibly unofficial fallback results.

In local Python, BRNS imports `BRC.main` directly. In Docker Compose,
`sitecustomize.py` substitutes a compatible client that calls the private BRC
container service.

## Result presentation

Compact cards show restaurant name, location, cuisine, Google rating, route
distance or time, and important cautions. Full details can include:

- address and phone number;
- rating and review count;
- estimated price range;
- today's and weekly opening hours;
- dietary and halal status;
- wheelchair-accessibility evidence;
- factual fit reasons and checks;
- route steps and transit line details.

If no match exists, BRNS explains exclusion totals, official verification
status, and why the leading alternative is not an exact match before offering
alternatives.

## Routing and sorting

`route_to()` requests a selected restaurant route only when verified
coordinates are available. A Google Maps URL is always prepared from the
confirmed origin, destination, and mode. Traffic-aware driving is passed to
the route provider when selected.

`sort_results()` reorders the existing matches and alternatives by rating or
distance. It preserves the match/alternative classification and does not spend
another Places or AI request.

## Restaurant persistence schema

Saved records are upserted by `google_place_id` and include available values
for:

```text
google_place_id
name
postal_code
address
number
g_rating
g_no_reviews
cuisine
dietary
avg_price_low_sgd
avg_price_high_sgd
opening_hours
wheelchair_accessible
halal_certification
latitude
longitude
```

Known values are retained when a later response omits them. Weekly opening
hours use compact `HHMM` ranges. Halal certification from Google remains
`unofficial`; only verified BRC output can become `official`.

Search history stores a small validated summary instead of raw API responses.
Live searches store top Google place IDs, while offline searches store top
restaurant names.

## Configuration

Key settings from the root `.env`:

```text
DEBUG
OPENROUTER_API_KEY
GEMINI_API_KEY
GROQ_API_KEY
BITEFINDER_OPENROUTER_URL
BITEFINDER_GEMINI_URL
BITEFINDER_GROQ_URL
GOOGLE_MAPS_API_KEY
USE_LIVE_GOOGLE
```

Endpoint environment overrides allow black box tests to redirect geocoding,
Places, matrices, routes, and AI calls to local fixture servers.

## Failure behavior

- Invalid BIS JSON stops before external requests or saved search history.
- Missing provider credentials stop before Places spending.
- No usable candidates returns an explicit search error.
- Invalid AI output stops recommendation and does not save a completed search.
- Unsupported AI reasons are removed rather than displayed.
- Missing route coordinates disable routing for that result.
- Corrupt or missing restaurant/history files log the problem and return empty
  collections where safe.
- BRC failure is summarized and only evidence-backed Google fallback survives.
- All search events share the BIS trace ID in `logs/bitefinder.log`.

## Tests

Run BRNS-focused suites from the repository root:

```bash
python tests/test_blackbox_brns.py
python -m unittest tests.test_unit_brns_ai -v
python -m unittest tests.test_unit_brns_logic -v
python -m unittest tests.test_unit_data_manager.TestBRNSDataManager -v
python -m unittest tests.test_bis_brns_integration -v
python tests/test_blackbox_bis_to_brns.py
```

The black box suite starts the real standalone entry point, posts fixed AI,
Places, and Routes responses from a local server, and verifies both visible
output and external call order.

## Extending BRNS

- Add external restaurant and route calls to `io_manager.py`.
- Add AI fields only with prompt, parser, schema, Logic, and test changes in the
  same update.
- Keep final acceptance, scoring, and factual reason checks in
  `logic_manager.py`.
- Persist only normalized evaluated facts through `data_manager.py`.
- Maintain the exact BIS request boundary and update both applications
  together when it changes.
- Update [the root flow document](../ProjectFlow.md) for new result or failure
  branches.

