"""Pydantic schemas — webhook request/response."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class OrderItemIn(BaseModel):
    product: str = Field(..., min_length=1, max_length=255, description="İlaç adı")
    quantity: int = Field(..., gt=0, description="Sipariş miktarı (kutu/adet)")

    @field_validator("product")
    @classmethod
    def strip_product(cls, v: str) -> str:
        return v.strip()


class OrderWebhookIn(BaseModel):
    """ElevenLabs agent webhook tool'undan gelen payload."""

    batch_id: str = Field(..., min_length=1, description="ElevenLabs batch_id")
    conversation_id: str = Field(..., min_length=1, description="ElevenLabs conversation_id")
    recipient_number: str = Field(..., min_length=3, description="Aranan eczane numarası")
    items: list[OrderItemIn] = Field(..., min_length=1, description="Sipariş edilen ürünler")


class OrderOut(BaseModel):
    order_id: int
    batch_id: str
    conversation_id: str
    recipient_number: str
    item_count: int
    created_at: datetime
    status: str = "ok"


class HealthOut(BaseModel):
    status: str
    db: str
