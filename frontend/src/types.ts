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
}

export interface MaterialInput {
  name: string;
  source_label: string;
  kind: "consumable" | "reusable";
  shared_units: number;
  per_attendee_units: number;
  pack_size: number;
  pack_price_minor: number;
}

export interface DraftPayload {
  title: string;
  description: string;
  financials: {
    currency: "GBP";
    ticket_price_minor: number;
    capacity: number;
    minimum_operating_attendance: number;
    fixed_costs_minor: number;
    materials: MaterialInput[];
    shipping_allowance_minor: number;
    shipping_allowance_source: string;
    contingency_minor: number;
    fee_estimate: { percent_basis_points: number; fixed_minor: number; label: string };
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
  status: "OPEN";
  capacity: number;
  cutoff_at: string;
  terms_version: number;
  terms_id: string;
  terms_snapshot_hash: string;
}