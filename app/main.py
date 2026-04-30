"""FastAPI server — ElevenLabs siparis webhook'u."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Header, Request
from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from database import engine, get_session
from models import Order, OrderItem
from schemas import (
    HealthOut,
    OrderDetailOut,
    OrderItemOut,
    OrderOut,
    OrderWebhookIn,
    OrdersByConversationsRequest,
    OrdersByConversationsResponse,
)

WEBHOOK_API_TOKEN = os.getenv("WEBHOOK_API_TOKEN", "").strip()
MAX_CONVERSATION_IDS_PER_REQUEST = 600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("order-webhook")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("DB connection OK")
    yield
    await engine.dispose()


app = FastAPI(
    title="Eczane Siparis Webhook",
    version="2.0.0",
    lifespan=lifespan,
)

def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Optional bearer auth.

    WEBHOOK_API_TOKEN bos ise kontrol yapilmaz (local/dev davranisi).
    Set edildiyse Authorization: Bearer <token> zorunlu, yoksa 401.
    """
    if not WEBHOOK_API_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_or_invalid_authorization",
        )
    token = authorization[len("Bearer "):].strip()
    if token != WEBHOOK_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
        )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = await request.body()
    logger.error(
        "422 validation error\n  errors=%s\n  body=%s",
        exc.errors(),
        body.decode("utf-8", errors="replace"),
    )
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "received_body": body.decode("utf-8", errors="replace")},
    )


@app.get("/health", response_model=HealthOut)
async def health(session: AsyncSession = Depends(get_session)) -> HealthOut:
    try:
        await session.execute(text("SELECT 1"))
        return HealthOut(status="ok", db="ok")
    except Exception as e:
        logger.exception("DB health check failed")
        raise HTTPException(status_code=503, detail=f"db_error: {e}")


@app.post(
    "/webhook/order",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
)
async def receive_order(
    payload: OrderWebhookIn,
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """ElevenLabs agent tool'undan gelen siparisi kaydeder.

    Idempotent: ayni conversation_id ile gelen istek tekrar yazmaz,
    mevcut kaydi doner. Batch_id agent'tan gelmez; raporlama UI tarafinda
    ElevenLabs API ile conversation_id eslemesi yaparak yapilir.
    """
    logger.info(
        "Incoming order: conv=%s to=%s items=%d",
        payload.conversation_id,
        payload.recipient_number,
        len(payload.items),
    )

    # Idempotency check
    existing = await session.execute(
        select(Order).where(Order.conversation_id == payload.conversation_id)
    )
    existing_order = existing.scalar_one_or_none()
    if existing_order is not None:
        logger.info("Duplicate conversation_id=%s, returning existing", payload.conversation_id)
        await session.refresh(existing_order, attribute_names=["items"])
        return OrderOut(
            order_id=existing_order.id,
            conversation_id=existing_order.conversation_id,
            recipient_number=existing_order.recipient_number,
            item_count=len(existing_order.items),
            created_at=existing_order.created_at,
            status="duplicate",
        )

    # Yeni siparis yaz
    order = Order(
        conversation_id=payload.conversation_id,
        recipient_number=payload.recipient_number,
        raw_payload=payload.model_dump(),
    )
    session.add(order)
    await session.flush()

    for item in payload.items:
        session.add(
            OrderItem(
                order_id=order.id,
                product_name=item.product,
                quantity=item.quantity,
            )
        )

    await session.commit()
    logger.info("Saved order id=%s with %d items", order.id, len(payload.items))

    return OrderOut(
        order_id=order.id,
        conversation_id=order.conversation_id,
        recipient_number=order.recipient_number,
        item_count=len(payload.items),
        created_at=order.created_at,
        status="ok",
    )


@app.post(
    "/orders/by-conversations",
    response_model=OrdersByConversationsResponse,
    dependencies=[Depends(require_auth)],
)
async def orders_by_conversations(
    payload: OrdersByConversationsRequest,
    session: AsyncSession = Depends(get_session),
) -> OrdersByConversationsResponse:
    """Verilen conversation_id listesi icin siparisleri items ile birlikte doner.

    Bulunamayan id'ler sessizce response'tan dusurulur (null/error donmez).
    """
    ids = payload.conversation_ids
    if len(ids) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="conversation_ids must be non-empty",
        )
    if len(ids) > MAX_CONVERSATION_IDS_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"conversation_ids exceeds maximum of {MAX_CONVERSATION_IDS_PER_REQUEST}",
        )

    stmt = (
        select(Order)
        .where(Order.conversation_id.in_(ids))
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
    )
    result = await session.execute(stmt)
    orders = result.scalars().all()

    return OrdersByConversationsResponse(
        orders=[
            OrderDetailOut(
                order_id=o.id,
                conversation_id=o.conversation_id,
                recipient_number=o.recipient_number,
                created_at=o.created_at,
                items=[
                    OrderItemOut(product_name=i.product_name, quantity=i.quantity)
                    for i in sorted(o.items, key=lambda i: i.id)
                ],
            )
            for o in orders
        ]
    )
