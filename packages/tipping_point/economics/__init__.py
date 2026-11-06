"""Workshop economics: input schemas, viability calculation, and terms service."""

from .calculator import (
    ALGORITHM_VERSION,
    COSTING_POLICY,
    ViabilityReport,
    build_snapshot_hash,
    calculate_viability,
)
from .errors import (
    AlreadyPublishedError,
    CampaignTermsError,
    InfeasibleCampaignError,
    InvalidCampaignDatesError,
    MissingAssumptionsError,
    StaleMaterialOfferError,
    TermsFrozenError,
    ZeroTicketPriceError,
)
from .schemas import (
    CAMPAIGN_MAX_DURATION_HOURS,
    CampaignFinancialsInput,
    CampaignScheduleInput,
    FeeEstimateInput,
    MaterialLineInput,
    MaterialOfferProvenanceInput,
)
from .service import CampaignTermsService
from .publishing import (
    WorkshopNotOwnedError,
    publish_campaign,
)

__all__ = [
    "ALGORITHM_VERSION",
    "COSTING_POLICY",
    "ViabilityReport",
    "build_snapshot_hash",
    "calculate_viability",
    "CampaignTermsError",
    "InvalidCampaignDatesError",
    "MissingAssumptionsError",
    "StaleMaterialOfferError",
    "TermsFrozenError",
    "ZeroTicketPriceError",
    "CAMPAIGN_MAX_DURATION_HOURS",
    "CampaignFinancialsInput",
    "CampaignScheduleInput",
    "FeeEstimateInput",
    "MaterialLineInput",
    "MaterialOfferProvenanceInput",
    "CampaignTermsService",
    "WorkshopNotOwnedError",
    "publish_campaign",
    "AlreadyPublishedError",
    "InfeasibleCampaignError",
]