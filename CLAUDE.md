# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FastAPI webhook that receives pharmacy order payloads from an ElevenLabs voice agent and persists them to PostgreSQL. Designed to run behind a pre-existing Traefik reverse proxy on a VPS via Docker Compose.

## Common commands

Build and run the full stack (db + app) locally / on VPS:

```bash
docker compose up -d --build
docker compose logs -f app
```

Tail just the app, restart after code changes:

```bash
docker compose restart app
docker compose logs -f app
```

Open a psql shell against the running DB:

```bash
docker compose exec db psql -U orders -d orders
```

There is no test suite, linter config, or migration tool in this repo. Schema changes go in `db/init.sql` (only applied on a fresh volume — see "Schema changes" below).

## Architecture

Three-tier, all defined in `docker-compose.yml`:

1. **Traefik** (external, not in this compose file) — terminates TLS and routes `https://${DOMAIN}` to the app via labels on the `app` service. Traefik is assumed to run in host network mode, so the app binds to `127.0.0.1:8000` on the host and Traefik reaches it through loopback (not via the docker network). The Traefik network name, entrypoint, and certresolver are all `.env`-driven.
2. **`app`** — FastAPI + async SQLAlchemy + asyncpg. Source under `app/`. Single endpoint of substance: `POST /webhook/order`.
3. **`db`** — Postgres 16. Schema bootstrapped from `db/init.sql` via the official image's `/docker-entrypoint-initdb.d` hook.

### Request flow (`app/main.py`)

`POST /webhook/order` → Pydantic validates body (`OrderWebhookIn` in `schemas.py`) → idempotency check on `conversation_id` (returns existing order with `status: "duplicate"` if found) → otherwise inserts a new `Order` + N `OrderItem` rows in one transaction → returns `OrderOut`.

The full inbound payload is also persisted into `orders.raw_payload` (JSONB) for debugging — keep this behavior when modifying the handler.

A custom `RequestValidationError` handler logs the offending body and echoes it back in the 422 response. This is intentional for debugging ElevenLabs payloads, which change shape across agent versions — don't silence it without asking.

### Data model

- `orders` — one row per ElevenLabs conversation. `conversation_id` is `UNIQUE` and is the idempotency key.
- `order_items` — line items, `order_id → orders.id ON DELETE CASCADE`, `CHECK (quantity > 0)`.
- `v_orders_full` — flattened view for reporting; the README's example queries hit this.

The README mentions a `batches` table, but it does not exist. Batch-to-conversation mapping is intentionally done outside this DB (UI + ElevenLabs API). Don't add a `batches` table without confirming.

The ORM models in `app/models.py` and the SQL in `db/init.sql` are maintained independently — keep them in sync by hand when changing the schema.

### Schema changes

`db/init.sql` only runs on **first** container start (empty volume). For an existing deployment, either:
- apply DDL manually via `docker compose exec db psql ...`, or
- destroy the volume (`docker compose down -v`) — destructive, asks the user first.

There is no Alembic / migration tooling. The README explicitly calls this out as future work.

### Configuration

All config is env vars (loaded by Docker Compose from `.env`). `DATABASE_URL` defaults to the in-compose `db` hostname; the app has no fallback for running outside Docker. The `.env.example` / `env.example` files are the canonical list of required vars (`POSTGRES_PASSWORD`, `DOMAIN`, `TRAEFIK_NETWORK`, `TRAEFIK_ENTRYPOINT`, `TRAEFIK_CERTRESOLVER`, `WEBHOOK_API_TOKEN`).

`WEBHOOK_API_TOKEN` is read once at import time in `app/main.py` via `os.getenv`. Empty/unset = auth disabled (preserves the original open-endpoint behavior); set = read endpoints require `Authorization: Bearer <token>`. The dependency is `require_auth` and is meant to be reused on future read endpoints — attach it via `dependencies=[Depends(require_auth)]` on the route decorator.

## Read API

### `POST /orders/by-conversations`

Bulk lookup of orders by ElevenLabs `conversation_id`. Used by the reporting UI to join a batch's conversations (fetched from the ElevenLabs API) against this DB.

Request:

```json
{ "conversation_ids": ["conv_abc", "conv_xyz", "conv_123"] }
```

- `conversation_ids` must be non-empty and ≤ 600 (returns 400 otherwise — note: this is a manual check in the handler, *not* Pydantic, so it bypasses the verbose 422 echo handler).
- IDs not found in the DB are silently absent from the response (no nulls, no errors).
- Items are inlined per order, sorted by `id` ascending (insertion order); orders are sorted by `created_at` descending.
- Single SQL query with `selectinload(Order.items)` — do not refactor into per-order item lookups.

Example (auth off):

```bash
curl -X POST http://localhost:8000/orders/by-conversations \
  -H "Content-Type: application/json" \
  -d '{"conversation_ids":["conv_test1","conv_missing"]}'
```

Example (auth on, `WEBHOOK_API_TOKEN=s3cret`):

```bash
curl -X POST https://webhook.your-domain.com/orders/by-conversations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer s3cret" \
  -d '{"conversation_ids":["conv_test1"]}'
```

## Conventions

- Code comments and log messages are in Turkish (the product domain is Turkish pharmacies). Match that style when editing existing files; new code can be English unless it sits next to Turkish text.
- Async everywhere on the app side: `AsyncSession`, `await session.execute(...)`, `async def` route handlers. Don't introduce sync SQLAlchemy calls.
- The endpoint is currently unauthenticated by design (see README "Sonra Eklenecekler"). Don't add auth without being asked.
