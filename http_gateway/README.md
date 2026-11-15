# HTTP Gateway — FastAPI transport for BIS

`http_gateway/` owns HTTP route registration and ASGI lifecycle. It delegates
application work exclusively to BIS web IO; it does not import BRNS/BRC domain
services or own ranking, account persistence or verification rules.

| File | Responsibility |
| --- | --- |
| `main.py` | `create_app()`, `app`, lifespan construction/cleanup and error handlers |
| `routes.py` | Thin `/api/*` handlers using `request.app.state.runtime.io` |
| `dependencies.py` | Delegate to `BIS.runtime.build_web_runtime()` |

BIS composes repositories and services, then calls `BRNSService` through the
BRNS runtime boundary. BRNS owns BRC integration. See
[ProjectFlow.md](../ProjectFlow.md) and [BIS/README.md](../BIS/README.md).

## Start and access

```powershell
docker compose up -d --build --wait web
```

The browser uses nginx on `http://localhost:8080`; `/api/` is proxied to
`api:8000`. API port `8000` is internal and is not published on the host.
The web runtime requires `BITEFINDER_STORAGE=mongo`, reachable MongoDB, and BRC
configuration. Compose supplies `MONGO_URI`, `MONGO_DATABASE` and
`BRC_SERVICE_URL`. Importing the app does not start Docker or open a browser.

For host API development with dependencies and services already configured:

```powershell
$env:BITEFINDER_STORAGE = "mongo"
$env:MONGO_URI = "mongodb://127.0.0.1:27017/"
uvicorn http_gateway.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Supply a reachable BRC URL for halal checks. `BITEFINDER_EXPOSE_DOCS=1` enables
FastAPI `/docs`, `/redoc` and `/openapi.json` on the API itself. The current
nginx configuration proxies **only `/api/`**, so it does not expose those docs
paths through `localhost:8080`. API schema exposure is disabled by default.

## Routes and authentication

| Routes | Purpose |
| --- | --- |
| `GET /api/health`, `/api/cuisines`, `/api/active-model` | Mongo readiness, vocabulary and model display metadata |
| `POST /api/auth/register`, `/api/auth/login` | Account signup/login and OTP or configured bypass flow |
| `POST /api/auth/verify-otp`, `/api/auth/resend-otp` | Verify/resend challenges |
| `GET /api/auth/me`, `POST /api/auth/logout` | Resolve/revoke bearer session |
| `GET /api/profile`, `POST /api/profile` | Read/write authenticated owner's profile |
| `POST /api/search`, `/api/chat`, `/api/route` | Search, conversational filter/profile actions and navigation |
| `GET /api/favorites`, `POST /api/favorites`, `DELETE /api/favorites` | User bookmarks; delete selects `place_key` |
| `GET /api/history`, `/api/recent-searches`, `DELETE /api/history` | User search summaries/recent queries and deletion |

Authenticated calls use `Authorization: Bearer <token>`. Profile writes,
favorite mutations and history deletion require a valid user. Guest search,
chat and route requests are supported; guest favorites/history reads return
empty lists. Public profiles do not include password hashes or session digests.

New passwords require 8–128 characters. With SMTP bypass disabled, auth uses
real email challenges. `SMTP_BYPASS=true` also bypasses **web** OTP and can
complete legacy enrollment; it is a testing shortcut, not email ownership proof.

## Search and chat contracts

`SearchRequestModel` accepts the form fields and optional `locations`,
`liked_cuisines`, `confirm_only` and `confirmation_token`. BIS resolves origins,
computes a midpoint, creates individual cuisine requests and merges results
through Logic. `/api/search` runs directly unless `confirm_only=true` requests
a stored proposal; its returned token can be consumed once for continuation.

`/api/chat` returns an action, reply, filters, changes, quick replies and
clarification state. The browser applies these to the form and triggers search
only on the relevant action. Supported profile saves require authentication.
AI chat has deterministic fallback parsing. Model display metadata can describe
a configured/current provider; it is not proof that a specific request used it.

Permission errors map to 401, domain/input `ValueError` to 400, and unavailable
`RuntimeError` to 503. Pydantic transport validation uses 422. Recognized no-open
search outcomes can be returned by BIS as successful empty results with a
message; malformed AI and database failures must not be confused with those.

## Verification and shutdown

```powershell
docker compose --profile test run --rm web-test
docker compose --profile test run --rm -e MONGO_TEST_URI=mongodb://mongodb:27017/ web-test
docker compose exec -T api python tests/web/smoke_stack.py
docker compose --profile "*" down
```

Normal web tests inject external collaborators and use mongomock. The optional
Mongo URI enables an isolated real database test. Stack smoke checks require
running services; they do not run a live paid recommendation. See
[tests/README.md](../tests/README.md). Shutdown preserves named data volumes.
