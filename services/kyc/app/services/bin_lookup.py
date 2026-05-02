"""
KYC Service — BIN Lookup Service

Lookup flow:
  1. Redis cache (hot, TTL-based)
  2. PostgreSQL local DB cache (warm)
  3. External BIN API (cold, then persisted to both caches)

Supports binlist.net-compatible APIs.
Pluggable: swap provider in config without touching routes.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import BINRecord
from app.schemas.bin import BankInfo, BINLookupResponse, BINValidationResult

log = logging.getLogger(__name__)

REDIS_BIN_PREFIX = "bin:lookup:"


class BINLookupService:
    """
    Three-tier BIN lookup with caching and circuit-breaking.
    """

    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def lookup(self, bin_number: str) -> BINLookupResponse:
        """
        Resolve BIN metadata. Checks cache → DB → external API in order.
        """
        bin_number = bin_number[:8]  # normalize to max 8 digits

        # 1. Redis cache
        cached = await self._from_redis(bin_number)
        if cached:
            log.debug("BIN cache hit (Redis): %s", bin_number)
            return BINLookupResponse(**cached, source="cache")

        # 2. PostgreSQL cache
        record = await self._from_db(bin_number)
        if record and not self._is_expired(record):
            log.debug("BIN cache hit (DB): %s", bin_number)
            resp = self._record_to_response(record, source="db")
            await self._set_redis(bin_number, resp)
            return resp

        # 3. External API
        log.info("BIN cache miss — fetching from provider: %s", bin_number)
        raw = await self._fetch_from_api(bin_number)
        resp = self._parse_api_response(bin_number, raw)

        # Persist to DB and cache
        await self._upsert_db(bin_number, raw, resp)
        await self._set_redis(bin_number, resp)

        return resp

    async def validate(
        self,
        bin_number: str,
        allowed_brands: list[str] | None = None,
        block_prepaid: bool = False,
        block_international: bool = False,
        allowed_countries: list[str] | None = None,
    ) -> BINValidationResult:
        """
        Validate a BIN against configurable lender rules.
        """
        try:
            info = await self.lookup(bin_number)
        except Exception as exc:
            log.warning("BIN lookup failed during validation: %s — %s", bin_number, exc)
            return BINValidationResult(
                bin=bin_number,
                is_valid=False,
                is_allowed=False,
                rejection_reasons=["BIN lookup failed — card cannot be verified"],
            )

        reasons: list[str] = []

        if block_prepaid and info.is_prepaid:
            reasons.append("Prepaid cards are not accepted")

        if allowed_brands and info.card_brand:
            if info.card_brand.upper() not in [b.upper() for b in allowed_brands]:
                reasons.append(f"Card brand {info.card_brand} is not accepted")

        if block_international and info.country_code:
            # Assumes tenant's base country; compare against customer country in caller
            reasons.append(f"International cards from {info.country_code} are not accepted")

        if allowed_countries and info.country_code:
            if info.country_code.upper() not in [c.upper() for c in allowed_countries]:
                reasons.append(f"Cards from {info.country_code} are not accepted")

        return BINValidationResult(
            bin=bin_number,
            is_valid=True,
            is_allowed=len(reasons) == 0,
            rejection_reasons=reasons,
            bin_info=info,
        )

    # -------------------------------------------------------------------------
    # Internal: Redis
    # -------------------------------------------------------------------------

    async def _from_redis(self, bin_number: str) -> dict[str, Any] | None:
        raw = await self.redis.get(f"{REDIS_BIN_PREFIX}{bin_number}")
        if raw:
            return json.loads(raw)
        return None

    async def _set_redis(self, bin_number: str, resp: BINLookupResponse) -> None:
        await self.redis.setex(
            f"{REDIS_BIN_PREFIX}{bin_number}",
            settings.bin_cache_ttl,
            resp.model_dump_json(),
        )

    # -------------------------------------------------------------------------
    # Internal: PostgreSQL
    # -------------------------------------------------------------------------

    async def _from_db(self, bin_number: str) -> BINRecord | None:
        result = await self.db.execute(select(BINRecord).where(BINRecord.bin == bin_number))
        return result.scalar_one_or_none()

    async def _upsert_db(
        self, bin_number: str, raw: dict[str, Any], resp: BINLookupResponse
    ) -> None:
        existing = await self._from_db(bin_number)
        expires = datetime.now(datetime.UTC) + timedelta(seconds=settings.bin_cache_ttl)

        if existing:
            existing.card_brand = resp.card_brand
            existing.card_type = resp.card_type
            existing.card_category = resp.card_category
            existing.bank_name = resp.bank.name
            existing.bank_url = resp.bank.url
            existing.bank_phone = resp.bank.phone
            existing.country_name = resp.country_name
            existing.country_code = resp.country_code
            existing.currency = resp.currency
            existing.is_prepaid = resp.is_prepaid
            existing.raw_response = raw
            existing.fetched_at = datetime.now(datetime.UTC)
            existing.expires_at = expires
        else:
            record = BINRecord(
                bin=bin_number,
                card_brand=resp.card_brand,
                card_type=resp.card_type,
                card_category=resp.card_category,
                bank_name=resp.bank.name,
                bank_url=resp.bank.url,
                bank_phone=resp.bank.phone,
                country_name=resp.country_name,
                country_code=resp.country_code,
                currency=resp.currency,
                is_prepaid=resp.is_prepaid,
                raw_response=raw,
                expires_at=expires,
            )
            self.db.add(record)

        await self.db.flush()

    # -------------------------------------------------------------------------
    # Internal: External API
    # -------------------------------------------------------------------------

    async def _fetch_from_api(self, bin_number: str) -> dict[str, Any]:
        """
        Fetch BIN data from binlist.net-compatible API.
        Raises httpx.HTTPError on failure.
        """
        headers: dict[str, str] = {"Accept-Version": "3"}
        if settings.bin_api_key:
            headers["Authorization"] = f"Bearer {settings.bin_api_key}"

        async with httpx.AsyncClient(timeout=settings.bin_request_timeout) as client:
            response = await client.get(
                f"{settings.bin_api_url}/{bin_number}",
                headers=headers,
            )
            if response.status_code == 404:
                log.warning("BIN not found in external API: %s", bin_number)
                return {}
            response.raise_for_status()
            return response.json()

    # -------------------------------------------------------------------------
    # Internal: Parsing
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_api_response(bin_number: str, raw: dict[str, Any]) -> BINLookupResponse:
        """Normalize binlist.net API response to BINLookupResponse."""
        bank_data = raw.get("bank", {})
        country_data = raw.get("country", {})

        return BINLookupResponse(
            bin=bin_number,
            card_brand=raw.get("brand") or raw.get("scheme"),
            card_type=raw.get("type"),
            card_category=raw.get("category"),
            bank=BankInfo(
                name=bank_data.get("name"),
                url=bank_data.get("url"),
                phone=bank_data.get("phone"),
            ),
            country_name=country_data.get("name"),
            country_code=country_data.get("alpha2"),
            currency=country_data.get("currency"),
            is_prepaid=raw.get("prepaid"),
            source="api",
        )

    @staticmethod
    def _record_to_response(record: BINRecord, source: str = "db") -> BINLookupResponse:
        return BINLookupResponse(
            bin=record.bin,
            card_brand=record.card_brand,
            card_type=record.card_type,
            card_category=record.card_category,
            bank=BankInfo(
                name=record.bank_name,
                url=record.bank_url,
                phone=record.bank_phone,
            ),
            country_name=record.country_name,
            country_code=record.country_code,
            currency=record.currency,
            is_prepaid=record.is_prepaid,
            source=source,
        )

    @staticmethod
    def _is_expired(record: BINRecord) -> bool:
        if record.expires_at is None:
            return False
        return datetime.now(datetime.UTC) > record.expires_at
