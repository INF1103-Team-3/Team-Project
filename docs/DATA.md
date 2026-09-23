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
