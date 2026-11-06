"""Operator-only, one-stage-at-a-time PayPal Sandbox authorization/void runner.

Importing this file performs no work.  ``preflight`` is offline by default;
every other stage additionally requires the future explicit ``--allow-network``
flag and must not be run until the operator checklist is approved.
"""

from __future__ import annotations

import argparse
import sys

from tipping_point.paypal.operator_runner import (
    OperatorRunError,
    load_or_create_record,
    run_stage_sync,
)
from tipping_point.settings import AppSettings


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--stage", default="preflight", choices=(
        "preflight", "create", "inspect-order", "authorize",
        "inspect-authorization", "void", "verify-void",
    ))
    command.add_argument("--run-id", required=True)
    command.add_argument("--reference-id", required=True)
    command.add_argument("--expected-payee", required=True)
    command.add_argument("--allow-network", action="store_true")
    return command


def main() -> None:
    args = parser().parse_args()
    try:
        record = load_or_create_record(
            run_id=args.run_id,
            expected_amount_minor=100,
            expected_reference_id=args.reference_id,
            expected_payee=args.expected_payee,
        )
        print(run_stage_sync(
            stage=args.stage,
            record=record,
            settings=AppSettings(),
            allow_network=args.allow_network,
        ))
    except OperatorRunError as exc:
        sys.exit(f"stopped: {exc}")


if __name__ == "__main__":
    main()