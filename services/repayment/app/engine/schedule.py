"""
Repayment Service — Amortization Schedule Engine

Pure functions — no DB, no I/O, fully testable.

Given a loan (principal, APR, tenure, start_date) generates the complete
reducing-balance amortization schedule: one installment row per month.

Each row shows:
  - What you owe at the start of the period
  - How much of the payment covers interest
  - How much chips away at principal
  - Your balance after payment

The last installment is adjusted (±1 kobo) to eliminate any rounding drift
so that the schedule zeroes out exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Installment:
    """One row in the amortization schedule."""

    installment_number: int          # 1-indexed
    due_date: date                   # calendar due date
    opening_balance_kobo: int        # balance at start of period
    principal_due_kobo: int          # principal portion of this payment
    interest_due_kobo: int           # interest portion
    total_due_kobo: int              # principal + interest (= monthly installment)
    closing_balance_kobo: int        # balance after payment


# ---------------------------------------------------------------------------
# Date arithmetic
# ---------------------------------------------------------------------------


def _add_months(d: date, months: int) -> date:
    """
    Add `months` calendar months to `d`, clamping to the last day of the
    target month if the day overflows (e.g., Jan 31 + 1 month → Feb 28/29).
    """
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    # Clamp day to the last valid day of the target month
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


# ---------------------------------------------------------------------------
# Core formula helpers
# ---------------------------------------------------------------------------


def _monthly_installment(principal: int, annual_rate: float, months: int) -> int:
    """
    Standard reducing-balance (amortising) monthly payment, in kobo.
    Always rounded UP (lender-safe).

    Formula:
        r = annual_rate / 12
        P * r * (1+r)^n / ((1+r)^n - 1)
    """
    if months <= 0:
        return 0
    r = annual_rate / 12
    if r == 0:
        return math.ceil(principal / months)
    factor = (1 + r) ** months
    return math.ceil(principal * r * factor / (factor - 1))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(
    principal_kobo: int,
    annual_rate: float,
    tenure_months: int,
    first_due_date: date,
) -> list[Installment]:
    """
    Generate the full amortization schedule for a loan.

    Parameters
    ----------
    principal_kobo:
        Original loan principal in kobo.
    annual_rate:
        Annual interest rate as a decimal (e.g. 0.24 for 24%).
    tenure_months:
        Total repayment period in months.
    first_due_date:
        Calendar date of the first installment.

    Returns
    -------
    List of `Installment` objects, one per month (length == tenure_months).
    The list is sorted ascending by due_date.

    Notes
    -----
    - All kobo values are integers.
    - Interest each period = opening_balance × (annual_rate / 12), ceil-rounded.
    - Principal each period = monthly_installment − interest.
    - The final installment absorbs any accumulated rounding drift so the
      closing balance reaches exactly zero.
    """
    if tenure_months <= 0 or principal_kobo <= 0:
        return []

    monthly = _monthly_installment(principal_kobo, annual_rate, tenure_months)
    r_monthly = annual_rate / 12

    schedule: list[Installment] = []
    balance = principal_kobo

    for i in range(1, tenure_months + 1):
        due_date = _add_months(first_due_date, i - 1)
        opening_balance = balance

        # Interest this period (ceil — never shortchange the lender)
        interest = math.ceil(opening_balance * r_monthly) if r_monthly > 0 else 0

        # On the last installment, pay off whatever is left
        if i == tenure_months:
            principal = opening_balance
            total = opening_balance + interest
        else:
            total = monthly
            principal = total - interest
            # Guard against negative principal (can happen with very low balances)
            if principal <= 0:
                principal = opening_balance
                total = opening_balance + interest

        closing_balance = max(0, opening_balance - principal)

        schedule.append(
            Installment(
                installment_number=i,
                due_date=due_date,
                opening_balance_kobo=opening_balance,
                principal_due_kobo=principal,
                interest_due_kobo=interest,
                total_due_kobo=total,
                closing_balance_kobo=closing_balance,
            )
        )

        balance = closing_balance

    return schedule


def total_interest(schedule: list[Installment]) -> int:
    """Sum of all interest portions across the full schedule (kobo)."""
    return sum(inst.interest_due_kobo for inst in schedule)


def total_repayable(schedule: list[Installment]) -> int:
    """Sum of all payments across the full schedule (kobo)."""
    return sum(inst.total_due_kobo for inst in schedule)
