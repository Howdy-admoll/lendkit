"""
Repayment Service — Delinquency Classifier Unit Tests

All tests are pure Python — no DB, no HTTP calls.
"""

import pytest

from app.engine.delinquency import (
    ClassificationConfig,
    ClassificationResult,
    RepaymentStatus,
    classify,
    days_past_due_from_due_date,
)


# ===========================================================================
# classify — happy path status transitions
# ===========================================================================


class TestClassifyStatusTransitions:
    def test_dpd_zero_is_current(self):
        result = classify(0)
        assert result.status == RepaymentStatus.CURRENT
        assert not result.is_terminal
        assert not result.requires_collection
        assert not result.write_off_recommended

    def test_dpd_within_grace_period_is_at_risk(self):
        result = classify(5)
        assert result.status == RepaymentStatus.AT_RISK
        assert not result.requires_collection

    def test_dpd_at_grace_period_boundary_is_at_risk(self):
        # Default grace_period_days == 7 → DPD 7 → AT_RISK
        result = classify(7)
        assert result.status == RepaymentStatus.AT_RISK

    def test_dpd_just_past_grace_is_delinquent(self):
        # DPD 8 → DELINQUENT (grace_period_days = 7, delinquent_threshold = 8)
        result = classify(8)
        assert result.status == RepaymentStatus.DELINQUENT
        assert result.requires_collection
        assert not result.write_off_recommended

    def test_dpd_89_is_delinquent(self):
        result = classify(89)
        assert result.status == RepaymentStatus.DELINQUENT

    def test_dpd_90_is_default(self):
        result = classify(90)
        assert result.status == RepaymentStatus.DEFAULT
        assert result.requires_collection

    def test_dpd_180_is_default(self):
        result = classify(180)
        assert result.status == RepaymentStatus.DEFAULT
        assert not result.write_off_recommended

    def test_dpd_360_write_off_recommended(self):
        result = classify(360)
        assert result.status == RepaymentStatus.DEFAULT
        assert result.write_off_recommended

    def test_dpd_500_write_off_recommended(self):
        result = classify(500)
        assert result.write_off_recommended


# ===========================================================================
# classify — terminal states
# ===========================================================================


class TestClassifyTerminalStates:
    def test_settled_loan_is_terminal(self):
        result = classify(0, is_settled=True)
        assert result.status == RepaymentStatus.SETTLED
        assert result.is_terminal
        assert not result.requires_collection
        assert result.days_past_due == 0

    def test_settled_even_with_dpd(self):
        """Once settled, DPD doesn't matter — balance is zero."""
        result = classify(120, is_settled=True)
        assert result.status == RepaymentStatus.SETTLED
        assert result.days_past_due == 0  # reset to 0 on settlement

    def test_written_off_is_terminal(self):
        result = classify(400, is_written_off=True)
        assert result.status == RepaymentStatus.WRITTEN_OFF
        assert result.is_terminal
        assert not result.requires_collection
        assert not result.write_off_recommended  # already written off

    def test_written_off_takes_precedence_over_settled(self):
        """written_off is checked before settled."""
        result = classify(0, is_settled=True, is_written_off=True)
        assert result.status == RepaymentStatus.WRITTEN_OFF


# ===========================================================================
# classify — custom configuration
# ===========================================================================


class TestClassifyCustomConfig:
    def test_custom_grace_period(self):
        config = ClassificationConfig(
            grace_period_days=3,
            delinquent_threshold_days=4,
            default_threshold_days=30,
        )
        # DPD 3 → still AT_RISK with custom config
        assert classify(3, config=config).status == RepaymentStatus.AT_RISK
        # DPD 4 → DELINQUENT
        assert classify(4, config=config).status == RepaymentStatus.DELINQUENT

    def test_custom_default_threshold(self):
        config = ClassificationConfig(
            grace_period_days=7,
            delinquent_threshold_days=8,
            default_threshold_days=60,  # earlier than CBN standard
        )
        assert classify(59, config=config).status == RepaymentStatus.DELINQUENT
        assert classify(60, config=config).status == RepaymentStatus.DEFAULT


# ===========================================================================
# classify — validation
# ===========================================================================


class TestClassifyValidation:
    def test_negative_dpd_raises(self):
        with pytest.raises(ValueError, match="days_past_due cannot be negative"):
            classify(-1)


# ===========================================================================
# days_past_due_from_due_date helper
# ===========================================================================


class TestDaysPastDue:
    def test_due_today_returns_zero(self):
        assert days_past_due_from_due_date("2025-03-15", "2025-03-15") == 0

    def test_due_yesterday_returns_one(self):
        assert days_past_due_from_due_date("2025-03-14", "2025-03-15") == 1

    def test_future_due_date_returns_zero(self):
        assert days_past_due_from_due_date("2025-04-01", "2025-03-15") == 0

    def test_30_days_overdue(self):
        assert days_past_due_from_due_date("2025-02-13", "2025-03-15") == 30

    def test_exactly_90_days(self):
        assert days_past_due_from_due_date("2024-12-15", "2025-03-15") == 90
