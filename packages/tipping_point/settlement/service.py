"""Strict group settlement saga; short campaign-first locks, never network in a transaction."""

from datetime import timedelta
from types import SimpleNamespace
from sqlalchemy import select

from ..db.models import Booking, BookingEvent, Campaign, CampaignDecision, DecisionCohortMember, PaymentOperation
from ..guest.payments import BookingPaymentService, validate_authorization_association
from ..guest.service import utcnow
from ..paypal.client import PayPalError, PayPalRequestError
from .decision import cleanup_intent

UNRESOLVED = ("IN_FLIGHT", "UNKNOWN", "PROVIDER_PENDING")
CAPTURE_FAILURES = ("DECLINED", "DENIED", "FAILED")
REFUND_FAILURES = ("FAILED", "CANCELLED")


class SettlementService:
    def __init__(self, db, settings, gateway):
        self.db, self.settings, self.gateway = db, settings, gateway
        self.payments = BookingPaymentService(db, settings, gateway)

    def _campaign(self, campaign_id):
        return self.db.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update()
                              .execution_options(populate_existing=True))

    def _decision(self, campaign_id):
        return self.db.scalar(select(CampaignDecision).where(CampaignDecision.campaign_id == campaign_id)
                              .execution_options(populate_existing=True))

    def _member(self, booking_id):
        return self.db.scalar(select(DecisionCohortMember).where(DecisionCohortMember.booking_id == booking_id)
                              .execution_options(populate_existing=True))

    def _abort(self, campaign, decision, reason):
        if campaign.status not in ("CONFIRMED", "CANCELLED", "RELEASING"):
            campaign.status = "ABORTING"
        decision.post_collection = {**decision.post_collection, "abort_reason": reason}

    @staticmethod
    def _validate_order(booking, order):
        """Reuse guest expectations but allow captures on this settlement's order."""
        if (
            order.provider_order_id != booking.provider_order_id or order.purchase_unit_count != 1
            or order.intent != "AUTHORIZE" or order.reference_id != str(booking.id)
            or order.amount_minor != booking.amount_minor or order.currency != "GBP"
            or booking.expected_payee not in (order.payee_identifiers or (order.payee_identifier,))
            or booking.provider_authorization_id not in {a.authorization_id for a in order.authorizations}
        ):
            raise ValueError("settlement order association mismatch")

    @staticmethod
    def _validate_capture(member, capture, order):
        if (
            capture.amount_minor != member.amount_minor or capture.currency != member.currency
            or capture.order_id not in (None, member.order_id)
            or capture.authorization_id not in (None, member.authorization_id)
            or not (capture.authorization_id == member.authorization_id
                    or capture.capture_id in {c.capture_id for c in order.captures})
        ):
            raise ValueError("capture identity or money mismatch")

    def _record(self, campaign_id, claim, resource, kind):
        """Persist references before validation/fencing, including stale-worker observations."""
        campaign = self._campaign(campaign_id)
        booking = self.payments._booking(claim.booking_id, lock=True)
        member = self._member(booking.id)
        operation, _ = self.payments._fenced(claim)
        resource_id = getattr(resource, "capture_id" if kind == "CAPTURE" else "refund_id")
        fields = ("status", "amount_minor", "currency", "authorization_id", "order_id", "capture_id", "refund_id", "fee_minor")
        observation = {k: getattr(resource, k) for k in fields if hasattr(resource, k)}
        self.db.add(BookingEvent(booking_id=booking.id, operation_id=claim.operation_id,
                                 kind="SETTLEMENT_RESOURCE_OBSERVED", details={"kind": kind, **observation}))
        if operation.provider_resource_id is None:
            operation.provider_resource_id = resource_id
        attr = "capture_id" if kind == "CAPTURE" else "refund_id"
        other = self.db.scalar(select(DecisionCohortMember.id).where(
            getattr(DecisionCohortMember, attr) == resource_id,
            DecisionCohortMember.booking_id != booking.id,
        ))
        conflict = bool(other or (getattr(member, attr) and getattr(member, attr) != resource_id)
                        or operation.provider_resource_id != resource_id)
        if not conflict:
            setattr(member, attr, resource_id)
        else:
            self._decision(campaign.id).review_required = True
            booking.state = "REVIEW_REQUIRED"
        self.db.commit()
        return not conflict

    def _claim(self, campaign_id, booking_id, kind):
        from ..paypal.client import build_capture_payload, build_refund_payload
        campaign = self._campaign(campaign_id)
        decision = self._decision(campaign_id)
        booking = self.payments._booking(booking_id, lock=True)
        member = self._member(booking_id)
        if kind == "CAPTURE" and cleanup_intent(decision):
            # Operator test cleanup is refund-only; no capture claim (even retrieval) may restart.
            self.db.commit()
            return None
        if kind == "CAPTURE":
            scope = member.authorization_id
            payload = {"authorization_id": scope, "body": build_capture_payload(member.amount_minor, member.currency)}
        else:
            scope = member.capture_id
            payload = {"capture_id": scope, "body": build_refund_payload(member.amount_minor, member.currency)}
        operation = self.db.scalar(select(PaymentOperation).where(
            PaymentOperation.booking_id == booking_id, PaymentOperation.kind == kind,
            PaymentOperation.resource_scope == scope,
        ))
        fresh = operation is None or operation.state == "PREPARED"
        if kind == "CAPTURE" and fresh:
            if booking.cancelled_at or utcnow() >= decision.settlement_deadline:
                self._abort(campaign, decision, "CANCELLATION_OR_COLLECTION_DEADLINE")
            if campaign.status != "SETTLING":
                if operation is not None and operation.state == "PREPARED":
                    operation.state = "DEFINITIVELY_FAILED"
                self.db.commit()
                return None
        if operation is not None and operation.state == "DEFINITIVELY_FAILED":
            decision.review_required = kind == "REFUND" or decision.review_required
            self.db.commit()
            return None
        if kind == "CAPTURE":
            booking.state = "CAPTURE_PENDING"
        else:
            booking.state = "REFUND_PENDING"
        # Existing ledger supplies immutable payload/hash, request UUID, claim lease and fencing.
        claim = self.payments.claim_operation(booking_id, kind, scope, payload, retrieval=not fresh)
        return (claim, fresh) if claim is not None else None

    def _error(self, campaign_id, claim, error, kind, *, definitive=False):
        reference = getattr(error, "resource_id", None)
        if reference:
            field = "capture_id" if kind == "CAPTURE" else "refund_id"
            self._record(campaign_id, claim, SimpleNamespace(**{field: reference}, status="UNKNOWN"), kind)
        campaign = self._campaign(campaign_id)
        decision = self._decision(campaign_id)
        booking = self.payments._booking(claim.booking_id, lock=True)
        operation, fenced = self.payments._fenced(claim)
        if fenced:
            operation.state = "DEFINITIVELY_FAILED" if definitive else "UNKNOWN"
            operation.error_code = type(error).__name__
            booking.state = "REFUND_PENDING" if kind == "REFUND" else "REVIEW_REQUIRED"
        decision.review_required = True
        if kind == "CAPTURE" and definitive:
            self._abort(campaign, decision, "REQUIRED_CAPTURE_FAILED")
        self.db.add(BookingEvent(booking_id=booking.id, operation_id=claim.operation_id,
                                 kind="SETTLEMENT_ERROR", details={"kind": kind, "error": type(error).__name__, "fenced": fenced}))
        self.db.commit()

    async def _capture(self, campaign_id, booking_id):
        member = self._member(booking_id)
        if member.capture_status == "COMPLETED":
            operation = self.db.scalar(select(PaymentOperation).where(
                PaymentOperation.booking_id == booking_id, PaymentOperation.kind == "CAPTURE"))
            if operation is not None and operation.state == "SUCCEEDED":
                self.db.commit()
                return True
        claimed = self._claim(campaign_id, booking_id, "CAPTURE")
        if claimed is None:
            return False
        claim, fresh = claimed
        mutation_sent, mutation_returned = False, False
        try:
            booking = self.payments._booking(booking_id)
            member = self._member(booking_id)
            order_id, auth_id, capture_id = member.order_id, member.authorization_id, member.capture_id
            self.db.commit()
            assert not self.db.in_transaction()
            order = await self.gateway.get_order(order_id)
            self._validate_order(booking, order)
            if fresh and order.captures:
                if len(order.captures) != 1:
                    raise ValueError("multiple captures require manual reconciliation")
                capture_id, fresh = order.captures[0].capture_id, False
            if fresh:
                authorization = await self.gateway.get_authorization(auth_id)
                validate_authorization_association(booking, authorization)
                now = utcnow()
                if authorization.status != "CREATED" or authorization.create_time is None or authorization.expiration_time is None or min(
                    authorization.expiration_time, authorization.create_time + timedelta(hours=72)
                ) <= now:
                    raise ValueError("authorization is no longer capturable")
                # Last campaign-first dispatch fence. Cancellation after dispatch is compensated.
                campaign = self._campaign(campaign_id)
                current = self.payments._booking(booking_id, lock=True)
                _, fenced = self.payments._fenced(claim)
                permitted = fenced and campaign.status == "SETTLING" and current.cancelled_at is None and utcnow() < self._decision(campaign_id).settlement_deadline
                if not permitted:
                    operation, fenced = self.payments._fenced(claim)
                    if fenced:
                        operation.state = "DEFINITIVELY_FAILED"
                    self._abort(campaign, self._decision(campaign_id), "CAPTURE_DISPATCH_CANCELLED")
                    self.db.commit()
                    return False
                self.db.commit()
                assert not self.db.in_transaction()
                mutation_sent = True
                capture = await self.gateway.capture_authorization(
                    auth_id, amount_minor=member.amount_minor, currency=member.currency, operation_id=claim.request_id,
                )
                mutation_returned = True
            else:
                # Never replay an uncertain POST, even inside provider idempotency retention.
                if not capture_id:
                    candidates = [c.capture_id for c in order.captures]
                    if len(candidates) != 1:
                        raise ValueError("unknown capture needs a verified provider reference")
                    capture_id = candidates[0]
                capture = await self.gateway.get_capture(capture_id)
            if not self._record(campaign_id, claim, capture, "CAPTURE"):
                self._error(campaign_id, claim, ValueError("conflicting capture references"), "CAPTURE")
                return False
            assert not self.db.in_transaction()
            capture = await self.gateway.get_capture(capture.capture_id)
            if not self._record(campaign_id, claim, capture, "CAPTURE"):
                return False
            self._validate_capture(member, capture, order)
            return self._apply_capture(campaign_id, claim, capture)
        except (PayPalError, ValueError) as error:
            definitive = fresh and ((not mutation_sent and isinstance(error, ValueError))
                                    or (mutation_sent and not mutation_returned and isinstance(error, PayPalRequestError)))
            self._error(campaign_id, claim, error, "CAPTURE", definitive=definitive)
            return False

    def _apply_capture(self, campaign_id, claim, capture):
        campaign = self._campaign(campaign_id)
        decision = self._decision(campaign_id)
        booking = self.payments._booking(claim.booking_id, lock=True)
        member = self._member(booking.id)
        operation, fenced = self.payments._fenced(claim)
        if capture.status == "COMPLETED":
            member.capture_status = "COMPLETED"
            member.actual_fee_minor = capture.fee_minor
            member.capture_observation = {"status": capture.status, "amount_minor": capture.amount_minor, "currency": capture.currency}
            booking.state = "REFUNDED" if member.refund_status == "COMPLETED" else (
                "REFUND_PENDING" if member.refund_id else "PAID")
            if fenced:
                operation.state, operation.error_code = "SUCCEEDED", None
            if booking.cancelled_at or campaign.status != "SETTLING":
                self._abort(campaign, decision, "CAPTURE_COMPLETED_DURING_ABORT")
        elif member.capture_status != "COMPLETED":
            member.capture_status = capture.status
            if fenced:
                operation.state = "DEFINITIVELY_FAILED" if capture.status in CAPTURE_FAILURES else "PROVIDER_PENDING"
            booking.state = "CAPTURE_PENDING"
            if capture.status in CAPTURE_FAILURES:
                self._abort(campaign, decision, "REQUIRED_CAPTURE_FAILED")
        self.db.commit()
        return capture.status == "COMPLETED" and fenced

    async def _refund(self, campaign_id, booking_id):
        member = self._member(booking_id)
        if member.refund_status == "COMPLETED":
            operation = self.db.scalar(select(PaymentOperation).where(
                PaymentOperation.booking_id == booking_id, PaymentOperation.kind == "REFUND"))
            if operation is not None and operation.state == "SUCCEEDED":
                self.db.commit()
                return True
        claimed = self._claim(campaign_id, booking_id, "REFUND")
        if claimed is None:
            return False
        claim, fresh = claimed
        mutation_sent, mutation_returned = False, False
        try:
            member = self._member(booking_id)
            booking = self.payments._booking(booking_id)
            capture_id, refund_id, order_id = member.capture_id, member.refund_id, member.order_id
            self.db.commit()
            assert not self.db.in_transaction()
            order = await self.gateway.get_order(order_id)
            self._validate_order(booking, order)
            capture = await self.gateway.get_capture(capture_id)
            self._validate_capture(member, capture, order)
            if fresh:
                if capture.status != "COMPLETED":
                    raise ValueError("capture is not available for a full refund")
                mutation_sent = True
                refund = await self.gateway.refund_capture(
                    capture_id, amount_minor=member.amount_minor, currency=member.currency, operation_id=claim.request_id,
                )
                mutation_returned = True
            else:
                if not refund_id:
                    # No safe list/refund-discovery API is assumed. Escalate rather than issue another refund.
                    raise ValueError("unknown refund requires a verified refund reference")
                refund = await self.gateway.get_refund(refund_id)
            if not self._record(campaign_id, claim, refund, "REFUND"):
                return False
            assert not self.db.in_transaction()
            refund = await self.gateway.get_refund(refund.refund_id)
            if not self._record(campaign_id, claim, refund, "REFUND"):
                return False
            if refund.capture_id != capture_id or refund.amount_minor != member.amount_minor or refund.currency != "GBP":
                raise ValueError("refund identity or money mismatch")
            self._campaign(campaign_id)
            decision = self._decision(campaign_id)
            booking = self.payments._booking(booking_id, lock=True)
            member = self._member(booking_id)
            operation, fenced = self.payments._fenced(claim)
            if refund.status == "COMPLETED":
                member.refund_status = "COMPLETED"
                member.refund_observation = {"status": refund.status, "amount_minor": refund.amount_minor, "currency": refund.currency}
                booking.state = "REFUNDED"
                if fenced:
                    operation.state, operation.error_code = "SUCCEEDED", None
            elif member.refund_status != "COMPLETED":
                member.refund_status = refund.status
                booking.state = "REFUND_PENDING"
                if fenced:
                    operation.state = "DEFINITIVELY_FAILED" if refund.status in REFUND_FAILURES else "PROVIDER_PENDING"
                if refund.status in REFUND_FAILURES:
                    decision.review_required = True
            self.db.commit()
            return refund.status == "COMPLETED" and fenced
        except (PayPalError, ValueError) as error:
            definitive = fresh and ((not mutation_sent and isinstance(error, ValueError))
                                    or (mutation_sent and not mutation_returned and isinstance(error, PayPalRequestError)))
            self._error(campaign_id, claim, error, "REFUND", definitive=definitive)
            return False

    async def _release_booking(self, booking_id):
        booking = self.payments._booking(booking_id)
        if booking.state in ("VOIDED", "REFUNDED", "CANCELLED", "EXPIRED"):
            self.db.commit()
            return
        ops = list(self.db.scalars(select(PaymentOperation).where(PaymentOperation.booking_id == booking_id)))
        unresolved = any(o.kind in ("CREATE_ORDER", "AUTHORIZE") and o.state in UNRESOLVED for o in ops)
        self.db.commit()
        if unresolved:
            await self.payments.reconcile(booking_id)
        booking = self.payments._booking(booking_id)
        has_auth = bool(booking.provider_authorization_id)
        self.db.commit()
        await self.payments.cancel(booking_id)
        if has_auth:
            await self.payments.release_pending(booking_id)

    def _finalize(self, campaign_id):
        campaign = self._campaign(campaign_id)
        decision = self._decision(campaign_id)
        members = list(self.db.scalars(select(DecisionCohortMember).where(DecisionCohortMember.decision_id == decision.id)))
        bookings = list(self.db.scalars(select(Booking).where(Booking.campaign_id == campaign_id).with_for_update()
                                      .execution_options(populate_existing=True)))
        ops = list(self.db.scalars(select(PaymentOperation).where(PaymentOperation.booking_id.in_([b.id for b in bookings]))))
        if campaign.status == "SETTLING":
            if any(b.cancelled_at for b in bookings if b.id in {m.booking_id for m in members}):
                self._abort(campaign, decision, "COHORT_CANCELLATION")
            elif utcnow() >= decision.settlement_deadline:
                self._abort(campaign, decision, "COLLECTION_DEADLINE_EXCEEDED")
            elif members and len(members) == decision.attendance and all(m.capture_status == "COMPLETED" for m in members) and all(
                any(o.kind == "CAPTURE" and o.booking_id == m.booking_id and o.state == "SUCCEEDED" for o in ops)
                for m in members
            ):
                point = decision.evidence["point"]
                per_estimate = point["estimated_fees_minor"] // len(members)
                fees = sum(max(per_estimate, m.actual_fee_minor if m.actual_fee_minor is not None else per_estimate) for m in members)
                actual = sum(m.actual_fee_minor for m in members) if all(m.actual_fee_minor is not None for m in members) else None
                gross = sum(m.amount_minor for m in members)
                surplus = gross - fees - point["required_budget_minor"]
                basis = "actual" if actual is not None and all(m.actual_fee_minor >= per_estimate for m in members) else (
                    "estimated" if all(m.actual_fee_minor is None for m in members) else "mixed")
                decision.post_collection = {"gross_minor": gross, "deducted_fees_minor": fees, "actual_fees_minor": actual,
                                            "fee_basis": basis, "surplus_minor": surplus,
                                            "label": "post-collection policy surplus; not audited profit"}
                if surplus >= 0:
                    campaign.status = "CONFIRMED"
                    decision.review_required = False
                else:
                    self._abort(campaign, decision, "POST_COLLECTION_ECONOMICS_FAILED")
        if campaign.status in ("RELEASING", "ABORTING", "COMPENSATING"):
            if campaign.status == "ABORTING":
                campaign.status = "COMPENSATING"
            unresolved = any(o.state in UNRESOLVED for o in ops)
            cleaned = all(b.state in ("VOIDED", "REFUNDED", "CANCELLED", "EXPIRED") for b in bookings)
            decision.review_required = (
                decision.result == "REVIEW_REQUIRED"
                or any(o.state == "UNKNOWN" or (o.kind == "REFUND" and o.state == "DEFINITIVELY_FAILED") for o in ops)
                or any(b.state == "REVIEW_REQUIRED" for b in bookings)
            )
            if not unresolved and cleaned and not decision.review_required:
                campaign.status = "CANCELLED"
        self.db.commit()
        return campaign.status

    async def advance(self, campaign_id, *, max_steps=25):
        """A bounded saga pass. Dispatch again for pending or unknown resources."""
        campaign = self._campaign(campaign_id)
        decision = self._decision(campaign_id)
        if decision is None:
            raise ValueError("freeze a deadline decision before settlement")
        members = list(self.db.scalars(select(DecisionCohortMember).where(
            DecisionCohortMember.decision_id == decision.id).order_by(DecisionCohortMember.booking_id)))
        if not 1 <= max_steps <= 100:
            raise ValueError("saga pass budget must be between 1 and 100")
        if len(members) != decision.attendance or {str(m.booking_id) for m in members} != set(decision.evidence["cohort_booking_ids"]):
            decision.review_required = True
            self._abort(campaign, decision, "FROZEN_COHORT_MISMATCH")
            self.db.commit()
            return campaign.status
        if campaign.status == "SETTLING" and utcnow() >= decision.settlement_deadline:
            self._abort(campaign, decision, "COLLECTION_DEADLINE_EXCEEDED")
        self.db.commit()
        steps = 0
        for member in members:
            campaign = self.db.get(Campaign, campaign_id, populate_existing=True)
            settling = campaign.status == "SETTLING"
            self.db.commit()
            if not settling:
                break
            if member.capture_status == "COMPLETED":
                operation = self.db.scalar(select(PaymentOperation).where(
                    PaymentOperation.booking_id == member.booking_id, PaymentOperation.kind == "CAPTURE"))
                resolved = operation is not None and operation.state == "SUCCEEDED"
                self.db.commit()
                if resolved:
                    continue
            if steps >= max_steps:
                break
            steps += 1
            if not await self._capture(campaign_id, member.booking_id):
                break
        phase = self._finalize(campaign_id)
        if phase in ("RELEASING", "ABORTING", "COMPENSATING"):
            for member in members:
                if steps >= max_steps:
                    break
                member = self._member(member.booking_id)
                booking = self.payments._booking(member.booking_id)
                operation = self.db.scalar(select(PaymentOperation).where(
                    PaymentOperation.booking_id == member.booking_id, PaymentOperation.kind == "CAPTURE"))
                unresolved = operation is not None and operation.state in UNRESOLVED
                refund_operation = self.db.scalar(select(PaymentOperation).where(
                    PaymentOperation.booking_id == member.booking_id, PaymentOperation.kind == "REFUND"))
                refund_unresolved = refund_operation is not None and refund_operation.state in UNRESOLVED
                if booking.state in ("VOIDED", "REFUNDED", "CANCELLED", "EXPIRED") and not unresolved and not refund_unresolved:
                    self.db.commit()
                    continue
                self.db.commit()
                if unresolved:
                    steps += 1
                    await self._capture(campaign_id, member.booking_id)
                member = self._member(member.booking_id)
                status, booking_id = member.capture_status, member.booking_id
                operation = self.db.scalar(select(PaymentOperation).where(
                    PaymentOperation.booking_id == booking_id, PaymentOperation.kind == "CAPTURE"))
                uncertain = operation is not None and operation.state in UNRESOLVED
                self.db.commit()
                if status == "COMPLETED":
                    if (member.refund_status != "COMPLETED" or refund_unresolved) and steps < max_steps:
                        steps += 1
                        await self._refund(campaign_id, booking_id)
                elif not uncertain and status not in ("PENDING",):
                    if steps < max_steps:
                        steps += 1
                        await self._release_booking(booking_id)
        # Late/out-of-cohort authorizations must be released even on a confirmed campaign.
        other_ids = list(self.db.scalars(select(Booking.id).where(
            Booking.campaign_id == campaign_id, Booking.id.notin_([m.booking_id for m in members]))))
        self.db.commit()
        for booking_id in other_ids:
            booking = self.payments._booking(booking_id)
            terminal = booking.state in ("VOIDED", "REFUNDED", "CANCELLED", "EXPIRED")
            self.db.commit()
            if terminal:
                continue
            if steps >= max_steps:
                break
            steps += 1
            await self._release_booking(booking_id)
        return self._finalize(campaign_id)

    async def recover_reference(self, campaign_id, booking_id, kind, resource_id):
        """Operator-supplied reference is retrieved and fully validated, never guessed or POSTed."""
        if kind not in ("CAPTURE", "REFUND"):
            raise ValueError("only existing capture/refund references can be reconciled")
        member = self._member(booking_id)
        decision = self._decision(campaign_id)
        if member is None or decision is None or member.decision_id != decision.id:
            raise ValueError("booking is outside this frozen decision")
        operation = self.db.scalar(select(PaymentOperation).where(
            PaymentOperation.booking_id == booking_id, PaymentOperation.kind == kind))
        if operation is None or operation.state not in ("UNKNOWN", "PROVIDER_PENDING"):
            raise ValueError("reference recovery requires an unresolved existing logical operation")
        self.db.commit()
        claimed = self._claim(campaign_id, booking_id, kind)
        if claimed is None:
            return False
        claim, fresh = claimed
        if fresh:
            raise ValueError("reference recovery must never prepare a replacement mutation")
        try:
            member = self._member(booking_id)
            booking = self.payments._booking(booking_id)
            self.db.commit()
            order = await self.gateway.get_order(member.order_id)
            self._validate_order(booking, order)
            if kind == "CAPTURE":
                resource = await self.gateway.get_capture(resource_id)
                self._validate_capture(member, resource, order)
            else:
                resource = await self.gateway.get_refund(resource_id)
                if resource.capture_id != member.capture_id or resource.amount_minor != member.amount_minor or resource.currency != member.currency:
                    raise ValueError("operator refund reference does not match frozen capture")
            if not self._record(campaign_id, claim, resource, kind):
                return False
            self._campaign(campaign_id)
            operation, fenced = self.payments._fenced(claim)
            if fenced:
                operation.state = "UNKNOWN"
                operation.lease_expires_at = None
            self.db.commit()
            return fenced
        except (PayPalError, ValueError) as error:
            self._error(campaign_id, claim, error, kind)
            return False
