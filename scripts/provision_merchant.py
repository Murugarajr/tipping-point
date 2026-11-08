"""Local operator command to provision the initial merchant account.

Prompts for the login identifier and password interactively (the
password is read with no echo via getpass). Never accepts a plaintext
password as a command-line argument and never logs it. Refuses to
run against the isolated test database, refuses to overwrite an
existing merchant name or login, and never assigns a default
password. Creates the merchant and their credentials in one
transaction.
"""

from __future__ import annotations

import getpass
import re
import sys
import uuid

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from tipping_point.auth.passwords import hash_password
from tipping_point.db.config import DatabaseConfig
from tipping_point.db.engine import SessionLocal
from tipping_point.db.models import Merchant, MerchantCredential
from tipping_point.db.testguard import ALLOWED_TEST_DATABASES

LOGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._@-]{2,63}$")
MIN_PASSWORD_LENGTH = 12


def _prompt(label: str) -> str:
    value = input(label).strip()
    if not value:
        sys.exit("aborted: empty input")
    return value


def _prompt_password() -> str:
    first = getpass.getpass("Password (input hidden, min 12 chars): ")
    if len(first) < MIN_PASSWORD_LENGTH:
        sys.exit(f"aborted: password must be at least {MIN_PASSWORD_LENGTH} characters")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        sys.exit("aborted: passwords do not match")
    return first


def main() -> None:
    # Effective target, including a hosted TIPPING_POINT_DATABASE_URL (password never printed).
    target = make_url(DatabaseConfig().database_url)
    if target.database in ALLOWED_TEST_DATABASES:
        sys.exit(
            f"refusing to provision real credentials against the test "
            f"database {target.database!r}; run against the development database"
        )

    print(f"target database: {target.database} at {target.host}:{target.port}")
    name = _prompt("Merchant display name: ")
    login = _prompt("Login identifier (lowercase): ").lower()
    if not LOGIN_PATTERN.match(login):
        sys.exit("aborted: login must be 3-64 chars of a-z 0-9 . _ @ -")
    password = _prompt_password()
    if login in password.lower():
        sys.exit("aborted: password must not contain the login identifier")

    with SessionLocal() as session:
        if session.scalars(
            select(Merchant).where(Merchant.name == name)
        ).first():
            sys.exit("aborted: a merchant with this name already exists")
        if session.scalars(
            select(MerchantCredential).where(
                func.lower(MerchantCredential.login_identifier) == login
            )
        ).first():
            sys.exit("aborted: this login identifier is already taken")

        merchant = Merchant(id=uuid.uuid4(), name=name)
        session.add(merchant)
        session.flush()
        credential = MerchantCredential(
            id=uuid.uuid4(),
            merchant_id=merchant.id,
            login_identifier=login,
            password_hash=hash_password(password),
        )
        session.add(credential)
        session.commit()
        print(f"provisioned merchant {name!r} with login {login!r}")
        print("password was consumed from hidden input and never stored in plaintext")


if __name__ == "__main__":
    main()