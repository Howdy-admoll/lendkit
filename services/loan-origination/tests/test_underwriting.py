"""
Loan Origination — Underwriting Engine Unit Tests

All tests are pure Python — no DB, no HTTP calls.
"""

import pytest

from app.engine.underwriting import (
    TIER_PARAMS,
    TierParams,
    monthly_repayment,
    underwrite,
)

# ===========================================================================
# monthly_repayment helper
# ===========================================================================


class TestMonthlyRepayment:
    def test_zero_rate_returns_principal_divided(self):
        result = monthly_repayment(1_200_000, 0.0, 12)
        assert result == 100_000

    def test_standard_amortisation(self):
        # ₦100,000 at 24% APR over 12 months → monthly ≈ ₦9,456
        result = monthly_repayment(100_000_00, 0.24, 12)
        # 100_000_00 kobo = ₦100,000; expected monthly repayment ≈ ₦9,456
        assert 9_000_00 < result < 10_000_00

    def test_rounds_up_not_down(self):
        # Should always round UP (lender-safe)
        result = monthly_repayment(100_003, 0.18, 12)
        # Confirm it's ceiling, not floor
        import math

        r = 0.18 / 12
        factor = (1 + r) ** 12
        exact = 100_003 * r * factor / (factor - 1)
        assert result == math.ceil(exact)

    def test_zero_months_returns_zero(self):
        assert monthly_repayment(1_000_000, 0.24, 0) == 0


# ===========================================================================
# underwrite — eligibility
# ===========================================================================


class TestUnderwriteEligibility:
    def test_very_poor_declined(self):
        result = underwrite("very_poor", 50_000_00, 12)
        assert not result.approved
        assert "eligibility" in result.decline_reasons

    def test_poor_declined(self):
        result = underwrite("poor", 50_000_00, 12)
        assert not result.approved
        assert "eligibility" in result.decline_reasons

    def test_unknown_tier_declined(self):
        result = underwrite("platinum_plus", 50_000_00, 12)
        assert not result.approved
        assert "tier" in result.decline_reasons

    def test_fair_approved(self):
        result = underwrite("fair", 50_000_00, 12)
        assert result.approved

    def test_good_approved(self):
        result = underwrite("good", 100_000_00, 12)
        assert result.approved

    def test_excellent_approved(self):
        result = underwrite("excellent", 500_000_00, 36)
        assert result.approved


# ===========================================================================
# underwrite — amount capping
# ===========================================================================


class TestUnderwriteAmountCapping:
    def test_fair_amount_capped_at_500k(self):
        # Requesting ₦2,000,000 on a "fair" tier — max is ₦500,000
        result = underwrite("fair", 200_000_000, 12)
        assert result.approved
        assert result.approved_amount_kobo == TIER_PARAMS["fair"].max_amount_kobo

    def test_good_amount_capped_at_2m(self):
        result = underwrite("good", 400_000_000, 12)
        assert result.approved
        assert result.approved_amount_kobo == TIER_PARAMS["good"].max_amount_kobo

    def test_excellent_amount_not_capped(self):
        # Request ₦1,000,000 under a ₦5,000,000 ceiling — no cap
        result = underwrite("excellent", 100_000_000, 12)
        assert result.approved
        assert result.approved_amount_kobo == 100_000_000

    def test_amount_at_exactly_min_passes(self):
        result = underwrite("fair", 10_000_00, 6)  # ₦100,000 = min
        assert result.approved
        assert result.approved_amount_kobo == 10_000_00


# ===========================================================================
# underwrite — tenure capping
# ===========================================================================


class TestUnderwriteTenureCapping:
    def test_fair_tenure_capped_at_12_months(self):
        result = underwrite("fair", 50_000_00, 24)
        assert result.approved
        assert result.tenure_months == TIER_PARAMS["fair"].max_tenure_months

    def test_good_tenure_capped_at_24_months(self):
        result = underwrite("good", 100_000_00, 36)
        assert result.approved
        assert result.tenure_months == TIER_PARAMS["good"].max_tenure_months

    def test_excellent_accepts_36_months(self):
        result = underwrite("excellent", 100_000_000, 36)
        assert result.approved
        assert result.tenure_months == 36


# ===========================================================================
# underwrite — DTI guard
# ===========================================================================


class TestUnderwriteDTI:
    def test_low_dti_passes_unchanged(self):
        # ₦300,000/month income, ₦100,000 loan → repayment << 40% income
        result = underwrite(
            "excellent",
            requested_amount_kobo=10_000_000,  # ₦100,000
            tenure_months=12,
            monthly_income_kobo=30_000_000,    # ₦300,000
        )
        assert result.approved
        # Amount should NOT be reduced — well within DTI
        assert result.approved_amount_kobo == 10_000_000

    def test_high_dti_reduces_amount(self):
        # ₦50,000/month income, ₦5,000,000 loan → way over 40%
        result = underwrite(
            "excellent",
            requested_amount_kobo=500_000_000,  # ₦5,000,000
            tenure_months=12,
            monthly_income_kobo=5_000_000,      # ₦50,000
        )
        assert result.approved
        # Amount must be reduced to fit within 40% DTI
        assert result.approved_amount_kobo < 500_000_000

    def test_impossible_dti_declines(self):
        # ₦1,000/month income — can't service even the minimum loan
        result = underwrite(
            "excellent",
            requested_amount_kobo=500_000_000,
            tenure_months=12,
            monthly_income_kobo=100_00,  # ₦1,000/month
        )
        assert not result.approved
        assert "dti" in result.decline_reasons

    def test_no_income_skips_dti(self):
        # No income provided — DTI guard is skipped
        result = underwrite("good", 100_000_00, 12, monthly_income_kobo=None)
        assert result.approved


# ===========================================================================
# underwrite — APR and repayment maths
# ===========================================================================


class TestUnderwriteRepaymentMaths:
    def test_apr_matches_tier(self):
        result = underwrite("excellent", 100_000_000, 12)
        assert result.annual_percentage_rate == TIER_PARAMS["excellent"].base_apr

        result2 = underwrite("good", 50_000_000, 12)
        assert result2.annual_percentage_rate == TIER_PARAMS["good"].base_apr

    def test_total_repayable_equals_monthly_times_tenure(self):
        result = underwrite("fair", 30_000_00, 6)
        assert result.approved
        assert result.total_repayable_kobo == result.monthly_repayment_kobo * result.tenure_months

    def test_total_repayable_exceeds_principal(self):
        # Always true for APR > 0
        result = underwrite("good", 100_000_00, 12)
        assert result.total_repayable_kobo > result.approved_amount_kobo

    def test_monthly_repayment_positive(self):
        result = underwrite("fair", 30_000_00, 6)
        assert result.monthly_repayment_kobo > 0
