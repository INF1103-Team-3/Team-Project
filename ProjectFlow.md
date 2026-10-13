# BiteFinder Project Flow

This document shows the complete BiteFinder workflow and its major decision
branches. BiteFinder consists of three procedural applications:

- **BIS** collects accounts, profiles, and today's search request.
- **BRNS** finds, ranks, filters, and routes to restaurants.
- **BRC** builds a cleaned MUIS dataset and verifies halal candidates.

## Complete application flow

```mermaid
flowchart TD
    A[Start BiteFinder CLI] --> B[BIS I/O: sign up, resume, or quit]
    B -->|Sign up| C[Validate email and username]
    B -->|Resume| D[Load account by email]
    B -->|Quit| Z[Goodbye]
    C --> E[Send and verify six-digit email code]
    D --> E
    E -->|Verification fails| B
    E -->|Verified or SMTP test bypass| F{Profile complete?}

    F -->|No| G[BIS I/O: collect the next preference]
    G --> H[BIS AI: interpret or correct free text]
    H --> I[BIS Logic: validate typed update]
    I -->|Invalid or declined| G
    I -->|Accepted| J[BIS Data: save account and preferences]
    J --> F

    F -->|Yes| K[BIS command loop]
    K -->|Profile and help| L[BIS I/O: display information]
    L --> K
    K -->|Edit, add, remove, reset, or color| M[BIS managers: validate and save change]
    M --> K
    K -->|Logout| B
    K -->|Quit| Z
    K -->|Search or natural-language search command| N[BIS I/O: collect today's choices]

    N --> O[BIS AI: interpret confirmed choices and special request]
    O -->|Provider or schema failure| X[BIS I/O: show error with trace ID]
    O --> P[BIS Logic: protect confirmed values and validate JSON]
    P -->|Needs clarification| N
    P -->|User declines| K
    P -->|Confirmed| Q[BIS Data: serialize validated search JSON]

    Q --> R[BRNS I/O: validate BIS JSON and gather candidates]
    R -->|No candidates or external failure| X
    R --> S[BRNS AI: rank candidate IDs and reason codes]
    S -->|All AI providers fail or output is invalid| X
    S --> T{Halal required?}
    T -->|No| U[BRNS Logic: classify matches, alternatives, and exclusions]
    T -->|Yes| V[BRC: check candidates against cleaned MUIS data]
    V -->|Official match| W[Mark candidate officially halal]
    V -->|Not verified| Y{Google indicates halal?}
    V -->|BRC unavailable| Y
    Y -->|Yes| AA[Keep as clearly labelled unofficial fallback]
    Y -->|No| AB[Exclude from halal results]
    W --> U
    AA --> U
    AB --> U

    U --> AC[BRNS Data: save restaurant facts and search summary]
    AC --> AD[BIS and BRNS I/O: display matches or no-match explanation]
    AD --> AE{Results action}
    AE -->|Details| AF[Show full restaurant facts]
    AE -->|Sort| AG[Sort existing results by rating or distance]
    AE -->|Route| AH[Google route or Maps link]
    AE -->|Email| AI[SMTP: send selected Google Maps link]
    AE -->|Alternatives| AJ[Show non-matching alternatives and cautions]
    AE -->|Change choices| N
    AE -->|Repeat same search| R
    AE -->|Finish| K
    AF --> AE
    AG --> AE
    AH --> AE
    AI --> AE
    AJ --> AE
    X --> K
```

## BIS account and profile branches

```mermaid
flowchart LR
    A[Account menu] --> B{Choice}
    B -->|Sign up| C[Validate email and username]
    B -->|Resume| D[Find saved account]
    B -->|Quit| E[Exit]
    C --> F[Create verification challenge]
    D --> F
    F --> G{Code accepted?}
    G -->|No, attempts remain| H[Retry or resend after cooldown]
    H --> G
    G -->|Attempt window reached| I[Wait for configured reset window]
    I --> F
    G -->|Yes| J[Load profile session]
    J --> K{Missing preference?}
    K -->|Yes| L[I/O collects one answer]
    L --> M{Simple typed answer?}
    M -->|Yes| N[Logic validates locally]
    M -->|Free text or correction needed| O[AI returns structured interpretation]
    O --> P[I/O asks user to confirm correction]
    P -->|Decline| L
    P -->|Accept| N
    N -->|Invalid| L
    N -->|Valid| Q[Data saves profile]
    Q --> K
    K -->|No| R[Enter command loop and optional first search]
```

