"""
Disbursement Service — Idempotency Key Generation

Every transfer attempt needs a globally unique, stable reference so that:
  - Retries of the same attempt never create duplicate transfers
  - Different attempts for the same loan get distinct references

Reference format:
    lk-{loan_id_short}-{attempt_number}-{checksum}

    lk           = LendKit prefix (provider-safe, avoids collisions)
    loan_id_short = first 8 chars of the loan UUID
    attempt      = zero-padded attempt number (01, 02, 03)
    checksum     = first 6 chars of SHA256(loan_id + attempt + secret_salt)

Example:
    lk-a3f2b1c4-01-d7e9f2

Pure functions — no DB, no I/O, fully testable.
"""

from __future__ import annotations

import hashlib


def generate_transfer_reference(
    loan_id: str,
    attempt_number: int,
    salt: str = "",
) -> str:
    """
    Generate a stable, unique transfer reference for a disbursement attempt.

    Parameters
    ----------
    loan_id:
        The UUID of the loan being disbursed.
    attempt_number:
        1-indexed attempt counter (1 = first attempt, 2 = first retry, ...).
    salt:
        Optional application secret to prevent reference guessing.
        In production, set this to your SECRET_KEY.

    Returns
    -------
    A URL-safe alphanumeric string ≤ 32 characters, suitable as a
    Paystack transfer reference.
    """
    loan_short = loan_id.replace("-", "")[:8]
    attempt_str = f"{attempt_number:02d}"
    payload = f"{loan_id}:{attempt_number}:{salt}"
    checksum = hashlib.sha256(payload.encode()).hexdigest()[:6]
    return f"lk-{loan_short}-{attempt_str}-{checksum}"


def references_same_loan(reference: str, loan_id: str) -> bool:
    """
    Check whether a transfer reference was generated for a given loan_id.
    Used in webhook handlers to match incoming callbacks to the right loan.
    """
    loan_short = loan_id.replace("-", "")[:8]
    return reference.startswith(f"lk-{loan_short}-")
