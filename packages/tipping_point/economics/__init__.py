"""Workshop economics: input schemas, viability calculation, and terms service."""

from .calculator import (
    ALGORITHM_VERSION,
    COSTING_POLICY,
    ViabilityReport,
    build_snapshot_hash,
    calculate_viability,
)
from .errors import (
    CampaignTermsError,
    InvalidCampaignDatesError,
    MissingAssumptionsError,
    TermsFrozenError,
    ZeroTicketPriceError,
)
from .schemas import (
    CAMPAIGN_MAX_DURATION_HOURS,
    CampaignFinancialsInput,
    CampaignScheduleInput,
    FeeEstimateInput,
    MaterialLineInput,
)
from .service import CampaignTermsService

__all__ = [
    "ALGORITHM_VERSION",
    "COSTING_POLICY",
    "ViabilityReport",
    "build_snapshot_hash",
    "calculate_viability",
    "CampaignTermsError",
    "InvalidCampaignDatesError",
    "MissingAssumptionsError",
    "TermsFrozenError",
    "ZeroTicketPriceError",
    "CAMPAIGN_MAX_DURATION_HOURS",
    "CampaignFinancialsInput",
    "CampaignScheduleInput",
    "FeeEstimateInput",
    "MaterialLineInput",
    "CampaignTermsService",
]