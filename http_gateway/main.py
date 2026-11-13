"""FastAPI composition and lifecycle; domain behavior lives in OOP subsystems."""
from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from http_gateway.routes import register_routes


def create_app(runtime_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        factory = runtime_factory
        if factory is None:
            from http_gateway.dependencies import build_runtime
            factory = build_runtime
        app.state.runtime = await run_in_threadpool(factory)
        try:
            yield
        finally:
            await run_in_threadpool(app.state.runtime.close)

    docs_enabled = os.getenv("BITEFINDER_EXPOSE_DOCS", "0") == "1"
    app = FastAPI(
        title="BiteFinder API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    @app.exception_handler(PermissionError)
    async def permission_error(_request: Request, error: PermissionError):
        return JSONResponse({"detail": str(error)}, status_code=401)

    @app.exception_handler(ValueError)
    async def invalid_input(_request: Request, error: ValueError):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def unavailable(_request: Request, error: RuntimeError):
        return JSONResponse({"detail": str(error)}, status_code=503)

    register_routes(app)
    return app


app = create_app()
