"""Merchant authentication service.

Opaque server-side sessions: the cookie carries a cryptographically
random token; only its SHA-256 hash is persisted. Login rotates the
session (a valid presented session is revoked and replaced). Logout
revokes server-side. Bounded in-memory throttling is applied per login
identifier.

Throttling scope and limitations (documented, deliberate): the failure
window lives in process memory, so it is per-worker, resets on
restart, and is not shared across processes. It is keyed on the login
identifier only — never on IP addresses or forwarded headers, which
are untrusted. It is a bounded MVP control, not a distributed
rate-limiting system.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Merchant, MerchantCredential, MerchantSession
from .passwords import dummy_verify, verify_password


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    """SHA-256 hex digest of an opaque secret token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_login(login_identifier: str) -> str:
    return login_identifier.strip().lower()


class LoginRejected(Exception):
    """Raised when credentials are invalid (message is intentionally generic)."""


class LoginThrottled(Exception):
    """Raised when the bounded failure window is exhausted."""


@dataclass
class _ThrottleState:
    failures: int = 0
    window_start: float = field(default_factory=time.monotonic)


# Process-wide failure window shared by all service instances (each
# HTTP request constructs a fresh service). In-memory only: per
# worker, resets on restart, not shared across processes. Keyed on the
# normalized login identifier — never on IPs or forwarded headers.
# Bounded to _MAX_THROTTLE_KEYS entries with expired-window pruning and
# oldest-entry eviction so memory cannot grow without bound.
_MAX_THROTTLE_KEYS = 4096
_THROTTLE: dict[str, _ThrottleState] = {}
_THROTTLE_LOCK = threading.Lock()


class MerchantAuthService:
    """Login, logout, and session resolution for merchants."""

    def __init__(
        self,
        session: Session,
        *,
        ttl_hours: int,
        max_failures: int,
        window_minutes: int,
    ) -> None:
        self._session = session
        self._ttl = timedelta(hours=ttl_hours)
        self._max_failures = max_failures
        self._window_seconds = window_minutes * 60

    # -- login / logout --------------------------------------------------

    def login(
        self,
        login_identifier: str,
        password: str,
        *,
        rotate_session_token: str | None = None,
    ) -> tuple[Merchant, MerchantSession, str, str]:
        """Authenticate and create a fresh session (rotating any presented one).

        Returns (merchant, session_row, raw_session_token, raw_csrf_token).
        Raises LoginThrottled or LoginRejected.
        """
        normalized = _normalize_login(login_identifier)
        self._enforce_throttle(normalized)

        credential = self._session.scalars(
            select(MerchantCredential).where(
                func.lower(MerchantCredential.login_identifier) == normalized
            )
        ).first()
        if credential is None:
            # Comparable verification cost for unknown logins so the
            # generic rejection cannot be timed for enumeration.
            dummy_verify(password)
            self._record_failure(normalized)
            raise LoginRejected("invalid login credentials")
        if not verify_password(password, credential.password_hash):
            self._record_failure(normalized)
            raise LoginRejected("invalid login credentials")

        self._clear_failures(normalized)

        # Session rotation: a valid presented session is revoked before
        # the fresh session is issued.
        if rotate_session_token is not None:
            existing = self._resolve_row(rotate_session_token)
            if existing is not None:
                existing.revoked_at = _now()

        merchant = self._session.get(Merchant, credential.merchant_id)
        assert merchant is not None  # FK guarantees existence
        row, session_token, csrf_token = self._create_session(merchant.id)
        return merchant, row, session_token, csrf_token

    def logout(self, session_token: str) -> bool:
        """Revoke the session server-side. Returns True when it was active."""
        row = self._resolve_row(session_token)
        if row is None:
            return False
        row.revoked_at = _now()
        return True

    # -- session resolution ----------------------------------------------

    def _create_session(
        self, merchant_id: uuid.UUID
    ) -> tuple[MerchantSession, str, str]:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        row = MerchantSession(
            merchant_id=merchant_id,
            token_hash=hash_token(session_token),
            csrf_token_hash=hash_token(csrf_token),
            expires_at=_now() + self._ttl,
        )
        self._session.add(row)
        self._session.flush()
        return row, session_token, csrf_token

    def _resolve_row(self, session_token: str) -> MerchantSession | None:
        row = self._session.scalars(
            select(MerchantSession).where(
                MerchantSession.token_hash == hash_token(session_token)
            )
        ).first()
        if row is None:
            return None
        if row.revoked_at is not None:
            return None
        if row.expires_at <= _now():
            return None
        return row

    def resolve_session(
        self, session_token: str
    ) -> tuple[MerchantSession, Merchant] | None:
        """Resolve a session token to its (session, merchant), if active."""
        row = self._resolve_row(session_token)
        if row is None:
            return None
        merchant = self._session.get(Merchant, row.merchant_id)
        assert merchant is not None
        return row, merchant

    # -- bounded throttling -----------------------------------------------

    def _enforce_throttle(self, normalized: str) -> None:
        now = time.monotonic()
        with _THROTTLE_LOCK:
            state = _THROTTLE.get(normalized)
            if state is None:
                return
            if now - state.window_start > self._window_seconds:
                del _THROTTLE[normalized]
                return
            if state.failures >= self._max_failures:
                raise LoginThrottled("too many failed login attempts")

    def _record_failure(self, normalized: str) -> None:
        now = time.monotonic()
        with _THROTTLE_LOCK:
            state = _THROTTLE.get(normalized)
            if state is not None and now - state.window_start <= self._window_seconds:
                state.failures += 1
                return
            if len(_THROTTLE) >= _MAX_THROTTLE_KEYS:
                expired = [
                    key
                    for key, entry in _THROTTLE.items()
                    if now - entry.window_start > self._window_seconds
                ]
                for key in expired:
                    del _THROTTLE[key]
                if len(_THROTTLE) >= _MAX_THROTTLE_KEYS:
                    oldest_key = min(
                        _THROTTLE, key=lambda k: _THROTTLE[k].window_start
                    )
                    del _THROTTLE[oldest_key]
            _THROTTLE[normalized] = _ThrottleState(failures=1, window_start=now)

    def _clear_failures(self, normalized: str) -> None:
        with _THROTTLE_LOCK:
            _THROTTLE.pop(normalized, None)