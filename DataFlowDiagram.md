# BiteFinder Data Flow Diagram

This document shows how BiteFinder data changes shape and trust state as it
moves from user input through BIS, AI providers, BRNS, BRC, external fact
providers, and JSON storage.

For control flow and decision branches, see [ProjectFlow.md](ProjectFlow.md).
The diagrams below focus on **what data enters a process, how it is transformed,
and where the validated result is stored**.

## Diagram notation

| Shape or label | Meaning |
| --- | --- |
| Rectangle | Person, external provider, or another BiteFinder subsystem |
| Rounded process | A manager that transforms or validates data |
| Cylinder | Durable JSON file, cache, or log |
| `raw` | Untrusted text or provider response |
| `proposed` | Parsed structure that still requires validation |
| `validated` | Structure accepted by deterministic application rules |
| `persisted` | Validated structure written to durable storage |

## Level 0: complete project data flow

```mermaid
flowchart LR
    USER["User"]
    BIS(["BIS<br/>account, profile, and search input"])
    BRNS(["BRNS<br/>recommendation and navigation"])
    BRC(["BRC<br/>official halal checker"])
    AI["AI providers"]
    GOOGLE["Google Geocoding, Places, and Routes"]
    MUIS["MUIS halal directory"]
    SMTP["SMTP server"]

    USERS[("BIS user and state JSON")]
    GEO[("Shared geocode cache")]
    RESTAURANTS[("BRNS restaurants JSON")]
    HISTORY[("BRNS search history JSON")]
    HALAL[("BRC raw and cleaned halal JSON")]
    CHECKS[("BRC check caches and outputs")]
    LOG[("Shared BiteFinder log")]

    USER -->|"raw account, preference, command, and search text"| BIS
    BIS -->|"prompt plus bounded interpretation task"| AI
    AI -->|"untrusted structured proposal"| BIS
    BIS -->|"validated account and confirmed preferences"| USERS
    BIS <-->|"location query and validated coordinates"| GEO
    BIS -->|"validated in-memory search JSON"| BRNS

    BRNS -->|"search query, origin, and route constraints"| GOOGLE
    GOOGLE -->|"untrusted place and route facts"| BRNS
    BRNS -->|"candidate IDs and normalized facts"| AI
    AI -->|"untrusted ranking and reason codes"| BRNS
    BRNS -->|"candidate restaurant objects when halal is required"| BRC

    MUIS -->|"raw official establishment listings"| BRC
    BRC -->|"uncached establishment names and addresses"| AI
    AI -->|"untrusted cuisine tags or match proposal"| BRC
    BRC -->|"raw snapshot and validated official database"| HALAL
    BRC -->|"validated check result and MUIS evidence"| CHECKS
    BRC -->|"shape-preserving checked restaurant objects"| BRNS

    BRNS -->|"normalized restaurant facts"| RESTAURANTS
    BRNS -->|"small validated search summary"| HISTORY
    BRNS -->|"matches, alternatives, exclusions, and routes"| BIS
    BIS -->|"formatted results and actions"| USER
    BIS -->|"verification code or selected Maps link"| SMTP

    BIS -->|"stage, count, outcome, and trace ID"| LOG
    BRNS -->|"stage, count, outcome, and trace ID"| LOG
    BRC -->|"stage, count, outcome, and trace ID"| LOG
```

The AI providers never receive authority to write files directly. Their output
returns to the calling AI manager, then passes through schema checks, business
logic, and sometimes user confirmation before a data manager can persist it.

## Level 1: BIS account and profile data

```mermaid
flowchart TD
    U1["Raw signup input<br/>email and username"] --> IO1(["BIS IO Manager<br/>collect input"])
    IO1 --> L1(["BIS Logic and schema<br/>normalize and validate"])
    L1 -->|"invalid"| IO1
    L1 -->|"normalized account candidate"| D1(["BIS Data Manager<br/>assign userID"])
    D1 --> USERS[("BIS/data/users.json")]

    D1 --> CHALLENGE(["Email verification service<br/>create salted code hash"])
    CHALLENGE --> SMTP["SMTP provider<br/>six-digit code"]
    SMTP --> U2["User inbox"]
    U2 -->|"raw six-digit answer"| CHALLENGE
    CHALLENGE -->|"attempt, resend, expiry, and verification state"| STATE[("BIS/data/profile_state.json")]
    CHALLENGE -->|"verified account flag"| D1

    U3["Raw profile answer"] --> IO2(["BIS IO Manager<br/>identify profile field"])
    IO2 --> DECIDE{"Free text interpretation needed?"}
    DECIDE -->|"No"| L2(["BIS Logic<br/>validate typed value"])
    DECIDE -->|"Yes"| PROMPT["AI payload<br/>task, allowed schema, raw answer, current profile"]
    PROMPT --> AIP["BIS AI provider"]
    AIP -->|"untrusted JSON text"| PARSE(["BIS AI Manager<br/>parse and validate envelope"])
    PARSE -->|"invalid"| IO2
    PARSE -->|"proposed correction or structured value"| CONFIRM{"User confirms proposal?"}
    CONFIRM -->|"No"| IO2
    CONFIRM -->|"Yes"| L2
    L2 -->|"invalid or conflicting"| IO2
    L2 -->|"validated profile update"| D2(["BIS Data Manager<br/>merge with account"])
    D2 --> USERS
```

