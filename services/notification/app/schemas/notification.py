"""Notification Service — API Schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.engine.channels.base import ChannelType


class NotificationLogOut(BaseModel):
    id: uuid.UUID
    loan_id: str
    borrower_id: str
    event_type: str
    channel_type: ChannelType
    recipient: str
    subject: str
    body_preview: str
    success: bool
    provider_message_id: str
    provider_error: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PreferenceIn(BaseModel):
    sms_opted_out: bool = False
    email_opted_out: bool = False


class PreferenceOut(BaseModel):
    borrower_id: str
    sms_opted_out: bool
    email_opted_out: bool
    updated_at: datetime

    model_config = {"from_attributes": True}
