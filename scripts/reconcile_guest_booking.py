"""Inspect persisted guest status; Sandbox retrieval/release requires opt-in.

Configuration is process-environment-only (AppSettings(_env_file=None));
the runner deliberately never loads an environment file.
This runner never creates or authorizes replacement orders.
"""

import argparse
import asyncio
import json
from uuid import UUID

from tipping_point.db.session import SessionLocal
from tipping_point.guest.payments import BookingPaymentService
from tipping_point.guest.service import BookingService
from tipping_point.paypal.client import PayPalGateway
from tipping_point.settings import AppSettings


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("booking_id", type=UUID)
    result.add_argument("--allow-network", action="store_true", help="explicitly permit Sandbox resource retrieval")
    result.add_argument("--known-order-id", help="fully validate a known reference after an unknown create")
    result.add_argument("--release", action="store_true", help="release queued exact authorizations; requires --allow-network")
    return result


async def run(args):
    settings = AppSettings(_env_file=None)
    if not args.allow_network and (args.release or args.known_order_id):
        raise SystemExit("--release and --known-order-id require --allow-network")
    with SessionLocal() as db:
        service = BookingService(db, settings)
        if args.allow_network:
            async with PayPalGateway.from_settings(settings) as gateway:
                payments = BookingPaymentService(db, settings, gateway)
                booking = await payments.reconcile(args.booking_id, args.known_order_id)
                db.commit()
                if args.release:
                    booking = await payments.release_pending(args.booking_id)
        else:
            booking = BookingPaymentService(db, settings, None)._booking(args.booking_id)
        print(json.dumps(service.booking_out(booking).model_dump(mode="json"), sort_keys=True))
        db.commit()


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
