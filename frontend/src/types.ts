export interface Merchant {
  merchant_id: string;
  name: string;
}

export interface GuestSession {
  expires_at: string;
  csrf_token: string;
}

export interface GuestBooking {
  booking_id: string;
  campaign_id: string;
  workshop_id: string;
  workshop_title: string;
  state: "CHECKOUT_RESERVED" | "AWAITING_APPROVAL" | "AUTHORIZATION_PENDING" | "AUTHORIZED" | "EXPIRED" | "CANCELLED" | "RELEASE_PENDING" | "VOIDED" | "REVIEW_REQUIRED" | "AUTHORIZATION_FAILED" | "CAPTURE_PENDING" | "PAID" | "REFUND_PENDING" | "REFUNDED";
  payment_state: "NOT_STARTED" | "AWAITING_APPROVAL" | "CHECKING" | "AUTHORIZED" | "RELEASE_PENDING" | "VOIDED" | "REVIEW_REQUIRED" | "CAPTURE_PENDING" | "PAID" | "REFUND_PENDING" | "REFUNDED";
  amount_minor: number;
  currency: "GBP";
  reservation_expires_at: string;
  seat_held: boolean;
  approve_url: string | null;
  notice: string;
  can_create_order: boolean;
  can_authorize: boolean;
  can_cancel: boolean;
  updated_at: string;
  campaign_status?: string;
  workshop_confirmed?: boolean;
  captured_minor?: number;
  refunded_minor?: number;
  sandbox_cleanup_status?: SandboxCleanupState | null;
}

export interface SessionInfo {
  merchant: Merchant;
  session_id: string;
  expires_at: string;
  csrf_token: string;
}

export interface Workshop {
  workshop_id: string;
  title: string;
  description: string | null;
  capacity: number;
  ticket_price_minor: number;
  currency: "GBP";
  terms_version: number;
  is_frozen: boolean;
  opens_at: string | null;
  closes_at: string | null;
  campaign_id?: string | null;
  /** Discovery-listing metadata only; null means listed in public browsing. */
  hidden_from_discovery_at?: string | null;
}

export type HostVisibilityFilter = "listed" | "hidden" | "all";
export interface WorkshopVisibilityResult { workshop_id: string; hidden_from_discovery_at: string | null; changed: boolean }

export interface MaterialInput {
  name: string;
  source_label: string;
  kind: "consumable" | "reusable";
  shared_units: number;
  per_attendee_units: number;
  pack_size: number;
  pack_price_minor: number;
  selected_offer_snapshot_id?: string;
}

export interface DraftPayload {
  title: string;
  description: string;
  financials: {
    currency: "GBP";
    ticket_price_minor: number;
    capacity: number;
    minimum_operating_attendance: number | null;
    fixed_costs_minor: number;
    materials: MaterialInput[];
    shipping_allowance_minor: number;
    shipping_allowance_source: string;
    contingency_minor: number;
    fee_estimate: { percent_basis_points: number; fixed_minor: number; label: string } | null;
  };
  schedule: { opens_at: string; closes_at: string };
}

export interface AttendancePoint {
  attendance: number;
  packs_by_material: Record<string, number>;
  material_cost_minor: number;
  required_budget_minor: number;
  gross_minor: number;
  estimated_fees_minor: number;
  estimated_net_minor: number;
  estimated_surplus_minor: number;
  is_viable: boolean;
}

export interface ViabilityPreview {
  terms_version: number;
  terms_snapshot_hash: string;
  algorithm_version: string;
  currency: "GBP";
  ticket_price_minor: number;
  capacity: number;
  minimum_operating_attendance: number;
  first_viable_attendance: number | null;
  any_viable_attendance: boolean;
  is_viable_at_capacity: boolean;
  attendance_curve: AttendancePoint[];
  materials_note: string;
}

/** Approved Sandbox operator-test cleanup only; never a general refund policy. */
export type SandboxCleanupState = "REFUND_PROCESSING" | "REFUNDED" | "REVIEW_REQUIRED";

export interface SandboxCleanupStatus {
  status: SandboxCleanupState;
  reason: string | null;
  requested_at: string | null;
  previously_confirmed: boolean;
  review_reason: string | null;
}

export interface SettlementStatus {
  state: string;
  decision_result: "COLLECT" | "RELEASE" | "REVIEW_REQUIRED" | null;
  decision_reason: string | null;
  frozen_attendance: number | null;
  admitted_attendance: number;
  authorized_minor: number;
  collected_minor: number;
  refunded_minor: number;
  net_collected_minor?: number;
  capture_pending: number;
  release_pending: number;
  refund_pending: number;
  review_required: boolean;
  settlement_deadline: string | null;
  /** Read-only: when the deadline decision was frozen; null before a decision. */
  decided_at?: string | null;
  fee_basis: "estimated" | "actual" | "mixed";
  actual_fees_minor: number | null;
  estimated_fees_minor: number | null;
  estimated_surplus_minor: number | null;
  post_collection_surplus_minor: number | null;
  sandbox_cleanup?: SandboxCleanupStatus | null;
}

export interface Campaign {
  campaign_id: string;
  workshop_id: string;
  status: string;
  capacity: number;
  cutoff_at: string;
  terms_version: number;
  terms_id: string;
  terms_snapshot_hash: string;
  /** Read-only: when the campaign was published. */
  published_at?: string | null;
  settlement?: SettlementStatus | null;
}
export interface OfferProvenance {
  offer_snapshot_id: string;
  provider: "channel3";
  product_title: string;
  merchant_domain: string;
  price_minor: number;
  retrieved_at: string;
  product_url: string | null;
  suitability_reviewed: boolean;
  pack_size_reviewed: boolean;
  review_notes: string | null;
}
export interface WorkshopDetail extends Workshop {
  terms_snapshot_hash: string;
  financials: Omit<DraftPayload["financials"], "materials"> & {
    materials: (MaterialInput & { offer_provenance: OfferProvenance | null })[];
  };
  campaign: Campaign | null;
  offer_stale_after_seconds: number;
}
export interface MaterialOffer {
  offer_snapshot_id: string;
  product_title: string;
  merchant_domain: string;
  price_minor: number;
  currency: "GBP";
  product_url: string | null;
  retrieved_at: string;
  is_stale: boolean;
  freshness_label: string;
  limitations_note: string;
}
export interface MaterialSearchResult {
  offers: MaterialOffer[];
  rejected_count: number;
  rejected_offers: { product_title: string; ineligible_reason: string }[];
  retrieved_at: string;
}
export interface MaterialSelection {
  offer_snapshot_id: string;
  material_name: string;
  kind: "consumable" | "reusable";
  pack_size: number;
  shared_units: number;
  per_attendee_units: number;
  suitability_reviewed: boolean;
  pack_size_reviewed: boolean;
  review_notes: string;
  shipping_allowance_minor: number;
  shipping_allowance_source: string;
}
export interface PublicWorkshop {
  workshop_id: string;
  campaign_id: string;
  title: string;
  description: string | null;
  currency: "GBP";
  ticket_price_minor: number;
  capacity: number;
  opens_at: string;
  cutoff_at: string;
  publication_status: string;
  booking_window_status: "not_open_yet" | "open" | "closed" | "unavailable";
  reservations_available: boolean;
  availability_note: string;
  availability_reason: "available" | "not_open_yet" | "closed" | "full" | "payment_unconfigured" | "ineligible" | "schema_unavailable";
  available_seats: number | null;
}
