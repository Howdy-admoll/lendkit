"""
Collections Service — Escalation Ladder

Defines the rules for escalating a collection case based on days past due (DPD).

Ladder (CBN-aligned, Nigeria fintech standard):

  DPD  1–7    AUTO_OUTREACH   Automated SMS + email reminders only.
  DPD  8–30   AUTO_OUTREACH   Increased outreach frequency (daily).
  DPD 31–60   AGENT_REQUIRED  Assign a human collections agent.
  DPD 61–89   LEGAL_NOTICE    Send formal legal demand letter.
  DPD 90+     WRITE_OFF_READY Account eligible for write-off recommendation.

The escalation engine does NOT directly update state — it returns a recommended
action that the CollectionService applies after checking business rules (e.g.
a promise-to-pay agreement can delay escalation).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EscalationAction(str, Enum):
    """Recommended action based on current DPD."""
    AUTO_OUTREACH = "auto_outreach"    # no human needed, automated channels only
    AGENT_REQUIRED = "agent_required"  # assign a collections agent
    LEGAL_NOTICE = "legal_notice"      # send formal legal demand
    WRITE_OFF_READY = "write_off_ready"  # eligible for write-off recommendation


@dataclass(frozen=True)
class EscalationRule:
    min_dpd: int
    max_dpd: int   # inclusive; use a large number for open-ended upper bound
    action: EscalationAction
    description: str


# Rules applied in order — first match wins
_LADDER: list[EscalationRule] = [
    EscalationRule(
        min_dpd=1,
        max_dpd=30,
        action=EscalationAction.AUTO_OUTREACH,
        description="Automated SMS/email outreach — no human intervention",
    ),
    EscalationRule(
        min_dpd=31,
        max_dpd=60,
        action=EscalationAction.AGENT_REQUIRED,
        description="Assign collections agent — DPD 31-60",
    ),
    EscalationRule(
        min_dpd=61,
        max_dpd=89,
        action=EscalationAction.LEGAL_NOTICE,
        description="Issue formal legal demand letter — DPD 61-89",
    ),
    EscalationRule(
        min_dpd=90,
        max_dpd=9_999,
        action=EscalationAction.WRITE_OFF_READY,
        description="Eligible for write-off recommendation — DPD 90+",
    ),
]


@dataclass(frozen=True)
class EscalationResult:
    """Output of the escalation engine for a single case."""
    action: EscalationAction
    description: str
    dpd: int
    rule_min_dpd: int
    rule_max_dpd: int


def evaluate(dpd: int) -> EscalationResult:
    """
    Evaluate the escalation action for a case with the given DPD.

    Parameters
    ----------
    dpd:
        Days past due. Must be >= 0.

    Returns
    -------
    EscalationResult
        The recommended action and associated metadata.

    Raises
    ------
    ValueError:
        If dpd is negative.
    """
    if dpd < 0:
        raise ValueError(f"DPD cannot be negative; got {dpd}")

    if dpd == 0:
        # Not yet past due — no escalation action
        return EscalationResult(
            action=EscalationAction.AUTO_OUTREACH,
            description="Not yet past due — monitoring only",
            dpd=dpd,
            rule_min_dpd=0,
            rule_max_dpd=0,
        )

    for rule in _LADDER:
        if rule.min_dpd <= dpd <= rule.max_dpd:
            return EscalationResult(
                action=rule.action,
                description=rule.description,
                dpd=dpd,
                rule_min_dpd=rule.min_dpd,
                rule_max_dpd=rule.max_dpd,
            )

    # Should never reach here given max_dpd=9_999
    raise RuntimeError(f"No escalation rule matched DPD={dpd}")


def should_assign_agent(dpd: int) -> bool:
    """True if the DPD warrants assigning a human agent."""
    result = evaluate(dpd)
    return result.action in {
        EscalationAction.AGENT_REQUIRED,
        EscalationAction.LEGAL_NOTICE,
        EscalationAction.WRITE_OFF_READY,
    }


def should_refer_legal(dpd: int) -> bool:
    """True if the DPD warrants a legal referral."""
    result = evaluate(dpd)
    return result.action in {
        EscalationAction.LEGAL_NOTICE,
        EscalationAction.WRITE_OFF_READY,
    }


def is_write_off_eligible(dpd: int) -> bool:
    """True if the DPD meets the write-off threshold (90+ days)."""
    return evaluate(dpd).action == EscalationAction.WRITE_OFF_READY


def outreach_frequency_days(dpd: int) -> int:
    """
    How often (in days) automated outreach should be sent for a given DPD.

    Returns
    -------
    int
        Number of days between outreach messages.
        0 means no automated outreach (case is terminal or human-led).
    """
    if dpd <= 0:
        return 0
    if dpd <= 7:
        return 3   # every 3 days in the first week
    if dpd <= 30:
        return 1   # daily during 8–30 DPD
    # Beyond 30 DPD, human agents take over — automated outreach stops
    return 0
