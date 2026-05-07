"""
Notification Service — Router Unit Tests

Pure Python — no HTTP, no DB.
"""

import pytest

from app.engine.channels.base import ChannelType
from app.engine.router import DeliveryTarget, route, supported_events

PHONE = "+2348012345678"
EMAIL = "amara@example.com"


class TestRouteBasic:
    def test_loan_disbursed_produces_sms_and_email(self):
        targets = route("loan.disbursed", phone=PHONE, email=EMAIL)
        types = {t.channel_type for t in targets}
        assert ChannelType.SMS in types
        assert ChannelType.EMAIL in types

    def test_targets_have_correct_recipients(self):
        targets = route("loan.disbursed", phone=PHONE, email=EMAIL)
        sms = next(t for t in targets if t.channel_type == ChannelType.SMS)
        email = next(t for t in targets if t.channel_type == ChannelType.EMAIL)
        assert sms.recipient == PHONE
        assert email.recipient == EMAIL

    @pytest.mark.parametrize(
        "event_type",
        [
            "loan.offer_accepted",
            "loan.disbursed",
            "repayment.due_soon",
            "repayment.received",
            "repayment.missed",
            "loan.defaulted",
        ],
    )
    def test_all_known_events_produce_targets(self, event_type: str):
        targets = route(event_type, phone=PHONE, email=EMAIL)
        assert len(targets) >= 1


class TestRouteOptOut:
    def test_sms_opt_out_suppresses_sms(self):
        targets = route("loan.disbursed", phone=PHONE, email=EMAIL, sms_opted_out=True)
        types = {t.channel_type for t in targets}
        assert ChannelType.SMS not in types
        assert ChannelType.EMAIL in types

    def test_email_opt_out_suppresses_email(self):
        targets = route("loan.disbursed", phone=PHONE, email=EMAIL, email_opted_out=True)
        types = {t.channel_type for t in targets}
        assert ChannelType.EMAIL not in types
        assert ChannelType.SMS in types

    def test_both_opt_out_returns_empty(self):
        targets = route(
            "loan.disbursed",
            phone=PHONE,
            email=EMAIL,
            sms_opted_out=True,
            email_opted_out=True,
        )
        assert targets == []

    def test_no_phone_suppresses_sms(self):
        targets = route("loan.disbursed", phone=None, email=EMAIL)
        types = {t.channel_type for t in targets}
        assert ChannelType.SMS not in types

    def test_no_email_suppresses_email(self):
        targets = route("loan.disbursed", phone=PHONE, email=None)
        types = {t.channel_type for t in targets}
        assert ChannelType.EMAIL not in types

    def test_no_phone_no_email_returns_empty(self):
        targets = route("loan.disbursed", phone=None, email=None)
        assert targets == []


class TestRouteUnknownEvent:
    def test_unknown_event_returns_empty(self):
        targets = route("charge.success", phone=PHONE, email=EMAIL)
        assert targets == []


class TestSupportedEvents:
    def test_supported_events_is_frozenset(self):
        assert isinstance(supported_events(), frozenset)

    def test_known_events_are_supported(self):
        known = {
            "loan.offer_accepted",
            "loan.disbursed",
            "repayment.due_soon",
            "repayment.received",
            "repayment.missed",
            "loan.defaulted",
        }
        assert known.issubset(supported_events())

    def test_delivery_target_is_frozen(self):
        target = DeliveryTarget(channel_type=ChannelType.SMS, recipient=PHONE)
        with pytest.raises(Exception):
            target.recipient = "other"  # type: ignore[misc]
