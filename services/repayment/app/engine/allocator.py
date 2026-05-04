"""
Repayment Service — Payment Allocation Engine

Pure functions — no DB, no I/O, fully testable.

When a borrower makes a payment, it must be allocated across three buckets
in strict priority order:

    1. Accrued penalties  (highest priority — lender recoup)
    2. Accrued interest   (second priority)
    3. Outstanding principal  (last — reduces the balance you owe)

Any excess beyond what is owed becomes overpayment, which the caller can
credit back or hold in a suspense account.

All values are in kobo (integer). Division is performed in kobo so there is
no floating-point drift.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AllocationResult:
    """
    Breakdown of how a payment was distributed across the three buckets.

    All fields are in kobo. The invariant is:
        penalty_portion + interest_portion + principal_portion + overpayment
        == payment_amount
    """

    payment_amount_kobo: int      # original payment received
    penalty_portion_kobo: int     # amount applied to penalties
    interest_portion_kobo: int    # amount applied to accrued interest
    principal_portion_kobo: int   # amount applied to outstanding principal
    overpayment_kobo: int         # excess beyond total outstanding (refundable)

    # Resulting balances after allocation
    remaining_penalty_kobo: int
    remaining_interest_kobo: int
    remaining_principal_kobo: int

    @property
    def total_outstanding_before(self) -> int:
        return (
            self.remaining_penalty_kobo
            + self.penalty_portion_kobo
            + self.remaining_interest_kobo
            + self.interest_portion_kobo
            + self.remaining_principal_kobo
            + self.principal_portion_kobo
        )

    @property
    def total_outstanding_after(self) -> int:
        return (
            self.remaining_penalty_kobo
            + self.remaining_interest_kobo
            + self.remaining_principal_kobo
        )

    @property
    def is_full_settlement(self) -> bool:
        """True if payment cleared all outstanding balances."""
        return self.total_outstanding_after == 0


# ---------------------------------------------------------------------------
# Core allocation function
# ---------------------------------------------------------------------------


def allocate(
    payment_kobo: int,
    *,
    accrued_penalty_kobo: int = 0,
    accrued_interest_kobo: int = 0,
    outstanding_principal_kobo: int = 0,
) -> AllocationResult:
    """
    Allocate a payment across penalty → interest → principal.

    Parameters
    ----------
    payment_kobo:
        The gross payment amount received (must be > 0).
    accrued_penalty_kobo:
        Total penalty charges currently outstanding.
    accrued_interest_kobo:
        Total accrued interest currently outstanding.
    outstanding_principal_kobo:
        Total remaining principal currently outstanding.

    Returns
    -------
    AllocationResult with per-bucket breakdown and resulting balances.

    Raises
    ------
    ValueError:
        If payment_kobo ≤ 0 or any balance parameter is negative.
    """
    if payment_kobo <= 0:
        raise ValueError(f"payment_kobo must be positive, got {payment_kobo}")
    if accrued_penalty_kobo < 0:
        raise ValueError("accrued_penalty_kobo cannot be negative")
    if accrued_interest_kobo < 0:
        raise ValueError("accrued_interest_kobo cannot be negative")
    if outstanding_principal_kobo < 0:
        raise ValueError("outstanding_principal_kobo cannot be negative")

    remaining_payment = payment_kobo

    # --- Bucket 1: Penalties ---
    penalty_taken = min(remaining_payment, accrued_penalty_kobo)
    remaining_payment -= penalty_taken
    remaining_penalty = accrued_penalty_kobo - penalty_taken

    # --- Bucket 2: Interest ---
    interest_taken = min(remaining_payment, accrued_interest_kobo)
    remaining_payment -= interest_taken
    remaining_interest = accrued_interest_kobo - interest_taken

    # --- Bucket 3: Principal ---
    principal_taken = min(remaining_payment, outstanding_principal_kobo)
    remaining_payment -= principal_taken
    remaining_principal = outstanding_principal_kobo - principal_taken

    # Whatever is left is overpayment
    overpayment = remaining_payment

    return AllocationResult(
        payment_amount_kobo=payment_kobo,
        penalty_portion_kobo=penalty_taken,
        interest_portion_kobo=interest_taken,
        principal_portion_kobo=principal_taken,
        overpayment_kobo=overpayment,
        remaining_penalty_kobo=remaining_penalty,
        remaining_interest_kobo=remaining_interest,
        remaining_principal_kobo=remaining_principal,
    )


# ---------------------------------------------------------------------------
# Penalty calculation
# ---------------------------------------------------------------------------


_DEFAULT_DAILY_PENALTY_RATE = 0.001  # 0.1% of outstanding principal per day


def daily_penalty(
    outstanding_principal_kobo: int,
    days_past_due: int,
    daily_rate: float = _DEFAULT_DAILY_PENALTY_RATE,
) -> int:
    """
    Calculate total penalty accrued for `days_past_due` days past due.

    Penalty = outstanding_principal × daily_rate × days_past_due
    Rounded up (lender-safe).

    Parameters
    ----------
    outstanding_principal_kobo:
        Current outstanding principal balance.
    days_past_due:
        Number of calendar days the payment is overdue.
    daily_rate:
        Daily penalty rate (default: 0.001 = 0.1% per day).
    """
    import math

    if days_past_due <= 0 or outstanding_principal_kobo <= 0:
        return 0
    return math.ceil(outstanding_principal_kobo * daily_rate * days_past_due)
