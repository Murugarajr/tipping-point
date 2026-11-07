"""Thin external dispatch boundary; no unverified Render SDK or remote execution claim."""

from typing import Awaitable, Callable


async def submit_work(submit: Callable[[dict], Awaitable[str]] | None, claim):
    """A configured Render integration may deliver this durable identity repeatedly.

    Its task invokes the same database-backed dispatcher/service. An actual SDK,
    remote task registration, deployment and execution evidence are pending.
    """
    if submit is None:
        raise RuntimeError("Render Workflow integration is not configured")
    return await submit({
        "work_id": str(claim.id), "campaign_id": str(claim.campaign_id),
        "generation": claim.version,
    })