### Profile state transformation

| Stage | Example | State |
| --- | --- | --- |
| User input | `wesaten italian` | Raw text; not saved |
| AI request | Task, supported cuisine list, current values, and raw text | Bounded interpretation payload |
| AI response | `{"cuisines":["Western","Italian"]}` | Proposed and untrusted |
| User confirmation | User accepts corrected cuisines | Confirmed proposal |
| Logic result | Unique supported cuisines with liked/disliked conflicts removed | Validated profile value |
| Data write | Value merged into the account keyed by `userID` | Persisted in `BIS/data/users.json` |

Simple values still pass through validation even when no AI call is needed.
Declined corrections and invalid provider responses are not persisted.

## Level 1: search request and AI payloads

```mermaid
flowchart TD
    RAW["Raw search answers<br/>location, mode, limit, cuisine, budget, special request"]
    RAW --> SIO(["BIS IO Manager<br/>collect and confirm choices"])

    SIO -->|"address, postal code, or landmark"| CACHE{"Shared geocode cache hit?"}
    CACHE -->|"Yes"| POINT["Validated Singapore origin<br/>label, latitude, longitude"]
    CACHE -->|"No"| GEOCODE["Google Geocoding response"]
    GEOCODE --> GVALID(["BIS validation<br/>parse and require Singapore coordinates"])
    GVALID --> POINT
    GVALID -->|"successful aliases and point"| GEO[("data/geocode_cache.json")]

    SIO --> TEXT["Special request text"]
    TEXT --> WPAYLOAD["BIS AI wording payload<br/>raw text plus saved requests"]
    WPAYLOAD --> WAI["BIS AI provider"]
    WAI -->|"untrusted corrected text and equivalence proposal"| WVALID(["BIS AI parser and Logic validation"])
    WVALID --> WCONFIRM{"User confirms wording and hard constraints?"}
    WCONFIRM -->|"No"| SIO
    WCONFIRM -->|"Yes"| CONFIRMED["Confirmed search choices"]
    POINT --> CONFIRMED

    CONFIRMED --> IPAYLOAD["BIS AI search payload<br/>confirmed fields plus required output schema"]
    IPAYLOAD --> IAI["BIS AI provider"]
    IAI -->|"untrusted search proposal JSON"| IPARSE(["BIS AI Manager<br/>parse, type-check, and validate schema"])
    IPARSE --> ILOGIC(["BIS Logic Manager<br/>protect every confirmed value"])
    ILOGIC -->|"conflict or missing value"| SIO
    ILOGIC -->|"validated request dictionary"| SERIALIZE(["BIS Data Manager<br/>serialize compact JSON"])
    SERIALIZE --> REQUEST["In-memory BIS to BRNS request"]
```

The BIS-to-BRNS request is a transient JSON message rather than a BIS profile
file. It contains the confirmed origin, travel mode and limit, traffic setting,
cuisine, budget, dietary requirements, disliked cuisines, and other
preferences. BRNS validates the complete message again at its IO boundary.

## Level 2: BRNS recommendation data

