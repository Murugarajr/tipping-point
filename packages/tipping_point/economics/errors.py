"""Domain errors for campaign terms management."""

from __future__ import annotations


class CampaignTermsError(ValueError):
    """Base class for campaign terms validation failures."""


class TermsFrozenError(CampaignTermsError):
    """Frozen (published) campaign terms are immutable."""


class ZeroTicketPriceError(CampaignTermsError):
    """Publishable terms require a strictly positive ticket price."""


class MissingAssumptionsError(CampaignTermsError):
    """Publishable terms are missing required reviewed assumptions."""


class InvalidCampaignDatesError(CampaignTermsError):
    """Campaign dates are absent, out of order, too long, or in the past."""


class InfeasibleCampaignError(CampaignTermsError):
    """Costs cannot be covered at maximum capacity; publishing is blocked."""


class StaleMaterialOfferError(CampaignTermsError):
    """A selected Channel3 offer snapshot requires explicit reviewed replacement."""


class AlreadyPublishedError(CampaignTermsError):
    """A campaign already exists; the approved cancellation path is required."""
