# OminiFlow for Odoo 19

HTTP connector between **Odoo 19** and the existing **OminiFlow PHP** backend.

This addon does not rebuild OminiFlow. It does not write to the OminiFlow database. It calls the public REST APIs that already exist in the PHP application.

```
Odoo 19  →  ominiflow_odoo  →  HTTPS REST  →  OminiFlow PHP  →  existing channels / catalog
```

## Features

Supported against real OminiFlow endpoints:

- Connection configuration (URL + `OMINI_` API key, stored in Odoo)
- **Test Connection** via `GET /api/wpbox/me`
- Product catalog pull (and optional push) via `/api/wpbox/ecommerce/products`
- Customer sync from WhatsApp contacts via `/api/wpbox/getContacts` and `/api/wpbox/makeContact`
- Idempotent matching: OminiFlow id, then SKU (products) or phone (contacts)
- Sync logs with success / failed filters
- Hourly scheduled sync (can be disabled)
- Inbound Developer Portal webhooks with HMAC-SHA256 verification

Not implemented, because OminiFlow does not publish those APIs:

- Sales order synchronization (`sale.order`)
- Warehouse inventory moves (`stock.quant` / stock pickings)

Catalog `stock_quantity` is stored on the Odoo product as **OminiFlow stock quantity**. Odoo warehouse on-hand qty is never written directly.

## Requirements

- Odoo **19.0**
- Python used by that Odoo install (`requests` is already bundled)
- Reachable OminiFlow URL
- Developer Portal API key starting with `OMINI_`

## Odoo version

Module version: `19.0.1.0.0`

## Installation

1. Copy the `ominiflow_odoo` folder into an Odoo 19 addons directory.
2. Add that directory to `addons_path` in `odoo.conf` if needed.
3. Restart Odoo.
4. Enable developer mode → Apps → Update Apps List.
5. Install **OminiFlow**.

Example:

```bash
odoo-bin -c odoo.conf -d YOUR_DATABASE -i ominiflow_odoo --stop-after-init
```

Do **not** put this folder inside the OminiFlow PHP project. It is an Odoo addon only.

## Configuration

1. In OminiFlow Developer Portal, create an API key (`OMINI_…`). Copy it immediately; it is shown once.
2. In Odoo: **OminiFlow → Connections → New**.
3. Set:
   - **API Base URL**: origin only, e.g. `https://whatsapp.ominiflow.com`
   - **API Key**: the `OMINI_` key
4. Click **Test Connection**. Connected is set only after a successful HTTP call to `/api/wpbox/me`.

Optional: paste the Developer Portal webhook signing secret, then register this Odoo URL in the portal:

```
https://YOUR_ODOO/ominiflow/webhook/<connection_id>
```

## OminiFlow API configuration

Auth header:

```http
Authorization: Bearer OMINI_xxxxxxxx
Accept: application/json
```

| Method | Path | Used for |
|---|---|---|
| GET | `/api/wpbox/me` | Connection test |
| GET | `/api/wpbox/ecommerce/products?page=&per_page=` | Product pull (Laravel pagination) |
| POST | `/api/wpbox/ecommerce/products` | Product push / SKU upsert |
| PUT/PATCH | `/api/wpbox/ecommerce/products/{id}` | Product update |
| GET | `/api/wpbox/getContacts` | Customer pull (full list, no pagination in PHP) |
| POST | `/api/wpbox/makeContact` | Customer push (`phone` required) |
| GET | `/api/wpbox/getSingleContact` | Lookup by `contact_id` or `phone` |

Rate limit: 60 requests/minute per key. HTTP 429 includes `Retry-After`.

Missing (not called by this module):

- `GET /api/wpbox/ecommerce/orders`
- warehouse inventory endpoint

## Sync behavior

- **Products**: bind `ominiflow_id` first, else match `default_code` (SKU). Name-only matching is never used.
- **Customers**: bind id first, else normalized phone, else email. Existing street/VAT/etc. are not overwritten.
- Repeated sync does not create duplicates.
- Per-row failures are logged; remaining rows continue.
- Orders / inventory actions stay disabled until PHP publishes APIs.

## Webhooks

OminiFlow signs the **raw body** with HMAC-SHA256:

```
X-Ominiflow-Signature: sha256=<hex>
X-Ominiflow-Event: message.received
```

Events are WhatsApp lifecycle events (`message.received`, `message.delivered`, `message.read`, `message.failed`, `button.click`, `flow.submit`, `template.status`). They are verified, de-duplicated by `evt_` id, and logged. They do not create products or orders.

Unsigned or invalid signatures return HTTP 401.

## Cron

- OminiFlow: Sync Products — every 60 minutes
- OminiFlow: Sync Customers — every 60 minutes

Each job only processes **active** connections with the matching sync flag. Exceptions are caught so the Odoo worker does not crash. Disable globally under **OminiFlow → Configuration → Settings**.

## Security

- API keys and webhook secrets use Odoo password fields and are hidden from list views.
- Only **OminiFlow / Administrator** can read or write credentials.
- Keys are never written to logs or user-facing exceptions.
- Company record rules apply to connections, logs, and bindings.
- Public webhook routes do not accept unsigned destructive work.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Connection failed / invalid token | Key must be `OMINI_…` from Developer Portal, not a login password |
| Could not reach OminiFlow | URL scheme `https://`, host reachable from the Odoo server |
| Did not respond in time | Firewall, wrong host, or PHP app down |
| Rate limit exceeded | Wait for `Retry-After`; avoid overlapping crons |
| No products imported | Enable **Sync products**, then Sync Products; catalog must exist in OminiFlow |
| Orders menu shows a notice | Expected: no public orders API yet |

## Testing

External HTTP is mocked. Tests do not call production OminiFlow.

```bash
odoo-bin -c odoo.conf -d YOUR_DATABASE -i ominiflow_odoo --test-enable --stop-after-init --test-tags ominiflow
```

Live API testing still requires a real `OMINI_` key and a running Odoo 19 database. Until that is done, treat the connector as ready for install and mocked tests, not as certified against production.

## License

LGPL-3
