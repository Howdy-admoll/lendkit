"""
Collections Service — State Machine Unit Tests

All tests are pure Python — no DB, no HTTP.
"""

import pytest

from app.engine.state_machine import (
    CollectionState,
    InvalidCollectionTransitionError,
    is_open,
    is_terminal,
    transition,
)


# ===========================================================================
# transition — valid paths
# ===========================================================================


class TestTransitionValid:
    def test_open_to_agent_assigned(self):
        assert transition(CollectionState.OPEN, CollectionState.AGENT_ASSIGNED) == CollectionState.AGENT_ASSIGNED

    def test_open_to_promise_to_pay(self):
        assert transition(CollectionState.OPEN, CollectionState.PROMISE_TO_PAY) == CollectionState.PROMISE_TO_PAY

    def test_open_to_legal(self):
        assert transition(CollectionState.OPEN, CollectionState.LEGAL) == CollectionState.LEGAL

    def test_open_to_recovered(self):
        assert transition(CollectionState.OPEN, CollectionState.RECOVERED) == CollectionState.RECOVERED

    def test_open_to_written_off(self):
        assert transition(CollectionState.OPEN, CollectionState.WRITTEN_OFF) == CollectionState.WRITTEN_OFF

    def test_agent_assigned_to_promise_to_pay(self):
        assert transition(CollectionState.AGENT_ASSIGNED, CollectionState.PROMISE_TO_PAY) == CollectionState.PROMISE_TO_PAY

    def test_agent_assigned_to_legal(self):
        assert transition(CollectionState.AGENT_ASSIGNED, CollectionState.LEGAL) == CollectionState.LEGAL

    def test_agent_assigned_to_recovered(self):
        assert transition(CollectionState.AGENT_ASSIGNED, CollectionState.RECOVERED) == CollectionState.RECOVERED

    def test_agent_assigned_to_written_off(self):
        assert transition(CollectionState.AGENT_ASSIGNED, CollectionState.WRITTEN_OFF) == CollectionState.WRITTEN_OFF

    def test_promise_to_pay_to_recovered(self):
        assert transition(CollectionState.PROMISE_TO_PAY, CollectionState.RECOVERED) == CollectionState.RECOVERED

    def test_promise_to_pay_to_broken_promise(self):
        assert transition(CollectionState.PROMISE_TO_PAY, CollectionState.BROKEN_PROMISE) == CollectionState.BROKEN_PROMISE

    def test_broken_promise_to_agent_assigned(self):
        assert transition(CollectionState.BROKEN_PROMISE, CollectionState.AGENT_ASSIGNED) == CollectionState.AGENT_ASSIGNED

    def test_broken_promise_to_legal(self):
        assert transition(CollectionState.BROKEN_PROMISE, CollectionState.LEGAL) == CollectionState.LEGAL

    def test_broken_promise_to_written_off(self):
        assert transition(CollectionState.BROKEN_PROMISE, CollectionState.WRITTEN_OFF) == CollectionState.WRITTEN_OFF

    def test_legal_to_recovered(self):
        assert transition(CollectionState.LEGAL, CollectionState.RECOVERED) == CollectionState.RECOVERED

    def test_legal_to_written_off(self):
        assert transition(CollectionState.LEGAL, CollectionState.WRITTEN_OFF) == CollectionState.WRITTEN_OFF


# ===========================================================================
# transition — invalid paths
# ===========================================================================


class TestTransitionInvalid:
    def test_recovered_is_terminal(self):
        with pytest.raises(InvalidCollectionTransitionError, match="terminal state"):
            transition(CollectionState.RECOVERED, CollectionState.OPEN)

    def test_written_off_is_terminal(self):
        with pytest.raises(InvalidCollectionTransitionError, match="terminal state"):
            transition(CollectionState.WRITTEN_OFF, CollectionState.OPEN)

    def test_open_cannot_go_to_broken_promise(self):
        with pytest.raises(InvalidCollectionTransitionError):
            transition(CollectionState.OPEN, CollectionState.BROKEN_PROMISE)

    def test_promise_to_pay_cannot_go_to_agent_assigned(self):
        with pytest.raises(InvalidCollectionTransitionError):
            transition(CollectionState.PROMISE_TO_PAY, CollectionState.AGENT_ASSIGNED)

    def test_promise_to_pay_cannot_go_to_legal(self):
        with pytest.raises(InvalidCollectionTransitionError):
            transition(CollectionState.PROMISE_TO_PAY, CollectionState.LEGAL)

    def test_legal_cannot_go_to_open(self):
        with pytest.raises(InvalidCollectionTransitionError):
            transition(CollectionState.LEGAL, CollectionState.OPEN)

    def test_legal_cannot_go_to_agent_assigned(self):
        with pytest.raises(InvalidCollectionTransitionError):
            transition(CollectionState.LEGAL, CollectionState.AGENT_ASSIGNED)

    def test_error_message_contains_state_names(self):
        with pytest.raises(InvalidCollectionTransitionError) as exc_info:
            transition(CollectionState.OPEN, CollectionState.BROKEN_PROMISE)
        assert "open" in str(exc_info.value)
        assert "broken_promise" in str(exc_info.value)


# ===========================================================================
# is_terminal
# ===========================================================================


class TestIsTerminal:
    def test_recovered_is_terminal(self):
        assert is_terminal(CollectionState.RECOVERED)

    def test_written_off_is_terminal(self):
        assert is_terminal(CollectionState.WRITTEN_OFF)

    def test_open_is_not_terminal(self):
        assert not is_terminal(CollectionState.OPEN)

    def test_agent_assigned_is_not_terminal(self):
        assert not is_terminal(CollectionState.AGENT_ASSIGNED)

    def test_promise_to_pay_is_not_terminal(self):
        assert not is_terminal(CollectionState.PROMISE_TO_PAY)

    def test_broken_promise_is_not_terminal(self):
        assert not is_terminal(CollectionState.BROKEN_PROMISE)

    def test_legal_is_not_terminal(self):
        assert not is_terminal(CollectionState.LEGAL)


# ===========================================================================
# is_open
# ===========================================================================


class TestIsOpen:
    def test_open_state_is_open(self):
        assert is_open(CollectionState.OPEN)

    def test_agent_assigned_is_open(self):
        assert is_open(CollectionState.AGENT_ASSIGNED)

    def test_recovered_is_not_open(self):
        assert not is_open(CollectionState.RECOVERED)

    def test_written_off_is_not_open(self):
        assert not is_open(CollectionState.WRITTEN_OFF)


# ===========================================================================
# CollectionState values
# ===========================================================================


class TestCollectionStateValues:
    def test_state_values_are_strings(self):
        for state in CollectionState:
            assert isinstance(state.value, str)

    def test_all_states_present(self):
        expected = {
            "open", "agent_assigned", "promise_to_pay",
            "broken_promise", "legal", "recovered", "written_off"
        }
        actual = {s.value for s in CollectionState}
        assert actual == expected
