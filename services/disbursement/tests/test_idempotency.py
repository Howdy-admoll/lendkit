"""
Disbursement Service — Idempotency Key Unit Tests

All tests are pure Python — no DB, no HTTP calls.
"""

import pytest

from app.engine.idempotency import generate_transfer_reference, references_same_loan


# ===========================================================================
# generate_transfer_reference
# ===========================================================================


class TestGenerateTransferReference:
    LOAN_ID = "a3f2b1c4-dead-beef-cafe-123456789abc"

    def test_returns_string(self):
        ref = generate_transfer_reference(self.LOAN_ID, 1)
        assert isinstance(ref, str)

    def test_starts_with_lk_prefix(self):
        ref = generate_transfer_reference(self.LOAN_ID, 1)
        assert ref.startswith("lk-")

    def test_contains_loan_id_short(self):
        ref = generate_transfer_reference(self.LOAN_ID, 1)
        loan_short = self.LOAN_ID.replace("-", "")[:8]
        assert loan_short in ref

    def test_contains_attempt_number(self):
        ref1 = generate_transfer_reference(self.LOAN_ID, 1)
        ref2 = generate_transfer_reference(self.LOAN_ID, 2)
        assert "-01-" in ref1
        assert "-02-" in ref2

    def test_same_inputs_same_output(self):
        """Reference generation must be deterministic (idempotent)."""
        ref1 = generate_transfer_reference(self.LOAN_ID, 1, salt="secret")
        ref2 = generate_transfer_reference(self.LOAN_ID, 1, salt="secret")
        assert ref1 == ref2

    def test_different_attempts_different_references(self):
        """Each attempt must get a distinct reference to avoid duplicate transfer."""
        ref1 = generate_transfer_reference(self.LOAN_ID, 1)
        ref2 = generate_transfer_reference(self.LOAN_ID, 2)
        ref3 = generate_transfer_reference(self.LOAN_ID, 3)
        assert ref1 != ref2 != ref3

    def test_different_loans_different_references(self):
        loan_a = "aaaaaaaa-0000-0000-0000-000000000000"
        loan_b = "bbbbbbbb-0000-0000-0000-000000000000"
        ref_a = generate_transfer_reference(loan_a, 1)
        ref_b = generate_transfer_reference(loan_b, 1)
        assert ref_a != ref_b

    def test_salt_affects_checksum(self):
        """Different salts must produce different checksums."""
        ref1 = generate_transfer_reference(self.LOAN_ID, 1, salt="salt-a")
        ref2 = generate_transfer_reference(self.LOAN_ID, 1, salt="salt-b")
        assert ref1 != ref2

    def test_reference_length_is_reasonable(self):
        """Must fit in Paystack's reference field (≤ 100 chars)."""
        ref = generate_transfer_reference(self.LOAN_ID, 1, salt="some-secret")
        assert len(ref) <= 100

    def test_reference_is_url_safe(self):
        """Reference must not contain characters that break URL or JSON."""
        ref = generate_transfer_reference(self.LOAN_ID, 1, salt="secret")
        for char in ref:
            assert char in "abcdefghijklmnopqrstuvwxyz0123456789-_"


# ===========================================================================
# references_same_loan
# ===========================================================================


class TestReferencesSameLoan:
    LOAN_ID = "a3f2b1c4-dead-beef-cafe-123456789abc"

    def test_reference_matches_its_own_loan(self):
        ref = generate_transfer_reference(self.LOAN_ID, 1)
        assert references_same_loan(ref, self.LOAN_ID)

    def test_reference_does_not_match_different_loan(self):
        other_loan = "ffffffff-0000-0000-0000-000000000000"
        ref = generate_transfer_reference(self.LOAN_ID, 1)
        assert not references_same_loan(ref, other_loan)

    def test_retry_reference_still_matches_loan(self):
        ref2 = generate_transfer_reference(self.LOAN_ID, 2)
        assert references_same_loan(ref2, self.LOAN_ID)

    def test_arbitrary_reference_does_not_match(self):
        assert not references_same_loan("random-ref-12345", self.LOAN_ID)
