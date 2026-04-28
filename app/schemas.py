"""Pydantic schemas — webhook request/response."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class OrderItemIn(BaseModel):
    product: str = Field(..., min_length=1, max_length=255, description="Ilac adi")
    quantity: int = Field(..., gt=0, description="Siparis miktari (kutu/adet)")

    @field_validator("product")
    @classmethod
    def strip_product(cls, v: str) -> str:
        return v.strip()


class OrderWebhookIn(BaseModel):
    """ElevenLabs agent webhook tool'undan gelen payload."""

    conversation_id: str = Field(..., min_length=1, description="ElevenLabs conversation_id")
    recipient_number: str = Field(..., min_length=3, description="Aranan eczane numarasi")
    items: list[OrderItemIn] = Field(..., min_length=1, description="Siparis edilen urunler")


class OrderOut(BaseModel):
    order_id: int
    conversation_id: str
    recipient_number: str
    item_count: int
    created_at: datetime
    status: str = "ok"


class HealthOut(BaseModel):
    status: str
    db: str
