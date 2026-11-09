"""Rescue Analyst routes for one owned workshop (read-only).

GET  /api/merchant/workshops/{id}/intelligence/analyst  -> availability + provider/model label (no secrets)
POST /api/merchant/workshops/{id}/intelligence/analyst  -> one bounded, server-side model/tool run

Security: merchant session (401), session-bound CSRF on POST (403), the app's Origin middleware (403),
ownership via the authenticated merchant only (404 for other merchants' workshops), strict request
schema (422), per-merchant throttle and single concurrent run (429/409), server-selected provider and
model, and Cache-Control: no-store. Prompts and answers are not logged.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analyst import AnalystContext, AnalystLimiter, AnalystProviderError, ChatCompletionsClient, PROVIDERS, run_analyst
from ..auth.dependencies import AuthContext, get_auth_context, get_db, require_csrf
from ..db.models import Campaign
from ..economics import CampaignFinancialsInput, calculate_viability
from ..settlement.projections import campaign_projection
from .workshop_routes import _latest_terms, _owned_workshop

router = APIRouter(prefix="/api/merchant")

MAX_MESSAGES = 12
MAX_MESSAGE_CHARS = 2000
MAX_HISTORY_CHARS = 12000


class AnalystMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class AnalystRequest(BaseModel):
    """Only untrusted conversation text. No provider, model, URL, key, headers, prompt or tools."""

    model_config = ConfigDict(extra="forbid")
    messages: list[AnalystMessageIn] = Field(min_length=1, max_length=MAX_MESSAGES)

    @model_validator(mode="after")
    def _shape(self):
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be from the user")
        if sum(len(m.content) for m in self.messages) > MAX_HISTORY_CHARS:
            raise ValueError("conversation history is too long")
        return self


class AnalystStatusOut(BaseModel):
    available: bool
    status: Literal["ready", "disabled", "missing_key", "missing_model"]
    provider: str | None = None
    model: str | None = None


class AnalystActivityOut(BaseModel):
    tool: str
    status: Literal["ok", "rejected", "limit"]
    summary: str


class AnalystVisualizationOut(BaseModel):
    preset: Literal["revenue_vs_costs", "surplus_by_attendance", "material_cost_by_attendance", "attendance_table", "materials_table"]
    title: str | None = None


class AnalystResponseOut(BaseModel):
    status: Literal["answered", "limit_reached"]
    answer: str
    activity: list[AnalystActivityOut]
    visualizations: list[AnalystVisualizationOut]
    provider: str
    model: str
    rounds: int
    tool_calls: int


def _status(request: Request) -> AnalystStatusOut:
    settings = request.app.state.settings
    status = settings.rescue_analyst_status
    preset = PROVIDERS[settings.rescue_analyst_provider]
    return AnalystStatusOut(
        available=status == "ready", status=status, provider=preset.label,
        model=settings.rescue_analyst_model if status == "ready" else None,
    )


def _client(request: Request) -> ChatCompletionsClient:
    settings = request.app.state.settings
    key = settings.rescue_analyst_key()
    return ChatCompletionsClient(
        provider=settings.rescue_analyst_provider,
        api_key=key.get_secret_value() if key is not None else None,
        model=settings.rescue_analyst_model,
        # Tests inject an httpx.MockTransport here; production uses the real network transport.
        transport=getattr(request.app.state, "analyst_transport", None),
    )


def _limiter(request: Request) -> AnalystLimiter:
    limiter = getattr(request.app.state, "analyst_limiter", None)
    if limiter is None:
        limiter = request.app.state.analyst_limiter = AnalystLimiter()
    return limiter


def _error(status: int, code: str, message: str, headers: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message}, headers={"Cache-Control": "no-store", **(headers or {})})


def _context(db: Session, auth: AuthContext, workshop_id: _uuid.UUID) -> AnalystContext:
    workshop = _owned_workshop(db, auth.merchant.id, workshop_id)
    terms = _latest_terms(db, workshop_id)
    inputs = CampaignFinancialsInput.model_validate(terms.financial_inputs)
    report = calculate_viability(inputs)
    campaign = db.scalars(select(Campaign).where(Campaign.terms_id == terms.id)).first()
    projection = campaign_projection(db, campaign) if campaign is not None else None
    # Same rule the guest booking service applies: no new bookings once now >= min(cutoff, terms close).
    cutoff = None
    if campaign is not None:
        cutoff = min((t for t in (campaign.cutoff_at, terms.closes_at) if t is not None), default=None)
    return AnalystContext(
        title=workshop.title, description=workshop.description, terms_version=terms.version,
        published=campaign is not None, campaign_status=campaign.status if campaign is not None else None,
        inputs=inputs, report=report,
        admitted_attendance=projection["admitted_attendance"] if projection else None,
        authorized_minor=projection["authorized_minor"] if projection else None,
        collected_minor=projection["collected_minor"] if projection else None,
        booking_cutoff_at=cutoff,
        bookings_closed=(datetime.now(timezone.utc) >= cutoff) if cutoff is not None else None,
    )


@router.get("/workshops/{workshop_id}/intelligence/analyst", response_model=AnalystStatusOut)
def analyst_status(
    workshop_id: _uuid.UUID, request: Request, response: Response,
    auth: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db),
) -> AnalystStatusOut:
    _owned_workshop(db, auth.merchant.id, workshop_id)
    response.headers["Cache-Control"] = "no-store"
    return _status(request)


@router.post("/workshops/{workshop_id}/intelligence/analyst", response_model=AnalystResponseOut)
def ask_analyst(
    workshop_id: _uuid.UUID, payload: AnalystRequest, request: Request, response: Response,
    auth: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db),
) -> AnalystResponseOut:
    require_csrf(request, auth)
    response.headers["Cache-Control"] = "no-store"
    ctx = _context(db, auth, workshop_id)  # ownership enforced (404 for others)
    status = _status(request)
    if not status.available:
        raise _error(503, "ANALYST_NOT_CONFIGURED", "The analyst is not configured on this server. The dashboard is unaffected.")
    # End the read transaction: no database transaction is held open across provider calls.
    db.commit()
    merchant_key = str(auth.merchant.id)
    limiter = _limiter(request)
    denied = limiter.acquire(merchant_key)
    if denied == "busy":
        raise _error(409, "ANALYST_BUSY", "An analyst request is already running for your account. Wait for it to finish.")
    if denied == "rate_limited":
        raise _error(429, "ANALYST_RATE_LIMITED", "Too many analyst requests. Try again in a few minutes.", {"Retry-After": "60"})
    try:
        result = run_analyst(_client(request), ctx, [m.model_dump() for m in payload.messages])
    except AnalystProviderError as exc:
        raise _error(exc.status, exc.code, type(exc).message) from None
    finally:
        limiter.release(merchant_key)
    return AnalystResponseOut(
        status=result.status, answer=result.answer,
        activity=[AnalystActivityOut(tool=a.tool, status=a.status, summary=a.summary) for a in result.activity],
        visualizations=[AnalystVisualizationOut(**v) for v in result.visualizations],
        provider=status.provider or "", model=status.model or "", rounds=result.rounds, tool_calls=result.tool_calls,
    )
