# Part of La Madeleine.
import time
from odoo import http
from .pos_api_base import PosApiBase
from odoo.addons.lm_pos_api.models.pos_api_common import request_id

class PosApiMisc(PosApiBase):
    @http.route("/api/v1/pos/health", type="http", auth="none", methods=["GET"], csrf=False)
    def pos_health(self):
        req_id, t0 = request_id(), time.time(); device, err_resp = self._auth_device(req_id)
        if err_resp: return err_resp
        self._log(req_id, device, "health", t0, True)
        return self._ok({"status": "ok", "device": device.name}, req_id=req_id)

    @http.route("/api/v1/openapi.json", type="http", auth="none", methods=["GET"], csrf=False)
    def pos_openapi(self):
        spec = {"openapi":"3.0.3","info":{"title":"La Madeleine Windows POS API","version":"1.0.0"},"servers":[{"url":"/"}],"security":[{"bearerAuth":[]}],"paths":{
            "/api/v1/pos/auth":{"post":{"security":[],"summary":"Authenticate POS device"}},
            "/api/v1/pos/health":{"get":{"summary":"Authenticated health check"}},
            "/api/v1/pos/bootstrap":{"get":{"summary":"Full master-data bootstrap"}},
            "/api/v1/pos/sync":{"get":{"summary":"Incremental master-data sync"}},
            "/api/v1/pos/orders":{"post":{"summary":"Create/idempotently sync a native Odoo POS order"}},
            "/api/v1/pos/sessions/open":{"post":{"summary":"Open POS session"}},
            "/api/v1/pos/sessions/current":{"get":{"summary":"Get current POS session"}},
            "/api/v1/pos/sessions/close":{"post":{"summary":"Close POS session using Odoo UI closing workflow"}},
            "/api/v1/pos/cash":{"post":{"summary":"Cash in/out using Odoo POS cash workflow"}}},
            "components":{"securitySchemes":{"bearerAuth":{"type":"http","scheme":"bearer"}}}}
        return self._ok(spec, req_id=request_id())
