"""
Repayment Service — Payment Allocator Unit Tests

All tests are pure Python — no DB, no HTTP calls.
"""

import pytest

from app.engine.allocator import AllocationResult, allocate, daily_penalty


# ===========================================================================
# allocate — basic routing
# ===========================================================================


class TestAllocateBasicRouting:
    def test_payment_covers_penalty_only(self):
        result = allocate(5_000, accrued_penalty_kobo=5_000)
        assert result.penalty_portion_kobo == 5_000
        assert result.interest_portion_kobo == 0
        assert result.principal_portion_kobo == 0
        assert result.overpayment_kobo == 0
        assert result.remaining_penalty_kobo == 0

    def test_payment_covers_interest_only(self):
        result = allocate(3_000, accrued_interest_kobo=3_000)
        assert result.interest_portion_kobo == 3_000
        assert result.penalty_portion_kobo == 0
        assert result.principal_portion_kobo == 0
        assert result.overpayment_kobo == 0

    def test_payment_covers_principal_only(self):
        result = allocate(100_000, outstanding_principal_kobo=100_000)
        assert result.principal_portion_kobo == 100_000
        assert result.interest_portion_kobo == 0
        assert result.penalty_portion_kobo == 0
        assert result.overpayment_kobo == 0
        assert result.remaining_principal_kobo == 0

    def test_overpayment_captured(self):
        result = allocate(
            150_000,
            accrued_penalty_kobo=10_000,
            accrued_interest_kobo=20_000,
            outstanding_principal_kobo=100_000,
        )
        assert result.overpayment_kobo == 20_000
        assert result.is_full_settlement

    def test_is_full_settlement_false_when_remainder(self):
        result = allocate(50_000, outstanding_principal_kobo=100_000)
        assert not result.is_full_settlement
        assert result.remaining_principal_kobo == 50_000


# ===========================================================================
# allocate — priority ordering (penalty → interest → principal)
# ===========================================================================


class TestAllocatePriorityOrder:
    def test_penalty_cleared_before_interest(self):
        """If payment only covers penalty, interest is untouched."""
        result = allocate(
            5_000,
            accrued_penalty_kobo=5_000,
            accrued_interest_kobo=10_000,
            outstanding_principal_kobo=50_000,
        )
        assert result.penalty_portion_kobo == 5_000
        assert result.interest_portion_kobo == 0
        assert result.principal_portion_kobo == 0
        assert result.remaining_interest_kobo == 10_000

    def test_penalty_and_interest_cleared_before_principal(self):
        result = allocate(
            15_000,
            accrued_penalty_kobo=5_000,
            accrued_interest_kobo=10_000,
            outstanding_principal_kobo=50_000,
        )
        assert result.penalty_portion_kobo == 5_000
        assert result.interest_portion_kobo == 10_000
        assert result.principal_portion_kobo == 0
        assert result.remaining_principal_kobo == 50_000

    def test_full_allocation_across_all_buckets(self):
        result = allocate(
            65_000,
            accrued_penalty_kobo=5_000,
            accrued_interest_kobo=10_000,
            outstanding_principal_kobo=50_000,
        )
        assert result.penalty_portion_kobo == 5_000
        assert result.interest_portion_kobo == 10_000
        assert result.principal_portion_kobo == 50_000
        assert result.overpayment_kobo == 0
        assert result.is_full_settlement

    def test_payment_sum_invariant(self):
        """All portions + overpayment must equal the original payment."""
        payment = 77_777
        result = allocate(
            payment,
            accrued_penalty_kobo=3_000,
            accrued_interest_kobo=7_000,
            outstanding_principal_kobo=60_000,
        )
        total = (
            result.penalty_portion_kobo
            + result.interest_portion_kobo
            + result.principal_portion_kobo
            + result.overpayment_kobo
        )
        assert total == payment


# ===========================================================================
# allocate — edge cases and validation
# ===========================================================================


class TestAllocateEdgeCases:
    def test_zero_payment_raises_value_error(self):
        with pytest.raises(ValueError, match="payment_kobo must be positive"):
            allocate(0)

    def test_negative_payment_raises_value_error(self):
        with pytest.raises(ValueError, match="payment_kobo must be positive"):
            allocate(-100)

    def test_negative_penalty_raises_value_error(self):
        with pytest.raises(ValueError, match="accrued_penalty_kobo cannot be negative"):
            allocate(1_000, accrued_penalty_kobo=-1)

    def test_negative_interest_raises_value_error(self):
        with pytest.raises(ValueError, match="accrued_interest_kobo cannot be negative"):
            allocate(1_000, accrued_interest_kobo=-1)

    def test_negative_principal_raises_value_error(self):
        with pytest.raises(ValueError, match="outstanding_principal_kobo cannot be negative"):
            allocate(1_000, outstanding_principal_kobo=-1)

    def test_all_zero_balances_is_pure_overpayment(self):
        result = allocate(10_000)
        assert result.overpayment_kobo == 10_000
        assert result.penalty_portion_kobo == 0
        assert result.interest_portion_kobo == 0
        assert result.principal_portion_kobo == 0


# ===========================================================================
# daily_penalty
# ===========================================================================


class TestDailyPenalty:
    def test_zero_days_no_penalty(self):
        assert daily_penalty(1_000_000, 0) == 0

    def test_zero_principal_no_penalty(self):
        assert daily_penalty(0, 30) == 0

    def test_penalty_grows_with_days(self):
        p1 = daily_penalty(1_000_000, 10)
        p2 = daily_penalty(1_000_000, 20)
        assert p2 > p1

    def test_default_rate_one_day(self):
        """0.1% daily rate on ₦1,000,000 (10,000,000 kobo) for 1 day = 10,000 kobo."""
        # 10,000,000 * 0.001 * 1 = 10,000 kobo
        result = daily_penalty(10_000_000, 1, daily_rate=0.001)
        assert result == 10_000

    def test_custom_rate(self):
        result = daily_penalty(10_000_000, 5, daily_rate=0.002)
        # 10,000,000 * 0.002 * 5 = 100,000 kobo
        assert result == 100_000
