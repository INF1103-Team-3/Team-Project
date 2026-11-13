# http_gateway — FastAPI ASGI Entrypoint, Routes, and Composition Boundary

`http_gateway/` contains the FastAPI ASGI application (`uvicorn http_gateway.main:app`), HTTP route
registrations, and thin runtime delegation to `BIS.runtime`.

## Files

| File | Responsibility |
| --- | --- |
| `__init__.py` | Package marker |
| `main.py` | FastAPI app factory (`create_app()`, `app`), lifespan wiring, exception handlers, and schema exposure gating |
| `routes.py` | Thin `/api/*` FastAPI route registrations delegating strictly to `BISWebIOInterface` / `WebIOManager` (`request.app.state.runtime.io`) |
| `dependencies.py` | Thin composition boundary delegating exclusively to `BIS.runtime.build_web_runtime()` (keeps `BRNS` and `BRC` hidden from `http_gateway/`) |

## Runtime Requirements

`build_runtime()` (via `BIS.runtime.build_web_runtime()`) requires:

- `BITEFINDER_STORAGE=mongo`
- Reachable MongoDB via `MONGO_URI` and `MONGO_DATABASE` (default `bitefinder`)
- Reachable BRC HTTP service via `BRC_SERVICE_URL` (default `http://brc:8000` in Compose)

Swagger/OpenAPI endpoints (`/docs`, `/redoc`, `/openapi.json`) are disabled by default unless `BITEFINDER_EXPOSE_DOCS=1`.

## API Endpoints

Registered under `/api` by `http_gateway/routes.py`:

- `GET /api/health`, `GET /api/cuisines`, `GET /api/active-model`
- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/verify-otp`, `POST /api/auth/resend-otp`, `GET /api/auth/me`, `POST /api/auth/logout`
- `GET /api/profile`, `POST /api/profile`
- `POST /api/search`, `POST /api/chat`, `POST /api/route`
- `GET /api/favorites`, `POST /api/favorites`, `DELETE /api/favorites`
- `GET /api/history`, `GET /api/recent-searches`, `DELETE /api/history`

## Run & Test

With MongoDB running via [docker-compose.yml](../docker-compose.yml):

```powershell
# Start full web stack (nginx + api + brc + mongodb)
docker compose up -d --build --wait web

# Smoke check nginx -> api -> mongodb/brc
docker compose exec -T api python tests/web/smoke_stack.py

# Web + live MongoDB test suite
docker compose --profile test run --rm -e MONGO_TEST_URI=mongodb://mongodb:27017/ web-test
```

See [BIS/README.md](../BIS/README.md) for the BIS web IO and application services, and [tests/README.md](../tests/README.md) for the web/Mongo test suite.