Saved profile fields are locations, distance and time estimates, budget,
dietary requirements, liked cuisines, disliked cuisines, and reusable special
requests.

## BIS command branches

```mermaid
flowchart TD
    A[User message] --> B{Slash command or natural text?}
    B -->|Recognized slash command| C[Dispatch command]
    B -->|Natural text| D[BIS AI interprets an allowed command]
    D -->|No supported command| E[Ask user to clarify]
    D -->|Supported command| C
    C -->|help| F[Show commands and return]
    C -->|profile| G[Show saved profile and return]
    C -->|edit, add-location, remove-location| H[Collect and save selected field]
    C -->|reset| I[Clear preferences but retain account]
    C -->|color on or off| J[Save display preference]
    C -->|search| K[Start today's search flow]
    C -->|logout| L[Return to account menu]
    C -->|quit or exit| M[Save and close]
    F --> A
    G --> A
    H --> A
    I --> A
    J --> A
```

`/help` and color commands are available while other questions are active and
return the user to the same prompt.

## Search collection and BIS handoff

```mermaid
flowchart TD
    A[Start search] --> B[Choose current location]
    B --> C{Location form}
    C -->|Latitude and longitude| D[Validate Singapore coordinates]
    C -->|Postal code, address, or landmark| E{Shared geocode cache hit?}
    E -->|Yes| F[Use cached coordinates]
    E -->|No| G[Google geocode, validate, and cache]
    D --> H[Confirm location]
    F --> H
    G --> H
    H -->|No| B
    H -->|Yes| I[Choose walk, drive, or transit]
    I -->|Walk or drive| J[Choose distance or journey time]
    I -->|Transit| K[Choose journey time]
    J --> L[Use entered value or compatible profile default]
    K --> L
    L --> M{Drive with time limit?}
    M -->|Yes| N[Choose normal or traffic-aware duration]
    M -->|No| O[Continue]
    N --> O
    O --> P[Choose specific cuisine or none]
    P --> Q[Choose budget]
    Q --> R[Choose saved requests or enter new text]
    R --> S[BIS AI reviews wording and meaning]
    S --> T{Hard language such as only or at least?}
    T -->|Yes| U[Explain reduced-result risk and confirm hard constraint]
    T -->|No| V[Keep as soft preference]
    U --> W[Show complete search summary]
    V --> W
    W -->|No or cancel| X[Return without BRNS search]
    W -->|Yes or Enter| Y[BIS AI produces structured search proposal]
    Y --> Z[BIS Logic validates and preserves confirmed choices]
    Z -->|Conflict| R
    Z -->|Valid and confirmed| AA[BIS Data serializes JSON for BRNS]
```

## BRNS recommendation branches

```mermaid
flowchart TD
    A[BRNS I/O receives BIS JSON] --> B[Validate keys, types, ranges, and coordinates]
    B -->|Invalid| C[Stop without saving search history]
    B -->|Valid| D{USE_LIVE_GOOGLE}
    D -->|True| E[Google Places search and Routes matrix]
    D -->|False| F[Load saved BRNS restaurant JSON]
    E --> G[Normalize candidates and current opening status]
    F --> G
    G -->|No usable candidates| C
    G --> H[BRNS AI ranks every current candidate ID]
    H -->|Malformed or unsupported output| C
    H --> I{Halal requested?}
    I -->|No| J[BRNS Logic applies business rules]
    I -->|Yes| K[BRC verification flow]
    K --> J
    J --> L{Classification}
    L -->|Meets requirements| M[Match]
    L -->|Useful but misses soft or relaxed limits| N[Alternative]
    L -->|Closed, disliked, hard mismatch, or unsupported| O[Excluded]
    M --> P[Order results using AI order and validated facts]
    N --> P
    O --> P
    P --> Q[Data upserts restaurant facts]
    Q --> R[Data saves validated search summary]
    R --> S[Return results to BIS]
```

BRNS grounds every displayed AI reason in candidate facts. Unsupported reason
codes are removed and written to the shared log rather than shown as facts.
Ratings use both the Google score and review count. Live candidates must have
usable current opening information before they can be recommended.

## BRC workflow branches

