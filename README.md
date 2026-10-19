# lm_pos_api — Windows POS backend for Odoo 19 Community

Production-ready versioned API for a native C#/.NET/WPF POS with local SQLite.

## Verified Odoo 19 design
- Real `pos.order` ingestion through `pos.order.sync_from_ui()` (NOT `sale.order`)
- Native order lines with required `uuid` + `name`, company-scoped taxes
- Real `pos.session` open/close/cash via `open_ui`, `set_opening_control`,
  `post_closing_cash_details`, `close_session_from_ui`, `try_cash_in_out`
- ORM only, no SQL, no core modifications
- Bearer-token devices (`lm.pos.device`), SHA-256 hashed, company + POS config isolated
- UTC ISO8601 everywhere, `write_date` incremental sync + tombstones for archived records
- Compact paginated bootstrap for low-end POS hardware

## Install
1. Copy `lm_pos_api/` into your custom addons path
2. Restart Odoo, Update Apps List, Install `lm_pos_api`
3. Point of Sale → Windows POS API → POS Devices → create POS-01/POS-02/...
   - Set Company, POS Config, POS User
   - Copy the one-time raw token for the Windows client

## Endpoints (/api/v1)
- POST /api/v1/pos/auth
- GET /api/v1/pos/health (Bearer)
- GET /api/v1/pos/bootstrap?limit=500&offset=0 (Bearer)
- GET /api/v1/pos/sync?since=2026-10-13T18:00:00Z (Bearer)
- POST /api/v1/pos/orders (Bearer, idempotent by UUID)
- POST /api/v1/pos/sessions/open (Bearer)
- POST /api/v1/pos/sessions/close (Bearer)
- GET /api/v1/pos/sessions/current (Bearer)
- POST /api/v1/pos/cash (Bearer, type in/out)
- GET /api/v1/openapi.json

## Curl
curl -X POST http://localhost:8069/api/v1/pos/auth -H "Content-Type: application/json" -d "{\"device_uuid\":\"...\",\"api_token\":\"...\"}"
curl http://localhost:8069/api/v1/pos/bootstrap?limit=500 -H "Authorization: Bearer <token>"
curl "http://localhost:8069/api/v1/pos/sync?since=2026-10-13T18:00:00Z" -H "Authorization: Bearer <token>"

## .NET notes
- Store device_uuid + token once; send `Authorization: Bearer <token>` always
- First install: loop bootstrap with limit/offset until has_more=false, rebuild SQLite
- Hourly: GET /sync?since=<last sync_timestamp>, apply created/updated/deleted
- Orders: generate UUID v4 locally, POST once, retry safely on timeout (duplicate UUID returns existing order)
- UTC everywhere; convert to local time only for display

