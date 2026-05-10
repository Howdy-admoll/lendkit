"""
Collections Service — Escalation Ladder Unit Tests

All tests are pure Python — no DB, no HTTP.
"""

import pytest

from app.engine.escalation import (
    EscalationAction,
    EscalationResult,
    evaluate,
    is_write_off_eligible,
    outreach_frequency_days,
    should_assign_agent,
    should_refer_legal,
)


# ===========================================================================
# evaluate — escalation action per DPD
# ===========================================================================


class TestEvaluate:
    def test_dpd_zero_returns_auto_outreach(self):
        result = evaluate(0)
        assert result.action == EscalationAction.AUTO_OUTREACH

    def test_dpd_1_is_auto_outreach(self):
        result = evaluate(1)
        assert result.action == EscalationAction.AUTO_OUTREACH

    def test_dpd_7_is_auto_outreach(self):
        result = evaluate(7)
        assert result.action == EscalationAction.AUTO_OUTREACH

    def test_dpd_8_is_auto_outreach(self):
        result = evaluate(8)
        assert result.action == EscalationAction.AUTO_OUTREACH

    def test_dpd_30_is_auto_outreach(self):
        result = evaluate(30)
        assert result.action == EscalationAction.AUTO_OUTREACH

    def test_dpd_31_requires_agent(self):
        result = evaluate(31)
        assert result.action == EscalationAction.AGENT_REQUIRED

    def test_dpd_45_requires_agent(self):
        result = evaluate(45)
        assert result.action == EscalationAction.AGENT_REQUIRED

    def test_dpd_60_requires_agent(self):
        result = evaluate(60)
        assert result.action == EscalationAction.AGENT_REQUIRED

    def test_dpd_61_is_legal_notice(self):
        result = evaluate(61)
        assert result.action == EscalationAction.LEGAL_NOTICE

    def test_dpd_75_is_legal_notice(self):
        result = evaluate(75)
        assert result.action == EscalationAction.LEGAL_NOTICE

    def test_dpd_89_is_legal_notice(self):
        result = evaluate(89)
        assert result.action == EscalationAction.LEGAL_NOTICE

    def test_dpd_90_is_write_off_ready(self):
        result = evaluate(90)
        assert result.action == EscalationAction.WRITE_OFF_READY

    def test_dpd_180_is_write_off_ready(self):
        result = evaluate(180)
        assert result.action == EscalationAction.WRITE_OFF_READY

    def test_dpd_360_is_write_off_ready(self):
        result = evaluate(360)
        assert result.action == EscalationAction.WRITE_OFF_READY

    def test_very_high_dpd_is_write_off_ready(self):
        result = evaluate(9_999)
        assert result.action == EscalationAction.WRITE_OFF_READY

    def test_negative_dpd_raises_value_error(self):
        with pytest.raises(ValueError, match="negative"):
            evaluate(-1)

    def test_result_contains_dpd(self):
        result = evaluate(45)
        assert result.dpd == 45

    def test_result_is_frozen(self):
        result = evaluate(10)
        assert isinstance(result, EscalationResult)
        with pytest.raises(Exception):
            result.dpd = 99  # type: ignore[misc]

    def test_result_description_is_non_empty(self):
        for dpd in [1, 31, 61, 90]:
            assert evaluate(dpd).description


# ===========================================================================
# should_assign_agent
# ===========================================================================


class TestShouldAssignAgent:
    def test_dpd_30_does_not_require_agent(self):
        assert not should_assign_agent(30)

    def test_dpd_31_requires_agent(self):
        assert should_assign_agent(31)

    def test_dpd_60_requires_agent(self):
        assert should_assign_agent(60)

    def test_dpd_61_requires_agent(self):
        assert should_assign_agent(61)

    def test_dpd_90_requires_agent(self):
        assert should_assign_agent(90)


# ===========================================================================
# should_refer_legal
# ===========================================================================


class TestShouldReferLegal:
    def test_dpd_60_does_not_need_legal(self):
        assert not should_refer_legal(60)

    def test_dpd_61_needs_legal(self):
        assert should_refer_legal(61)

    def test_dpd_89_needs_legal(self):
        assert should_refer_legal(89)

    def test_dpd_90_needs_legal(self):
        assert should_refer_legal(90)

    def test_dpd_200_needs_legal(self):
        assert should_refer_legal(200)


# ===========================================================================
# is_write_off_eligible
# ===========================================================================


class TestIsWriteOffEligible:
    def test_dpd_89_not_eligible(self):
        assert not is_write_off_eligible(89)

    def test_dpd_90_is_eligible(self):
        assert is_write_off_eligible(90)

    def test_dpd_91_is_eligible(self):
        assert is_write_off_eligible(91)

    def test_dpd_365_is_eligible(self):
        assert is_write_off_eligible(365)


# ===========================================================================
# outreach_frequency_days
# ===========================================================================


class TestOutreachFrequencyDays:
    def test_dpd_zero_no_outreach(self):
        assert outreach_frequency_days(0) == 0

    def test_dpd_1_every_3_days(self):
        assert outreach_frequency_days(1) == 3

    def test_dpd_7_every_3_days(self):
        assert outreach_frequency_days(7) == 3

    def test_dpd_8_daily(self):
        assert outreach_frequency_days(8) == 1

    def test_dpd_30_daily(self):
        assert outreach_frequency_days(30) == 1

    def test_dpd_31_no_auto_outreach(self):
        """Beyond 30 DPD, human agents take over."""
        assert outreach_frequency_days(31) == 0

    def test_dpd_90_no_auto_outreach(self):
        assert outreach_frequency_days(90) == 0
