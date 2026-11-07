"""Inspect due settlement work; execution/network each require explicit operator opt-in.

PayPal settings are process-environment-only. No browser or public API triggers this runner.

``--sandbox-test-cleanup`` is the approved Sandbox-only operator-test exception:
it cancels one CONFIRMED test campaign whose frozen cohort is exactly one
booking with one verified GBP 1.00 capture, by refunding that capture through
the existing durable refund ledger. It is scoped to that exact campaign and
cleanup purpose; it never discovers, claims or dispatches other work. Without
``--execute`` it only inspects (no locks, writes or provider calls).
"""

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from tipping_point.db.models import Campaign, SettlementWork
from tipping_point.db.session import SessionLocal
from tipping_point.paypal.client import PayPalGateway
from tipping_point.settings import AppSettings
from tipping_point.settlement.decision import schema_available
from tipping_point.settlement.dispatch import process_due
from tipping_point.settlement.operator_cleanup import (
    ACTION, CleanupRejected, CleanupRequest, inspect_cleanup, request_cleanup, run_cleanup,
)
from tipping_point.settlement.service import SettlementService


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--campaign-id", type=UUID)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--execute", action="store_true", help="permit due-work/decision database transitions")
    p.add_argument("--allow-network", action="store_true", help="permit Sandbox settlement/compensation provider operations")
    p.add_argument("--booking-id", type=UUID, help="booking within the selected campaign for verified-reference recovery")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--known-capture-id")
    group.add_argument("--known-refund-id")
    cleanup = p.add_argument_group("approved Sandbox operator-test cleanup (single-booking GBP 1.00 only)")
    cleanup.add_argument("--sandbox-test-cleanup", action="store_true",
                         help="explicit cleanup action; requires every identifier below")
    cleanup.add_argument("--capture-id", help="exact verified capture ID of the single cohort booking")
    cleanup.add_argument("--expected-amount-minor", type=int, help="must be 100 (GBP 1.00)")
    cleanup.add_argument("--expected-currency", help="must be GBP")
    cleanup.add_argument("--reason", help="operator-test cancellation reason (10-200 printable characters)")
    return p


def _cleanup_request(args):
    missing = [flag for flag, value in (
        ("--campaign-id", args.campaign_id), ("--booking-id", args.booking_id), ("--capture-id", args.capture_id),
        ("--expected-amount-minor", args.expected_amount_minor), ("--expected-currency", args.expected_currency),
        ("--reason", args.reason),
    ) if value is None]
    if missing:
        raise SystemExit("Sandbox test cleanup requires " + " ".join(missing))
    if args.known_capture_id:
        raise SystemExit("Sandbox test cleanup is refund-only; --known-capture-id is not accepted")
    if args.known_refund_id and not (args.execute and args.allow_network):
        raise SystemExit("Known-refund recovery requires --execute --allow-network")
    return CleanupRequest(
        campaign_id=args.campaign_id, booking_id=args.booking_id, capture_id=args.capture_id,
        expected_amount_minor=args.expected_amount_minor, expected_currency=args.expected_currency,
        reason=args.reason, action=ACTION,
    )


async def run_sandbox_cleanup(args, settings):
    request = _cleanup_request(args)
    with SessionLocal() as db:
        if not schema_available(db):
            raise SystemExit("Settlement schema is unavailable; do not execute against an unmigrated database")
        db.commit()
        try:
            if not args.execute:
                return inspect_cleanup(db, settings, request)
            if not args.allow_network:
                # Durable intent/audit/re-armed work only; no provider call.
                return {**request_cleanup(db, settings, request), "provider_calls": "not permitted"}
            async with PayPalGateway.from_settings(settings) as gateway:
                return await run_cleanup(db, settings, gateway, request, known_refund_id=args.known_refund_id)
        except CleanupRejected as error:
            raise SystemExit(f"Sandbox test cleanup rejected: {error.code}") from None


async def run(args):
    if not 1 <= args.limit <= 100:
        raise SystemExit("--limit must be between 1 and 100")
    if args.allow_network and not args.execute:
        raise SystemExit("--allow-network requires --execute")
    settings = AppSettings(_env_file=None)
    if args.sandbox_test_cleanup:
        print(json.dumps(await run_sandbox_cleanup(args, settings)))
        return
    if any(v is not None for v in (args.capture_id, args.expected_amount_minor, args.expected_currency, args.reason)):
        raise SystemExit("Cleanup arguments require the explicit --sandbox-test-cleanup action")
    recovery = args.known_capture_id or args.known_refund_id
    if recovery and not (args.execute and args.allow_network and args.campaign_id and args.booking_id):
        raise SystemExit("Known-reference recovery requires --execute --allow-network --campaign-id --booking-id")
    with SessionLocal() as db:
        if not schema_available(db):
            raise SystemExit("Settlement schema is unavailable; do not execute against an unmigrated database")
        if not args.execute:
            query = select(Campaign).where(Campaign.status.notin_(("DRAFT", "CONFIRMED", "CANCELLED")))
            if args.campaign_id:
                query = query.where(Campaign.id == args.campaign_id)
            rows = list(db.scalars(query.order_by(Campaign.cutoff_at).limit(args.limit)))
            print(json.dumps([{"campaign_id": str(c.id), "state": c.status, "cutoff_at": c.cutoff_at.isoformat()} for c in rows]))
            return
        db.commit()
        if args.allow_network:
            async with PayPalGateway.from_settings(settings) as gateway:
                if recovery:
                    kind = "CAPTURE" if args.known_capture_id else "REFUND"
                    recovered = await SettlementService(db, settings, gateway).recover_reference(
                        args.campaign_id, args.booking_id, kind, recovery)
                    if not recovered:
                        raise SystemExit("Reference could not be validated; no replacement mutation was issued")
                result = await process_due(db, settings, gateway, limit=args.limit, campaign_id=args.campaign_id)
        else:
            result = await process_due(db, settings, None, limit=args.limit, campaign_id=args.campaign_id)
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        asyncio.run(run(parser().parse_args()))
    except Exception as error:
        raise SystemExit(f"Settlement worker stopped: {type(error).__name__}; inspect persisted state before retrying") from None
