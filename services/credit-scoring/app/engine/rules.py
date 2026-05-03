"""
Credit Scoring Service — Individual Scoring Rules

Each rule evaluates one signal and returns a RuleResult describing how many
points it awards, out of a maximum, and why.

Design principles
-----------------
* Rules are pure functions — they take data-in and produce a RuleResult.
  No database access, no I/O, no side effects.
* Every rule specifies its own weight (points_possible).  The scorer sums
  awarded points across all rules then maps the raw total onto the 300–850
  FICO-like scale.
* If a signal is not available (None), the rule returns 0 awarded out of 0
  possible so the missing data doesn't artificially lower the score — the
  max_possible score is adjusted accordingly.
* Sanctions and PEP flags are hard-stops evaluated before any numeric
  scoring — the scorer short-circuits when it finds them.

Signal buckets and weights
--------------------------
  KYC Outcome         35 points max
  Identity            25 points max
  Income/Employment   25 points max
  Repayment History   15 points max
  ─────────────────────────────────
  Total               100 raw points  →  mapped to 300–850
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.score import IncomeSignal, KYCSignal, RepaymentSignal

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class RuleResult:
    category: str  # SignalCategory value
    factor_key: str  # unique key within this score
    factor_label: str  # human-readable label shown in the report
    points_awarded: int
    points_possible: int  # 0 means signal unavailable (not counted against score)
    detail: str = ""
    impact: str = "neutral"  # positive | negative | neutral

    @property
    def is_available(self) -> bool:
        return self.points_possible > 0


# ===========================================================================
# 1.  KYC OUTCOME  (35 pts max)
# ===========================================================================

_KYC_STATUS_POINTS: dict[str, int] = {
    "approved": 35,
    "in_review": 18,
    "initiated": 10,
    "pending": 5,
    "expired": -10,
    "rejected": -40,
}


def rule_kyc_status(kyc: KYCSignal | None) -> RuleResult:
    """
    KYC verification status is the most important single signal.
    An approved KYC awards the full 35 pts; rejected deducts heavily.
    """
    if kyc is None:
        return RuleResult(
            category="kyc_outcome",
            factor_key="kyc_status",
            factor_label="KYC Verification Status",
            points_awarded=0,
            points_possible=0,
            detail="No KYC data provided",
        )

    awarded = _KYC_STATUS_POINTS.get(kyc.status, 0)
    impact = "positive" if awarded > 0 else ("negative" if awarded < 0 else "neutral")
    return RuleResult(
        category="kyc_outcome",
        factor_key="kyc_status",
        factor_label="KYC Verification Status",
        points_awarded=awarded,
        points_possible=35,
        detail=f"KYC status '{kyc.status}' → {awarded:+d} pts",
        impact=impact,
    )


def rule_kyc_risk_score(kyc: KYCSignal | None) -> RuleResult:
    """
    Provider-assigned risk score (0–100, lower = safer).
    Absent from basic-level verifications — treated as unavailable.
    """
    if kyc is None or kyc.risk_score is None:
        return RuleResult(
            category="kyc_outcome",
            factor_key="kyc_provider_risk",
            factor_label="KYC Provider Risk Score",
            points_awarded=0,
            points_possible=0,
            detail="Provider risk score not available",
        )

    # Invert: risk_score 0→10 pts, 50→5 pts, 100→0 pts (linear)
    awarded = max(0, round(10 * (1 - kyc.risk_score / 100)))
    return RuleResult(
        category="kyc_outcome",
        factor_key="kyc_provider_risk",
        factor_label="KYC Provider Risk Score",
        points_awarded=awarded,
        points_possible=10,
        detail=f"Provider risk score {kyc.risk_score}/100 → {awarded:+d} pts",
        impact="positive" if awarded >= 7 else ("negative" if awarded <= 3 else "neutral"),
    )


def rule_pep_flag(kyc: KYCSignal | None) -> RuleResult:
    """
    Politically Exposed Person flag — deducts points but is NOT a hard stop.
    Hard-stop logic lives in the scorer, not here.
    """
    if kyc is None:
        return RuleResult(
            category="kyc_outcome",
            factor_key="pep_flag",
            factor_label="Politically Exposed Person (PEP)",
            points_awarded=0,
            points_possible=0,
            detail="PEP data not available",
        )

    awarded = -20 if kyc.is_pep else 0
    return RuleResult(
        category="kyc_outcome",
        factor_key="pep_flag",
        factor_label="Politically Exposed Person (PEP)",
        points_awarded=awarded,
        points_possible=0,  # not a bonus, only a penalty
        detail="PEP flag set — enhanced due diligence required" if kyc.is_pep else "Not a PEP",
        impact="negative" if kyc.is_pep else "neutral",
    )


# ===========================================================================
# 2.  IDENTITY VERIFICATION  (25 pts max)
# ===========================================================================

_DOCUMENT_POINTS: dict[str, int] = {
    "bvn": 12,
    "nin": 10,
    "passport": 8,
    "drivers_license": 7,
    "voters_card": 6,
    "utility_bill": 4,
}
_IDENTITY_MAX = 25


def rule_identity_documents(kyc: KYCSignal | None) -> RuleResult:
    """
    Points for each verified identity document, capped at _IDENTITY_MAX.
    BVN is the most valuable signal in the Nigerian market — it links
    to the banking record and provides a cross-bank identity anchor.
    """
    if kyc is None or not kyc.verified_documents:
        return RuleResult(
            category="identity",
            factor_key="verified_documents",
            factor_label="Verified Identity Documents",
            points_awarded=0,
            points_possible=0,
            detail="No identity documents provided",
        )

    raw_pts = sum(_DOCUMENT_POINTS.get(doc, 2) for doc in kyc.verified_documents)
    awarded = min(raw_pts, _IDENTITY_MAX)
    docs_str = ", ".join(kyc.verified_documents)
    return RuleResult(
        category="identity",
        factor_key="verified_documents",
        factor_label="Verified Identity Documents",
        points_awarded=awarded,
        points_possible=_IDENTITY_MAX,
        detail=f"Documents: [{docs_str}] → raw {raw_pts} pts, capped at {_IDENTITY_MAX}",
        impact="positive" if awarded >= 12 else ("neutral" if awarded >= 6 else "negative"),
    )


# ===========================================================================
# 3.  INCOME & EMPLOYMENT  (25 pts max)
# ===========================================================================

_EMPLOYMENT_POINTS: dict[str, int] = {
    "salary": 12,
    "business": 10,
    "self_employed": 9,
    "contract": 7,
    "retired": 6,
    "unemployed": -5,
}


def rule_employment_type(income: IncomeSignal | None) -> RuleResult:
    """Employment stability bonus/penalty."""
    if income is None or income.employment_type is None:
        return RuleResult(
            category="income_employment",
            factor_key="employment_type",
            factor_label="Employment Type",
            points_awarded=0,
            points_possible=0,
            detail="Employment data not provided",
        )

    emp = income.employment_type.lower()
    awarded = _EMPLOYMENT_POINTS.get(emp, 0)
    impact = "positive" if awarded > 0 else ("negative" if awarded < 0 else "neutral")
    return RuleResult(
        category="income_employment",
        factor_key="employment_type",
        factor_label="Employment Type",
        points_awarded=awarded,
        points_possible=12,
        detail=f"Employment type '{emp}' → {awarded:+d} pts",
        impact=impact,
    )


def rule_employment_tenure(income: IncomeSignal | None) -> RuleResult:
    """
    Longer tenure at current employer = more stable income.
    Uses months_employed for salaried workers or business_age_months for
    the self-employed / business owners.
    """
    if income is None:
        return RuleResult(
            category="income_employment",
            factor_key="employment_tenure",
            factor_label="Employment Tenure",
            points_awarded=0,
            points_possible=0,
            detail="Income data not provided",
        )

    months = income.months_employed or income.business_age_months
    if months is None:
        return RuleResult(
            category="income_employment",
            factor_key="employment_tenure",
            factor_label="Employment Tenure",
            points_awarded=0,
            points_possible=0,
            detail="Tenure data not provided",
        )

    # 0–5 months → 1 pt; 6–11 → 3 pt; 12–23 → 5 pt; 24–47 → 7 pt; 48+ → 8 pt
    if months < 6:
        awarded, detail = 1, f"{months} months (<6)"
    elif months < 12:
        awarded, detail = 3, f"{months} months (6–11)"
    elif months < 24:
        awarded, detail = 5, f"{months} months (12–23)"
    elif months < 48:
        awarded, detail = 7, f"{months} months (24–47)"
    else:
        awarded, detail = 8, f"{months} months (48+)"

    return RuleResult(
        category="income_employment",
        factor_key="employment_tenure",
        factor_label="Employment Tenure",
        points_awarded=awarded,
        points_possible=8,
        detail=detail,
        impact="positive" if awarded >= 5 else "neutral",
    )


def rule_income_sufficiency(income: IncomeSignal | None, requested_kobo: int | None) -> RuleResult:
    """
    Checks if income is sufficient relative to the requested loan amount.
    Uses a 40% DTI (Debt-to-Income) threshold as a rule of thumb:
    monthly repayment should not exceed 40% of monthly income.
    Assumes 12-month loan term for the estimate.
    """
    if income is None or income.monthly_income_kobo is None:
        return RuleResult(
            category="income_employment",
            factor_key="income_sufficiency",
            factor_label="Income Sufficiency",
            points_awarded=0,
            points_possible=0,
            detail="Income data not available",
        )

    if requested_kobo is None:
        # No loan amount to compare against — award baseline pts for having income data
        awarded = 3
        return RuleResult(
            category="income_employment",
            factor_key="income_sufficiency",
            factor_label="Income Sufficiency",
            points_awarded=awarded,
            points_possible=5,
            detail="Income declared but no loan amount to compare",
            impact="neutral",
        )

    monthly_income = income.monthly_income_kobo
    # Estimated monthly repayment (simple, no compounding — rule-based approximation)
    monthly_repayment = requested_kobo / 12
    dti = monthly_repayment / monthly_income if monthly_income > 0 else 999

    if dti <= 0.20:
        awarded, note = 5, f"DTI {dti:.0%} ≤ 20% (excellent)"
    elif dti <= 0.30:
        awarded, note = 4, f"DTI {dti:.0%} 21–30% (good)"
    elif dti <= 0.40:
        awarded, note = 2, f"DTI {dti:.0%} 31–40% (acceptable)"
    elif dti <= 0.55:
        awarded, note = 0, f"DTI {dti:.0%} 41–55% (stretched)"
    else:
        awarded, note = -5, f"DTI {dti:.0%} >55% (over-leveraged)"

    return RuleResult(
        category="income_employment",
        factor_key="income_sufficiency",
        factor_label="Income Sufficiency",
        points_awarded=awarded,
        points_possible=5,
        detail=note,
        impact="positive" if awarded >= 4 else ("negative" if awarded < 0 else "neutral"),
    )


# ===========================================================================
# 4.  REPAYMENT HISTORY  (15 pts max)
# ===========================================================================


def rule_repayment_track_record(repayment: RepaymentSignal | None) -> RuleResult:
    """
    On-time payment ratio across all historical loans.
    Customers with no prior loans get 0/0 (signal unavailable).
    """
    if repayment is None or repayment.total_loans == 0:
        return RuleResult(
            category="repayment_history",
            factor_key="repayment_track_record",
            factor_label="Repayment Track Record",
            points_awarded=0,
            points_possible=0,
            detail="No prior loan history",
        )

    total_payments = (
        repayment.on_time_payments + repayment.late_payments + repayment.missed_payments
    )
    if total_payments == 0:
        return RuleResult(
            category="repayment_history",
            factor_key="repayment_track_record",
            factor_label="Repayment Track Record",
            points_awarded=0,
            points_possible=0,
            detail="Loan history present but no payment records",
        )

    on_time_ratio = repayment.on_time_payments / total_payments

    if on_time_ratio >= 0.97:
        awarded, note = 8, f"{on_time_ratio:.0%} on-time (excellent)"
    elif on_time_ratio >= 0.90:
        awarded, note = 6, f"{on_time_ratio:.0%} on-time (good)"
    elif on_time_ratio >= 0.80:
        awarded, note = 3, f"{on_time_ratio:.0%} on-time (fair)"
    elif on_time_ratio >= 0.70:
        awarded, note = 1, f"{on_time_ratio:.0%} on-time (poor)"
    else:
        awarded, note = -3, f"{on_time_ratio:.0%} on-time (very poor)"

    return RuleResult(
        category="repayment_history",
        factor_key="repayment_track_record",
        factor_label="Repayment Track Record",
        points_awarded=awarded,
        points_possible=8,
        detail=note,
        impact="positive" if awarded >= 6 else ("negative" if awarded < 0 else "neutral"),
    )


def rule_defaults(repayment: RepaymentSignal | None) -> RuleResult:
    """
    Defaults (write-offs) are the strongest negative repayment signal.
    Even one default significantly reduces the score.
    """
    if repayment is None or repayment.total_loans == 0:
        return RuleResult(
            category="repayment_history",
            factor_key="defaults",
            factor_label="Loan Defaults",
            points_awarded=0,
            points_possible=0,
            detail="No prior loan history",
        )

    if repayment.defaults == 0:
        awarded = 4
        note = "No defaults"
        impact = "positive"
    elif repayment.defaults == 1:
        awarded = -5
        note = "1 default on record"
        impact = "negative"
    else:
        awarded = -10
        note = f"{repayment.defaults} defaults on record"
        impact = "negative"

    return RuleResult(
        category="repayment_history",
        factor_key="defaults",
        factor_label="Loan Defaults",
        points_awarded=awarded,
        points_possible=4,
        detail=note,
        impact=impact,
    )


def rule_days_past_due(repayment: RepaymentSignal | None) -> RuleResult:
    """
    Maximum days past due in the last 24 months.
    Even short delinquencies affect the score; 90+ days is severe.
    """
    if repayment is None or repayment.total_loans == 0:
        return RuleResult(
            category="repayment_history",
            factor_key="max_days_past_due",
            factor_label="Maximum Days Past Due",
            points_awarded=0,
            points_possible=0,
            detail="No prior loan history",
        )

    dpd = repayment.max_days_past_due

    if dpd == 0:
        awarded, note = 3, "Never past due"
    elif dpd <= 14:
        awarded, note = 1, f"Max {dpd} days past due (minor)"
    elif dpd <= 29:
        awarded, note = 0, f"Max {dpd} days past due (moderate)"
    elif dpd <= 59:
        awarded, note = -3, f"Max {dpd} days past due (serious)"
    elif dpd <= 89:
        awarded, note = -5, f"Max {dpd} days past due (severe)"
    else:
        awarded, note = -8, f"Max {dpd} days past due (critical)"

    return RuleResult(
        category="repayment_history",
        factor_key="max_days_past_due",
        factor_label="Maximum Days Past Due",
        points_awarded=awarded,
        points_possible=3,
        detail=note,
        impact="positive" if awarded > 0 else ("negative" if awarded < 0 else "neutral"),
    )


# ---------------------------------------------------------------------------
# Public export: ordered list of all rules (used by the scorer)
# ---------------------------------------------------------------------------

ALL_RULES = [
    # KYC Outcome
    rule_kyc_status,
    rule_kyc_risk_score,
    rule_pep_flag,
    # Identity
    rule_identity_documents,
    # Income & Employment
    rule_employment_type,
    rule_employment_tenure,
    rule_income_sufficiency,
    # Repayment History
    rule_repayment_track_record,
    rule_defaults,
    rule_days_past_due,
]
