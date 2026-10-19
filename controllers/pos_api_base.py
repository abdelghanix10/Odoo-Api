# Part of La Madeleine.
import hashlib
import json
import logging
import time

from odoo import http
from odoo.http import request

from odoo.addons.lm_pos_api.models.pos_api_common import err, ok, request_id

_logger = logging.getLogger(__name__)
MAX_JSON_BYTES = 2 * 1024 * 1024
_RATE_BUCKET = {}
_RATE_LIMIT = 300
_RATE_WINDOW = 60


def _client_ip():
    try:
        return request.httprequest.remote_addr or "unknown"
    except Exception:
        return "unknown"


def _check_rate(key):
    now = time.time()
    bucket = [t for t in _RATE_BUCKET.get(key, []) if now - t < _RATE_WINDOW]
    if len(bucket) >= _RATE_LIMIT:
        _RATE_BUCKET[key] = bucket
        return False
    bucket.append(now)
    _RATE_BUCKET[key] = bucket
    return True


def _json_body():
    try:
        raw = request.httprequest.get_data() or b"{}"
        if len(raw) > MAX_JSON_BYTES:
            return None, "PAYLOAD_TOO_LARGE"
        if not raw.strip():
            return {}, None
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            return None, "INVALID_JSON"
        return value, None
    except Exception:
        return None, "INVALID_JSON"


def _bearer_token():
    auth = request.httprequest.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def _hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PosApiBase(http.Controller):
    def _json(self, payload, status=200, req_id=None):
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")]
        if req_id:
            headers.append(("X-Request-ID", req_id))
        return request.make_response(json.dumps(payload, separators=(",", ":"), default=str), headers=headers, status=status)

    def _fail(self, code, message, status=400, retryable=False, details=None, req_id=None):
        payload, status = err(code, message, status=status, retryable=retryable, details=details, req_id=req_id)
        return self._json(payload, status=status, req_id=req_id)

    def _ok(self, data=None, meta=None, status=200, req_id=None):
        return self._json(ok(data=data, meta=meta, req_id=req_id), status=status, req_id=req_id)

    def _log(self, req_id, device, endpoint, t0, success, extra=""):
        try:
            _logger.info("lm_pos_api endpoint=%s device=%s ok=%s ms=%s %s req=%s", endpoint, device.name if device else "-", success, int((time.time()-t0)*1000), extra, req_id)
        except Exception:
            pass

    def _auth_device(self, req_id, token=None, device_uuid=None, rate_limit=True):
        token = token or _bearer_token()
        if not token:
            return None, self._fail("INVALID_TOKEN", "Missing bearer token.", 401, req_id=req_id)
        Device = request.env["lm.pos.device"].sudo()
        ip = _client_ip()
        rate_key = "%s:%s" % (ip, device_uuid or "-")
        if rate_limit and not _check_rate(rate_key):
            return None, self._fail("RATE_LIMITED", "Too many requests, retry later.", 429, retryable=True, req_id=req_id)
        try:
            dev = Device.search([("api_token_hash", "=", _hash(token))], limit=1)
        except Exception:
            return None, self._fail("INVALID_TOKEN", "Invalid POS credentials.", 401, req_id=req_id)
        if not dev:
            return None, self._fail("INVALID_TOKEN", "Invalid POS credentials.", 401, req_id=req_id)
        try:
            valid = dev._verify_token(token)
        except Exception:
            valid = False
        if not valid:
            return None, self._fail("INVALID_TOKEN", "Invalid POS credentials.", 401, req_id=req_id)
        if device_uuid and dev.device_uuid != device_uuid:
            return None, self._fail("INVALID_TOKEN", "Device mismatch.", 401, req_id=req_id)
        try:
            user_active = bool(dev.user_id and dev.user_id.active)
        except Exception:
            user_active = False
        if not dev.active or not user_active:
            return None, self._fail("DEVICE_DISABLED", "POS device is disabled.", 403, req_id=req_id)
        try:
            dev._touch_seen()
        except Exception:
            pass
        return dev, None

    def _env_for(self, device):
        ctx = dict(request.env.context)
        ctx["allowed_company_ids"] = [device.company_id.id]
        return request.env(user=device.user_id.id, context=ctx)

    def _device_config(self, env, device):
        cfg = env["pos.config"].browse(device.pos_config_id.id)
        if not cfg.exists() or cfg.company_id.id != device.company_id.id:
            return None
        return cfg
