# Part of La Madeleine.
import time
from odoo import http
from odoo.http import request
from .pos_api_base import PosApiBase, _json_body
from odoo.addons.lm_pos_api.models.pos_api_common import iso_utc, request_id, utcnow

class PosApiAuth(PosApiBase):
    @http.route("/api/v1/pos/auth", type="http", auth="none", methods=["POST"], csrf=False)
    def pos_auth(self):
        req_id, t0 = request_id(), time.time()
        body, perr = _json_body()
        if perr:
            return self._fail("INVALID_REQUEST", "Invalid JSON body.", 413 if perr == "PAYLOAD_TOO_LARGE" else 400, req_id=req_id)
        device_uuid = str(body.get("device_uuid") or "").strip()
        api_token = str(body.get("api_token") or "").strip()
        if not device_uuid or not api_token:
            return self._fail("INVALID_REQUEST", "device_uuid and api_token are required.", 400, req_id=req_id)
        dev, err_resp = self._auth_device(req_id, token=api_token, device_uuid=device_uuid, rate_limit=True)
        if err_resp:
            self._log(req_id, None, "auth", t0, False)
            return err_resp
        env = self._env_for(dev)
        cfg = self._device_config(env, dev)
        if not cfg:
            return self._fail("CONFIG_NOT_FOUND", "POS configuration not found.", 404, req_id=req_id)
        try:
            company = dev.company_id
            currency_id = company.currency_id.id if company and company.currency_id else None
            cfg_currency = cfg.currency_id.id if cfg.currency_id else None
            data = {
                "device": {"id": dev.id, "name": dev.name, "device_uuid": dev.device_uuid},
                "company": {"id": company.id if company else None,
                            "name": company.name if company else "",
                            "currency_id": currency_id},
                "pos_config": {"id": cfg.id, "name": cfg.name, "currency_id": cfg_currency},
                "server_time": iso_utc(utcnow()),
            }
        except Exception:
            return self._fail("INTERNAL_ERROR", "Unable to build auth response.", 500, retryable=True, req_id=req_id)
        self._log(req_id, dev, "auth", t0, True)
        return self._ok(data, req_id=req_id)
