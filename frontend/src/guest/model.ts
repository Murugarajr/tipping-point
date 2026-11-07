import type { GuestBooking } from "../types";

export const authorizationExplanation = "This Sandbox prototype authorizes a test payment. An authorization is not a completed charge. The workshop is not confirmed by this step.";

export const bookingStates = {
  CHECKOUT_RESERVED: ["Seat held temporarily", "Continue to PayPal before your temporary seat expires."],
  AWAITING_APPROVAL: ["Awaiting buyer approval", "Approve in PayPal Sandbox, then explicitly check approval here. A return link is not proof of approval."],
  AUTHORIZATION_PENDING: ["Checking payment", "The provider outcome is pending. Do not start another payment; refresh the saved status."],
  AUTHORIZED: ["Authorized reservation", "Your test payment is authorized, not collected. This does not confirm the workshop."],
  EXPIRED: ["Temporary seat expired", "The temporary seat is no longer held. Any unresolved payment still needs review or release."],
  CANCELLED: ["Reservation cancelled", "This reservation is not admitted. Cancellation alone does not prove provider cleanup is complete."],
  RELEASE_PENDING: ["Authorization release pending", "Release is requested or awaiting reconciliation. It is not yet confirmed voided; provider timing varies."],
  VOIDED: ["Authorization voided", "The server has verified the authorization is voided. Statement timing depends on the provider."],
  REVIEW_REQUIRED: ["Payment status requires review", "The outcome is unresolved. Do not create a replacement payment. Refresh the saved status or contact the host."],
  AUTHORIZATION_FAILED: ["Authorization failed", "No authorized reservation has been admitted. Check the saved status before trying a new reservation."],
  CAPTURE_PENDING: ["Collection pending", "Payment collection is pending or being checked. No completed collection or workshop confirmation is assumed."],
  PAID: ["Payment collected · campaign processing", "Collection was verified for your reservation. This alone does not confirm the whole workshop."],
  REFUND_PENDING: ["Refund processing", "A refund is pending or being reconciled. Completion and timing are not yet guaranteed."],
  REFUNDED: ["Payment refunded", "The full Sandbox refund was verified. Keep this booking as your record."],
} as const;

export function bookingPresentation(state: string): readonly [string, string] {
  return bookingStates[state as keyof typeof bookingStates]
    ?? ["Payment status requires review", "The saved state is not recognized by this frontend. No payment success is assumed."];
}

export function guestSettlementPresentation(booking: GuestBooking): readonly [string, string] {
  if (booking.workshop_confirmed === true && booking.campaign_status === "CONFIRMED"
    && booking.state === "PAID" && booking.captured_minor === booking.amount_minor
    && booking.refunded_minor === 0) {
    return ["Workshop confirmed", "All required campaign collections and the financial policy checks succeeded. This is financial confirmation, not proof of workshop delivery."];
  }
  return bookingPresentation(booking.state);
}

export function campaignStatusMessage(status?: string): string | null {
  if (!status || status === "OPEN") return null;
  if (status === "CONFIRMED") return "Campaign collection completed. Your own booking status remains authoritative.";
  if (status === "CANCELLED") return "Campaign cancelled. Your release or refund status is shown separately below.";
  return "Campaign processing. Pending collections, releases, refunds or review must resolve before a final result.";
}

export function sandboxApproveUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.hostname !== "www.sandbox.paypal.com"
      || url.port || url.username || url.password) return null;
    return url.href;
  } catch { return null; }
}

export function isPublishedId(value: string | null): value is string {
  return value !== null && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
}
