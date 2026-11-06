"""Print the runtime database identity through the configured application engine.

Never prints passwords or credential-bearing URLs.
"""

from tipping_point.db.engine import engine


def main() -> None:
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            db = conn.execute(text("SELECT current_database()")).scalar()
            session_user = conn.execute(text("SELECT session_user")).scalar()
            current_user = conn.execute(text("SELECT current_user")).scalar()
            rows = conn.execute(
                text(
                    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole "
                    "FROM pg_roles WHERE rolname = ANY(:names) ORDER BY rolname"
                ),
                {"names": [session_user, current_user]},
            ).all()
            print("connection: OK")
            print("current_database:", db)
            print("session_user:", session_user)
            print("current_user:", current_user)
            for row in rows:
                print(
                    f"role {row[0]}: LOGIN={row[1]} SUPERUSER={row[2]} "
                    f"CREATEDB={row[3]} CREATEROLE={row[4]}"
                )
    except Exception as exc:  # noqa: BLE001 - report sanitized failure only
        print("connection: FAILED")
        print("error_type:", type(exc).__name__)
        message = str(exc)
        password = engine.url.password
        if password:
            message = message.replace(password, "***")
        print("error_message:", message[:300])


if __name__ == "__main__":
    main()