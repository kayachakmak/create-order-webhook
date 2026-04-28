-- =========================================================
-- Eczane Sipariş Webhook — PostgreSQL Schema (v3, sade)
-- batch yonetimi tamamen ElevenLabs + UI tarafinda.
-- Bu DB sadece siparisleri tutar.
-- Batch raporlamasi: UI ElevenLabs API'den conversation_id'leri alir,
-- sonra burada `SELECT ... WHERE conversation_id = ANY(...)` ile join eder.
-- =========================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------- ORDERS ----------
CREATE TABLE IF NOT EXISTS orders (
    id                  BIGSERIAL PRIMARY KEY,
    conversation_id     TEXT NOT NULL UNIQUE,       -- ElevenLabs conversation_id
    recipient_number    TEXT NOT NULL,              -- aranan eczane numarasi
    raw_payload         JSONB,                      -- ham webhook payload (debug)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_conversation_id ON orders(conversation_id);
CREATE INDEX IF NOT EXISTS idx_orders_recipient_number ON orders(recipient_number);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);

-- ---------- ORDER ITEMS ----------
CREATE TABLE IF NOT EXISTS order_items (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_name    TEXT NOT NULL,
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_name ON order_items(product_name);

-- ---------- VIEW ----------
CREATE OR REPLACE VIEW v_orders_full AS
SELECT
    o.id              AS order_id,
    o.conversation_id,
    o.recipient_number,
    o.created_at      AS order_created_at,
    oi.product_name,
    oi.quantity
FROM orders o
LEFT JOIN order_items oi ON oi.order_id = o.id
ORDER BY o.created_at DESC, oi.id;
