# Part of La Madeleine.
import time
from odoo import http
from odoo.http import request
from .pos_api_base import PosApiBase
from odoo.addons.lm_pos_api.models.pos_api_common import has_field, iso_utc, parse_since, request_id, serialize_category, serialize_tax, serialize_uom, utcnow
from odoo.addons.lm_pos_api.models.pos_api_catalog import serialize_product

def _paginate_params():
    args = request.httprequest.args
    def integer(key, default, lo, hi):
        try: value = int(args.get(key, default))
        except Exception: value = default
        return max(lo, min(hi, value))
    return integer("limit", 500, 1, 2000), integer("offset", 0, 0, 10**9)

def _pos_category_model(env):
    return "pos.category" if "pos.category" in env else "product.category"

def _payment_type(pm):
    if has_field(pm, "type") and pm.type in ("cash", "bank", "pay_later"):
        return pm.type
    if has_field(pm, "is_cash_count") and pm.is_cash_count:
        return "cash"
    return "bank"

class PosApiCatalogCtrl(PosApiBase):
    def _pricelist(self, cfg):
        if has_field(cfg, "pricelist_id") and cfg.pricelist_id:
            return cfg.pricelist_id
        return cfg.available_pricelist_ids[:1] if has_field(cfg, "available_pricelist_ids") else False

    def _product_domain(self, env, cfg, company_id):
        Product = env["product.product"]
        domain = [("sale_ok", "=", True), ("active", "=", True)]
        if has_field(Product, "company_id"):
            domain += ["|", ("company_id", "=", False), ("company_id", "=", company_id)]
        Template = env["product.template"]
        if has_field(Template, "available_in_pos"):
            domain.append(("product_tmpl_id.available_in_pos", "=", True))
        return domain

    def _serialize_pricelist(self, env, pl):
        Item = env["product.pricelist.item"]
        rows = []
        for it in Item.search([("pricelist_id", "=", pl.id)], order="id"):
            row = {"id": it.id}
            for f in ("product_tmpl_id", "product_id", "categ_id", "compute_price", "fixed_price", "percent_price", "price_discount", "price_surcharge", "price_round", "min_quantity", "base", "base_pricelist_id", "date_start", "date_end"):
                if has_field(it, f):
                    v = it[f]
                    row[f] = v.id if f.endswith("_id") and v else (iso_utc(v) if f in ("date_start", "date_end") else v)
            rows.append(row)
        return {"id": pl.id, "name": pl.name, "currency_id": pl.currency_id.id, "items": rows}

    def _bootstrap_payload(self, env, device, limit, offset, include_stock=False):
        cfg = self._device_config(env, device)
        if not cfg:
            return None
        company = env["res.company"].browse(device.company_id.id)
        pricelist = self._pricelist(cfg)
        Product = env["product.product"]
        domain = self._product_domain(env, cfg, company.id)
        total = Product.search_count(domain)
        products = Product.search(domain, limit=limit, offset=offset, order="write_date desc, id desc")
        cat_model = _pos_category_model(env)
        Cat = env[cat_model]
        cats = Cat.search([], limit=5000, order="sequence,id")
        Tax = env["account.tax"]
        taxes = Tax.search([("company_id", "in", [False, company.id])] if has_field(Tax, "company_id") else [])
        uoms = env["uom.uom"].search([], limit=500)
        PM = env["pos.payment.method"]
        allowed_ids = set(cfg.payment_method_ids.ids)
        methods = PM.browse(list(allowed_ids)) if allowed_ids else PM.browse()
        pricelists = []
        pls = cfg.available_pricelist_ids if has_field(cfg, "available_pricelist_ids") else pricelist
        for pl in pls:
            pricelists.append(self._serialize_pricelist(env, pl))
        return ({
            "company": {"id": company.id, "name": company.name, "currency_id": company.currency_id.id},
            "currency": {"id": company.currency_id.id, "name": company.currency_id.name, "symbol": company.currency_id.symbol},
            "pos_config": {"id": cfg.id, "name": cfg.name, "currency_id": cfg.currency_id.id, "company_id": company.id},
            "categories": [serialize_category(c, cat_model) for c in cats],
            "products": [serialize_product(p, pricelist, include_stock=include_stock) for p in products],
            "taxes": [serialize_tax(t) for t in taxes],
            "pricelists": pricelists,
            "active_pricelist_id": pricelist.id if pricelist else None,
            "payment_methods": [{"id": pm.id, "name": pm.name, "type": _payment_type(pm), "active": True, "journal_id": pm.journal_id.id if pm.journal_id else None} for pm in methods],
            "uoms": [serialize_uom(u) for u in uoms],
        }, {"pagination": {"limit": limit, "offset": offset, "total": total, "has_more": offset + limit < total}, "sync_timestamp": iso_utc(utcnow())})

    @http.route("/api/v1/pos/bootstrap", type="http", auth="none", methods=["GET"], csrf=False)
    def pos_bootstrap(self):
        req_id, t0 = request_id(), time.time()
        device, err_resp = self._auth_device(req_id)
        if err_resp: return err_resp
        limit, offset = _paginate_params()
        try:
            args = request.httprequest.args
        except Exception:
            args = {}
        include_stock = str(args.get("include_stock") or "").lower() in ("1", "true", "yes")
        try:
            env = self._env_for(device)
            payload = self._bootstrap_payload(env, device, limit, offset, include_stock=include_stock)
            if not payload: return self._fail("CONFIG_NOT_FOUND", "POS configuration not found.", 404, req_id=req_id)
            device.sudo().write({"last_sync_at": utcnow().replace(tzinfo=None)})
            self._log(req_id, device, "bootstrap", t0, True)
            return self._ok(payload[0], meta=payload[1], req_id=req_id)
        except Exception:
            self._log(req_id, device, "bootstrap", t0, False)
            return self._fail("SYNC_ERROR", "Unable to build bootstrap payload.", 500, retryable=True, req_id=req_id)

    def _changed(self, env, model_name, since, domain, serializer, limit=5000):
        Model = env[model_name]
        base = list(domain or [])
        changed = list(base)
        if since and has_field(Model, "write_date"):
            changed.append(("write_date", ">", since))
        recs = Model.search(changed, limit=limit, order="write_date asc,id asc")
        created, updated = [], []
        for rec in recs:
            if since and has_field(Model, "create_date") and rec.create_date and rec.create_date.replace(tzinfo=None) > since:
                created.append(serializer(rec))
            else:
                updated.append(serializer(rec))
        archived = []
        if has_field(Model, "active"):
            arch_base = [term for term in base if not (isinstance(term, tuple) and term[0] == "active")]
            arch_domain = arch_base + [("active", "=", False)]
            if since and has_field(Model, "write_date"):
                arch_domain.append(("write_date", ">", since))
            ctx = dict(env.context)
            ctx["active_test"] = False
            arch_env = env(context=ctx)
            for rec in arch_env[Model._name].search(arch_domain, limit=limit, order="write_date asc,id asc"):
                archived.append({"id": rec.id, "write_date": iso_utc(rec.write_date)})
        return {"created": created, "updated": updated, "deleted": archived}

    @http.route("/api/v1/pos/sync", type="http", auth="none", methods=["GET"], csrf=False)
    def pos_sync(self):
        req_id, t0 = request_id(), time.time()
        device, err_resp = self._auth_device(req_id)
        if err_resp: return err_resp
        since = parse_since(request.httprequest.args.get("since"))
        if request.httprequest.args.get("since") and not since:
            return self._fail("INVALID_REQUEST", "Invalid since timestamp.", 400, req_id=req_id)
        try:
            env = self._env_for(device)
            cfg = self._device_config(env, device)
            company_id = device.company_id.id
            pricelist = self._pricelist(cfg)
            product_domain = self._product_domain(env, cfg, company_id)
            cat_model = _pos_category_model(env)
            data = {
                "products": self._changed(env, "product.product", since, product_domain, lambda r: serialize_product(r, pricelist)),
                "categories": self._changed(env, cat_model, since, [], lambda r: serialize_category(r, cat_model)),
                "taxes": self._changed(env, "account.tax", since, [("company_id", "in", [False, company_id])] if has_field(env["account.tax"], "company_id") else [], serialize_tax),
                "uoms": self._changed(env, "uom.uom", since, [], serialize_uom),
            }
            device.sudo().write({"last_sync_at": utcnow().replace(tzinfo=None)})
            self._log(req_id, device, "sync", t0, True)
            return self._ok(data, meta={"since": request.httprequest.args.get("since"), "sync_timestamp": iso_utc(utcnow())}, req_id=req_id)
        except Exception:
            self._log(req_id, device, "sync", t0, False)
            return self._fail("SYNC_ERROR", "Synchronization failed.", 500, retryable=True, req_id=req_id)

    def _pricelist(self, cfg):
        if has_field(cfg, "pricelist_id") and cfg.pricelist_id: return cfg.pricelist_id
        return cfg.available_pricelist_ids[:1] if has_field(cfg, "available_pricelist_ids") else False
