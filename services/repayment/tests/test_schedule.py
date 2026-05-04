"""
Repayment Service — Amortization Schedule Engine Unit Tests

All tests are pure Python — no DB, no HTTP calls.
"""

import math
from datetime import date

import pytest

from app.engine.schedule import (
    Installment,
    _add_months,
    _monthly_installment,
    generate,
    total_interest,
    total_repayable,
)


# ===========================================================================
# _add_months helper
# ===========================================================================


class TestAddMonths:
    def test_simple_case(self):
        assert _add_months(date(2025, 1, 15), 1) == date(2025, 2, 15)

    def test_crosses_year_boundary(self):
        assert _add_months(date(2025, 12, 1), 2) == date(2026, 2, 1)

    def test_clamps_to_last_day_of_february(self):
        # Jan 31 + 1 month → Feb 28 (non-leap year)
        assert _add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)

    def test_clamps_to_last_day_of_february_leap_year(self):
        # Jan 31 + 1 month → Feb 29 (2024 is a leap year)
        assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)

    def test_zero_months_returns_same_date(self):
        d = date(2025, 6, 15)
        assert _add_months(d, 0) == d


# ===========================================================================
# _monthly_installment helper
# ===========================================================================


class TestMonthlyInstallment:
    def test_zero_rate_divides_evenly(self):
        result = _monthly_installment(1_200_000, 0.0, 12)
        assert result == 100_000

    def test_zero_months_returns_zero(self):
        assert _monthly_installment(1_000_000, 0.24, 0) == 0

    def test_standard_amortisation_24pct_12m(self):
        # ₦100,000 at 24% APR over 12 months → monthly ≈ ₦9,456
        result = _monthly_installment(10_000_000, 0.24, 12)
        assert 9_000_00 < result < 10_000_00  # in kobo

    def test_rounds_up_not_down(self):
        """Monthly installment must always be rounded UP (lender-safe)."""
        result = _monthly_installment(100_003, 0.18, 12)
        r = 0.18 / 12
        factor = (1 + r) ** 12
        exact = 100_003 * r * factor / (factor - 1)
        assert result == math.ceil(exact)


# ===========================================================================
# generate — structure and count
# ===========================================================================


class TestGenerateStructure:
    def test_returns_correct_number_of_installments(self):
        schedule = generate(10_000_000, 0.24, 12, date(2025, 2, 1))
        assert len(schedule) == 12

    def test_installment_numbers_are_sequential(self):
        schedule = generate(10_000_000, 0.24, 6, date(2025, 2, 1))
        for i, inst in enumerate(schedule, start=1):
            assert inst.installment_number == i

    def test_due_dates_advance_monthly(self):
        schedule = generate(10_000_000, 0.24, 6, date(2025, 1, 15))
        for i, inst in enumerate(schedule):
            expected = _add_months(date(2025, 1, 15), i)
            assert inst.due_date == expected

    def test_empty_schedule_for_zero_tenure(self):
        assert generate(10_000_000, 0.24, 0, date(2025, 1, 1)) == []

    def test_empty_schedule_for_zero_principal(self):
        assert generate(0, 0.24, 12, date(2025, 1, 1)) == []


# ===========================================================================
# generate — mathematical correctness
# ===========================================================================


class TestGenerateMaths:
    def test_first_row_opening_balance_equals_principal(self):
        principal = 50_000_000  # ₦500,000 in kobo
        schedule = generate(principal, 0.36, 12, date(2025, 1, 1))
        assert schedule[0].opening_balance_kobo == principal

    def test_closing_balance_of_each_row_equals_next_opening(self):
        schedule = generate(30_000_000, 0.24, 6, date(2025, 1, 1))
        for i in range(len(schedule) - 1):
            assert schedule[i].closing_balance_kobo == schedule[i + 1].opening_balance_kobo

    def test_final_closing_balance_is_zero(self):
        schedule = generate(10_000_000, 0.24, 12, date(2025, 1, 1))
        assert schedule[-1].closing_balance_kobo == 0

    def test_total_due_equals_principal_plus_interest(self):
        principal = 10_000_000
        schedule = generate(principal, 0.24, 12, date(2025, 1, 1))
        total = total_repayable(schedule)
        interest = total_interest(schedule)
        # total repayable = principal + all interest (±1 kobo rounding)
        assert abs(total - (principal + interest)) <= 1

    def test_total_repayable_exceeds_principal(self):
        """APR > 0 always means you pay back more than you borrowed."""
        schedule = generate(10_000_000, 0.18, 12, date(2025, 1, 1))
        assert total_repayable(schedule) > 10_000_000

    def test_zero_rate_total_repayable_equals_principal(self):
        """No interest → you repay exactly what you borrowed."""
        schedule = generate(1_200_000, 0.0, 12, date(2025, 1, 1))
        assert total_repayable(schedule) == 1_200_000

    def test_principal_portions_sum_to_original(self):
        """Sum of all principal_due must equal the original principal (±1 kobo)."""
        principal = 20_000_000
        schedule = generate(principal, 0.24, 12, date(2025, 1, 1))
        principal_sum = sum(inst.principal_due_kobo for inst in schedule)
        assert abs(principal_sum - principal) <= 1

    def test_all_installments_have_positive_interest(self):
        """Every row should have a positive interest component when APR > 0."""
        schedule = generate(10_000_000, 0.24, 12, date(2025, 1, 1))
        assert all(inst.interest_due_kobo > 0 for inst in schedule)

    def test_interest_declines_across_schedule(self):
        """In a reducing-balance schedule, interest decreases each month."""
        schedule = generate(10_000_000, 0.24, 12, date(2025, 1, 1))
        interest_values = [inst.interest_due_kobo for inst in schedule]
        # Each month's interest should be ≤ the previous month's
        for i in range(1, len(interest_values)):
            assert interest_values[i] <= interest_values[i - 1]

    def test_36_month_tenure(self):
        """Long tenure — schedule generates correctly and zeroes out."""
        schedule = generate(500_000_000, 0.18, 36, date(2025, 1, 1))
        assert len(schedule) == 36
        assert schedule[-1].closing_balance_kobo == 0

    def test_total_due_equals_principal_plus_interest_each_row(self):
        """Per-row: total_due == principal_due + interest_due."""
        schedule = generate(10_000_000, 0.24, 12, date(2025, 1, 1))
        for inst in schedule:
            assert inst.total_due_kobo == inst.principal_due_kobo + inst.interest_due_kobo
