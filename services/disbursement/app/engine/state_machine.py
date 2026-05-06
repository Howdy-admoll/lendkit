"""
Disbursement Service — State Machine

Tracks the lifecycle of a single disbursement attempt:

    PENDING
      │
      ▼
    RECIPIENT_READY   ← transfer recipient exists in Paystack
      │
      ▼
    TRANSFER_INITIATED  ← Paystack transfer created, awaiting webhook
      │
      ├──► COMPLETED    ← transfer.success webhook received
      │
      ├──► FAILED       ← transfer.failed webhook / timeout (retry-eligible)
      │      │
      │      └──► PENDING  (retry resets to PENDING, increments attempt count)
      │
      └──► REVERSED     ← transfer.reversed (Paystack clawed back funds)

Terminal states: COMPLETED, REVERSED, CANCELLED
Retry-eligible:  FAILED (up to max_attempts)

This module is pure Python — no DB, no I/O, fully testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------


class DisbursementState(str, Enum):
    PENDING = "pending"                       # received, not yet started
    RECIPIENT_READY = "recipient_ready"       # Paystack recipient created
    TRANSFER_INITIATED = "transfer_initiated" # Paystack transfer in-flight
    COMPLETED = "completed"                   # funds confirmed received
    FAILED = "failed"                         # transfer rejected / timed out
    REVERSED = "reversed"                     # Paystack clawed back funds
    CANCELLED = "cancelled"                   # manually cancelled


# ---------------------------------------------------------------------------
# Allowed transitions
# ---------------------------------------------------------------------------

_TRANSITIONS: dict[DisbursementState, set[DisbursementState]] = {
    DisbursementState.PENDING: {
        DisbursementState.RECIPIENT_READY,
        DisbursementState.CANCELLED,
    },
    DisbursementState.RECIPIENT_READY: {
        DisbursementState.TRANSFER_INITIATED,
        DisbursementState.CANCELLED,
    },
    DisbursementState.TRANSFER_INITIATED: {
        DisbursementState.COMPLETED,
        DisbursementState.FAILED,
        DisbursementState.REVERSED,
    },
    DisbursementState.FAILED: {
        DisbursementState.PENDING,   # retry resets to PENDING
        DisbursementState.CANCELLED,
    },
    # Terminal states — no outbound transitions
    DisbursementState.COMPLETED: set(),
    DisbursementState.REVERSED: set(),
    DisbursementState.CANCELLED: set(),
}

_TERMINAL_STATES = {
    DisbursementState.COMPLETED,
    DisbursementState.REVERSED,
    DisbursementState.CANCELLED,
}

_RETRY_ELIGIBLE = {DisbursementState.FAILED}

MAX_ATTEMPTS = 3  # maximum disbursement attempts before giving up


# ---------------------------------------------------------------------------
# Transition validation
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """Raised when a state transition is not permitted."""


def transition(
    current: DisbursementState,
    target: DisbursementState,
) -> DisbursementState:
    """
    Validate and apply a state transition.

    Parameters
    ----------
    current:
        The disbursement's current state.
    target:
        The desired next state.

    Returns
    -------
    The target state (same object) if the transition is valid.

    Raises
    ------
    InvalidTransitionError:
        If the transition is not permitted.
    """
    allowed = _TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from {current.value!r} to {target.value!r}. "
            f"Allowed from {current.value!r}: "
            + (", ".join(s.value for s in allowed) if allowed else "none (terminal state)")
        )
    return target


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def is_terminal(state: DisbursementState) -> bool:
    """True if the disbursement has reached a final, non-retryable state."""
    return state in _TERMINAL_STATES


def is_retry_eligible(state: DisbursementState, attempt_count: int) -> bool:
    """
    True if a failed disbursement can be retried.

    A disbursement is retry-eligible when:
      - It is in a FAILED state
      - It has not yet exhausted MAX_ATTEMPTS
    """
    return state in _RETRY_ELIGIBLE and attempt_count < MAX_ATTEMPTS


def next_retry_delay_seconds(attempt_count: int) -> int:
    """
    Exponential backoff delay before the next retry attempt.

    Attempt 1 →  60s  (1 min)
    Attempt 2 → 300s  (5 min)
    Attempt 3 → 900s (15 min)
    """
    delays = [60, 300, 900]
    idx = max(0, min(attempt_count - 1, len(delays) - 1))
    return delays[idx]
