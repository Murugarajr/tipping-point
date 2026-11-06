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