```mermaid
flowchart TD
    REQ["Validated BIS search JSON"] --> RIO(["BRNS IO Manager<br/>validate exact keys, types, and ranges"])
    RIO --> SOURCE{"Restaurant source"}

    SOURCE -->|"Live"| QUERY["Google Places query<br/>origin, radius, cuisine, and request text"]
    QUERY --> GOOGLE["Raw Google place records"]
    GOOGLE --> NORMAL(["BRNS IO Manager<br/>normalize candidate facts"])
    NORMAL --> ROUTE["Google Routes matrix<br/>origin, candidate points, and travel mode"]
    ROUTE --> CANDIDATES["Normalized in-memory candidates<br/>facts plus current route values"]

    SOURCE -->|"Offline fallback"| RFILE[("BRNS/data/restaurants.json")]
    RFILE --> NORMAL_OFFLINE(["BRNS IO Manager<br/>validate saved fact records"])
    NORMAL_OFFLINE --> CANDIDATES

    CANDIDATES --> RPAYLOAD["BRNS AI payload<br/>request, candidate IDs, normalized facts, prior result names"]
    RPAYLOAD --> RAI["BRNS AI provider"]
    RAI -->|"untrusted ordered IDs and reason codes"| RPARSE(["BRNS AI Manager<br/>parse and validate envelope"])
    RPARSE -->|"every ID exactly once"| JOIN(["Join ranking back to original candidate facts"])
    RPARSE -->|"missing, duplicate, or unknown ID"| STOP["Stop without completed search storage"]

    JOIN --> HALAL{"Halal requested?"}
    HALAL -->|"Yes"| BRC["BRC checked restaurant objects"]
    HALAL -->|"No"| RULES(["BRNS Logic Manager"])
    BRC --> RULES

    RULES -->|"facts satisfy requirements"| MATCH["Validated matches"]
    RULES -->|"useful but misses or relaxes a condition"| ALT["Validated alternatives and cautions"]
    RULES -->|"closed, disliked, unsupported, or hard mismatch"| EXCLUDED["Exclusion counts and reasons"]

    MATCH --> RESULT["Validated result dictionary"]
    ALT --> RESULT
    EXCLUDED --> RESULT
    CANDIDATES --> SAVE_FACTS(["BRNS Data Manager<br/>upsert normalized facts by Google place ID"])
    SAVE_FACTS --> RFILE
    RESULT --> SAVE_HISTORY(["BRNS Data Manager<br/>retain small approved summary"])
    SAVE_HISTORY --> HISTORY[("BRNS/data/search_history.json")]
    RESULT --> BIS["BIS result menu and user display"]
```

BRNS sends candidate facts to the model with small numeric identifiers. The
model returns ordering and controlled reason codes, not replacement restaurant
facts. BRNS joins the IDs back to the original candidates and checks each reason
against the factual record before displaying it.

### Restaurant fact transformation

| Stage | Data form | Storage effect |
| --- | --- | --- |
| Google response | Provider-specific place, rating, review, price, hours, and accessibility fields | None; untrusted |
| Normalized candidate | Stable internal keys, parsed numbers, coordinates, cuisines, dietary hints, and routes | In memory |
| AI ranking | Candidate IDs in order plus controlled reason codes | In memory; untrusted until validated |
| Logic result | Match, alternative, or exclusion with grounded reasons | In memory; validated |
| Restaurant upsert | Public fact fields keyed by `google_place_id`; earlier known values retained when a later response omits them | `BRNS/data/restaurants.json` |
| Search summary | Source, origin coordinates, travel mode, cuisine, and top IDs or names | `BRNS/data/search_history.json` |

Raw Google responses, raw prompts, and raw AI responses are not copied into the
restaurant or search-history files.

## Level 2: BRC database and verification data

```mermaid
flowchart TD
    MUIS["MUIS directory API<br/>raw establishment pages"] --> SCRAPE(["BRC scraper<br/>normalize listings and prove prefix coverage"])
    SCRAPE --> RAW[("BRC/data/muis_establishments.json<br/>raw snapshot plus completeness metadata")]
    SCRAPE --> PROGRESS[("BRC/data/scrape_progress.json")]
    SCRAPE --> ONEMAP["OneMap geocoding"]
    ONEMAP --> OCACHE[("BRC/data/onemap_cache.json")]

    RAW --> BIO(["BRC IO Manager<br/>validate complete raw snapshot"])
    BIO --> CCACHE[("BRC/data/cuisine_tags_cache.json")]
    BIO --> CPAYLOAD["BRC AI payload<br/>only uncached names and addresses"]
    CPAYLOAD --> CAI["Gemini cuisine tagging"]
    CAI -->|"untrusted cuisine JSON"| CVALID(["BRC AI validation"])
    CVALID -->|"validated completed batches"| CCACHE
    CVALID --> CLEAN(["BRC Logic Manager<br/>remove invalid, expired, duplicate, and non-eating records"])
    CLEAN --> HALALDB[("BRC/data/halal_restaurants.json<br/>clean official halal database")]

    INPUT["One restaurant object or shape-preserving array from BRNS"] --> CHECKIO(["BRC IO Manager<br/>validate records and query likely MUIS candidates"])
    HALALDB --> CHECKIO
    CHECKIO --> EXACT{"One deterministic outlet match?"}
    EXACT -->|"Yes"| VERIFY(["BRC Logic<br/>verify postal, name, address, unit, and certificate validity"])
    EXACT -->|"Ambiguous"| MPAYLOAD["BRC AI match payload<br/>restaurant and bounded MUIS candidates"]
    MPAYLOAD --> MAI["Gemini outlet proposal"]
    MAI -->|"untrusted candidate ID or null"| MVALID(["BRC AI schema validation"])
    MVALID --> VERIFY
    EXACT -->|"No candidate"| NOTVERIFIED["Validated not_verified result"]
    VERIFY -->|"all deterministic checks pass"| VERIFIED["Official certification plus MUIS evidence"]
    VERIFY -->|"check fails"| NOTVERIFIED
    VERIFIED --> OUTPUT["Shape-preserving checked restaurant JSON"]
    NOTVERIFIED --> OUTPUT
    OUTPUT --> CHECKCACHE[("BRC/data/checked_restaurants_cache.json")]
    OUTPUT --> LAST[("BRC/data/checked_restaurant.json<br/>or checked_restaurants.json")]
    OUTPUT --> BRNS["Return checked object or array to BRNS"]
```

