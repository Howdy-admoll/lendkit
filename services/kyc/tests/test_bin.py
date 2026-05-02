"""
KYC Service — BIN Lookup Tests
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.bin import BankInfo, BINLookupResponse
from app.services.bin_lookup import BINLookupService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    return redis


@pytest.fixture
def bin_service(mock_db, mock_redis):
    return BINLookupService(db=mock_db, redis=mock_redis)


@pytest.fixture
def sample_bin_response():
    return BINLookupResponse(
        bin="440393",
        card_brand="VISA",
        card_type="DEBIT",
        card_category="CLASSIC",
        bank=BankInfo(name="Access Bank", url="https://accessbank.com", phone="+234"),
        country_name="Nigeria",
        country_code="NG",
        currency="NGN",
        is_prepaid=False,
        source="api",
    )


# ---------------------------------------------------------------------------
# BIN Lookup Tests
# ---------------------------------------------------------------------------


class TestBINLookup:
    async def test_lookup_from_redis_cache(self, bin_service, mock_redis, sample_bin_response):
        """Should return cached result without hitting DB or external API."""
        mock_redis.get.return_value = sample_bin_response.model_dump_json()

        result = await bin_service.lookup("440393")

        assert result.bin == "440393"
        assert result.card_brand == "VISA"
        assert result.source == "cache"
        mock_redis.get.assert_called_once()

    async def test_lookup_cache_miss_hits_api(self, bin_service, mock_redis, mock_db):
        """Should call external API when Redis and DB both miss."""
        mock_redis.get.return_value = None

        # DB returns no existing record
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = db_result

        api_response = {
            "scheme": "visa",
            "type": "debit",
            "brand": "VISA",
            "prepaid": False,
            "bank": {"name": "GTBank", "url": "https://gtbank.com", "phone": None},
            "country": {"name": "Nigeria", "alpha2": "NG", "currency": "NGN"},
        }

        with patch("app.services.bin_lookup.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await bin_service.lookup("440393")

        assert result.bin == "440393"
        assert result.card_brand == "VISA"
        assert result.source == "api"

    async def test_bin_normalizes_to_8_digits(self, bin_service, mock_redis, mock_db):
        """BINs longer than 8 digits should be truncated."""
        mock_redis.get.return_value = None
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = db_result

        with patch("app.services.bin_lookup.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {}
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            await bin_service.lookup("4403930123456789")  # should use first 8 digits

        call_url = mock_client.return_value.__aenter__.return_value.get.call_args[0][0]
        assert call_url.endswith("/44039301")

    async def test_bin_validation_blocks_prepaid(self, bin_service, sample_bin_response):
        """Validation should reject prepaid cards when block_prepaid=True."""
        prepaid_response = sample_bin_response.model_copy(update={"is_prepaid": True})

        with patch.object(bin_service, "lookup", return_value=prepaid_response):
            result = await bin_service.validate("440393", block_prepaid=True)

        assert result.is_allowed is False
        assert any("prepaid" in r.lower() for r in result.rejection_reasons)

    async def test_bin_validation_allows_valid_card(self, bin_service, sample_bin_response):
        """Validation should pass for a standard debit card with no restrictions."""
        with patch.object(bin_service, "lookup", return_value=sample_bin_response):
            result = await bin_service.validate(
                "440393",
                allowed_brands=["VISA", "MASTERCARD"],
                block_prepaid=False,
            )

        assert result.is_valid is True
        assert result.is_allowed is True
        assert result.rejection_reasons == []

    async def test_bin_validation_wrong_brand(self, bin_service, sample_bin_response):
        """Validation should reject cards not in allowed_brands list."""
        with patch.object(bin_service, "lookup", return_value=sample_bin_response):
            result = await bin_service.validate(
                "440393",
                allowed_brands=["MASTERCARD"],  # Only Mastercard, this is VISA
            )

        assert result.is_allowed is False
        assert len(result.rejection_reasons) == 1


class TestBINParsing:
    def test_parse_binlist_response(self):
        raw = {
            "scheme": "mastercard",
            "type": "credit",
            "brand": "MASTERCARD",
            "prepaid": False,
            "bank": {
                "name": "First Bank",
                "url": "https://firstbank.com",
                "phone": "0800-033-3400",
            },
            "country": {"name": "Nigeria", "alpha2": "NG", "currency": "NGN"},
            "category": "WORLD",
        }
        result = BINLookupService._parse_api_response("512345", raw)

        assert result.bin == "512345"
        assert result.card_brand == "MASTERCARD"
        assert result.card_type == "credit"
        assert result.bank.name == "First Bank"
        assert result.country_code == "NG"
        assert result.is_prepaid is False

    def test_parse_empty_response_returns_nones(self):
        result = BINLookupService._parse_api_response("999999", {})
        assert result.bin == "999999"
        assert result.card_brand is None
        assert result.bank.name is None
