"""
Credit Scoring Service — Scoring Orchestrator

Takes raw signals, runs all rules, maps the result onto the 300–850 scale,
and returns a ScoringResult with full factor breakdown.

Scaling formula
---------------
  raw_score  = sum of points_awarded across all rules with points_possible > 0
  raw_max    = sum of points_possible across those same rules
  normalised = raw_score / raw_max  (clamped to [0, 1])
  final      = score_min + round(normalised × (score_max - score_min))

Hard stops (sanctioned, too many defaults for new customers, etc.) bypass the
numeric calculation entirely and return a declined status.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.engine.rules import ALL_RULES, RuleResult
from app.schemas.score import IncomeSignal, KYCSignal, RepaymentSignal

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class ScoringResult:
    score: int
    tier: str  # ScoreTier value
    recommendation: str
    factors: list[RuleResult] = field(default_factory=list)
    decline_reasons: dict = field(default_factory=dict)
    is_sanctioned: bool = False
    is_pep: bool = False
    max_possible_score: int = settings.score_max
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    @property
    def is_declined(self) -> bool:
        return self.tier == "very_poor" or self.is_sanctioned


# ---------------------------------------------------------------------------
# Tier helpers
# ---------------------------------------------------------------------------


def _tier_for_score(score: int) -> str:
    s = settings
    if score >= s.tier_excellent_min:
        return "excellent"
    if score >= s.tier_good_min:
        return "good"
    if score >= s.tier_fair_min:
        return "fair"
    if score >= s.tier_poor_min:
        return "poor"
    return "very_poor"


_TIER_RECOMMENDATIONS: dict[str, str] = {
    "excellent": (
        "Excellent credit profile. Eligible for our best rates and highest loan amounts."
    ),
    "good": ("Good credit profile. Eligible for competitive rates with standard loan amounts."),
    "fair": (
        "Fair credit profile. Eligible for standard rates; consider a lower loan amount "
        "or a guarantor to improve terms."
    ),
    "poor": (
        "Poor credit profile. Eligible for entry-level products only; demonstrating "
        "consistent repayment will improve future eligibility."
    ),
    "very_poor": (
        "Credit profile does not meet minimum eligibility criteria at this time. "
        "Improving KYC status, reducing outstanding debt, and building repayment history "
        "will improve future eligibility."
    ),
}


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------


def compute_score(
    kyc: KYCSignal | None = None,
    income: IncomeSignal | None = None,
    repayment: RepaymentSignal | None = None,
    requested_loan_amount_kobo: int | None = None,
    score_validity_days: int = 90,
) -> ScoringResult:
    """
    Run all scoring rules and return a ScoringResult.

    Parameters
    ----------
    kyc:
        Snapshot of the customer's KYC verification outcome.
    income:
        Income and employment data (from bank statement analysis or declaration).
    repayment:
        Historical repayment record from credit bureau or internal ledger.
    requested_loan_amount_kobo:
        The loan amount the customer is applying for.  Used for DTI calculation.
    score_validity_days:
        How long (in days) the resulting score is considered fresh before a
        re-computation is recommended.
    """

    # ------------------------------------------------------------------
    # Hard stop 1: sanctions — immediately decline, no numeric score
    # ------------------------------------------------------------------
    if kyc is not None and kyc.is_sanctioned:
        return ScoringResult(
            score=settings.score_min,
            tier="very_poor",
            recommendation="Application declined — customer is on a sanctions watchlist.",
            is_sanctioned=True,
            is_pep=kyc.is_pep,
            decline_reasons={"sanctions": "Customer appears on a regulatory sanctions list."},
        )

    # ------------------------------------------------------------------
    # Run every rule
    # ------------------------------------------------------------------
    factors: list[RuleResult] = []

    for rule_fn in ALL_RULES:
        sig = inspect.signature(rule_fn)
        params = sig.parameters

        # Determine which arguments to pass — rules declare only the params they need
        kwargs: dict = {}
        if "kyc" in params:
            kwargs["kyc"] = kyc
        if "income" in params:
            kwargs["income"] = income
        if "repayment" in params:
            kwargs["repayment"] = repayment
        if "requested_kobo" in params:
            kwargs["requested_kobo"] = requested_loan_amount_kobo

        result: RuleResult = rule_fn(**kwargs)
        factors.append(result)

    # ------------------------------------------------------------------
    # Aggregate raw score over *available* signals only
    # ------------------------------------------------------------------
    raw_awarded = sum(f.points_awarded for f in factors if f.is_available)
    raw_max = sum(f.points_possible for f in factors if f.is_available)

    if raw_max == 0:
        # No signals available — can't score
        return ScoringResult(
            score=settings.score_min,
            tier="very_poor",
            recommendation="Insufficient data to compute a credit score.",
            factors=factors,
            decline_reasons={"data": "No scoring signals were available."},
        )

    # Clamp to [0, raw_max] before normalising (penalties can push raw below 0)
    raw_awarded_clamped = max(0, min(raw_awarded, raw_max))
    normalised = raw_awarded_clamped / raw_max
    final_score = settings.score_min + round(normalised * (settings.score_max - settings.score_min))
    final_score = max(settings.score_min, min(settings.score_max, final_score))

    tier = _tier_for_score(final_score)
    recommendation = _TIER_RECOMMENDATIONS[tier]

    # ------------------------------------------------------------------
    # Collect decline reasons for very_poor tier
    # ------------------------------------------------------------------
    decline_reasons: dict = {}
    if tier == "very_poor":
        if kyc and kyc.status == "rejected":
            decline_reasons["kyc"] = "KYC verification was rejected."
        negative = [f for f in factors if f.impact == "negative" and f.points_awarded < -3]
        for f in negative[:3]:
            decline_reasons[f.factor_key] = f.detail

    expires_at = datetime.now(UTC) + timedelta(days=score_validity_days)

    return ScoringResult(
        score=final_score,
        tier=tier,
        recommendation=recommendation,
        factors=factors,
        decline_reasons=decline_reasons,
        is_sanctioned=False,
        is_pep=kyc.is_pep if kyc else False,
        max_possible_score=settings.score_max,
        computed_at=datetime.now(UTC),
        expires_at=expires_at,
    )
