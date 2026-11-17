# Frontend — BiteFinder browser interface

The browser application is static HTML/CSS and JavaScript ES modules, served
by the Docker nginx image at `http://localhost:8080`. Same-origin `/api/`
requests go through [common/nginx.conf](../common/nginx.conf) to FastAPI, then
BIS. The frontend never connects to MongoDB, BRNS or BRC directly.

## Modules

| Path | Responsibility |
| --- | --- |
| `index.html` | Filter/chat panels, results, route drawer and modal layout |
| `css/tailwind.css`, `css/styles.css` | Pre-built Tailwind bundle and custom styles |
| `js/main.js` | Bootstrap and module wiring |
| `js/api.js` | JSON fetch wrapper and bearer authorization headers |
| `js/state.js` | Shared UI state, token persistence, escaping and helpers |
| `js/auth.js` | Signup/login, OTP, profile, favorites and history interaction |
| `js/chatbot.js` | Onboarding, chat messages, clarification and form synchronization |
| `js/filters.js` | Locations, travel limits, cuisine validation, budget, search/refresh and AbortController cancellation |
| `js/results.js` | Cards, sorting, alternatives, badges and bookmark controls |
| `js/compare.js` | Comparison tray/modal for two or three existing results |
| `js/map.js` | Leaflet markers and selected restaurant route drawer |
| `js/modals.js`, `js/toast.js` | Modal focus/close behavior and notifications |

## User flow

Users can search as guests or sign in to use saved account actions. New
passwords must be 8–128 characters. Auth uses password plus OTP when SMTP bypass
is disabled; `SMTP_BYPASS=true` also enables the server's web bypass.

Filters accept multiple origins, travel mode and one limit, driving traffic,
budget, dietary needs, selected/custom cuisine terms, dislikes and wishes.
BIS computes a midpoint and orchestrates/merges cuisine searches. Chat can
collect missing values, update these same filters and explicitly save supported
preferences for a signed-in user.

The normal form posts a direct `/api/search` request. Chat's confirmation step
triggers that form submission. The API's separate `confirm_only`/proposal-token
mechanism is available, but the regular form does not use it by default.

Result cards display known facts, cautions and official/unofficial halal labels.
Users can sort existing results, view maps/routes, compare up to three
restaurants, bookmark restaurants and revisit history. Browser comparison is
presentation over returned facts; it does not reclassify eligibility or make
new verification calls.

Bearer tokens, recent locations and UI preferences use local browser storage.
Signed-in favorites/profiles/history are server-backed in MongoDB; guest local
recent queries are not the same store as authenticated history. HTML escaping
helpers are used when inserting dynamic text.

### Search cancellation and repeat searches

The search/cancel controls use an `AbortController`, including model polling.
Cancelling restores the prior displayed results and controls, preserves seen
restaurant tracking and ignores the cancelled response. It cancels the browser's
request; it does not roll back a backend search already running or guarantee
that AI/Maps work and persistence stop. There is no server cancellation endpoint.
Different Results sends up to 200 seen venues through BIS with strict exclusion;
exhaustion offers a reset instead of inventing new matches.

Custom cuisine Add actions call `/api/validate-cuisines`; ordinary keystrokes
do not submit a new cuisine. Local syntax feedback complements BIS validation,
which also runs for profile, chat and direct search requests. Travel/budget
controls retain an explicit unset state until selected.

## Build, run and inspect

```powershell
docker compose up -d --build --wait web
# After changing frontend source, rebuild its image.
docker compose up -d --build web
# Optional Mongo administration; separate from the website.
docker compose --profile dev up -d mongo-express
```

Open the website at `http://localhost:8080`; mongo-express is at
`http://localhost:8081`. Frontend files are copied into the image, not mounted
from the host. Opening `index.html` as a local file does not provide the API
proxy or a working same-origin application.

Only `/api/` is proxied. FastAPI docs are disabled by default and are not
proxied at `/docs` even if enabled on the API. AI/SMTP/Mongo credentials remain
server-side. `/api/map-config` intentionally returns the configured browser Maps
key (preferring `GOOGLE_MAPS_JS_API_KEY`, otherwise the Maps key); a supplied key
is browser-visible. Map configuration selects Google Maps or the Leaflet path.

Backend contracts use mocked services in `tests/web/`; the HTTP stack smoke
checks static delivery and API/service readiness. Those checks do not prove
browser rendering or every interactive UI path. Manual review should cover
login/OTP, filters/chat, a controlled search, comparison, favorites/history and
route rendering and cancellation. See [the test guide](../tests/README.md).
The offline Node suite resolves the cache-versioned module URLs imported by
`main.js`, so tests and modules share the same state object. It exercises both
refresh and abort recovery; it is not a visual browser test.

```powershell
docker compose --profile "*" down
```

This shuts down all profiles while preserving saved named volumes.
