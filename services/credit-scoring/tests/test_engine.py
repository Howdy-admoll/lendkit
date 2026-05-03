"""
Credit Scoring — Scoring Engine Unit Tests

Tests are fully isolated — no DB, no Redis.
The engine is pure Python so we can unit-test every rule and the scorer
without any infrastructure.
"""

from app.engine.rules import (
    rule_days_past_due,
    rule_defaults,
    rule_employment_tenure,
    rule_employment_type,
    rule_identity_documents,
    rule_income_sufficiency,
    rule_kyc_risk_score,
    rule_kyc_status,
    rule_pep_flag,
    rule_repayment_track_record,
)
from app.engine.scorer import compute_score
from app.schemas.score import IncomeSignal, KYCSignal, RepaymentSignal

# ===========================================================================
# Helper fixtures
# ===========================================================================


def approved_kyc(**kwargs) -> KYCSignal:
    defaults = {
        "verification_id": "kyc-001",
        "status": "approved",
        "level": "standard",
        "risk_score": 20,
        "is_pep": False,
        "is_sanctioned": False,
        "verified_documents": ["bvn", "nin"],
    }
    return KYCSignal(**{**defaults, **kwargs})


def good_income(**kwargs) -> IncomeSignal:
    defaults = {
        "monthly_income_kobo": 30_000_00,  # ₦300,000/month
        "employment_type": "salary",
        "months_employed": 36,
    }
    return IncomeSignal(**{**defaults, **kwargs})


def clean_repayment(**kwargs) -> RepaymentSignal:
    defaults = {
        "total_loans": 3,
        "on_time_payments": 36,
        "late_payments": 0,
        "missed_payments": 0,
        "defaults": 0,
        "max_days_past_due": 0,
    }
    return RepaymentSignal(**{**defaults, **kwargs})


# ===========================================================================
# Rule: KYC Status
# ===========================================================================


class TestKYCStatusRule:
    def test_approved_awards_max(self):
        result = rule_kyc_status(approved_kyc())
        assert result.points_awarded == 35
        assert result.impact == "positive"

    def test_rejected_penalises(self):
        result = rule_kyc_status(approved_kyc(status="rejected"))
        assert result.points_awarded == -40
        assert result.impact == "negative"

    def test_in_review_partial(self):
        result = rule_kyc_status(approved_kyc(status="in_review"))
        assert 0 < result.points_awarded < 35

    def test_none_input_zero_possible(self):
        result = rule_kyc_status(None)
        assert result.points_awarded == 0
        assert result.points_possible == 0
        assert not result.is_available


# ===========================================================================
# Rule: KYC Risk Score
# ===========================================================================


class TestKYCRiskScoreRule:
    def test_low_risk_high_points(self):
        result = rule_kyc_risk_score(approved_kyc(risk_score=0))
        assert result.points_awarded == 10

    def test_high_risk_zero_points(self):
        result = rule_kyc_risk_score(approved_kyc(risk_score=100))
        assert result.points_awarded == 0

    def test_mid_risk(self):
        result = rule_kyc_risk_score(approved_kyc(risk_score=50))
        assert result.points_awarded == 5

    def test_no_risk_score_unavailable(self):
        result = rule_kyc_risk_score(approved_kyc(risk_score=None))
        assert result.points_possible == 0

    def test_none_kyc_unavailable(self):
        result = rule_kyc_risk_score(None)
        assert result.points_possible == 0


# ===========================================================================
# Rule: PEP Flag
# ===========================================================================


class TestPEPFlagRule:
    def test_pep_penalises(self):
        result = rule_pep_flag(approved_kyc(is_pep=True))
        assert result.points_awarded == -20
        assert result.impact == "negative"

    def test_not_pep_neutral(self):
        result = rule_pep_flag(approved_kyc(is_pep=False))
        assert result.points_awarded == 0
        assert result.impact == "neutral"


# ===========================================================================
# Rule: Identity Documents
# ===========================================================================


class TestIdentityDocumentsRule:
    def test_bvn_plus_nin(self):
        result = rule_identity_documents(approved_kyc(verified_documents=["bvn", "nin"]))
        assert result.points_awarded == 22  # 12 + 10 = 22, capped at 25
        assert result.points_possible == 25

    def test_all_docs_capped_at_25(self):
        result = rule_identity_documents(
            approved_kyc(
                verified_documents=["bvn", "nin", "passport", "drivers_license", "voters_card"]
            )
        )
        assert result.points_awarded == 25  # capped

    def test_no_docs_unavailable(self):
        result = rule_identity_documents(approved_kyc(verified_documents=[]))
        assert result.points_possible == 0

    def test_none_kyc_unavailable(self):
        result = rule_identity_documents(None)
        assert result.points_possible == 0


# ===========================================================================
# Rule: Employment Type
# ===========================================================================


class TestEmploymentTypeRule:
    def test_salary_max(self):
        result = rule_employment_type(good_income(employment_type="salary"))
        assert result.points_awarded == 12
        assert result.impact == "positive"

    def test_unemployed_negative(self):
        result = rule_employment_type(good_income(employment_type="unemployed"))
        assert result.points_awarded < 0
        assert result.impact == "negative"

    def test_none_unavailable(self):
        result = rule_employment_type(None)
        assert result.points_possible == 0


# ===========================================================================
# Rule: Employment Tenure
# ===========================================================================


