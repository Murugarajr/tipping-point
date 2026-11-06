"""Guard that rejects non-allowlisted database targets before migrations or writes.

Integration tests must only operate on the isolated ``tipping_point_test``
database. This guard is applied before any migration or write so a missing
test configuration can never silently fall back to the development database.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.engine import Engine, make_url

ALLOWED_TEST_DATABASES: frozenset[str] = frozenset({"tipping_point_test"})


def assert_test_database_target(
    target: Engine | str,
    *,
    expected: Iterable[str] | None = None,
) -> str:
    """Return the database name of ``target`` or raise if it is not allowlisted.

    Accepts a SQLAlchemy ``Engine`` or a URL string. Raises ``RuntimeError``
    when the target database is not in the test allowlist, before any
    migration or write can run against it.
    """
    allowed = frozenset(expected) if expected is not None else ALLOWED_TEST_DATABASES
    if isinstance(target, Engine):
        database = target.url.database
    else:
        database = make_url(str(target)).database
    if database not in allowed:
        raise RuntimeError(
            "Refusing to operate on non-test database "
            f"{database!r}; expected one of {sorted(allowed)}."
        )
    return database