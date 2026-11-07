"""Inspect due settlement work; execution/network each require explicit operator opt-in.

PayPal settings are process-environment-only. No browser or public API triggers this runner.
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
from tipping_point.settlement.service import SettlementService


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--campaign-id", type=UUID)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--execute", action="store_true", help="permit due-work/decision database transitions")
    p.add_argument("--allow-network", action="store_true", help="permit Sandbox settlement/compensation provider operations")
    p.add_argument("--booking-id", type=UUID, help="booking within the selected campaign for verified-reference recovery")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--known-capture-id")
    group.add_argument("--known-refund-id")
    return p


async def run(args):
    if not 1 <= args.limit <= 100:
        raise SystemExit("--limit must be between 1 and 100")
    if args.allow_network and not args.execute:
        raise SystemExit("--allow-network requires --execute")
    recovery = args.known_capture_id or args.known_refund_id
    if recovery and not (args.execute and args.allow_network and args.campaign_id and args.booking_id):
        raise SystemExit("Known-reference recovery requires --execute --allow-network --campaign-id --booking-id")
    settings = AppSettings(_env_file=None)
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
