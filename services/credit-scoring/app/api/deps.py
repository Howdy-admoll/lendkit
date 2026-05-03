"""
Credit Scoring Service — FastAPI Dependencies
"""

from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import verify_token
from app.db.session import AsyncSession, get_db

log = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=True)

DbDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_subject(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> str:
    subject = verify_token(credentials.credentials)
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return subject


AuthDep = Annotated[str, Depends(get_current_subject)]
