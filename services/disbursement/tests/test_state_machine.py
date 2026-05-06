"""
Disbursement Service — State Machine Unit Tests

All tests are pure Python — no DB, no HTTP calls.
"""

import pytest

from app.engine.state_machine import (
    MAX_ATTEMPTS,
    DisbursementState,
    InvalidTransitionError,
    is_retry_eligible,
    is_terminal,
    next_retry_delay_seconds,
    transition,
)


# ===========================================================================
# transition — valid paths
# ===========================================================================


class TestTransitionValid:
    def test_pending_to_recipient_ready(self):
        result = transition(DisbursementState.PENDING, DisbursementState.RECIPIENT_READY)
        assert result == DisbursementState.RECIPIENT_READY

    def test_pending_to_cancelled(self):
        result = transition(DisbursementState.PENDING, DisbursementState.CANCELLED)
        assert result == DisbursementState.CANCELLED

    def test_recipient_ready_to_transfer_initiated(self):
        result = transition(DisbursementState.RECIPIENT_READY, DisbursementState.TRANSFER_INITIATED)
        assert result == DisbursementState.TRANSFER_INITIATED

    def test_transfer_initiated_to_completed(self):
        result = transition(DisbursementState.TRANSFER_INITIATED, DisbursementState.COMPLETED)
        assert result == DisbursementState.COMPLETED

    def test_transfer_initiated_to_failed(self):
        result = transition(DisbursementState.TRANSFER_INITIATED, DisbursementState.FAILED)
        assert result == DisbursementState.FAILED

    def test_transfer_initiated_to_reversed(self):
        result = transition(DisbursementState.TRANSFER_INITIATED, DisbursementState.REVERSED)
        assert result == DisbursementState.REVERSED

    def test_failed_to_pending_for_retry(self):
        """FAILED → PENDING represents a retry reset."""
        result = transition(DisbursementState.FAILED, DisbursementState.PENDING)
        assert result == DisbursementState.PENDING

    def test_failed_to_cancelled(self):
        result = transition(DisbursementState.FAILED, DisbursementState.CANCELLED)
        assert result == DisbursementState.CANCELLED


# ===========================================================================
# transition — invalid paths
# ===========================================================================


class TestTransitionInvalid:
    def test_completed_to_anything_raises(self):
        with pytest.raises(InvalidTransitionError, match="terminal state"):
            transition(DisbursementState.COMPLETED, DisbursementState.PENDING)

    def test_reversed_to_anything_raises(self):
        with pytest.raises(InvalidTransitionError, match="terminal state"):
            transition(DisbursementState.REVERSED, DisbursementState.PENDING)

    def test_cancelled_to_anything_raises(self):
        with pytest.raises(InvalidTransitionError, match="terminal state"):
            transition(DisbursementState.CANCELLED, DisbursementState.PENDING)

    def test_pending_to_completed_raises(self):
        """Can't skip steps — must go PENDING → RECIPIENT_READY → ... → COMPLETED."""
        with pytest.raises(InvalidTransitionError):
            transition(DisbursementState.PENDING, DisbursementState.COMPLETED)

    def test_pending_to_transfer_initiated_raises(self):
        with pytest.raises(InvalidTransitionError):
            transition(DisbursementState.PENDING, DisbursementState.TRANSFER_INITIATED)

    def test_recipient_ready_to_completed_raises(self):
        """Must pass through TRANSFER_INITIATED first."""
        with pytest.raises(InvalidTransitionError):
            transition(DisbursementState.RECIPIENT_READY, DisbursementState.COMPLETED)

    def test_error_message_contains_state_names(self):
        with pytest.raises(InvalidTransitionError) as exc_info:
            transition(DisbursementState.PENDING, DisbursementState.COMPLETED)
        assert "pending" in str(exc_info.value)
        assert "completed" in str(exc_info.value)


# ===========================================================================
# is_terminal
# ===========================================================================


class TestIsTerminal:
    def test_completed_is_terminal(self):
        assert is_terminal(DisbursementState.COMPLETED)

    def test_reversed_is_terminal(self):
        assert is_terminal(DisbursementState.REVERSED)

    def test_cancelled_is_terminal(self):
        assert is_terminal(DisbursementState.CANCELLED)

    def test_pending_is_not_terminal(self):
        assert not is_terminal(DisbursementState.PENDING)

    def test_failed_is_not_terminal(self):
        assert not is_terminal(DisbursementState.FAILED)

    def test_transfer_initiated_is_not_terminal(self):
        assert not is_terminal(DisbursementState.TRANSFER_INITIATED)


# ===========================================================================
# is_retry_eligible
# ===========================================================================


class TestIsRetryEligible:
    def test_failed_with_zero_attempts_is_eligible(self):
        assert is_retry_eligible(DisbursementState.FAILED, 0)

    def test_failed_below_max_attempts_is_eligible(self):
        assert is_retry_eligible(DisbursementState.FAILED, MAX_ATTEMPTS - 1)

    def test_failed_at_max_attempts_is_not_eligible(self):
        assert not is_retry_eligible(DisbursementState.FAILED, MAX_ATTEMPTS)

    def test_failed_above_max_attempts_is_not_eligible(self):
        assert not is_retry_eligible(DisbursementState.FAILED, MAX_ATTEMPTS + 5)

    def test_completed_is_never_retry_eligible(self):
        assert not is_retry_eligible(DisbursementState.COMPLETED, 0)

    def test_pending_is_never_retry_eligible(self):
        assert not is_retry_eligible(DisbursementState.PENDING, 0)

    def test_cancelled_is_never_retry_eligible(self):
        assert not is_retry_eligible(DisbursementState.CANCELLED, 0)


# ===========================================================================
# next_retry_delay_seconds
# ===========================================================================


class TestNextRetryDelay:
    def test_first_attempt_delay(self):
        assert next_retry_delay_seconds(1) == 60

    def test_second_attempt_delay(self):
        assert next_retry_delay_seconds(2) == 300

    def test_third_attempt_delay(self):
        assert next_retry_delay_seconds(3) == 900

    def test_delay_increases_with_attempts(self):
        delays = [next_retry_delay_seconds(i) for i in range(1, 4)]
        assert delays == sorted(delays), "Delays should be monotonically increasing"

    def test_delay_clamps_at_max(self):
        """Very high attempt counts should not crash — clamps to last value."""
        high = next_retry_delay_seconds(999)
        normal_max = next_retry_delay_seconds(3)
        assert high == normal_max
