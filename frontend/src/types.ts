export interface Merchant {
  merchant_id: string;
  name: string;
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
}

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

export interface Campaign {
  campaign_id: string;
  workshop_id: string;
  status: string;
  capacity: number;
  cutoff_at: string;
  terms_version: number;
  terms_id: string;
  terms_snapshot_hash: string;
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
  reservations_available: false;
  availability_note: string;
}
