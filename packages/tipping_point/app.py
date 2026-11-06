"""Tipping Point FastAPI application factory.

``app`` is the module-level instance for local development and the
offline smoke tests; tests can build isolated instances with explicit
settings via ``create_app``. /health/live remains a pure liveness
probe — it does not claim database or sponsor readiness.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .api import auth_routes, material_routes, workshop_routes
from .settings import AppSettings

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_AUTH_PATHS = frozenset(
    {
        "/api/auth/csrf",
        "/api/merchant/login",
        "/api/merchant/logout",
        "/api/me",
    }
)


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Build the application with explicit security configuration."""
    settings = settings or AppSettings()
    settings.validate_startup()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Refuse unsafe hosted configurations before serving requests.
        settings.validate_startup()
        yield

    app = FastAPI(
        title="Tipping Point",
        description="Sandbox-only workshop booking application",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def validate_browser_origin(request: Request, call_next):
        # Origin validation for state-changing requests: an Origin
        # header that is not a configured application origin is
        # rejected. Absent Origin (same-origin/non-browser) is allowed
        # and remains covered by SameSite + CSRF tokens. Wildcard
        # credentialed CORS is never enabled (no CORS middleware).
        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in settings.origins:
                response = JSONResponse(
                    status_code=403, content={"detail": "origin not allowed"}
                )
                if request.url.path in _AUTH_PATHS:
                    response.headers["Cache-Control"] = "no-store"
                    response.headers["Pragma"] = "no-cache"
                return response
        response = await call_next(request)
        if request.url.path in _AUTH_PATHS:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    app.include_router(auth_routes.router)
    app.include_router(workshop_routes.router)
    app.include_router(material_routes.router)

    @app.get("/health/live")
    async def health_live():
        """Liveness probe only; no database or sponsor claims."""
        return {"status": "ok"}

    return app


app = create_app()