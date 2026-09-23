# Restaurant evidence and data maintenance

The starter dataset contains three real Saizeriya outlets in central Singapore.
It is intentionally small and has limited cuisine coverage. Names and addresses
come from the [official outlet directory](https://www.saizeriya.com.sg/search/).
Three menu items and listed SGD prices come from the
[official menu](https://www.saizeriya.com.sg/menu/mobilemenu/grand_menu/menu.php).
Cuisine comes from the [restaurant website](https://www.saizeriya.com.sg/).
These pages were checked on 2026-09-23. Prices and availability can change.
The chain menu is applied to these outlets; check current availability locally.

Coordinates are the destination pins (`!3d` and `!4d`) in the Google Maps links
provided by the official outlet directory, not inferred coordinates or the map
viewport center. They identify a restaurant pin, not a verified accessible
entrance. Walking routes cannot account for indoor mall access.

No dietary certification, allergen absence, or cross-contact safety has been
verified. Those fields are empty and hard dietary/allergy searches will exclude
these records. Generic chain hours mention holiday closures without dates;
opening hours remain unknown until outlet-specific schedules and exceptions can
be verified. Open-now searches therefore exclude these starter records.

`data/sources.json` stores reference URLs, evidence types, and verification dates.
Source metadata does not automatically make a claim true: a maintainer must
check that each source supports the specific fact recorded. The runtime validates
record shape and source references; it does not independently verify webpages.

Restaurant records have `restaurant_id`, `name`, `address`, `location` (latitude,
longitude or null), `cuisines`, `source_ids`, `opening_hours` and `menu`.
Each menu item has `name`, `price` (or null), `currency` (`SGD`), `food_tags`,
`source_ids`, `dietary` and `allergen_free`. Diet and allergy dictionaries are
keyed by lowercase input tags. Confirmed claims need `confirmed: true`, an
`evidence_type` of `official` or `restaurant_reported`, and supporting `source_ids`.
Allergy claims also need `cross_contact_excluded: true` to pass a hard filter.
Do not infer these claims from a dish name or omitted ingredient.

Opening schedules use an IANA `timezone`, supporting `source_ids`, a `weekly`
dictionary keyed by weekday (`0` Monday to `6` Sunday), and optional date
`exceptions`. Each value is a list of `["HH:MM", "HH:MM"]` intervals. Missing
weekdays mean unknown; empty lists mean closed. End times at/before start times
cross midnight; equal times mean 24-hour service. A date exception with an empty
list closes that entire date, including overnight service from the previous day.

Test fixtures in `tests/support.py` are explicitly synthetic and never loaded as
production restaurant data. Extend real data only with checked source evidence.


## Importing reviewed data

1. Create the `data/incoming` directory (or `incoming` under `BITEFINDER_DATA_DIR`).
2. Prepare a `.json` bundle with exactly two top-level arrays: `sources` and
   `restaurants`, using the record formats above and the bundled data as reference.
3. Include every source referenced by the incoming records. Each source needs a
   unique `source_id`, a public HTTPS `source_reference`, `evidence_type`, and
   `collected_at`/`last_verified_at` dates in `YYYY-MM-DD` format.
4. Run the CLI, choose `i`, and enter only the JSON filename. Review the full
   preview against the cited sources, then confirm to save.

Each bundle supports 1–100 restaurants and 1–100 sources, up to 1 MB. Importing
adds records; it does not overwrite existing restaurants or redefine a source ID.
Duplicate restaurant IDs and matching names/addresses (ignoring case and repeated
spaces) reject the entire bundle. This is a basic duplicate check; spelling variants
and address abbreviations still need human review. A source ID may be reused only
with exactly matching metadata. Dietary/allergy claims require official or
restaurant-reported source metadata as well as the evidence fields described above.

Validated additions are saved together in `data/catalog_imports.json` through one
atomic write. Source and restaurant additions cannot be partially saved. Searches
combine this file with the bundled catalog. Corrupt imports stop catalog loading
and are preserved for repair. Failed validation, cancellation and failed saves leave
existing data unchanged. Files are restricted to `data/incoming`; path traversal
and symbolic-link escapes are rejected. Incoming files and saved imports are ignored
by Git and excluded from the Docker image. Mount your data directory to persist them.

Validation checks structure and references, not whether the webpage supports the
claims. The person confirming an import must verify the factual evidence. No API
key or network request is needed for a reviewed JSON import.


## AI-assisted source extraction

Choose `x` in the CLI to turn a supplied public source excerpt into draft records.
This uses the existing `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`; no additional
credential is required. Put a JSON file under `data/incoming` with exactly:

- `source`: one source metadata object (the same fields used by JSON imports).
- `text`: the public source excerpt, up to 20,000 characters.

Supply only text you have checked and are allowed to send to the model provider.
The application does not crawl or fetch the URL; it sends the supplied excerpt and
metadata to OpenRouter. Never put credentials or private documents into an excerpt.
Extraction makes at most two requests (one schema-repair retry), each with a
20-second timeout and a 4,000-token response limit. HTTP/network failures are not
retried. The same provider account and spending limits apply.

The model may extract up to five restaurants. Records need a literal name, address
and at least one menu item. Each restaurant/menu item includes an `evidence_quote`
copied verbatim from the excerpt, no longer than 1,000 characters. Names, addresses,
cuisine/food tags and numeric prices are checked against those quotes. A numeric
price needs an explicit `SGD` or `S$` marker and one unambiguous amount in its quote;
bare `$`, other currencies and missing prices must remain null. Quotes are retained
in saved records for later review.

The AI cannot establish dietary/allergy safety claims, coordinates or opening
schedules through this flow. Those fields must remain empty/null. Such information
can be added only through separately reviewed source-backed data. Extra AI fields,
unknown source references and conflicting catalog identities are rejected.

Grounding tests catch missing or invented text, but cannot prove that an amount
belongs to the right meal or that an excerpt is true/current. You must inspect the
full draft and supporting source before confirming. Cancellation or failed checks
leave the catalog unchanged. Confirmed drafts use the same atomic import path as
manual JSON bundles. If the excerpt lacks complete records, the CLI explains the
limitation instead of inventing missing facts.
