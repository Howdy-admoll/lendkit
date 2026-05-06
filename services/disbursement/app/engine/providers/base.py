"""
Disbursement Service — Abstract Payment Provider

Defines the interface every disbursement provider must implement.
Swap Paystack for Flutterwave, Mono, or any other provider by
implementing this interface — no changes to business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class TransferStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REVERSED = "reversed"


@dataclass(frozen=True)
class RecipientResult:
    """Result of creating a transfer recipient."""
    recipient_code: str      # provider's unique recipient identifier
    account_name: str        # confirmed account name (from bank verification)
    bank_code: str
    account_number: str
    provider_reference: str  # raw provider response reference


@dataclass(frozen=True)
class TransferResult:
    """Result of initiating a transfer."""
    transfer_code: str       # provider's transfer identifier (for webhooks)
    transfer_reference: str  # our idempotency reference
    status: TransferStatus
    amount_kobo: int
    provider_message: str


@dataclass(frozen=True)
class TransferStatusResult:
    """Result of polling a transfer's current status."""
    transfer_code: str
    status: TransferStatus
    amount_kobo: int
    provider_message: str
    completed_at: str | None  # ISO datetime string, if completed


class PaymentProvider(ABC):
    """
    Abstract interface for a disbursement payment provider.

    All monetary amounts are in kobo (integers).
    Providers convert to their native currency unit internally.
    """

    @abstractmethod
    async def create_recipient(
        self,
        *,
        account_number: str,
        bank_code: str,
        account_name: str,
        currency: str = "NGN",
    ) -> RecipientResult:
        """
        Register a bank account as a transfer recipient with the provider.

        This is a prerequisite for initiating a transfer. Providers typically
        require this step to verify the account before funds can be sent.
        """
        ...

    @abstractmethod
    async def initiate_transfer(
        self,
        *,
        recipient_code: str,
        amount_kobo: int,
        reference: str,
        reason: str = "Loan disbursement",
        currency: str = "NGN",
    ) -> TransferResult:
        """
        Initiate a bank transfer to the given recipient.

        `reference` must be globally unique per transfer attempt — use it
        as the idempotency key. Providers return a transfer_code that will
        appear in subsequent webhook callbacks.
        """
        ...

    @abstractmethod
    async def get_transfer_status(
        self,
        transfer_code: str,
    ) -> TransferStatusResult:
        """Poll the current status of a transfer by its provider transfer_code."""
        ...

    @abstractmethod
    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> bool:
        """
        Verify the HMAC signature of an inbound webhook from the provider.

        Returns True if the signature is valid, False otherwise.
        Never raises — callers should treat False as an untrusted payload.
        """
        ...
