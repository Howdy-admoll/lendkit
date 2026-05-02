"""
KYC Service — BIN Lookup Routes

GET  /api/v1/bin/{bin}         Lookup BIN metadata
POST /api/v1/bin/validate      Validate BIN against lender rules
"""
import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DBDep, RedisDep, TenantDep
from app.schemas.bin import BINLookupRequest, BINLookupResponse, BINValidationResult
from app.services.bin_lookup import BINLookupService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/bin", tags=["BIN Lookup"])


@router.get(
    "/{bin_number}",
    response_model=BINLookupResponse,
    summary="Look up card metadata by BIN (Bank Identification Number)",
    description="""
    Returns issuing bank, card brand, type, and country for a given BIN.
    Results are cached in Redis (24h TTL) and PostgreSQL.

    The BIN is the first 6–8 digits of any payment card number.
    """,
)
async def lookup_bin(
    bin_number: str,
    db: DBDep,
    redis: RedisDep,
    tenant_id: TenantDep,
) -> BINLookupResponse:
    # Validate format
    request = BINLookupRequest(bin=bin_number)
    svc = BINLookupService(db=db, redis=redis)

    try:
        return await svc.lookup(request.bin)
    except Exception as exc:
        log.error("BIN lookup failed for %s: %s", bin_number, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BIN lookup service temporarily unavailable",
        ) from exc


@router.post(
    "/validate",
    response_model=BINValidationResult,
    summary="Validate a BIN against configurable lender rules",
    description="""
    Validates a card BIN against lender-specific policies such as:
    - Allowed card brands (VISA, MASTERCARD, VERVE, etc.)
    - Block prepaid cards
    - Block international cards
    - Restrict to specific countries
    """,
)
async def validate_bin(
    payload: BINLookupRequest,
    db: DBDep,
    redis: RedisDep,
    tenant_id: TenantDep,
    block_prepaid: bool = Query(default=False, description="Reject prepaid cards"),
    block_international: bool = Query(default=False, description="Reject non-domestic cards"),
    allowed_brands: list[str] = Query(
        default=[],
        description="Comma-separated list of allowed card brands. Empty = allow all.",
    ),
    allowed_countries: list[str] = Query(
        default=[],
        description="Allowed ISO 3166-1 alpha-2 country codes. Empty = allow all.",
    ),
) -> BINValidationResult:
    svc = BINLookupService(db=db, redis=redis)

    return await svc.validate(
        bin_number=payload.bin,
        allowed_brands=allowed_brands or None,
        block_prepaid=block_prepaid,
        block_international=block_international,
        allowed_countries=allowed_countries or None,
    )
