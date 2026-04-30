# Eczane Sipariş Webhook

ElevenLabs voice agent'ından gelen siparişleri PostgreSQL'e yazan FastAPI webhook server'ı.

## Mimari

```
ElevenLabs Agent (Webhook Tool)
        │  HTTPS POST
        ▼
[Traefik]  ── SSL termination + routing (label-based, host network)
        │  HTTP 127.0.0.1:8000 (loopback)
        ▼
[FastAPI app]  ──►  [PostgreSQL 16]
```

## Veri Modeli

- **orders** — her ElevenLabs konuşması bir sipariş satırı. `conversation_id` UNIQUE, idempotency anahtarı. `recipient_number` + `raw_payload` (JSONB, debug için ham webhook gövdesi).
- **order_items** — sipariş satırları (ilaç adı + miktar). `order_id → orders.id ON DELETE CASCADE`, `quantity > 0`.
- **v_orders_full** — raporlama için flatten view (orders × order_items).

Batch yönetimi bu DB'de değil; UI ElevenLabs API'den `conversation_id` listesi alıp `POST /orders/by-conversations` ile join ediyor.

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
| `POSTGRES_USER` | `orders` | DB kullanıcı adı |
| `POSTGRES_PASSWORD` | `s3cret...` | DB parolası — mutlaka değiştir |
| `POSTGRES_DB` | `orders` | DB adı |
| `DOMAIN` | `webhook.example.com` | Webhook'un yayınlanacağı domain |
| `TRAEFIK_NETWORK` | `traefik` | Traefik'in bağlı olduğu external network adı (mevcut compose host-loopback kullandığı için referans olarak duruyor; networks bloğu eklersen kullanılır). |
| `TRAEFIK_ENTRYPOINT` | `websecure` | Traefik HTTPS entrypoint adı |
| `TRAEFIK_CERTRESOLVER` | `letsencrypt` | Traefik cert resolver adı |
| `WEBHOOK_API_TOKEN` | `(boş)` | Read endpoint'leri için bearer token. Boşsa auth kapalı; set edildiğinde `Authorization: Bearer <token>` zorunlu (sadece read endpoint'lerinde). |

> Entrypoint ve certresolver isimleri Traefik static config'inde (genelde `traefik.yml`) tanımlıdır. Farklı isimlendirmişsen (`https`, `myresolver` vs.) buradan eşle.

### DNS

Deploy'dan önce `<DOMAIN>` için A kaydı VPS IP'sine yönlendirilmiş olmalı, yoksa Let's Encrypt challenge başarısız olur.

## Webhook Endpoint

### `POST /webhook/order` (auth yok)

ElevenLabs agent tool'undan beklenen payload:

```json
{
  "conversation_id": "conv_xyz789",
  "recipient_number": "+905551234567",
  "items": [
    { "product": "Aspirin 100mg", "quantity": 5 },
    { "product": "Parol", "quantity": 10 }
  ]
}
```

**Davranış:**
- Aynı `conversation_id` ile ikinci kez gelirse tekrar yazmaz, mevcut kaydı `status: "duplicate"` ile döner (idempotent).
- Tüm payload `orders.raw_payload` JSONB kolonuna kaydedilir (debug için).
- 422 dönüşlerinde gelen ham gövde response'a `received_body` olarak eklenir — agent payload'ları sürüm sürüm değişebildiği için kasıtlı.

**Test:**

```bash
curl -X POST https://webhook.your-domain.com/webhook/order \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "conv_test1",
    "recipient_number": "+905551234567",
    "items": [
      {"product": "Aspirin", "quantity": 3},
      {"product": "Parol",   "quantity": 5}
    ]
  }'
```

### `POST /orders/by-conversations` (auth: `WEBHOOK_API_TOKEN` set ise zorunlu)

Bir batch'in `conversation_id`'lerini DB'deki siparişlerle eşleştirmek için bulk lookup. UI tarafında ElevenLabs API'den alınan listeyi bu endpoint ile join ediyoruz.

```json
{ "conversation_ids": ["conv_abc", "conv_xyz", "conv_123"] }
```

- Liste boş olamaz, en fazla 600 id (aşılırsa 400).
- DB'de bulunmayan id'ler response'tan sessizce düşer.
- Siparişler `created_at DESC`, item'lar order içinde `id ASC` sırasında döner.

```bash
curl -X POST https://webhook.your-domain.com/orders/by-conversations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WEBHOOK_API_TOKEN" \
  -d '{"conversation_ids":["conv_test1","conv_missing"]}'
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
  - `conversation_id` — `{{system__conversation_id}}`
  - `recipient_number` — `{{system__caller_id}}` ya da batch'teki recipient
  - `items` — agent'ın topladığı sipariş listesi (array of object: `{product, quantity}`)

> ElevenLabs'taki sistem değişkeni isimleri zamanla değişebiliyor — agent UI'ındaki "Insert variable" listesinden doğrula. `batch_id` payload'a eklenmez; batch eşlemesi UI tarafında yapılıyor.

## Veri Sorgulama

Tüm siparişleri ürün satırlarıyla birlikte:

```sql
SELECT * FROM v_orders_full;
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

Traefik host network mode'da çalıştığı varsayımıyla; app `127.0.0.1:8000` üzerine bind eder, Traefik label'daki `loadbalancer.server.url=http://127.0.0.1:8000` üzerinden ulaşır.

**404 dönüyor:**
- `docker compose logs app` → app çalışıyor mu?
- `curl -i http://127.0.0.1:8000/health` (VPS üzerinde) → app loopback'te erişilebilir mi?
- Traefik dashboard'da router görünüyor mu? Rule doğru domain mi?

**SSL sertifikası alınmadı:**
- DNS A kaydı VPS IP'sine işaret ediyor mu? (`dig <DOMAIN>`)
- Traefik logs: `docker logs <traefik-container>` → ACME challenge hataları
- Cert resolver adı `.env`'deki `TRAEFIK_CERTRESOLVER` ile Traefik static config'i eşleşiyor mu?

## Sonra Eklenecekler (şimdilik kapsam dışı)

- Webhook endpoint için auth (HMAC signature veya bearer) — şu an `POST /webhook/order` açık. Read endpoint'lerinde `WEBHOOK_API_TOKEN` zaten var.
- Rate limiting (Traefik middleware ile label üzerinden eklenebilir)
- Backup cronjob (`pg_dump`)
- Alembic migrations (schema değişirse)