Cuisine AI work is checkpointed after completed batches. If a provider quota
is exhausted, the next database build loads the saved tags and submits only
remaining records. An AI outlet match is only a proposal; deterministic BRC
Logic must verify the exact outlet before certification becomes `official`.

## Durable data stores

| Store | Writer | Stored state | Primary reader |
| --- | --- | --- | --- |
| `BIS/data/users.json` | BIS Data | Accounts, verification flag, and saved profile preferences | BIS |
| `BIS/data/profile_state.json` | BIS Data and email verification service | Verification challenge, display preference, and other per-user session state | BIS |
| `data/geocode_cache.json` | Shared geocode cache | Normalized query aliases mapped to validated coordinates | BIS and BRNS |
| `BRNS/data/restaurants.json` | BRNS Data | Normalized restaurant facts and offline fallback records | BRNS |
| `BRNS/data/search_history.json` | BRNS Data | Approved compact search summaries | BRNS repeat/history logic |
| `BRC/data/muis_establishments.json` | BRC scraper/Data | Raw normalized MUIS snapshot and completeness proof | BRC database build |
| `BRC/data/halal_restaurants.json` | BRC Data | Clean deduplicated official halal establishments | BRC checker |
| `BRC/data/cuisine_tags_cache.json` | BRC Data | Completed cuisine tags keyed by stable establishment identity | BRC AI/database build |
| `BRC/data/checked_restaurants_cache.json` | BRC Data | Reusable outlet verification outcomes | BRC checker |
| `BRC/data/checked_restaurant.json` | BRC Data | Most recent single checked object | Developer or integration consumer |
| `BRC/data/checked_restaurants.json` | BRC Data | Most recent checked array | Developer or integration consumer |
| `BRC/data/scrape_progress.json` | BRC scraper/Data | Completed and pending postal-prefix work | BRC scraper resume |
| `BRC/data/onemap_cache.json` | BRC scraper/Data | MUIS outlet geocoding results | BRC scraper |
| `logs/bitefinder.log` | Shared logger | Timestamp, severity, trace ID, event, and concise outcome | Developers and operators |

Application JSON writes use their owning data boundary. Critical account, BRC,
and shared-cache writes use temporary files and atomic replacement so a failed
write retains the previous valid file where supported.

## Data that remains transient

The following data is used in memory and is not intentionally stored as a
complete durable record:

- plaintext SMTP verification codes;
- raw AI prompts and raw provider response bodies;
- API keys and SMTP passwords;
- the complete serialized BIS-to-BRNS request;
- complete Google Places and Routes response bodies;
- rejected AI proposals;
- full user conversations; and
- route results that have not been selected for display.

The shared log stores operational stages, counts, error types, and trace IDs.
It must not contain credentials, verification codes, complete provider bodies,
email addresses, or full private user input.

## Failure-state data flow

```mermaid
flowchart LR
    INPUT["Raw input or provider response"] --> VALIDATE(["Schema and deterministic validation"])
    VALIDATE -->|"valid"| NEXT["Next manager or approved storage"]
    VALIDATE -->|"invalid"| ERROR["Concise user-facing error"]
    VALIDATE -->|"invalid"| EVENT["Sanitized event, error type, and trace ID"]
    EVENT --> LOG[("logs/bitefinder.log")]
    ERROR --> RETRY["Retry the current prompt or return to command loop"]
```

Invalid or incomplete data does not advance to the next trust state. A failed
BIS AI proposal does not call BRNS. Invalid BRNS ranking does not create a
completed search summary. An unverified BRC proposal does not grant official
halal status. Existing valid files remain the fallback when an atomic update
cannot be completed.

