# Eczane Sipariş Webhook

ElevenLabs voice agent'ından gelen siparişleri PostgreSQL'e yazan FastAPI webhook server'ı.

## Mimari

```
ElevenLabs Agent (Webhook Tool)
        │  HTTPS POST
        ▼
[Traefik]  ── SSL termination + routing (label-based)
        │  HTTP :8000 (internal docker network)
        ▼
[FastAPI app]  ──►  [PostgreSQL 16]
```

## Veri Modeli

- **batches** — ElevenLabs batch call kampanyaları (`batch_id` unique)
- **orders** — her konuşma bir sipariş (`conversation_id` unique, `recipient_number`, `raw_payload` JSONB olarak)
- **order_items** — siparişteki ilaç + miktar satırları

Foreign key zinciri: `order_items.order_id → orders.id → batches.id`

## Kurulum (VPS)

### Ön koşul: Traefik çalışıyor olmalı

Traefik'in zaten kurulu olduğunu ve bir external Docker network'üne bağlı olduğunu varsayıyoruz. Network adını öğren:

```bash
docker network ls | grep traefik
```

Tipik isimler: `traefik`, `proxy`, `traefik_proxy`, `web`. Bu ismi `.env`'e yazacağız.

### Deploy

```bash
cd order-webhook
cp .env.example .env
nano .env       # POSTGRES_PASSWORD, DOMAIN, TRAEFIK_NETWORK vs. düzenle
docker compose up -d --build
docker compose logs -f app
```

İlk açılışta Postgres `db/init.sql`'i otomatik çalıştırır, tablolar hazır olur. Traefik labels'ı görür, Let's Encrypt sertifikasını alır ve `https://<DOMAIN>` adresine yönlendirmeye başlar.

### `.env` Değişkenleri

| Değişken | Örnek | Açıklama |
|----------|-------|----------|
| `POSTGRES_PASSWORD` | `s3cret...` | DB parolası — mutlaka değiştir |
| `DOMAIN` | `webhook.example.com` | Webhook'un yayınlanacağı domain |
| `TRAEFIK_NETWORK` | `traefik` | Traefik'in bağlı olduğu external network'ün Docker adı |
| `TRAEFIK_ENTRYPOINT` | `websecure` | Traefik HTTPS entrypoint adı |
| `TRAEFIK_CERTRESOLVER` | `letsencrypt` | Traefik cert resolver adı |

> Entrypoint ve certresolver isimleri Traefik static config'inde (genelde `traefik.yml`) tanımlıdır. Farklı isimlendirmişsen (`https`, `myresolver` vs.) buradan eşle.

### DNS

Deploy'dan önce `<DOMAIN>` için A kaydı VPS IP'sine yönlendirilmiş olmalı, yoksa Let's Encrypt challenge başarısız olur.

## Webhook Endpoint

### `POST /webhook/order`

ElevenLabs agent tool'undan beklenen payload:

```json
{
  "batch_id": "batch_abc123",
  "conversation_id": "conv_xyz789",
  "recipient_number": "+905551234567",
  "items": [
    { "product": "Aspirin 100mg", "quantity": 5 },
    { "product": "Parol", "quantity": 10 }
  ]
}
```

**Davranış:**
- Batch yoksa otomatik oluşturulur.
- Aynı `conversation_id` ile ikinci kez gelirse tekrar yazmaz, mevcut kaydı `status: "duplicate"` ile döner (idempotent).
- Tüm payload `orders.raw_payload` JSONB kolonuna kaydedilir (debug için).

**Test:**

```bash
curl -X POST https://webhook.your-domain.com/webhook/order \
  -H "Content-Type: application/json" \
  -d '{
    "batch_id": "batch_test1",
    "conversation_id": "conv_test1",
    "recipient_number": "+905551234567",
    "items": [
      {"product": "Aspirin", "quantity": 3},
      {"product": "Parol",   "quantity": 5}
    ]
  }'
```

### `GET /health`

DB bağlantı kontrolü. `200 {"status":"ok","db":"ok"}`.

### `GET /docs`

FastAPI'nin otomatik Swagger UI'ı.

## ElevenLabs Agent Konfigürasyonu

Agent'ta **Webhook Tool** (server tool) tanımla:
- **URL:** `https://<DOMAIN>/webhook/order`
- **Method:** `POST`
- **Body parameters:**
  - `batch_id` — `{{system__batch_call__batch_id}}` (veya batch dynamic variable)
  - `conversation_id` — `{{system__conversation_id}}`
  - `recipient_number` — `{{system__caller_id}}` ya da batch'teki recipient
  - `items` — agent'ın topladığı sipariş listesi (array of object)

> ElevenLabs'taki sistem değişkeni isimleri zamanla değişebiliyor — agent UI'ındaki "Insert variable" listesinden doğrula.

## Veri Sorgulama

Tüm siparişleri ürün satırlarıyla birlikte:

```sql
SELECT * FROM v_orders_full;
```

Bir batch'in siparişleri:

```sql
SELECT * FROM v_orders_full WHERE batch_id = 'batch_abc123';
```

Bir ürünün toplam sipariş miktarı:

```sql
SELECT product_name, SUM(quantity) AS total
FROM order_items
GROUP BY product_name
ORDER BY total DESC;
```

DB'ye girmek:

```bash
docker compose exec db psql -U orders -d orders
```

## Sorun Giderme — Traefik

**404 dönüyor:**
- `docker compose logs app` → app çalışıyor mu?
- `docker network inspect <TRAEFIK_NETWORK>` → app container listede var mı?
- Traefik dashboard'da router görünüyor mu? Rule doğru domain mi?

**SSL sertifikası alınmadı:**
- DNS A kaydı VPS IP'sine işaret ediyor mu? (`dig <DOMAIN>`)
- Traefik logs: `docker logs <traefik-container>` → ACME challenge hataları
- Cert resolver adı `.env`'deki `TRAEFIK_CERTRESOLVER` ile Traefik static config'i eşleşiyor mu?

**"network ... declared as external, but could not be found":**
- `TRAEFIK_NETWORK` adı yanlış. `docker network ls` ile doğrula.

## Sonra Eklenecekler (şimdilik kapsam dışı)

- Auth (HMAC signature veya bearer token) — şu an açık endpoint
- Rate limiting (Traefik middleware ile label üzerinden eklenebilir)
- Backup cronjob (`pg_dump`)
- Alembic migrations (schema değişirse)
