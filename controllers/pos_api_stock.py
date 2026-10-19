# Part of La Madeleine.
"""GET /api/v1/pos/stock - ORM-computed stock for POS products."""
import time

from odoo import http
from odoo.http import request

from .pos_api_base import PosApiBase
from .pos_api_catalog_ctrl import PosApiCatalogCtrl
from odoo.addons.lm_pos_api.models.pos_api_common import (
    has_field, iso_utc, request_id, utcnow,
)
from odoo.addons.lm_pos_api.models.pos_api_catalog import product_stock


class PosApiStock(PosApiCatalogCtrl):

    @http.route("/api/v1/pos/stock", type="http", auth="none",
                methods=["GET"], csrf=False, cors="*")
    def pos_stock(self):
        req_id = request_id()
        t0 = time.time()
        device, err_resp = self._auth_device(req_id)
        if err_resp:
            self._log(req_id, None, "stock", t0, False)
            return err_resp
        try:
            args = request.httprequest.args
        except Exception:
            args = {}
        # Optional: ?product_ids=751,750&include_stock=1 (bootstrap flag too)
        ids = []
        try:
            raw_ids = (args.get("product_ids") or "").strip()
            if raw_ids:
                ids = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]
        except Exception:
            ids = []
        try:
            env = self._env_for(device)
            cfg = self._device_config(env, device)
            if not cfg:
                resp = self._fail("INVALID_REQUEST", "POS configuration not found.",
                                  status=404, req_id=req_id)
                self._log(req_id, device, "stock", t0, False)
                return resp
            Product = env["product.product"]
            domain = self._product_domain(env, cfg, device.company_id.id)
            if ids:
                domain += [("id", "in", ids[:500])]
            products = Product.search(domain, limit=2000, order="id")
            rows = []
            for p in products:
                stock = product_stock(p)
                rows.append({"product_id": p.id,
                             "name": p.display_name or p.name,
                             "default_code": p.default_code if has_field(p, "default_code") else None,
                             "stock": stock})
            meta = {"server_time": iso_utc(utcnow()),
                    "sync_timestamp": iso_utc(utcnow()),
                    "count": len(rows)}
            self._log(req_id, device, "stock", t0, True, extra="count=%s" % len(rows))
            return self._ok({"stock": rows}, meta=meta, req_id=req_id)
        except Exception:
            resp = self._fail("SYNC_ERROR", "Unable to read stock.",
                              status=500, retryable=True, req_id=req_id)
            self._log(req_id, device, "stock", t0, False)
            return resp
