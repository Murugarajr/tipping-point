"""Resumable Sandbox checkout. No transaction survives any gateway await.

Claims fence application transitions, not resource discovery: every returned
reference is committed in an audit event before checking a worker's fence.
Unknown create/authorize mutations are never blindly retried.
"""

from dataclasses import dataclass
from datetime import timedelta
import uuid

from sqlalchemy import select

from ..db.models import Booking, BookingEvent, Campaign, PaymentOperation
from ..paypal.client import (
    PayPalError, PayPalRequestError, build_authorization_order_payload,
    validate_sandbox_approve_url,
)
from .service import capacity_count, fail, payload_hash, utcnow


@dataclass(frozen=True)
class OperationClaim:
    operation_id: uuid.UUID
    booking_id: uuid.UUID
    token: uuid.UUID
    version: int
    request_id: str
    kind: str
    scope: str
    payload: dict


def validate_order(booking, order, *, expected_order_id=None, allow_failed_captures=False):
    """Strict full-resource validation; sparse/multi-unit resources fail closed."""
    if (
        (expected_order_id and order.provider_order_id != expected_order_id)
        or order.purchase_unit_count != 1 or order.intent != "AUTHORIZE"
        or order.reference_id != str(booking.id)
        or order.amount_minor != booking.amount_minor or order.currency != "GBP"
        or booking.expected_payee not in (order.payee_identifiers or (order.payee_identifier,))
        or (order.captures and not (allow_failed_captures and all(
            capture.status in ("DECLINED", "DENIED", "FAILED") for capture in order.captures
        )))
    ):
        raise ValueError("order does not match frozen booking expectations")


def validate_authorization(booking, authorization, campaign, settings, *, now=None):
    now = now or utcnow()
    validate_authorization_association(booking, authorization)
    if authorization.status != "CREATED":
        raise ValueError("authorization is not usable")
    created = authorization.create_time
    expires = authorization.expiration_time
    if (
        created is None or expires is None or created.tzinfo is None or expires.tzinfo is None
        or created > now + timedelta(minutes=5)
        or created < booking.created_at - timedelta(minutes=5)
    ):
        raise ValueError("authorization timestamps are invalid")
    required_until = max(campaign.cutoff_at, campaign.settlement_deadline or campaign.cutoff_at)
    required_until += timedelta(hours=settings.authorization_safety_buffer_hours)
    if min(expires, created + timedelta(hours=72)) < required_until:
        raise ValueError("authorization does not cover cutoff and safety buffer")


def validate_authorization_association(booking, authorization, *, authorization_id=None, order_id=None):
    """Validate identity/money even for terminal and release-only resources."""
    if (
        authorization.authorization_id != (authorization_id or booking.provider_authorization_id)
        or authorization.order_id != (order_id or booking.provider_order_id)
        or authorization.amount_minor != booking.amount_minor
        or authorization.currency != "GBP"
    ):
        raise ValueError("authorization does not match booking/order")


