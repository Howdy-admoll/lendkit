"""
LendKit Shared — Common Validators

Reusable validation functions used across all services.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Any


# ---------------------------------------------------------------------------
# Card / BIN
# ---------------------------------------------------------------------------

def is_valid_luhn(card_number: str) -> bool:
    """
    Luhn algorithm — validates card number checksums.
    Used to reject obviously invalid card numbers before a BIN lookup.
    """
    digits = [int(d) for d in card_number if d.isdigit()]
    if not digits or len(digits) < 12:
        return False

    checksum = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit

    return checksum % 10 == 0


def extract_bin(card_number: str, length: int = 6) -> str | None:
    """Extract the BIN from a full card number."""
    digits = re.sub(r"\D", "", card_number)
    if len(digits) < 12:
        return None
    return digits[:length]


def mask_card_number(card_number: str) -> str:
    """Mask card number for logging: 4111111111111111 → 411111######1111"""
    digits = re.sub(r"\D", "", card_number)
    if len(digits) < 12:
        return "****"
    return digits[:6] + "#" * (len(digits) - 10) + digits[-4:]


# ---------------------------------------------------------------------------
# Phone Numbers
# ---------------------------------------------------------------------------

_E164_RE = re.compile(r"^\+?[1-9]\d{6,14}$")
_NG_RE   = re.compile(r"^(0|\+234)[789][01]\d{8}$")


def is_valid_e164(phone: str) -> bool:
    """Validate E.164 international format."""
    return bool(_E164_RE.match(phone.replace(" ", "").replace("-", "")))


def is_valid_nigerian_phone(phone: str) -> bool:
    """Validate Nigerian mobile number (0XX or +234XX)."""
    return bool(_NG_RE.match(phone.replace(" ", "").replace("-", "")))


def normalize_nigerian_phone(phone: str) -> str:
    """Convert 080XXXXXXXX to +23480XXXXXXXX."""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("234"):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"+234{digits[1:]}"
    return phone


# ---------------------------------------------------------------------------
# Financial Amounts
# ---------------------------------------------------------------------------

def is_valid_amount(value: Any, min_amount: Decimal = Decimal("1"), currency_decimals: int = 2) -> bool:
    """Validate a monetary amount is positive and within expected precision."""
    try:
        amount = Decimal(str(value))
        if amount < min_amount:
            return False
        # Check decimal places don't exceed currency precision
        if amount.as_tuple().exponent < -currency_decimals:
            return False
        return True
    except (InvalidOperation, ValueError):
        return False


def to_kobo(naira: Decimal | float | str) -> int:
    """Convert Naira to Kobo (smallest unit). 1 NGN = 100 Kobo."""
    return int(Decimal(str(naira)) * 100)


def from_kobo(kobo: int) -> Decimal:
    """Convert Kobo to Naira."""
    return Decimal(kobo) / 100


# ---------------------------------------------------------------------------
# BVN / NIN
# ---------------------------------------------------------------------------

def is_valid_bvn(bvn: str) -> bool:
    """Nigerian BVN is exactly 11 digits."""
    return bool(re.fullmatch(r"\d{11}", bvn))


def is_valid_nin(nin: str) -> bool:
    """Nigerian NIN is exactly 11 digits."""
    return bool(re.fullmatch(r"\d{11}", nin))


# ---------------------------------------------------------------------------
# Account Numbers
# ---------------------------------------------------------------------------

def is_valid_nuban(account_number: str) -> bool:
    """
    Validate Nigerian Uniform Bank Account Number (NUBAN).
    NUBAN is 10 digits. Full checksum validation requires the bank code.
    This function validates format only.
    """
    return bool(re.fullmatch(r"\d{10}", account_number))


def nuban_checksum(bank_code: str, account_number: str) -> bool:
    """
    Full NUBAN checksum validation per CBN standard.
    Multipliers: 3, 7, 3, 3, 7, 3, 3, 7, 3
    """
    if len(bank_code) != 3 or len(account_number) != 10:
        return False

    serial = bank_code + account_number[:9]
    multipliers = [3, 7, 3, 3, 7, 3, 3, 7, 3]

    total = sum(int(d) * m for d, m in zip(serial, multipliers))
    check_digit = (10 - (total % 10)) % 10

    return check_digit == int(account_number[9])
