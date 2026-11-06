"""Minimal FastAPI application for Tipping Point."""

from fastapi import FastAPI

from . import __version__

app = FastAPI(
    title="Tipping Point",
    description="Sandbox-only workshop booking application",
    version=__version__,
)


@app.get("/health/live")
async def health_live():
    """Liveness probe for the Tipping Point service."""
    return {"status": "ok"}