class BookingPaymentService:
    def __init__(self, db, settings, gateway):
        self.db = db
        self.settings = settings
        self.gateway = gateway

    def _wake_settlement(self, campaign_id):
        # Only after observation commit: never invert campaign->booking lock order.
        from ..settlement.decision import enqueue, schema_available
        if schema_available(self.db):
            campaign = self.db.scalar(select(Campaign).where(Campaign.id == campaign_id)
                                      .with_for_update().execution_options(populate_existing=True))
            if campaign.status != "OPEN":
                enqueue(self.db, campaign)
        self.db.commit()

    def _booking(self, booking_id, *, lock=False):
        query = select(Booking).where(Booking.id == booking_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        booking = self.db.scalar(query)
        if booking is None:
            fail(404, "BOOKING_NOT_FOUND", "Reservation not found.")
        return booking

    def _operation(self, booking_id, kind, scope, payload):
        operation = self.db.scalar(select(PaymentOperation).where(
            PaymentOperation.booking_id == booking_id, PaymentOperation.kind == kind,
            PaymentOperation.resource_scope == scope,
        ).execution_options(populate_existing=True))
        digest = payload_hash(payload)
        if operation is None:
            operation = PaymentOperation(
                booking_id=booking_id, kind=kind, resource_scope=scope,
                request_payload=payload, request_hash=digest, state="PREPARED",
            )
            self.db.add(operation)
            self.db.flush()
        elif operation.request_hash != digest or payload_hash(operation.request_payload) != digest:
            fail(409, "IDEMPOTENCY_CONFLICT", "The durable payment request differs.")
        return operation

    def claim_operation(self, booking_id, kind, scope, payload, *, retrieval=False):
        booking = self._booking(booking_id, lock=True)
        operation = self._operation(booking_id, kind, scope, payload)
        now = utcnow()
        if operation.state == "IN_FLIGHT" and operation.lease_expires_at and operation.lease_expires_at > now:
            self.db.commit()
            return None
        if operation.state == "IN_FLIGHT":
            operation.state = "UNKNOWN"
            booking.state = "REVIEW_REQUIRED"
        allowed = ("PREPARED", "UNKNOWN", "PROVIDER_PENDING", "SUCCEEDED") if retrieval else ("PREPARED",)
        if operation.state not in allowed:
            self.db.commit()
            return None
        operation.state = "IN_FLIGHT"
        operation.claim_token = uuid.uuid4()
        operation.version += 1
        operation.lease_expires_at = now + timedelta(minutes=2)
        if kind in ("CREATE_ORDER", "AUTHORIZE"):
            booking.state = "AUTHORIZATION_PENDING"
        claim = OperationClaim(
            operation.id, booking.id, operation.claim_token, operation.version,
            str(operation.request_id), kind, scope, dict(operation.request_payload),
        )
        self.db.commit()
        return claim

    def _record_resources(self, claim, order=None, authorization=None):
        # Match claim/completion lock order before acquiring the operation lock
        # or inserting audit rows with booking/operation foreign keys.
        self._booking(claim.booking_id, lock=True)
        details = {}
        if order is not None:
            details = {
                "order_id": order.provider_order_id, "status": order.status,
                "authorization_ids": [a.authorization_id for a in order.authorizations],
                "capture_ids": [c.capture_id for c in order.captures],
            }
        if authorization is not None:
            details = {
                "authorization_id": authorization.authorization_id,
                "order_id": authorization.order_id, "status": authorization.status,
            }
        self.db.add(BookingEvent(
            booking_id=claim.booking_id, operation_id=claim.operation_id,
            kind="PROVIDER_OBSERVED", details=details,
        ))
        if order is not None and claim.kind != "VOID":
            operation = self.db.scalar(select(PaymentOperation).where(
                PaymentOperation.id == claim.operation_id
            ).with_for_update().execution_options(populate_existing=True))
            if operation.provider_resource_id is None:
                operation.provider_resource_id = order.provider_order_id
        self.db.commit()

    def _fenced(self, claim):
        operation = self.db.scalar(select(PaymentOperation).where(
            PaymentOperation.id == claim.operation_id
        ).execution_options(populate_existing=True))
        return operation, bool(
            operation and operation.claim_token == claim.token
            and operation.version == claim.version and operation.state == "IN_FLIGHT"
        )

    def _queue_release(self, booking, authorization_id, order_id=None):
        # Durable queue is scoped to the same authorization, never a replacement.
        self._operation(booking.id, "VOID", authorization_id, {
            "authorization_id": authorization_id,
            "order_id": order_id or booking.provider_order_id, "body": {},
        })

    def _preserve_order(self, booking, order, operation):
        existing = self.db.scalar(select(Booking.id).where(
            Booking.provider_order_id == order.provider_order_id, Booking.id != booking.id
        ))
        conflict = existing is not None or (
            booking.provider_order_id is not None and booking.provider_order_id != order.provider_order_id
        )
        if not conflict:
            booking.provider_order_id = order.provider_order_id
        if operation.provider_resource_id is None:
            operation.provider_resource_id = order.provider_order_id
        elif operation.provider_resource_id != order.provider_order_id:
            conflict = True
        for auth in order.authorizations:
            other = self.db.scalar(select(Booking.id).where(
                Booking.provider_authorization_id == auth.authorization_id, Booking.id != booking.id
            ))
            if other is not None:
                conflict = True
                continue
            if booking.provider_authorization_id is None:
                booking.provider_authorization_id = auth.authorization_id
            elif booking.provider_authorization_id != auth.authorization_id:
                conflict = True
                self._queue_release(booking, auth.authorization_id, order.provider_order_id)
        return conflict

    def finish_order(self, claim, order, *, valid, approve_url=None):
        self._record_resources(claim, order=order)
        booking = self._booking(claim.booking_id, lock=True)
        operation, fenced = self._fenced(claim)
        conflict = self._preserve_order(booking, order, operation)
        if (
            not fenced and booking.state in ("AUTHORIZED", "VOIDED", "CAPTURE_PENDING", "PAID", "REFUND_PENDING", "REFUNDED") and not conflict and valid
            and all(a.authorization_id == booking.provider_authorization_id for a in order.authorizations)
        ):
            self.db.commit()
            return False
        if not fenced or conflict or not valid:
            booking.state = "REVIEW_REQUIRED"
            for auth in order.authorizations:
                if not self.db.scalar(select(Booking.id).where(
                    Booking.provider_authorization_id == auth.authorization_id, Booking.id != booking.id
                )):
                    self._queue_release(booking, auth.authorization_id, order.provider_order_id)
            if fenced:
                operation.state = "UNKNOWN"
                operation.error_code = "PAYMENT_VALIDATION_FAILED"
        else:
            operation.state = "IN_FLIGHT" if order.authorizations or claim.kind == "AUTHORIZE" else "SUCCEEDED"
            booking.provider_status = order.status
            if claim.kind == "CREATE_ORDER":
                if order.authorizations:
                    booking.state = "AUTHORIZATION_PENDING"
                elif booking.cancelled_at or booking.reservation_expires_at <= utcnow():
                    booking.state = "REVIEW_REQUIRED" if order.authorizations else (
                        "CANCELLED" if booking.cancelled_at else "EXPIRED"
                    )
                else:
                    booking.state = "AWAITING_APPROVAL"
                    booking.approve_url = approve_url
        self.db.commit()
        self._wake_settlement(booking.campaign_id)
        return fenced and not conflict and valid

    def _error(self, claim, error, *, definitive=False):
        booking = self._booking(claim.booking_id, lock=True)
        operation, fenced = self._fenced(claim)
        if fenced:
            operation.state = "DEFINITIVELY_FAILED" if definitive else "UNKNOWN"
            operation.error_code = type(error).__name__
            booking.state = "AUTHORIZATION_FAILED" if definitive else "REVIEW_REQUIRED"
        self.db.add(BookingEvent(
            booking_id=booking.id, operation_id=claim.operation_id, kind="PAYMENT_ERROR",
            details={"error_code": type(error).__name__, "fenced": fenced},
        ))
        self.db.commit()

    def _result(self, booking_id):
        return self._booking(booking_id)

    def _check_active(self, booking):
        campaign = self.db.get(Campaign, booking.campaign_id, populate_existing=True)
        if (
            booking.cancelled_at or booking.reservation_expires_at <= utcnow()
            or campaign.status != "OPEN" or campaign.cutoff_at <= utcnow()
        ):
            fail(409, "BOOKING_NOT_ACTIVE", "The temporary reservation is no longer active.")

    def _may_authorize(self, claim):
        booking = self._booking(claim.booking_id, lock=True)
        operation, fenced = self._fenced(claim)
        campaign = self.db.get(Campaign, booking.campaign_id, populate_existing=True)
        active = (
            fenced and not booking.cancelled_at and booking.reservation_expires_at > utcnow()
            and campaign.status == "OPEN" and campaign.cutoff_at > utcnow()
        )
        if fenced and not active:
            operation.state = "DEFINITIVELY_FAILED"
            booking.state = "CANCELLED" if booking.cancelled_at else "EXPIRED"
        self.db.commit()
        return active

    async def create_order(self, booking_id):
        booking = self._booking(booking_id, lock=True)
        if booking.provider_order_id or booking.state in (
            "REVIEW_REQUIRED", "AUTHORIZATION_PENDING", "AUTHORIZED", "RELEASE_PENDING", "VOIDED",
        ):
            self.db.commit()
            return self._result(booking_id)
        self._check_active(booking)
        arguments = dict(
            reference_id=str(booking.id), amount_minor=booking.amount_minor,
            currency=booking.currency, expected_payee=booking.expected_payee,
            return_url=booking.return_url, cancel_url=booking.cancel_url,
        )
        payload = build_authorization_order_payload(**arguments)
        claim = self.claim_operation(booking_id, "CREATE_ORDER", "", payload)
        if claim is None:
            return self._result(booking_id)
        try:
            assert not self.db.in_transaction()
            order = await self.gateway.create_authorization_order(**arguments, operation_id=claim.request_id)
            # Persist references before any retrieval/validation can fail.
            self._record_resources(claim, order=order)
            observed = order
            if order.purchase_unit_count != 1 or order.amount_minor is None:
                assert not self.db.in_transaction()
                order = await self.gateway.get_order(order.provider_order_id)
                if order.provider_order_id != observed.provider_order_id:
                    self.finish_order(claim, observed, valid=False)
                    self._record_resources(claim, order=order)
                    fail(409, "PAYMENT_VALIDATION_FAILED", "PayPal order association did not match.")
            valid = True
            try:
                validate_order(booking, order)
                approve_url = validate_sandbox_approve_url(order.approve_url, order.provider_order_id)
            except ValueError:
                valid, approve_url = False, None
            self.finish_order(claim, order, valid=valid, approve_url=approve_url)
            if not valid:
                fail(409, "PAYMENT_VALIDATION_FAILED", "PayPal order did not match the reservation.")
        except PayPalError as error:
            self._error(claim, error, definitive=isinstance(error, PayPalRequestError))
        return self._result(booking_id)

    async def authorize(self, booking_id):
        booking = self._booking(booking_id, lock=True)
        if booking.state in ("AUTHORIZED", "VOIDED", "RELEASE_PENDING"):
            self.db.commit()
            return self._result(booking_id)
        if booking.state in ("AUTHORIZATION_PENDING", "REVIEW_REQUIRED"):
            self.db.commit()
            return await self.reconcile(booking_id)
        self._check_active(booking)
        order_id = booking.provider_order_id
        if not order_id:
            fail(409, "BOOKING_NOT_ACTIVE", "Create a PayPal order before authorizing.")
        claim = self.claim_operation(booking_id, "AUTHORIZE", order_id, {"order_id": order_id, "body": {}})
        if claim is None:
            return self._result(booking_id)
        try:
            assert not self.db.in_transaction()
            order = await self.gateway.get_order(order_id)
            self._record_resources(claim, order=order)
            try:
                validate_order(booking, order, expected_order_id=order_id)
            except ValueError:
                self.finish_order(claim, order, valid=False)
                fail(409, "PAYMENT_VALIDATION_FAILED", "PayPal order validation failed.")
            if not order.authorizations:
                if order.status != "APPROVED":
                    booking = self._booking(booking_id, lock=True)
                    operation, fenced = self._fenced(claim)
                    if fenced:
                        operation.state = "PREPARED"
                        booking.state = "AWAITING_APPROVAL"
                    self.db.commit()
                    fail(409, "BUYER_APPROVAL_REQUIRED", "Approve this order in PayPal before authorizing.")
                assert not self.db.in_transaction()
                if not self._may_authorize(claim):
                    return self._result(booking_id)
                order = await self.gateway.authorize_order(order_id, operation_id=claim.request_id)
            if not self.finish_order(claim, order, valid=self._valid_order(booking, order, order_id)):
                return self._result(booking_id)
            await self._inspect_authorizations(claim, order)
        except PayPalError as error:
            self._error(claim, error, definitive=isinstance(error, PayPalRequestError))
        return self._result(booking_id)

    @staticmethod
    def _valid_order(booking, order, order_id):
        try:
            validate_order(booking, order, expected_order_id=order_id)
            return True
        except ValueError:
            return False

    async def _inspect_authorizations(self, claim, order):
        # finish_order committed all refs and ended the transaction.
        if len(order.authorizations) != 1:
            booking = self._booking(claim.booking_id, lock=True)
            booking.state = "REVIEW_REQUIRED"
            operation, fenced = self._fenced(claim)
            if fenced:
                operation.state = "UNKNOWN"
            self.db.commit()
            return
        auth_id = order.authorizations[0].authorization_id
        assert not self.db.in_transaction()
        authorization = await self.gateway.get_authorization(auth_id)
        self._record_resources(claim, authorization=authorization)
        # Campaign lock serializes admission with reservations/deadline changes.
        booking = self._booking(claim.booking_id)
        campaign_id = booking.campaign_id
        campaign = self.db.scalar(select(Campaign).where(Campaign.id == campaign_id)
                                  .with_for_update().execution_options(populate_existing=True))
        booking = self._booking(claim.booking_id, lock=True)
        operation, fenced = self._fenced(claim)
        valid = fenced
        associated = True
        try:
            validate_authorization_association(booking, authorization)
        except ValueError:
            associated = False
        if not fenced and associated and booking.state in ("AUTHORIZED", "VOIDED", "CAPTURE_PENDING", "PAID", "REFUND_PENDING", "REFUNDED"):
            self.db.commit()
            return
        try:
            validate_authorization(booking, authorization, campaign, self.settings)
        except ValueError:
            valid = False
        now = utcnow()
        admitted = (
            valid and not booking.cancelled_at and booking.reservation_expires_at > now
            and campaign.status == "OPEN" and campaign.cutoff_at > now
            and capacity_count(self.db, campaign.id, now, booking.id) < campaign.capacity
        )
        booking.provider_status = authorization.status
        booking.authorization_created_at = authorization.create_time
        booking.authorization_expires_at = authorization.expiration_time
        if admitted:
            booking.state = "AUTHORIZED"
            booking.admitted_at = booking.admitted_at or now
            operation.state = "SUCCEEDED"
        elif (
            associated and authorization.status == "PENDING" and fenced and not booking.cancelled_at
            and booking.reservation_expires_at > now and campaign.status == "OPEN" and campaign.cutoff_at > now
        ):
            booking.state = "AUTHORIZATION_PENDING"
            operation.state = "PROVIDER_PENDING"
        elif associated and authorization.status == "VOIDED":
            booking.state = "VOIDED"
            if fenced:
                operation.state = "SUCCEEDED"
        else:
            self._queue_release(booking, auth_id)
            if authorization.authorization_id != auth_id:
                self._queue_release(booking, authorization.authorization_id, authorization.order_id)
            booking.state = "RELEASE_PENDING" if valid else "REVIEW_REQUIRED"
            if fenced:
                operation.state = "SUCCEEDED" if valid else "UNKNOWN"
        if associated and fenced and authorization.status in ("CREATED", "VOIDED"):
            original = self.db.scalar(select(PaymentOperation).where(
                PaymentOperation.booking_id == booking.id, PaymentOperation.kind == "AUTHORIZE",
                PaymentOperation.resource_scope == booking.provider_order_id,
                PaymentOperation.id != operation.id,
            ).execution_options(populate_existing=True))
            if original and original.state in ("UNKNOWN", "PROVIDER_PENDING", "IN_FLIGHT"):
                original.state = "SUCCEEDED"
                original.provider_resource_id = original.provider_resource_id or booking.provider_order_id
        self.db.add(BookingEvent(
            booking_id=booking.id, operation_id=claim.operation_id,
            kind="AUTHORIZATION_ADMISSION", details={"authorization_id": auth_id, "admitted": admitted, "fenced": fenced},
        ))
        self.db.commit()
        self._wake_settlement(campaign.id)

    async def cancel(self, booking_id):
        campaign_id = self.db.scalar(select(Booking.campaign_id).where(Booking.id == booking_id))
        campaign = self.db.scalar(select(Campaign).where(Campaign.id == campaign_id)
                                  .with_for_update().execution_options(populate_existing=True))
        booking = self._booking(booking_id, lock=True)
        if booking.state in ("VOIDED", "CANCELLED", "REFUNDED"):
            self.db.commit()
            return self._result(booking_id)
        from ..settlement.decision import enqueue, schema_available
        from ..db.models import DecisionCohortMember
        member = None
        if schema_available(self.db):
            member = self.db.scalar(select(DecisionCohortMember).where(DecisionCohortMember.booking_id == booking_id))
        if member is not None and campaign.status == "CONFIRMED":
            fail(409, "CONFIRMED_CANCELLATION_REQUIRES_REVIEW", "Confirmed-workshop cancellation requires a separately reviewed policy.")
        booking.cancelled_at = booking.cancelled_at or utcnow()
        operations = list(self.db.scalars(select(PaymentOperation).where(
            PaymentOperation.booking_id == booking_id
        )))
        if member is not None:
            if campaign.status == "SETTLING":
                campaign.status = "ABORTING"
            enqueue(self.db, campaign)
            captures = [op for op in operations if op.kind == "CAPTURE"]
            for op in captures:
                if op.state == "PREPARED":
                    op.state = "DEFINITIVELY_FAILED"
            if (member.capture_id and member.capture_status not in ("DECLINED", "DENIED", "FAILED")) or any(op.state in ("IN_FLIGHT", "UNKNOWN", "PROVIDER_PENDING", "SUCCEEDED") for op in captures):
                booking.state = "REFUND_PENDING" if member.capture_status == "COMPLETED" else "REVIEW_REQUIRED"
                self.db.add(BookingEvent(booking_id=booking_id, kind="CANCEL_REQUESTED", details={"settlement_cleanup": True}))
                self.db.commit()
                return self._result(booking_id)
        if booking.provider_authorization_id:
            self._queue_release(booking, booking.provider_authorization_id)
            booking.state = "RELEASE_PENDING"
        elif any(op.state in ("IN_FLIGHT", "UNKNOWN", "PROVIDER_PENDING") for op in operations):
            booking.state = "REVIEW_REQUIRED"
        else:
            booking.state = "CANCELLED"
        self.db.add(BookingEvent(booking_id=booking_id, kind="CANCEL_REQUESTED", details={}))
        self.db.commit()
        # Browser cancel queues only; the explicit operator resumes/releases.
        return self._result(booking_id)

    async def reconcile(self, booking_id, known_order_id=None):
        booking = self._booking(booking_id, lock=True)
        if booking.state in ("AUTHORIZED", "VOIDED", "CAPTURE_PENDING", "PAID", "REFUND_PENDING", "REFUNDED"):
            # This narrow worker resolves unknown/queued work, not routine
            # external-state auditing. A read retry must not turn a definitive
            # authorization/void back into an in-flight creation operation.
            self.db.commit()
            return self._result(booking_id)
        from ..settlement.decision import schema_available
        from ..db.models import DecisionCohortMember
        if schema_available(self.db) and self.db.scalar(select(DecisionCohortMember.id).where(
            DecisionCohortMember.booking_id == booking_id,
        )):
            # Only the campaign saga may reconcile a frozen member's collection.
            self.db.commit()
            return self._result(booking_id)
        active_authorize = self.db.scalar(select(PaymentOperation).where(
            PaymentOperation.booking_id == booking_id, PaymentOperation.kind == "AUTHORIZE",
            PaymentOperation.state == "IN_FLIGHT", PaymentOperation.lease_expires_at > utcnow(),
        ))
        if active_authorize:
            self.db.commit()
            return self._result(booking_id)
        if known_order_id and booking.provider_order_id and known_order_id != booking.provider_order_id:
            fail(409, "PAYMENT_VALIDATION_FAILED", "Operator order differs from the stored order.")
        operation = self.db.scalar(select(PaymentOperation).where(
            PaymentOperation.booking_id == booking_id, PaymentOperation.kind == "CREATE_ORDER"
        ))
        order_id = booking.provider_order_id or known_order_id or (
            operation.provider_resource_id if operation else None
        )
        if not order_id:
            booking.state = "REVIEW_REQUIRED"
            self.db.commit()
            return self._result(booking_id)
        # Unknown CREATE may be attached only through validated retrieval. Never
        # mint a replacement CREATE operation or request ID.
        if operation is None:
            self.db.commit()
            return self._result(booking_id)
        operation_payload = dict(operation.request_payload)
        claim = self.claim_operation(booking_id, "CREATE_ORDER", "", operation_payload, retrieval=True)
        if claim is None:
            return self._result(booking_id)
        try:
            assert not self.db.in_transaction()
            order = await self.gateway.get_order(order_id)
            valid = self._valid_order(booking, order, order_id)
            approve_url = None
            if valid and not order.authorizations:
                try:
                    approve_url = validate_sandbox_approve_url(order.approve_url, order_id)
                except ValueError:
                    valid = False
            if not self.finish_order(claim, order, valid=valid, approve_url=approve_url):
                return self._result(booking_id)
            if order.authorizations:
                await self._inspect_authorizations(claim, order)
            else:
                booking = self._booking(booking_id, lock=True)
                auth_op = self.db.scalar(select(PaymentOperation).where(
                    PaymentOperation.booking_id == booking_id, PaymentOperation.kind == "AUTHORIZE"
                ))
                # A prior ambiguous authorization remains unresolved even when a
                # current order read has not exposed an authorization yet.
                if auth_op and auth_op.state in ("UNKNOWN", "IN_FLIGHT", "PROVIDER_PENDING"):
                    booking.state = "REVIEW_REQUIRED"
                self.db.commit()
        except PayPalError as error:
            self._error(claim, error)
        return self._result(booking_id)

    async def release_pending(self, booking_id):
        """Operator-only retrieval-first release of queued, exact resources."""
        booking = self._booking(booking_id)
        from ..settlement.decision import schema_available
        from ..db.models import DecisionCohortMember
        allow_failed_captures = False
        if schema_available(self.db):
            member = self.db.scalar(select(DecisionCohortMember).where(DecisionCohortMember.booking_id == booking_id))
            if member is not None and member.capture_id:
                allow_failed_captures = member.capture_status in ("DECLINED", "DENIED", "FAILED")
                if not allow_failed_captures:
                    fail(409, "CAPTURE_REQUIRES_SETTLEMENT_RECONCILIATION", "Captured resources require settlement reconciliation, not authorization release.")
        queued = list(self.db.scalars(select(PaymentOperation).where(
            PaymentOperation.booking_id == booking_id, PaymentOperation.kind == "VOID",
            PaymentOperation.state != "SUCCEEDED",
        )))
        work = [(op.resource_scope, dict(op.request_payload)) for op in queued]
        self.db.commit()
        for auth_id, payload in work:
            claim = self.claim_operation(booking_id, "VOID", auth_id, payload, retrieval=True)
            if claim is None:
                continue
            try:
                assert not self.db.in_transaction()
                release_order_id = payload.get("order_id")
                if not release_order_id:
                    self._error(claim, ValueError("order association unavailable"))
                    continue
                order = await self.gateway.get_order(release_order_id)
                self._record_resources(claim, order=order)
                try:
                    validate_order(booking, order, expected_order_id=release_order_id, allow_failed_captures=allow_failed_captures)
                    if auth_id not in {a.authorization_id for a in order.authorizations}:
                        raise ValueError("authorization not in validated order")
                except ValueError as error:
                    self._error(claim, error)
                    continue
                assert not self.db.in_transaction()
                authorization = await self.gateway.get_authorization(auth_id)
                self._record_resources(claim, authorization=authorization)
                try:
                    validate_authorization_association(
                        booking, authorization, authorization_id=auth_id, order_id=release_order_id
                    )
                except ValueError as error:
                    self._error(claim, error)
                    continue
                if authorization.status == "VOIDED":
                    status = "VOIDED"
                elif authorization.status == "CREATED":
                    assert not self.db.in_transaction()
                    result = await self.gateway.void_authorization(auth_id, operation_id=claim.request_id)
                    status = result.status
                    self.db.add(BookingEvent(booking_id=booking_id, operation_id=claim.operation_id,
                                            kind="VOID_OBSERVED", details={"authorization_id": auth_id, "status": status}))
                    self.db.commit()
                else:
                    self._error(claim, ValueError("authorization requires review"))
                    continue
                booking = self._booking(booking_id, lock=True)
                operation, fenced = self._fenced(claim)
                if not fenced and booking.state == "VOIDED" and status == "VOIDED":
                    self.db.commit()
                    continue
                if fenced:
                    operation.state = "SUCCEEDED" if status == "VOIDED" else "PROVIDER_PENDING"
                remaining = self.db.scalar(select(PaymentOperation.id).where(
                    PaymentOperation.booking_id == booking_id, PaymentOperation.kind == "VOID",
                    PaymentOperation.id != claim.operation_id, PaymentOperation.state != "SUCCEEDED",
                ))
                unresolved = self.db.scalar(select(PaymentOperation.id).where(
                    PaymentOperation.booking_id == booking_id, PaymentOperation.kind != "VOID",
                    PaymentOperation.state.in_(("UNKNOWN", "IN_FLIGHT", "PROVIDER_PENDING")),
                ))
                booking.state = (
                    "VOIDED" if fenced and status == "VOIDED" and remaining is None and unresolved is None
                    else "REVIEW_REQUIRED"
                )
                self.db.commit()
            except PayPalError as error:
                self._error(claim, error)
        return self._result(booking_id)
