# Part of La Madeleine.
import time
from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError, UserError, AccessError
from .pos_api_base import PosApiBase, _json_body
from odoo.addons.lm_pos_api.models.pos_api_common import iso_utc, request_id

class PosApiSessions(PosApiBase):
    def _serialize(self, s):
        return {"id": s.id, "name": s.name, "state": s.state, "config_id": s.config_id.id, "user_id": s.user_id.id, "start_at": iso_utc(s.start_at), "stop_at": iso_utc(s.stop_at), "opening_cash": s.cash_register_balance_start, "theoretical_closing_cash": s.cash_register_balance_end, "counted_closing_cash": s.cash_register_balance_end_real, "difference": s.cash_register_difference, "order_count": s.order_count, "total_payments": s.total_payments_amount}

    def _get_session(self, env, device, body=None, allowed_states=("opening_control", "opened")):
        Session = env["pos.session"]
        sid = (body or {}).get("session_id")
        if sid:
            try:
                session = Session.browse(int(sid))
            except (TypeError, ValueError):
                return None
            if not session.exists() or session.config_id.id != device.pos_config_id.id:
                return None
            if session.state not in allowed_states:
                return None
            return session
        return Session.search([
            ("config_id", "=", device.pos_config_id.id),
            ("state", "in", allowed_states),
            ("rescue", "=", False),
        ], limit=1, order="id desc")

    @http.route("/api/v1/pos/sessions/open", type="http", auth="none", methods=["POST"], csrf=False)
    def open_session(self):
        req_id, t0 = request_id(), time.time()
        device, err_resp = self._auth_device(req_id)
        if err_resp: return err_resp
        body, perr = _json_body()
        if perr: return self._fail("INVALID_REQUEST", "Invalid JSON body.", 400, req_id=req_id)
        try:
            env = self._env_for(device); cfg = self._device_config(env, device)
            current = self._get_session(env, device, body)
            if current and current.state == "opened": return self._ok({"session": self._serialize(current), "reused": True}, req_id=req_id)
            if not current:
                result = cfg.open_ui()
                current = cfg.current_session_id
            if not current: raise UserError("Unable to create POS session.")
            opening_cash = float(body.get("opening_cash", 0) or 0)
            notes = str(body.get("opening_notes") or "")[:500]
            if current.state == "opening_control": current.set_opening_control(opening_cash, notes)
            self._log(req_id, device, "sessions.open", t0, True)
            return self._ok({"session": self._serialize(current), "reused": False}, status=201, req_id=req_id)
        except (ValidationError, UserError, AccessError) as e:
            return self._fail("ODOO_VALIDATION_ERROR", str(e)[:500], 422, req_id=req_id)
        except Exception:
            return self._fail("INTERNAL_ERROR", "Unable to open session.", 500, retryable=True, req_id=req_id)

    @http.route("/api/v1/pos/sessions/close", type="http", auth="none", methods=["POST"], csrf=False)
    def close_session(self):
        req_id, t0 = request_id(), time.time()
        device, err_resp = self._auth_device(req_id)
        if err_resp: return err_resp
        body, perr = _json_body()
        if perr: return self._fail("INVALID_REQUEST", "Invalid JSON body.", 400, req_id=req_id)
        try:
            env = self._env_for(device); session = self._get_session(env, device, body, allowed_states=("opened",))
            if not session: return self._fail("SESSION_NOT_FOUND", "No opened POS session.", 404, req_id=req_id)
            if body.get("closing_cash") is not None:
                result = session.post_closing_cash_details(float(body["closing_cash"]))
                if isinstance(result, dict) and result.get("successful") is False:
                    return self._fail("SESSION_CANNOT_CLOSE", result.get("message", "Unable to post closing cash."), 422, req_id=req_id)
            diffs = body.get("bank_payment_method_diffs") or []
            pairs = [(int(x[0]), float(x[1])) for x in diffs]
            result = session.close_session_from_ui(pairs)
            if isinstance(result, dict) and not result.get("successful", False):
                return self._fail("SESSION_CANNOT_CLOSE", result.get("message", "Unable to close session."), 422, details=result, req_id=req_id)
            self._log(req_id, device, "sessions.close", t0, True)
            return self._ok({"session": self._serialize(session), "result": result}, req_id=req_id)
        except (ValidationError, UserError, AccessError, ValueError) as e:
            return self._fail("ODOO_VALIDATION_ERROR", str(e)[:500], 422, req_id=req_id)
        except Exception:
            return self._fail("INTERNAL_ERROR", "Unable to close session.", 500, retryable=True, req_id=req_id)

    @http.route("/api/v1/pos/sessions/current", type="http", auth="none", methods=["GET"], csrf=False)
    def current_session(self):
        req_id = request_id(); device, err_resp = self._auth_device(req_id)
        if err_resp: return err_resp
        env = self._env_for(device); session = self._get_session(env, device, allowed_states=("opened",))
        if not session: return self._fail("SESSION_NOT_FOUND", "No opened POS session.", 404, req_id=req_id)
        return self._ok({"session": self._serialize(session)}, req_id=req_id)

    @http.route("/api/v1/pos/cash", type="http", auth="none", methods=["POST"], csrf=False)
    def cash_move(self):
        req_id = request_id(); device, err_resp = self._auth_device(req_id)
        if err_resp: return err_resp
        body, perr = _json_body()
        if perr: return self._fail("INVALID_REQUEST", "Invalid JSON body.", 400, req_id=req_id)
        try:
            kind = str(body.get("type") or "").lower(); amount = float(body.get("amount", 0) or 0); reason = str(body.get("reason") or "Cash move")[:200]
            if kind not in ("in", "out") or amount <= 0: return self._fail("INVALID_REQUEST", "type must be in/out and amount must be positive.", 400, req_id=req_id)
            env = self._env_for(device); session = self._get_session(env, device, body, allowed_states=("opened",))
            if not session: return self._fail("SESSION_NOT_FOUND", "No opened POS session.", 404, req_id=req_id)
            extras = {"translatedType": "Cash in" if kind == "in" else "Cash out"}
            session.try_cash_in_out(kind, amount, reason, False, extras)
            return self._ok({"session": self._serialize(session), "type": kind, "amount": amount, "reason": reason}, req_id=req_id)
        except (ValidationError, UserError, AccessError, ValueError) as e:
            return self._fail("ODOO_VALIDATION_ERROR", str(e)[:500], 422, req_id=req_id)
        except Exception:
            return self._fail("INTERNAL_ERROR", "Cash move failed.", 500, retryable=True, req_id=req_id)
