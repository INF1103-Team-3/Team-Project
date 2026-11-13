# frontend — Static Web Interface

`frontend/` contains the single-page browser UI for BiteFinder, served statically
by nginx (`http://localhost:8080`) using [common/nginx.conf](../common/nginx.conf).

## Structure

| Path | Role |
| --- | --- |
| `index.html` | Main HTML layout, filter/chat panels, results view, route drawer, and modals |
| `css/tailwind.css` | Pre-built Tailwind CSS bundle |
| `css/styles.css` | Custom UI styles |
| `js/api.js` | Shared `apiJson()` fetch wrapper sending `Authorization` headers to `/api/*` |
| `js/state.js` | Browser state, theme, bearer token storage (`bitefinder_auth_token`), escaping, and helpers |
| `js/auth.js` | Registration, password login, OTP verification, session check, and favorites sync |
| `js/chatbot.js` | Guided onboarding and natural-language AI chat controls |
| `js/filters.js` | Multi-location inputs, travel mode/limits, cuisines, budget, and recent queries |
| `js/results.js` | Result cards, match/alternative rendering, badges, sorting, and favorite toggles |
| `js/compare.js` | Side-by-side restaurant comparison tray and modal |
| `js/map.js` | Interactive Leaflet map markers and turn-by-turn route drawer |
| `js/modals.js` | Accessible modal focus and close helpers |
| `js/toast.js` | Toast notification helper |
| `js/main.js` | Application bootstrap wiring frontend modules and initial session check |

## Local Serving

nginx serves `frontend/` at `/` and proxies `/api/`, `/docs`, and `/openapi.json`
to the FastAPI `api` container (`http://api:8000`). Start the web stack with:

```powershell
docker compose up -d --build --wait web
```
