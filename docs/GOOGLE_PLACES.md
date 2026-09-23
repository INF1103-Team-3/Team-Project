# Google restaurant discovery

BiteFinder uses Places API (New) to discover restaurants automatically from a
latitude/longitude and search radius. It uses Google's API, with one bounded
nearby request per search. It does not crawl Google Maps pages.

## Setup and usage

Inject your existing Google Maps key into the container environment as
`GOOGLE_MAPS_API_KEY`. The associated project needs Places API (New) enabled,
billing configured, and key restrictions compatible with server-side Places
requests. Keep existing spending limits and quotas. The app reads environment
variables only; it does not read mounted secrets or automatically load `.env`.

Run a noninteractive discovery:

```sh
python3 main.py --discover-google 1.3 103.8 --radius-m 1000 --limit 20
```

This prints attributed results and automatically saves deduplicated place IDs in
`google_place_ids.json` under `BITEFINDER_DATA_DIR` (default `data`). Exit status is
0 for success, including no results, 1 for service/storage errors, and 2 for
invalid command syntax. This command can be called by a scheduler; scheduling is
not enabled automatically and each invocation may incur API charges.

For interactive use, run `python3 main.py`, select a profile, then choose `g`.
Choose `n` for nearby discovery or `s` to view the latest 20 saved IDs. Selecting
one result/ID fetches live details, including its website and reported hours when
available. Each selection makes one details request; saved IDs are not refreshed
in bulk. All saved IDs remain available in the local JSON file.

## Request limits and data handling

- Nearby search accepts a radius of 1–50,000 metres and 1–20 results, ordered by
  distance. It is not an exhaustive list of restaurants in the area.
- Each request has a 20-second timeout, a 1 MB response limit, and no automatic
  retries. API errors do not expose response bodies or credentials.
- Explicit field masks request basic discovery fields and attribution. Only an
  explicit details lookup requests website, hours, open-now status and price
  level. Field selection affects billing; details include Enterprise-tier fields.
- Only place IDs are persisted. Google names, addresses, coordinates, hours and
  other content stay in memory and are displayed with Google Maps/provider
  attribution. They are not stored in the restaurant catalog, history or logs,
  sent to AI, or used in the routing cache.
- Missing values remain unknown. General price level does not establish a meal
  price. Discovery cannot verify dietary requirements, allergens or cross-contact.

Google's [Places policies](https://developers.google.com/maps/documentation/places/web-service/policies)
restrict content storage and explicitly exempt place IDs. Before distributing a
public application, provide the publicly accessible terms and privacy policy
required by those policies. See the official
[Nearby Search documentation](https://developers.google.com/maps/documentation/places/web-service/nearby-search)
and [Place Details documentation](https://developers.google.com/maps/documentation/places/web-service/place-details)
for request fields, limits and billing categories.

To grow the meal recommendation catalog, collect independently sourced menu and
price evidence from restaurant websites, then use the
[reviewed import workflow](DATA.md#importing-reviewed-data). Google results remain
separate discovery leads; copying their content into an import is not this flow.

## Validation

Tests use synthetic responses and make no paid requests. They cover request
bounds, field masks, errors, attribution, deduplication, corrupt-file preservation,
CLI behavior and persistence of IDs only. Live API verification still requires an
injected key with Places API (New) access.
