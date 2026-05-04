"""
Repayment Service — Delinquency Classification Engine

Pure functions — no DB, no I/O, fully testable.

Classifies a loan's repayment health into one of six states based on
days-past-due (DPD) and whether the loan has been fully settled or
written off:

    CURRENT      — all payments up to date (DPD == 0)
    AT_RISK      — within grace period (1–7 DPD), payment still expected
    DELINQUENT   — missed payment, 8–89 DPD, collections engagement begins
    DEFAULT      — 90+ DPD, escalated to recovery / write-off review
    SETTLED      — outstanding balance has reached zero
    WRITTEN_OFF  — irrecoverable; balance zeroed, loss recognised

Thresholds are configurable via ClassificationConfig for tenants with
different regulatory requirements (e.g., microfinance vs. commercial banks).

CBN (Central Bank of Nigeria) classification reference:
    Substandard  : 90–179 DPD   (we map this to DEFAULT)
    Doubtful     : 180–359 DPD  (still DEFAULT — caller may sub-classify)
    Lost         : 360+ DPD     (WRITTEN_OFF candidate)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RepaymentStatus(str, Enum):
    CURRENT = "current"
    AT_RISK = "at_risk"
    DELINQUENT = "delinquent"
    DEFAULT = "default"
    SETTLED = "settled"
    WRITTEN_OFF = "written_off"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassificationConfig:
    """
    Configurable thresholds for delinquency classification.

    Defaults match standard Nigerian microfinance DPD brackets.
    """

    grace_period_days: int = 7       # DPD ≤ this → AT_RISK (not yet DELINQUENT)
    delinquent_threshold_days: int = 8    # DPD ≥ this → DELINQUENT
    default_threshold_days: int = 90      # DPD ≥ this → DEFAULT
    write_off_threshold_days: int = 360   # DPD ≥ this → recommend WRITTEN_OFF


DEFAULT_CONFIG = ClassificationConfig()


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassificationResult:
    """Output of the delinquency classifier."""

    status: RepaymentStatus
    days_past_due: int
    is_terminal: bool          # SETTLED or WRITTEN_OFF — no further action
    requires_collection: bool  # DELINQUENT or DEFAULT
    write_off_recommended: bool
    description: str           # human-readable explanation


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def classify(
    days_past_due: int,
    *,
    is_settled: bool = False,
    is_written_off: bool = False,
    config: ClassificationConfig = DEFAULT_CONFIG,
) -> ClassificationResult:
    """
    Classify a loan's delinquency status.

    Parameters
    ----------
    days_past_due:
        Number of calendar days the most recent payment is overdue.
        0 = current (payment made on time or not yet due).
    is_settled:
        True if the loan's outstanding balance has reached zero (fully repaid).
    is_written_off:
        True if the loan has been administratively written off.
    config:
        Optional custom thresholds. Uses DEFAULT_CONFIG if omitted.

    Returns
    -------
    ClassificationResult with status, flags, and a human-readable description.
    """
    # Terminal states take precedence
    if is_written_off:
        return ClassificationResult(
            status=RepaymentStatus.WRITTEN_OFF,
            days_past_due=days_past_due,
            is_terminal=True,
            requires_collection=False,
            write_off_recommended=False,
            description="Loan has been written off. Balance recognised as a loss.",
        )

    if is_settled:
        return ClassificationResult(
            status=RepaymentStatus.SETTLED,
            days_past_due=0,
            is_terminal=True,
            requires_collection=False,
            write_off_recommended=False,
            description="Loan fully repaid. Outstanding balance is zero.",
        )

    if days_past_due < 0:
        raise ValueError(f"days_past_due cannot be negative, got {days_past_due}")

    # DPD-based classification
    if days_past_due == 0:
        return ClassificationResult(
            status=RepaymentStatus.CURRENT,
            days_past_due=0,
            is_terminal=False,
            requires_collection=False,
            write_off_recommended=False,
            description="All payments are up to date.",
        )

    if days_past_due <= config.grace_period_days:
        return ClassificationResult(
            status=RepaymentStatus.AT_RISK,
            days_past_due=days_past_due,
            is_terminal=False,
            requires_collection=False,
            write_off_recommended=False,
            description=(
                f"Payment is {days_past_due} day(s) past due — within the "
                f"{config.grace_period_days}-day grace period. "
                "No penalty charged yet."
            ),
        )

    if days_past_due >= config.default_threshold_days:
        write_off = days_past_due >= config.write_off_threshold_days
        return ClassificationResult(
            status=RepaymentStatus.DEFAULT,
            days_past_due=days_past_due,
            is_terminal=False,
            requires_collection=True,
            write_off_recommended=write_off,
            description=(
                f"Loan is in DEFAULT — {days_past_due} days past due "
                f"(threshold: {config.default_threshold_days} days). "
                + ("Write-off review recommended." if write_off else "Escalated to recovery.")
            ),
        )

    # Between grace period and default threshold → DELINQUENT
    return ClassificationResult(
        status=RepaymentStatus.DELINQUENT,
        days_past_due=days_past_due,
        is_terminal=False,
        requires_collection=True,
        write_off_recommended=False,
        description=(
            f"Loan is DELINQUENT — {days_past_due} days past due. "
            "Collections engagement initiated."
        ),
    )


def days_past_due_from_due_date(
    due_date_str: str,
    today_str: str,
) -> int:
    """
    Compute days past due given ISO date strings (YYYY-MM-DD).

    Returns 0 if the due date is today or in the future.
    """
    from datetime import date

    due = date.fromisoformat(due_date_str)
    today = date.fromisoformat(today_str)
    delta = (today - due).days
    return max(0, delta)
