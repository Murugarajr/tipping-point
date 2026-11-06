"""Session lifecycle helpers for Tipping Point."""

from contextlib import contextmanager

from sqlalchemy.orm import Session

from .engine import SessionLocal


@contextmanager
def session_scope():
    """Provide a transactional session scope with rollback on error."""
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
