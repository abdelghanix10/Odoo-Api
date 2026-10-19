# Part of La Madeleine.
import time
import uuid
from datetime import datetime
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import ValidationError, UserError, AccessError
from .pos_api_base import PosApiBase, _json_body
from odoo.addons.lm_pos_api.models.pos_api_common import has_field, iso_utc, request_id

def _valid_uuid(value):
    try: uuid.UUID(str(value)); return True
    except Exception: return False

class PosApiOrders(PosApiBase):
    def _resolve_session(self, env, device, body):
        Session = env["pos.session"]
        sid = body.get("session_id")
        if sid:
            try: sess = Session.browse(int(sid))
            except Exception: return None, ("SESSION_NOT_FOUND", "Invalid session id.")
            if not sess.exists(): return None, ("SESSION_NOT_FOUND", "POS session not found.")
        else:
            sess = Session.search([("config_id", "=", device.pos_config_id.id), ("state", "=", "opened")], limit=1, order="id desc")
        if not sess: return None, ("SESSION_NOT_FOUND", "No open POS session.")
        if sess.config_id.id != device.pos_config_id.id: return None, ("SESSION_NOT_FOUND", "Session belongs to another POS config.")
        return sess, None

    def _serialize_order(self, order):
        return {"odoo_id": order.id, "name": order.name, "uuid": order.uuid, "state": order.state, "session_id": order.session_id.id, "amount_total": order.amount_total, "amount_tax": order.amount_tax, "amount_paid": order.amount_paid, "amount_return": order.amount_return, "date_order": iso_utc(order.date_order)}

    def _line_tax_ids(self, env, product, requested, fiscal_position):
        allowed = product.taxes_id.filtered_domain(env["account.tax"]._check_company_domain(env.company))
        mapped = fiscal_position.map_tax(allowed) if fiscal_position else allowed
        requested_ids = [int(x) for x in (requested or [])]
        if requested_ids and not set(requested_ids).issubset(set(mapped.ids)):
            raise ValidationError("Invalid tax ids for product/fiscal position.")
        return mapped.ids

    def _build_ui_order(self, env, device, sess, body):
        cfg = sess.config_id
        pricelist = cfg.pricelist_id
        fiscal_position = False
        if body.get("fiscal_position_id"):
            fiscal_position = env["account.fiscal.position"].browse(int(body["fiscal_position_id"]))
            if not fiscal_position.exists() or fiscal_position.company_id not in (False, device.company_id):
                raise ValidationError("Invalid fiscal position.")
        if not fiscal_position:
            fiscal_position = cfg.default_fiscal_position_id
        Product = env["product.product"]
        line_cmds, total_incl, total_excl = [], 0.0, 0.0
        for line in body.get("lines") or []:
            product = Product.browse(int(line.get("product_id", 0)))
            if not product.exists() or not product.active or not product.sale_ok or not product.product_tmpl_id.available_in_pos:
                raise ValidationError("Product is not available in this POS.")
            qty = float(line.get("quantity", 0) or 0)
            discount = float(line.get("discount", 0) or 0)
            if qty <= 0 or discount < 0 or discount > 100:
                raise ValidationError("Invalid quantity or discount.")
            price_unit = float(line.get("unit_price", 0) if line.get("unit_price") is not None else pricelist._get_product_price(product, qty))
            taxes = self._line_tax_ids(env, product, line.get("tax_ids"), fiscal_position)
            tax_records = env["account.tax"].browse(taxes)
            computed = tax_records.compute_all(price_unit * (1 - discount / 100.0), sess.currency_id, qty, product=product) if tax_records else {"total_excluded": price_unit * qty, "total_included": price_unit * qty}
            subtotal, subtotal_incl = computed["total_excluded"], computed["total_included"]
            total_excl += subtotal; total_incl += subtotal_incl
            vals = {"uuid": str(uuid.uuid4()), "name": product.display_name or product.name, "product_id": product.id, "qty": qty, "price_unit": price_unit, "discount": discount, "price_subtotal": subtotal, "price_subtotal_incl": subtotal_incl, "tax_ids": [(6, 0, taxes)], "pack_lot_ids": []}
            for key in ("note", "customer_note", "price_type", "full_product_name"):
                if line.get(key) is not None: vals[key] = str(line[key])[:500]
            line_cmds.append([0, 0, vals])
        if not line_cmds:
            raise ValidationError("Order must contain at least one line.")
        payment_cmds = []
        allowed_pm = set(cfg.payment_method_ids.ids)
        paid = 0.0
        for payment in body.get("payments") or []:
            pm = env["pos.payment.method"].browse(int(payment.get("payment_method_id", 0)))
            amount = float(payment.get("amount", 0) or 0)
            if not pm.exists() or pm.id not in allowed_pm or amount <= 0:
                raise ValidationError("Invalid payment method or amount.")
            paid += amount
            payment_cmds.append([0, 0, {"amount": amount, "name": str(payment.get("name") or "POS Payment")[:128], "payment_method_id": pm.id}])
        if not payment_cmds or paid + sess.currency_id.rounding < total_incl:
            raise ValidationError("Order is not fully paid.")
        return {"state": "paid", "company_id": device.company_id.id, "amount_paid": paid, "amount_return": max(0.0, paid-total_incl), "amount_tax": total_incl-total_excl, "amount_total": total_incl, "date_order": fields.Datetime.now(), "fiscal_position_id": fiscal_position.id if fiscal_position else False, "pricelist_id": pricelist.id, "name": "Order %s" % body["uuid"], "last_order_preparation_change": "{}", "lines": line_cmds, "partner_id": int(body["partner_id"]) if body.get("partner_id") else False, "session_id": sess.id, "payment_ids": payment_cmds, "uuid": body["uuid"], "user_id": device.user_id.id, "to_invoice": bool(body.get("to_invoice", False))}

    @http.route("/api/v1/pos/orders", type="http", auth="none", methods=["POST"], csrf=False)
    def pos_create_order(self):
        req_id, t0 = request_id(), time.time()
        device, err_resp = self._auth_device(req_id)
        if err_resp: return err_resp
        body, perr = _json_body()
        if perr: return self._fail("INVALID_REQUEST", "Invalid JSON body.", 413 if perr == "PAYLOAD_TOO_LARGE" else 400, req_id=req_id)
        order_uuid = str(body.get("uuid") or "").strip()
        if not _valid_uuid(order_uuid): return self._fail("INVALID_REQUEST", "uuid must be a valid UUID.", 400, req_id=req_id)
        try:
            env = self._env_for(device)
            Order = env["pos.order"]
            existing = Order.search([("uuid", "=", order_uuid)], limit=1)
            if existing:
                return self._ok({"created": False, "duplicate": True, "order": self._serialize_order(existing)}, req_id=req_id)
            sess, serr = self._resolve_session(env, device, body)
            if serr: return self._fail(serr[0], serr[1], 404, req_id=req_id)
            order_data = self._build_ui_order(env, device, sess, body)
            result = Order.sync_from_ui([order_data])
            ids = [x["id"] for x in result.get("pos.order", [])]
            order = Order.browse(ids[0]).exists() if ids else False
            if not order: raise UserError("Odoo did not return the created order.")
            self._log(req_id, device, "orders.create", t0, True)
            return self._ok({"created": True, "duplicate": False, "order": self._serialize_order(order)}, status=201, req_id=req_id)
        except (ValidationError, UserError, AccessError) as e:
            self._log(req_id, device, "orders.create", t0, False)
            return self._fail("ODOO_VALIDATION_ERROR", str(e)[:500], 422, req_id=req_id)
        except Exception:
            self._log(req_id, device, "orders.create", t0, False)
            return self._fail("INTERNAL_ERROR", "Unable to create order.", 500, retryable=True, req_id=req_id)
