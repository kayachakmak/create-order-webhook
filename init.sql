-- =========================================================
-- Eczane Sipariş Webhook — PostgreSQL Schema
-- =========================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------- BATCHES ----------
-- ElevenLabs batch calling kampanyaları
CREATE TABLE IF NOT EXISTS batches (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        TEXT NOT NULL UNIQUE,           -- ElevenLabs batch_id
    name            TEXT,                           -- opsiyonel açıklama
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_batches_batch_id ON batches(batch_id);

-- ---------- ORDERS ----------
-- Her ElevenLabs konuşması = bir sipariş
CREATE TABLE IF NOT EXISTS orders (
    id                  BIGSERIAL PRIMARY KEY,
    batch_pk            BIGINT NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    conversation_id     TEXT NOT NULL UNIQUE,       -- ElevenLabs conversation_id
    recipient_number    TEXT NOT NULL,              -- aranan eczane numarası (E.164)
    raw_payload         JSONB,                      -- gelen ham webhook payload (debug)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_batch_pk ON orders(batch_pk);
CREATE INDEX IF NOT EXISTS idx_orders_conversation_id ON orders(conversation_id);
CREATE INDEX IF NOT EXISTS idx_orders_recipient_number ON orders(recipient_number);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);

-- ---------- ORDER ITEMS ----------
-- Her siparişteki ürün satırları
CREATE TABLE IF NOT EXISTS order_items (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_name    TEXT NOT NULL,                  -- ilaç adı (dynamic variable'dan)
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_name ON order_items(product_name);

-- ---------- VIEW (kolay raporlama için) ----------
CREATE OR REPLACE VIEW v_orders_full AS
SELECT
    o.id              AS order_id,
    o.conversation_id,
    o.recipient_number,
    o.created_at      AS order_created_at,
    b.batch_id,
    b.name            AS batch_name,
    oi.product_name,
    oi.quantity
FROM orders o
JOIN batches b      ON b.id = o.batch_pk
LEFT JOIN order_items oi ON oi.order_id = o.id
ORDER BY o.created_at DESC, oi.id;
