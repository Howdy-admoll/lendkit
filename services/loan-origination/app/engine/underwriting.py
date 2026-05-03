"""
Loan Origination Service — Underwriting Engine

Pure functions — no DB, no I/O, fully testable.

Decision flow
-------------
1. Check credit tier eligibility (tier_params).
2. Cap requested amount at the tier maximum.
3. Cap tenure at the tier maximum.
4. Apply DTI guard: if monthly income provided, ensure monthly repayment
   does not exceed 40% of income; reduce approved amount if it would.
5. Compute amortised monthly repayment using reducing-balance formula.
6. Return an UnderwritingDecision.

Interest rate schedule (APR, annual)
-------------------------------------
  excellent (≥750) : 18%  — up to ₦5 000 000, 36 months
  good      (≥650) : 24%  — up to ₦2 000 000, 24 months
  fair      (≥550) : 36%  — up to ₦500 000,    12 months
  poor / very_poor : declined
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.schemas.loan import UnderwritingDecision

# ---------------------------------------------------------------------------
# Tier parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TierParams:
    can_approve: bool
    max_amount_kobo: int = 0
    max_tenure_months: int = 0
    base_apr: float = 0.0
    decline_reason: str = "Credit profile does not meet minimum eligibility criteria."


_MIN_AMOUNT_KOBO = 10_000_00  # ₦100 000

TIER_PARAMS: dict[str, TierParams] = {
    "excellent": TierParams(
        can_approve=True,
        max_amount_kobo=500_000_000,  # ₦5 000 000
        max_tenure_months=36,
        base_apr=0.18,
    ),
    "good": TierParams(
        can_approve=True,
        max_amount_kobo=200_000_000,  # ₦2 000 000
        max_tenure_months=24,
        base_apr=0.24,
    ),
    "fair": TierParams(
        can_approve=True,
        max_amount_kobo=50_000_000,  # ₦500 000
        max_tenure_months=12,
        base_apr=0.36,
    ),
    "poor": TierParams(
        can_approve=False,
        decline_reason="Credit score is below the minimum threshold for any loan product.",
    ),
    "very_poor": TierParams(
        can_approve=False,
        decline_reason="Credit profile does not meet minimum eligibility criteria at this time.",
    ),
}

_DTI_LIMIT = 0.40  # monthly repayment must not exceed 40% of monthly income


# ---------------------------------------------------------------------------
# Amortisation helper
# ---------------------------------------------------------------------------


def monthly_repayment(principal: int, annual_rate: float, months: int) -> int:
    """
    Standard reducing-balance (amortising) formula.

    Returns the monthly repayment amount in kobo (rounded up to nearest kobo).

    Formula:
        r = annual_rate / 12
        payment = P * r * (1 + r)^n / ((1 + r)^n - 1)

    Edge case: if rate == 0, returns a simple P/n division.
    """
    if months <= 0:
        return 0
    r = annual_rate / 12
    if r == 0:
        return math.ceil(principal / months)
    factor = (1 + r) ** months
    payment = principal * r * factor / (factor - 1)
    return math.ceil(payment)  # always round up (lender-safe)


# ---------------------------------------------------------------------------
# Main underwriting function
# ---------------------------------------------------------------------------


def underwrite(
    credit_tier: str,
    requested_amount_kobo: int,
    tenure_months: int,
    monthly_income_kobo: int | None = None,
) -> UnderwritingDecision:
    """
    Run underwriting rules and return a decision.

    Parameters
    ----------
    credit_tier:
        One of: excellent | good | fair | poor | very_poor
    requested_amount_kobo:
        Loan amount requested by the customer (kobo).
    tenure_months:
        Requested repayment period (months).
    monthly_income_kobo:
        Applicant's monthly income (kobo), if available.  Used for DTI check.
    """
    tier = TIER_PARAMS.get(credit_tier.lower())
    if tier is None:
        return UnderwritingDecision(
            approved=False,
            decline_reasons={"tier": f"Unknown credit tier '{credit_tier}'."},
        )

    if not tier.can_approve:
        return UnderwritingDecision(
            approved=False,
            decline_reasons={"eligibility": tier.decline_reason},
        )

    decline_reasons: dict[str, str] = {}
    notes_parts: list[str] = []

    # --- Cap amount ---
    approved_amount = min(requested_amount_kobo, tier.max_amount_kobo)
    if approved_amount < requested_amount_kobo:
        notes_parts.append(
            f"Amount capped from ₦{requested_amount_kobo // 100:,} "
            f"to ₦{approved_amount // 100:,} (tier limit)."
        )

    if approved_amount < _MIN_AMOUNT_KOBO:
        decline_reasons["amount"] = (
            f"Approved amount ₦{approved_amount // 100:,} is below the "
            f"minimum loan of ₦{_MIN_AMOUNT_KOBO // 100:,}."
        )
        return UnderwritingDecision(approved=False, decline_reasons=decline_reasons)

    # --- Cap tenure ---
    approved_tenure = min(tenure_months, tier.max_tenure_months)
    if approved_tenure < tenure_months:
        notes_parts.append(
            f"Tenure capped from {tenure_months} to {approved_tenure} months (tier limit)."
        )

    # --- DTI guard ---
    if monthly_income_kobo and monthly_income_kobo > 0:
        max_monthly_repayment = int(monthly_income_kobo * _DTI_LIMIT)
        candidate_repayment = monthly_repayment(approved_amount, tier.base_apr, approved_tenure)

        if candidate_repayment > max_monthly_repayment:
            # Back-calculate the maximum loan principal that fits within DTI
            r = tier.base_apr / 12
            if r > 0:
                factor = (1 + r) ** approved_tenure
                max_principal = int(max_monthly_repayment * (factor - 1) / (r * factor))
            else:
                max_principal = max_monthly_repayment * approved_tenure

            max_principal = max(0, max_principal)

            if max_principal < _MIN_AMOUNT_KOBO:
                decline_reasons["dti"] = (
                    f"Monthly income ₦{monthly_income_kobo // 100:,} is insufficient "
                    f"to service any loan above the minimum amount."
                )
                return UnderwritingDecision(approved=False, decline_reasons=decline_reasons)

            notes_parts.append(
                f"Amount reduced from ₦{approved_amount // 100:,} "
                f"to ₦{max_principal // 100:,} to satisfy DTI ≤ {int(_DTI_LIMIT * 100)}%."
            )
            approved_amount = max_principal

    # --- Final repayment computation ---
    apr = tier.base_apr
    repayment = monthly_repayment(approved_amount, apr, approved_tenure)
    total_repayable = repayment * approved_tenure

    return UnderwritingDecision(
        approved=True,
        approved_amount_kobo=approved_amount,
        tenure_months=approved_tenure,
        annual_percentage_rate=apr,
        monthly_repayment_kobo=repayment,
        total_repayable_kobo=total_repayable,
        notes=" ".join(notes_parts),
    )
