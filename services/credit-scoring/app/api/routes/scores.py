"""
Credit Scoring Service — Score API Routes

POST /scores          — compute a new score (synchronous, returns immediately)
GET  /scores/{id}     — retrieve a score by ID
GET  /customers/{id}/scores  — latest score for a customer
GET  /customers/{id}/scores/history  — score history for a customer
"""

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AuthDep, DbDep
from app.schemas.score import CreditScoreOut, ScoreListOut, ScoreRequest
from app.services import score_service

router = APIRouter(prefix="/scores", tags=["Credit Scores"])


@router.post(
    "",
    response_model=CreditScoreOut,
    status_code=status.HTTP_201_CREATED,
    summary="Compute a credit score",
    description="""
Compute a credit score for a customer using available signals.

**Signal buckets**  (provide what you have — the engine adapts):
- `kyc` — KYC verification outcome (status, risk score, PEP/sanctions flags, verified documents)
- `income` — Income & employment data (type, tenure, monthly income)
- `repayment` — Historical repayment record (on-time ratio, defaults, days past due)

The response includes a numeric score (300–850), a tier (excellent/good/fair/poor/very_poor),
a recommendation, and a full **factor breakdown** explaining what drove the score.
""",
)
async def compute_score(
    req: ScoreRequest,
    db: DbDep,
    _subject: AuthDep,
) -> CreditScoreOut:
    cs = await score_service.request_score(db, req)
    return CreditScoreOut.model_validate(cs)


@router.get(
    "/{score_id}",
    response_model=CreditScoreOut,
    summary="Get score by ID",
)
async def get_score(
    score_id: str,
    tenant_id: str = Query(..., description="Tenant ID for access control"),
    db: DbDep = None,
    _subject: AuthDep = None,
) -> CreditScoreOut:
    cs = await score_service.get_score_by_id(db, score_id, tenant_id)
    if cs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Score not found")
    return CreditScoreOut.model_validate(cs)


# ---------------------------------------------------------------------------
# Customer-scoped endpoints (different prefix)
# ---------------------------------------------------------------------------

customer_router = APIRouter(prefix="/customers", tags=["Credit Scores"])


@customer_router.get(
    "/{customer_id}/score",
    response_model=CreditScoreOut,
    summary="Get latest score for a customer",
)
async def get_customer_score(
    customer_id: str,
    tenant_id: str = Query(..., description="Tenant ID for access control"),
    db: DbDep = None,
    _subject: AuthDep = None,
) -> CreditScoreOut:
    cs = await score_service.get_latest_score(db, customer_id, tenant_id)
    if cs is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No computed score found for this customer",
        )
    return CreditScoreOut.model_validate(cs)


@customer_router.get(
    "/{customer_id}/scores",
    response_model=ScoreListOut,
    summary="Get score history for a customer",
)
async def get_customer_score_history(
    customer_id: str,
    tenant_id: str = Query(..., description="Tenant ID for access control"),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: DbDep = None,
    _subject: AuthDep = None,
) -> ScoreListOut:
    items, total = await score_service.list_scores(db, customer_id, tenant_id, limit, offset)
    return ScoreListOut(
        items=[CreditScoreOut.model_validate(cs) for cs in items],
        total=total,
    )
