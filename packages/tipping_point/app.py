"""Tipping Point FastAPI application factory.

``app`` is the module-level instance for local development and the
offline smoke tests; tests can build isolated instances with explicit
settings via ``create_app``. /health/live remains a pure liveness
probe — it does not claim database or sponsor readiness.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .analyst import AnalystLimiter
from .api import analyst_routes, auth_routes, guest_routes, material_routes, public_routes, workshop_routes
from .settings import AppSettings

logger = logging.getLogger(__name__)

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
    if settings.rescue_analyst_invalid_settings:
        # Names only: an invalid value is never logged (it could be a credential pasted into the wrong setting).
        logger.warning("Rescue Analyst disabled: invalid setting(s) %s; values not logged. The rest of the application is unaffected.",
                       ", ".join(settings.rescue_analyst_invalid_settings))

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
    app.state.analyst_limiter = AnalystLimiter()

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
                    status_code=403, content={"detail": (
                        {"code": "ORIGIN_NOT_ALLOWED", "message": "Origin not allowed."}
                        if request.url.path.startswith(("/api/guest/", "/api/bookings/", "/api/campaigns/"))
                        else "origin not allowed"
                    )}
                )
                if request.url.path in _AUTH_PATHS or request.url.path.startswith("/api/merchant/"):
                    response.headers["Cache-Control"] = "no-store"
                    response.headers["Pragma"] = "no-cache"
                return response
        response = await call_next(request)
        if request.url.path.startswith(("/api/guest/", "/api/bookings/", "/api/campaigns/")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        if request.url.path in _AUTH_PATHS or request.url.path.startswith("/api/merchant/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    app.include_router(auth_routes.router)
    app.include_router(workshop_routes.router)
    app.include_router(analyst_routes.router)
    app.include_router(material_routes.router)
    app.include_router(public_routes.router)
    app.include_router(guest_routes.router)

    @app.get("/health/live")
    async def health_live():
        """Liveness probe only; no database or sponsor claims."""
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready():
        """Readiness: database reachable and at the expected schema revision.

        Booleans only; no configuration values, versions of secrets or records.
        """
        from .workflows.tasks import readiness_report
        report = readiness_report(settings=settings)
        ready = report["database_reachable"] and report["schema_revision_matches"]
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready",
                     "database": report["database_reachable"], "schema": report["schema_revision_matches"]},
            headers={"Cache-Control": "no-store"},
        )

    if settings.serve_frontend:
        _mount_frontend(app, Path(settings.frontend_dist))

    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA same-origin without swallowing API or health routes."""
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file() or not (dist / "assets").is_dir():
        raise RuntimeError("serve_frontend is enabled but the built frontend (index.html, assets/) is missing")
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="frontend-assets")

    @app.api_route("/{frontend_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend(frontend_path: str):
        first = frontend_path.split("/", 1)[0]
        if first in ("api", "health", "assets"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist / frontend_path).resolve()
        if frontend_path and candidate.is_file() and candidate.parent == dist:
            return FileResponse(candidate)  # top-level public files such as favicon.svg
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()