```mermaid
flowchart TD
    A[BRC main receives no input, one object, or an array] --> B[BRC I/O selects scenario]
    B -->|No restaurant input| C{Fresh raw MUIS snapshot exists?}
    C -->|No| D[Scraper downloads all MUIS eating-establishment records]
    C -->|Yes| E[Load raw snapshot]
    D --> E
    E --> F[Load cuisine tag cache]
    F --> G[BRC AI tags uncached cuisines in batches]
    G --> H[BRC Logic removes expired, duplicate, and non-eating records]
    H --> I[BRC Data saves cleaned halal restaurant database]

    B -->|One object or array| J{Cleaned database exists?}
    J -->|No| C
    J -->|Yes| K[I/O validates restaurants and finds possible MUIS candidates]
    K --> L{One exact deterministic outlet match?}
    L -->|Yes| M[Reuse exact certificate candidate]
    L -->|No candidates| N[Return not verified]
    L -->|Ambiguous candidates| O[BRC AI proposes exact outlet or null]
    M --> P[BRC Logic verifies postal code, name, address, unit, and validity]
    O --> P
    N --> Q[BRC Data saves checked result and cache]
    P -->|Verified| R[Set official certification and MUIS evidence]
    P -->|Not verified| N
    R --> Q
    Q --> S[Return one object or shape-preserving array]
```

BRC can run interactively, accept `--input`, read `--stdin`, or be called by
BRNS. In Docker Compose, BRNS calls the dedicated BRC container through its
private HTTP service.

## Result-action branches

```mermaid
flowchart LR
    A[Results menu] --> B{Action}
    B -->|Details| C[Show ratings, reviews, hours, prices, dietary status, and reasons]
    B -->|Sort| D[Sort current matches and alternatives by rating or distance]
    B -->|Route| E[Request directions and show Google Maps link]
    B -->|Email| F{Verified account and coordinates?}
    F -->|Yes| G[Send Maps link through SMTP]
    F -->|No| H[Explain why email is unavailable]
    B -->|Alternatives| I[Show alternatives and cautions]
    B -->|Change| J[Return to selected search fields]
    B -->|Repeat| K[Run BRNS again and prefer unseen candidates]
    B -->|Enter or finish| L[Return to command loop]
    C --> A
    D --> A
    E --> A
    G --> A
    H --> A
    I --> A
```

## Failure and fallback paths

| Failure | Behavior |
| --- | --- |
| Invalid user answer | BIS I/O explains the accepted form and repeats the same prompt. |
| AI wording correction declined | The original value is not changed or saved. |
| All BIS AI providers fail | Search interpretation stops; BRNS is not called. |
| Invalid BIS search JSON | BRNS rejects the request before Places, AI ranking, or history saving. |
| Google live search disabled | BRNS loads `BRNS/data/restaurants.json`, while BRNS AI ranking remains required. |
| Google or route request fails | The search stops or reports unavailable route facts; route values are not invented. |
| BRNS AI fails or returns invalid IDs | Recommendation stops and no completed search summary is saved. |
| BRC database missing | BRC tries to build it from the raw MUIS snapshot or scraper before checking. |
| BRC unavailable during halal search | Google-indicated halal candidates may continue only as unofficial fallback results. |
| Missing or corrupt saved JSON | The responsible data boundary logs or reports the error and protects existing data. |
| SMTP delivery fails | The account or search session remains usable and the user receives an error. |

## Docker deployment flow

```mermaid
flowchart LR
    A[User terminal] -->|docker compose exec| B[bis-brns container]
    B --> C[BIS CLI]
    C --> D[BRNS search]
    D -->|Private HTTP check| E[brc container]
    E --> F[BRC service and MUIS database]
    B --> G[(bis-brns-data volume)]
    E --> H[(brc-data volume)]
    C --> I[AI, Maps, and SMTP services]
    D --> I
    E --> I
```

The two containers share the private `bitefinder-net` network. The `brc`
container exposes its health and checking service only inside that network.
Named volumes retain application JSON, caches, and logs across container
replacement.

## Main persisted data

| Path or volume area | Purpose |
| --- | --- |
| `BIS/data/users.json` | Accounts and saved profile preferences |
| `BIS/data/profile_state.json` | Search, verification, and display state |
| `BRNS/data/restaurants.json` | Saved Google restaurant facts and offline fallback |
| `BRNS/data/search_history.json` | Validated search summaries |
| `BRC/data/muis_establishments.json` | Raw MUIS scrape snapshot |
| `BRC/data/halal_restaurants.json` | Cleaned official halal database |
| `BRC/data/cuisine_tags_cache.json` | Resumable cuisine tags |
| `BRC/data/checked_restaurants_cache.json` | Previous outlet checks |
| `data/geocode_cache.json` | Shared successful geocoding results |
| `logs/bitefinder.log` | Shared traceable operational log |

