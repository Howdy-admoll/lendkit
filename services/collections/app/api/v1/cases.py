"""Collections Service — API v1 Routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CollectionCase
from app.db.session import get_db
from app.schemas.collection import CollectionCaseOut
from app.services.collection_service import CollectionService

router = APIRouter(prefix="/api/v1", tags=["Collections"])


@router.get(
    "/cases",
    response_model=list[CollectionCaseOut],
    summary="List all collection cases",
)
async def list_cases(
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[CollectionCaseOut]:
    result = await db.execute(
        select(CollectionCase)
        .order_by(CollectionCase.days_past_due.desc())
        .limit(limit)
        .offset(offset)
    )
    return [CollectionCaseOut.model_validate(c) for c in result.scalars().all()]


@router.get(
    "/cases/{loan_id}",
    response_model=CollectionCaseOut,
    summary="Get collection case for a loan",
    description="Returns 404 if no collection case exists (healthy loan).",
)
async def get_case(loan_id: str, db: AsyncSession = Depends(get_db)) -> CollectionCaseOut:
    svc = CollectionService(db)
    case = await svc.get_case(loan_id)
    if case is None:
        raise HTTPException(status_code=404, detail="No collection case for this loan")
    return CollectionCaseOut.model_validate(case)
