"""
Collections Service — State Machine

Collection case lifecycle:

  OPEN → AGENT_ASSIGNED | PROMISE_TO_PAY | LEGAL | RECOVERED | WRITTEN_OFF
  AGENT_ASSIGNED → PROMISE_TO_PAY | LEGAL | RECOVERED | WRITTEN_OFF
  PROMISE_TO_PAY → RECOVERED | BROKEN_PROMISE
  BROKEN_PROMISE → AGENT_ASSIGNED | LEGAL | WRITTEN_OFF
  LEGAL → RECOVERED | WRITTEN_OFF
  RECOVERED → (terminal)
  WRITTEN_OFF → (terminal)

State meanings:
  OPEN            Case created from a loan.defaulted event. Automated outreach
                  (SMS/email) is the only action taken at this stage.
  AGENT_ASSIGNED  A human collections agent has been assigned and is actively
                  working the account.
  PROMISE_TO_PAY  Borrower has verbally or in writing committed to a payment
                  by a specific date.
  BROKEN_PROMISE  A promise-to-pay date passed with no payment received.
  LEGAL           Account referred to the legal team for formal demand letter
                  or court action.
  RECOVERED       Payment received (partial settlement accepted, or full amount).
                  Terminal — case is closed successfully.
  WRITTEN_OFF     No recovery expected. Terminal — case is closed as a loss.
"""

from __future__ import annotations

from enum import Enum


class CollectionState(str, Enum):
    OPEN = "open"
    AGENT_ASSIGNED = "agent_assigned"
    PROMISE_TO_PAY = "promise_to_pay"
    BROKEN_PROMISE = "broken_promise"
    LEGAL = "legal"
    RECOVERED = "recovered"
    WRITTEN_OFF = "written_off"


_TERMINAL_STATES: frozenset[CollectionState] = frozenset(
    {CollectionState.RECOVERED, CollectionState.WRITTEN_OFF}
)

_TRANSITIONS: dict[CollectionState, frozenset[CollectionState]] = {
    CollectionState.OPEN: frozenset({
        CollectionState.AGENT_ASSIGNED,
        CollectionState.PROMISE_TO_PAY,
        CollectionState.LEGAL,
        CollectionState.RECOVERED,
        CollectionState.WRITTEN_OFF,
    }),
    CollectionState.AGENT_ASSIGNED: frozenset({
        CollectionState.PROMISE_TO_PAY,
        CollectionState.LEGAL,
        CollectionState.RECOVERED,
        CollectionState.WRITTEN_OFF,
    }),
    CollectionState.PROMISE_TO_PAY: frozenset({
        CollectionState.RECOVERED,
        CollectionState.BROKEN_PROMISE,
    }),
    CollectionState.BROKEN_PROMISE: frozenset({
        CollectionState.AGENT_ASSIGNED,
        CollectionState.LEGAL,
        CollectionState.WRITTEN_OFF,
    }),
    CollectionState.LEGAL: frozenset({
        CollectionState.RECOVERED,
        CollectionState.WRITTEN_OFF,
    }),
    # Terminal states — no outgoing transitions
    CollectionState.RECOVERED: frozenset(),
    CollectionState.WRITTEN_OFF: frozenset(),
}


class InvalidCollectionTransitionError(Exception):
    """Raised when a state transition is not permitted."""


def transition(current: CollectionState, target: CollectionState) -> CollectionState:
    """
    Validate and apply a state transition.

    Returns the target state on success.
    Raises InvalidCollectionTransitionError on invalid transitions.
    """
    if current in _TERMINAL_STATES:
        raise InvalidCollectionTransitionError(
            f"Cannot transition from terminal state {current.value!r} to {target.value!r}."
        )

    allowed = _TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidCollectionTransitionError(
            f"Invalid transition: {current.value!r} → {target.value!r}. "
            f"Allowed: {sorted(s.value for s in allowed)}"
        )

    return target


def is_terminal(state: CollectionState) -> bool:
    """Return True if the state is a terminal (closed) state."""
    return state in _TERMINAL_STATES


def is_open(state: CollectionState) -> bool:
    """Return True if the case is still active (not terminal)."""
    return state not in _TERMINAL_STATES
