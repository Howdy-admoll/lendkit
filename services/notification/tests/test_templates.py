"""
Notification Service — Template Unit Tests

Verifies that every supported event type renders without errors given
valid context, and that missing variables raise KeyError.
"""

import pytest

from app.engine.templates import SUPPORTED_EVENTS, RenderedMessage, render

# ---------------------------------------------------------------------------
# Minimal valid context per event type
# ---------------------------------------------------------------------------

_CONTEXTS: dict[str, dict] = {
    "loan.offer_accepted": {
        "first_name": "Amara",
        "amount": "₦150,000.00",
        "tenure_months": 12,
        "monthly_installment": "₦13,500.00",
        "bank_name": "GTBank",
        "account_number": "0123456789",
        "account_last4": "6789",
        "support_email": "support@lendkit.io",
        "support_phone": "+2348001234567",
    },
    "loan.disbursed": {
        "first_name": "Amara",
        "amount": "₦150,000.00",
        "bank_name": "GTBank",
        "account_last4": "6789",
        "transfer_reference": "lk-a3f2b1c4-01-d7e9f2",
        "transfer_date": "2025-03-01",
        "monthly_installment": "₦13,500.00",
        "first_due_date": "2025-04-01",
        "support_email": "support@lendkit.io",
        "support_phone": "+2348001234567",
    },
    "repayment.due_soon": {
        "first_name": "Amara",
        "amount": "₦13,500.00",
        "due_date": "2025-04-01",
        "days_left": 3,
        "installment_number": 1,
        "total_installments": 12,
        "support_email": "support@lendkit.io",
        "support_phone": "+2348001234567",
    },
    "repayment.received": {
        "first_name": "Amara",
        "amount": "₦13,500.00",
        "payment_date": "2025-04-01",
        "principal_paid": "₦10,000.00",
        "interest_paid": "₦3,500.00",
        "outstanding_balance": "₦140,000.00",
        "support_email": "support@lendkit.io",
        "support_phone": "+2348001234567",
    },
    "repayment.missed": {
        "first_name": "Amara",
        "amount": "₦13,500.00",
        "due_date": "2025-04-01",
        "days_overdue": 5,
        "penalty_amount": "₦675.00",
        "support_email": "support@lendkit.io",
        "support_phone": "+2348001234567",
    },
    "loan.defaulted": {
        "first_name": "Amara",
        "days_overdue": 92,
        "support_email": "support@lendkit.io",
        "support_phone": "+2348001234567",
    },
}


class TestRenderAllEvents:
    @pytest.mark.parametrize("event_type", sorted(SUPPORTED_EVENTS))
    def test_renders_without_error(self, event_type: str):
        ctx = _CONTEXTS[event_type]
        result = render(event_type, ctx)
        assert isinstance(result, RenderedMessage)

    @pytest.mark.parametrize("event_type", sorted(SUPPORTED_EVENTS))
    def test_sms_body_is_non_empty(self, event_type: str):
        result = render(event_type, _CONTEXTS[event_type])
        assert result.sms_body.strip()

    @pytest.mark.parametrize("event_type", sorted(SUPPORTED_EVENTS))
    def test_email_body_is_non_empty(self, event_type: str):
        result = render(event_type, _CONTEXTS[event_type])
        assert result.email_body.strip()

    @pytest.mark.parametrize("event_type", sorted(SUPPORTED_EVENTS))
    def test_subject_is_non_empty(self, event_type: str):
        result = render(event_type, _CONTEXTS[event_type])
        assert result.subject.strip()

    @pytest.mark.parametrize("event_type", sorted(SUPPORTED_EVENTS))
    def test_html_body_contains_name(self, event_type: str):
        result = render(event_type, _CONTEXTS[event_type])
        assert "Amara" in result.email_html

    @pytest.mark.parametrize("event_type", sorted(SUPPORTED_EVENTS))
    def test_sms_body_contains_name(self, event_type: str):
        result = render(event_type, _CONTEXTS[event_type])
        assert "Amara" in result.sms_body


class TestRenderErrors:
    def test_unknown_event_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown event type"):
            render("charge.success", {})

    def test_missing_variable_raises_key_error(self):
        """Omit 'first_name' — should raise KeyError."""
        ctx = dict(_CONTEXTS["loan.disbursed"])
        del ctx["first_name"]
        with pytest.raises(KeyError):
            render("loan.disbursed", ctx)


class TestRenderContent:
    def test_disbursed_sms_contains_amount(self):
        result = render("loan.disbursed", _CONTEXTS["loan.disbursed"])
        assert "₦150,000.00" in result.sms_body

    def test_disbursed_sms_contains_bank(self):
        result = render("loan.disbursed", _CONTEXTS["loan.disbursed"])
        assert "GTBank" in result.sms_body

    def test_disbursed_sms_contains_reference(self):
        result = render("loan.disbursed", _CONTEXTS["loan.disbursed"])
        assert "lk-a3f2b1c4-01-d7e9f2" in result.sms_body

    def test_due_soon_sms_contains_days(self):
        result = render("repayment.due_soon", _CONTEXTS["repayment.due_soon"])
        assert "3" in result.sms_body

    def test_missed_email_contains_penalty(self):
        result = render("repayment.missed", _CONTEXTS["repayment.missed"])
        assert "₦675.00" in result.email_body

    def test_defaulted_email_contains_support_phone(self):
        result = render("loan.defaulted", _CONTEXTS["loan.defaulted"])
        assert "+2348001234567" in result.email_body

    def test_received_email_contains_principal_and_interest(self):
        result = render("repayment.received", _CONTEXTS["repayment.received"])
        assert "₦10,000.00" in result.email_body
        assert "₦3,500.00" in result.email_body
