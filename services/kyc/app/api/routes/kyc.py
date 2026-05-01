"""
KYC Service — KYC Verification Routes

POST   /api/v1/kyc/            Initiate KYC
GET    /api/v1/kyc/{id}        Get verification status
PATCH  /api/v1/kyc/{id}        Update personal info
POST   /api/v1/kyc/{id}/documents  Upload a document
POST   /api/v1/kyc/webhooks/{provider}  Inbound provider webhook
"""
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import DBDep, RedisDep, TenantDep
from app.db.models import (
    DocumentStatus, DocumentType, KYCDocument, KYCStatus, KYCVerification, VerificationLevel
)
from app.schemas.kyc import (
    DocumentUploadRequest, DocumentVerificationResult,
    KYCInitiateRequest, KYCInitiateResponse, KYCStatusResponse, KYCUpdateRequest,
)
from app.services.document import get_document_processor
from app.services.identity import get_identity_provider
from app.workers.kyc_tasks import run_identity_check, run_document_verify

log = logging.getLogger(__name__)
router = APIRouter(prefix="/kyc", tags=["KYC Verification"])

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# POST /kyc/ — Initiate KYC
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=KYCInitiateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate KYC verification for a customer",
)
async def initiate_kyc(
    payload: KYCInitiateRequest,
    db: DBDep,
    tenant_id: TenantDep,
    background_tasks: BackgroundTasks,
) -> KYCInitiateResponse:
    # Validate tenant matches token
    if payload.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant_id in request does not match authenticated tenant",
        )

    # Check for existing non-expired verification
    existing = await db.execute(
        select(KYCVerification).where(
            KYCVerification.customer_id == payload.customer_id,
            KYCVerification.tenant_id  == payload.tenant_id,
            KYCVerification.status.notin_([KYCStatus.REJECTED, KYCStatus.EXPIRED]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active KYC verification already exists for this customer",
        )

    verification = KYCVerification(
        customer_id    = payload.customer_id,
        tenant_id      = payload.tenant_id,
        status         = KYCStatus.INITIATED,
        level          = VerificationLevel(payload.level),
        first_name     = payload.first_name,
        last_name      = payload.last_name,
        date_of_birth  = payload.date_of_birth,
        phone_number   = payload.phone_number,
        email          = str(payload.email) if payload.email else None,
        address_line1  = payload.address_line1,
        address_line2  = payload.address_line2,
        city           = payload.city,
        state          = payload.state,
        country        = payload.country,
        postal_code    = payload.postal_code,
    )
    db.add(verification)
    await db.flush()  # get the ID

    # Queue async identity check (for basic/standard)
    if payload.level in ("basic", "standard"):
        background_tasks.add_task(
            run_identity_check.delay,
            verification_id=str(verification.id),
        )

    await db.commit()
    log.info("KYC initiated: %s for customer %s", verification.id, payload.customer_id)

    return KYCInitiateResponse(
        verification_id=verification.id,
        customer_id=verification.customer_id,
        status=verification.status.value,
        level=verification.level.value,
    )


# ---------------------------------------------------------------------------
# GET /kyc/{verification_id} — Status
# ---------------------------------------------------------------------------

@router.get(
    "/{verification_id}",
    response_model=KYCStatusResponse,
    summary="Get KYC verification status",
)
async def get_kyc_status(
    verification_id: uuid.UUID,
    db: DBDep,
    tenant_id: TenantDep,
) -> KYCStatusResponse:
    result = await db.execute(
        select(KYCVerification).where(
            KYCVerification.id == verification_id,
            KYCVerification.tenant_id == tenant_id,
        )
    )
    verification = result.scalar_one_or_none()

    if not verification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification not found")

    return KYCStatusResponse(
        id               = verification.id,
        customer_id      = verification.customer_id,
        tenant_id        = verification.tenant_id,
        status           = verification.status.value,
        level            = verification.level.value,
        risk_score       = verification.risk_score,
        is_pep           = verification.is_pep,
        is_sanctioned    = verification.is_sanctioned,
        rejection_reason = verification.rejection_reason,
        documents        = [
            DocumentVerificationResult(
                document_id      = doc.id,
                status           = doc.status.value,
                document_type    = doc.document_type.value,
                confidence_score = float(doc.confidence_score) if doc.confidence_score else None,
                extracted_data   = doc.extracted_data,
                rejection_reason = doc.rejection_reason,
            )
            for doc in (verification.documents or [])
        ],
        created_at  = verification.created_at,
        updated_at  = verification.updated_at,
        approved_at = verification.approved_at,
        expires_at  = verification.expires_at,
    )


# ---------------------------------------------------------------------------
# PATCH /kyc/{verification_id} — Update personal info
# ---------------------------------------------------------------------------

@router.patch(
    "/{verification_id}",
    response_model=KYCInitiateResponse,
    summary="Update personal information on a KYC record",
)
async def update_kyc(
    verification_id: uuid.UUID,
    payload: KYCUpdateRequest,
    db: DBDep,
    tenant_id: TenantDep,
) -> KYCInitiateResponse:
    result = await db.execute(
        select(KYCVerification).where(
            KYCVerification.id == verification_id,
            KYCVerification.tenant_id == tenant_id,
        )
    )
    verification = result.scalar_one_or_none()

    if not verification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification not found")

    if verification.status in (KYCStatus.APPROVED, KYCStatus.EXPIRED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot update a {verification.status.value} verification",
        )

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(verification, field, str(value) if hasattr(value, "__str__") else value)

    await db.commit()
    return KYCInitiateResponse(
        verification_id=verification.id,
        customer_id=verification.customer_id,
        status=verification.status.value,
        level=verification.level.value,
        message="KYC record updated",
    )


# ---------------------------------------------------------------------------
# POST /kyc/{verification_id}/documents — Upload document
# ---------------------------------------------------------------------------

@router.post(
    "/{verification_id}/documents",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload an identity document for verification",
)
async def upload_document(
    verification_id: uuid.UUID,
    db: DBDep,
    tenant_id: TenantDep,
    background_tasks: BackgroundTasks,
    document_type: str = Form(...),
    document_number: str | None = Form(None),
    front_image: UploadFile = File(...),
    back_image: UploadFile | None = File(None),
) -> dict:
    # Validate verification exists and belongs to tenant
    result = await db.execute(
        select(KYCVerification).where(
            KYCVerification.id == verification_id,
            KYCVerification.tenant_id == tenant_id,
        )
    )
    verification = result.scalar_one_or_none()
    if not verification:
        raise HTTPException(status_code=404, detail="Verification not found")

    if verification.status in (KYCStatus.APPROVED, KYCStatus.EXPIRED, KYCStatus.REJECTED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot add document to a {verification.status.value} verification",
        )

    # Validate document type
    try:
        doc_type = DocumentType(document_type)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid document_type: {document_type}")

    # Validate file size
    front_bytes = await front_image.read()
    if len(front_bytes) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Front image exceeds 10 MB limit")

    # Upload to object storage
    processor = get_document_processor()
    front_key = await processor.upload(
        front_bytes,
        front_image.filename or "front.jpg",
        front_image.content_type or "image/jpeg",
    )

    back_key: str | None = None
    if back_image:
        back_bytes = await back_image.read()
        if len(back_bytes) > _MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="Back image exceeds 10 MB limit")
        back_key = await processor.upload(
            back_bytes,
            back_image.filename or "back.jpg",
            back_image.content_type or "image/jpeg",
        )

    # Create DB record
    doc = KYCDocument(
        verification_id = verification_id,
        document_type   = doc_type,
        document_number = document_number,
        status          = DocumentStatus.SUBMITTED,
        front_image_key = front_key,
        back_image_key  = back_key,
    )
    db.add(doc)
    await db.flush()
    await db.commit()

    # Queue async extraction
    background_tasks.add_task(run_document_verify.delay, document_id=str(doc.id))

    log.info("Document %s submitted for verification: %s", doc.id, verification_id)
    return {
        "document_id": str(doc.id),
        "status": "submitted",
        "message": "Document submitted for verification. Check status via GET /kyc/{verification_id}",
    }


# ---------------------------------------------------------------------------
# POST /kyc/webhooks/{provider} — Provider webhook
# ---------------------------------------------------------------------------

@router.post(
    "/webhooks/{provider}",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,  # not in public docs
)
async def handle_webhook(
    provider: str,
    db: DBDep,
    payload: dict,
) -> dict:
    """
    Inbound webhooks from identity providers (Smile ID, Onfido, etc.)
    Do NOT require tenant auth — validated by HMAC signature instead.
    """
    log.info("Received webhook from provider: %s", provider)

    identity_provider = get_identity_provider()
    result = await identity_provider.handle_webhook(payload)

    if not result.provider_reference:
        return {"status": "ignored"}

    stmt = select(KYCVerification).where(
        KYCVerification.provider_reference == result.provider_reference
    )
    db_result = await db.execute(stmt)
    verification = db_result.scalar_one_or_none()

    if not verification:
        log.warning("No verification found for provider ref: %s", result.provider_reference)
        return {"status": "not_found"}

    verification.status           = result.status
    verification.risk_score       = result.risk_score
    verification.is_pep           = result.is_pep
    verification.is_sanctioned    = result.is_sanctioned
    verification.provider_response = result.raw_response
    verification.rejection_reason  = result.rejection_reason

    if result.status == KYCStatus.APPROVED:
        from datetime import timedelta
        verification.approved_at = datetime.now(timezone.utc)
        verification.expires_at  = datetime.now(timezone.utc) + timedelta(days=365)

    await db.commit()
    return {"status": "processed"}
