"""Provision isolated PostgreSQL databases for Tipping Point."""

import subprocess
import sys

PSQL = "/usr/local/bin/psql"


def psql(args, check=True):
    return subprocess.run([PSQL, "-h", "localhost", "-p", "5432", "-U", "ohm"] + args, capture_output=True, text=True, check=check)


def main():
    psql(["-c", "SELECT 1 FROM pg_roles WHERE rolname = 'tipping_point_app'"]).check_returncode()
    r = psql(["-t", "-c", "SELECT 1 FROM pg_roles WHERE rolname = 'tipping_point_app'"])
    if r.stdout.strip() == "1":
        print("Role tipping_point_app already exists; leaving unchanged.")
    else:
        psql(["-c", "CREATE ROLE tipping_point_app NOLOGIN"])
        print("Created role tipping_point_app.")

    for db in ("tipping_point_dev", "tipping_point_test"):
        check = psql(["-t", "-c", f"SELECT 1 FROM pg_database WHERE datname = '{db}'"])
        if check.stdout.strip() == "1":
            print(f"Database {db} already exists; leaving unchanged.")
            continue
        psql(["-c", f"DROP DATABASE IF EXISTS {db}"], check=False)
        psql(["-c", f"CREATE DATABASE {db} OWNER tipping_point_app"], check=False)
        psql(["-c", f"GRANT ALL PRIVILEGES ON DATABASE {db} TO tipping_point_app"], check=False)
        print(f"Provisioned database {db}.")

    print("Provisioning complete.")


if __name__ == "__main__":
    main()
