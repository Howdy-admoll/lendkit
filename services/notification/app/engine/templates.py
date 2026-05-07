"""
Notification Service — Message Templates

All templates are defined here as plain Python strings rendered with
str.format_map() — no external dependency needed.

Each event type has:
  - An SMS body  (≤160 chars where possible, Nigerian-English tone)
  - An email subject
  - An email plain-text body
  - An email HTML body

Template variables use {curly_brace} syntax.  Any variable not supplied
to render() raises a KeyError so missing fields are caught at call time.

Supported event types (mirrors Redis Stream event names):
  loan.offer_accepted      → Loan approved, offer ready
  loan.disbursed           → Money sent to account
  repayment.due_soon       → Payment reminder N days before due date
  repayment.received       → Payment received confirmation
  repayment.missed         → Overdue payment alert
  loan.defaulted           → Default classification alert
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RenderedMessage:
    subject: str      # email subject (empty for SMS-only events)
    sms_body: str
    email_body: str   # plain text
    email_html: str   # HTML version


# ---------------------------------------------------------------------------
# Raw template definitions
# ---------------------------------------------------------------------------

_SMS: dict[str, str] = {
    "loan.offer_accepted": (
        "Hi {first_name}, your LendKit loan of {amount} has been approved! "
        "Funds will be sent to your {bank_name} account ending {account_last4} shortly."
    ),
    "loan.disbursed": (
        "Hi {first_name}, {amount} has been sent to your {bank_name} account "
        "ending {account_last4}. Ref: {transfer_reference}."
    ),
    "repayment.due_soon": (
        "Hi {first_name}, your repayment of {amount} is due on {due_date} "
        "({days_left} day(s) away). Log in to pay early and avoid penalties."
    ),
    "repayment.received": (
        "Hi {first_name}, we received your payment of {amount} on {payment_date}. "
        "Outstanding balance: {outstanding_balance}. Thank you!"
    ),
    "repayment.missed": (
        "Hi {first_name}, your repayment of {amount} due on {due_date} is overdue "
        "by {days_overdue} day(s). Penalties may apply. Please pay now to avoid default."
    ),
    "loan.defaulted": (
        "Hi {first_name}, your loan account is now classified as DEFAULT after "
        "{days_overdue} days overdue. Please contact support immediately: {support_phone}."
    ),
}

_EMAIL_SUBJECT: dict[str, str] = {
    "loan.offer_accepted": "Your LendKit loan of {amount} has been approved",
    "loan.disbursed": "Funds transferred — {amount} is on its way",
    "repayment.due_soon": "Payment reminder: {amount} due in {days_left} day(s)",
    "repayment.received": "Payment received — thank you, {first_name}",
    "repayment.missed": "Action required: overdue payment of {amount}",
    "loan.defaulted": "Urgent: your loan account is in default",
}

_EMAIL_PLAIN: dict[str, str] = {
    "loan.offer_accepted": (
        "Dear {first_name},\n\n"
        "Great news! Your loan application has been approved.\n\n"
        "  Amount:        {amount}\n"
        "  Tenure:        {tenure_months} months\n"
        "  Monthly repayment: {monthly_installment}\n"
        "  Disbursement account: {bank_name} — {account_number}\n\n"
        "Funds will be transferred shortly. You will receive another notification "
        "once the transfer is confirmed.\n\n"
        "Questions? Reach us at {support_email}.\n\n"
        "LendKit Team"
    ),
    "loan.disbursed": (
        "Dear {first_name},\n\n"
        "Your loan funds have been successfully transferred.\n\n"
        "  Amount:      {amount}\n"
        "  Account:     {bank_name} — {account_last4}\n"
        "  Reference:   {transfer_reference}\n"
        "  Transfer date: {transfer_date}\n\n"
        "Your first repayment of {monthly_installment} is due on {first_due_date}.\n\n"
        "LendKit Team"
    ),
    "repayment.due_soon": (
        "Dear {first_name},\n\n"
        "This is a friendly reminder that your next repayment is coming up.\n\n"
        "  Amount due:  {amount}\n"
        "  Due date:    {due_date} ({days_left} day(s) from today)\n"
        "  Installment: {installment_number} of {total_installments}\n\n"
        "Log in to your LendKit dashboard to make a payment early.\n\n"
        "LendKit Team"
    ),
    "repayment.received": (
        "Dear {first_name},\n\n"
        "We have received your payment. Here is the summary:\n\n"
        "  Amount paid:          {amount}\n"
        "  Payment date:         {payment_date}\n"
        "  Applied to principal: {principal_paid}\n"
        "  Applied to interest:  {interest_paid}\n"
        "  Outstanding balance:  {outstanding_balance}\n\n"
        "Thank you for staying on track!\n\n"
        "LendKit Team"
    ),
    "repayment.missed": (
        "Dear {first_name},\n\n"
        "We have not received your repayment of {amount} which was due on {due_date}.\n\n"
        "  Days overdue:  {days_overdue}\n"
        "  Penalty accrued: {penalty_amount}\n\n"
        "Please make this payment as soon as possible to avoid further penalties "
        "or a default classification.\n\n"
        "Pay now or contact us at {support_email}.\n\n"
        "LendKit Team"
    ),
    "loan.defaulted": (
        "Dear {first_name},\n\n"
        "After {days_overdue} days without payment, your loan account has been "
        "classified as DEFAULT.\n\n"
        "This may affect your credit profile. To resolve this, please contact "
        "our collections team immediately:\n\n"
        "  Phone: {support_phone}\n"
        "  Email: {support_email}\n\n"
        "LendKit Team"
    ),
}

# Minimal HTML wrappers — keeps the file readable without a template engine dependency.
_EMAIL_HTML: dict[str, str] = {
    k: (
        "<html><body style='font-family:sans-serif;max-width:600px;margin:auto'>"
        "<p>Dear <strong>{first_name}</strong>,</p>"
        "<pre style='font-family:inherit;white-space:pre-wrap'>"
        + v.replace("Dear {first_name},\n\n", "")
        + "</pre>"
        "<p style='color:#888;font-size:12px'>LendKit — confidential</p>"
        "</body></html>"
    )
    for k, v in _EMAIL_PLAIN.items()
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SUPPORTED_EVENTS = frozenset(_SMS.keys())


def render(event_type: str, context: dict[str, Any]) -> RenderedMessage:
    """
    Render all message formats for a given event type.

    Parameters
    ----------
    event_type:
        One of the keys in SUPPORTED_EVENTS.
    context:
        Template variables. A KeyError is raised for any missing variable.

    Raises
    ------
    KeyError:
        If event_type is not in SUPPORTED_EVENTS or a required variable
        is missing from context.
    """
    if event_type not in SUPPORTED_EVENTS:
        raise KeyError(f"Unknown event type: {event_type!r}")

    return RenderedMessage(
        subject=_EMAIL_SUBJECT[event_type].format_map(context),
        sms_body=_SMS[event_type].format_map(context),
        email_body=_EMAIL_PLAIN[event_type].format_map(context),
        email_html=_EMAIL_HTML[event_type].format_map(context),
    )