class TestEmploymentTenureRule:
    def test_short_tenure_low_points(self):
        result = rule_employment_tenure(good_income(months_employed=3))
        assert result.points_awarded == 1

    def test_long_tenure_max_points(self):
        result = rule_employment_tenure(good_income(months_employed=60))
        assert result.points_awarded == 8

    def test_medium_tenure(self):
        result = rule_employment_tenure(good_income(months_employed=18))
        assert result.points_awarded == 5

    def test_no_tenure_unavailable(self):
        result = rule_employment_tenure(IncomeSignal(employment_type="salary"))
        assert result.points_possible == 0


# ===========================================================================
# Rule: Income Sufficiency
# ===========================================================================


class TestIncomeSufficiencyRule:
    def test_low_dti_max_points(self):
        # ₦300,000/month income, ₦600,000 loan → monthly repayment ₦50,000 → DTI 16.7%
        result = rule_income_sufficiency(good_income(), requested_kobo=60_000_00)
        assert result.points_awarded == 5

    def test_high_dti_negative(self):
        # ₦100,000/month income, ₦10,000,000 loan → DTI >>55%
        result = rule_income_sufficiency(
            IncomeSignal(monthly_income_kobo=10_000_00, employment_type="salary"),
            requested_kobo=1_000_000_00,
        )
        assert result.points_awarded < 0

    def test_no_loan_amount_baseline(self):
        result = rule_income_sufficiency(good_income(), requested_kobo=None)
        assert result.points_awarded > 0

    def test_no_income_unavailable(self):
        result = rule_income_sufficiency(None, requested_kobo=100_000_00)
        assert result.points_possible == 0


# ===========================================================================
# Rule: Repayment Track Record
# ===========================================================================


class TestRepaymentTrackRecordRule:
    def test_perfect_record_max(self):
        result = rule_repayment_track_record(clean_repayment())
        assert result.points_awarded == 8

    def test_poor_record_negative(self):
        result = rule_repayment_track_record(
            clean_repayment(on_time_payments=5, late_payments=10, missed_payments=10)
        )
        assert result.points_awarded < 0

    def test_no_history_unavailable(self):
        result = rule_repayment_track_record(RepaymentSignal())
        assert result.points_possible == 0

    def test_none_unavailable(self):
        result = rule_repayment_track_record(None)
        assert result.points_possible == 0


# ===========================================================================
# Rule: Defaults
# ===========================================================================


class TestDefaultsRule:
    def test_no_defaults_positive(self):
        result = rule_defaults(clean_repayment())
        assert result.points_awarded == 4
        assert result.impact == "positive"

    def test_one_default_negative(self):
        result = rule_defaults(clean_repayment(defaults=1))
        assert result.points_awarded == -5

    def test_multiple_defaults_heavy_penalty(self):
        result = rule_defaults(clean_repayment(defaults=3))
        assert result.points_awarded == -10


# ===========================================================================
# Rule: Days Past Due
# ===========================================================================


class TestDaysPastDueRule:
    def test_never_past_due_max(self):
        result = rule_days_past_due(clean_repayment(max_days_past_due=0))
        assert result.points_awarded == 3

    def test_90_plus_days_severe_penalty(self):
        result = rule_days_past_due(clean_repayment(max_days_past_due=120))
        assert result.points_awarded == -8


# ===========================================================================
# Scorer Integration Tests
# ===========================================================================


class TestScorer:
    def test_sanctioned_hard_stop(self):
        result = compute_score(kyc=approved_kyc(is_sanctioned=True))
        assert result.is_sanctioned
        assert result.score == 300  # score_min
        assert result.tier == "very_poor"

    def test_excellent_profile(self):
        result = compute_score(
            kyc=approved_kyc(risk_score=5, is_pep=False, verified_documents=["bvn", "nin"]),
            income=good_income(months_employed=60),
            repayment=clean_repayment(),
            requested_loan_amount_kobo=60_000_00,
        )
        assert result.score >= 750
        assert result.tier == "excellent"
        assert not result.is_declined

    def test_rejected_kyc_very_poor(self):
        result = compute_score(kyc=approved_kyc(status="rejected"))
        assert result.score < 550
        assert result.tier in ("very_poor", "poor")

    def test_no_signals_cannot_score(self):
        result = compute_score()
        assert result.tier == "very_poor"
        assert "Insufficient data" in result.recommendation

    def test_kyc_only_produces_valid_score(self):
        result = compute_score(kyc=approved_kyc())
        assert 300 <= result.score <= 850
        assert result.tier is not None

    def test_score_in_bounds(self):
        """Score must always be in [300, 850] regardless of inputs."""
        # Worst possible profile (rejected KYC, many defaults, unemployed)
        result = compute_score(
            kyc=approved_kyc(
                status="rejected",
                risk_score=99,
                is_pep=True,
                verified_documents=[],
            ),
            income=IncomeSignal(employment_type="unemployed", months_employed=0),
            repayment=RepaymentSignal(
                total_loans=5,
                on_time_payments=2,
                late_payments=5,
                missed_payments=10,
                defaults=3,
                max_days_past_due=180,
            ),
        )
        assert 300 <= result.score <= 850

    def test_factors_populated(self):
        result = compute_score(
            kyc=approved_kyc(),
            income=good_income(),
            repayment=clean_repayment(),
        )
        assert len(result.factors) > 0
        factor_keys = {f.factor_key for f in result.factors}
        assert "kyc_status" in factor_keys

    def test_pep_reduces_score(self):
        base = compute_score(kyc=approved_kyc(is_pep=False))
        pep = compute_score(kyc=approved_kyc(is_pep=True))
        assert pep.score < base.score

    def test_expires_at_set(self):
        result = compute_score(kyc=approved_kyc())
        assert result.expires_at is not None
        assert result.expires_at > result.computed_at
