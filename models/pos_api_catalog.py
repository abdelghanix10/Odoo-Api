from .pos_api_common import has_field, iso_utc

def product_price(product, pricelist=None, quantity=1.0):
    if pricelist:
        try:
            return float(pricelist._get_product_price(product, quantity))
        except Exception:
            pass
    for fname in ("lst_price", "list_price"):
        if has_field(product, fname):
            return float(product[fname] or 0.0)
    return 0.0

def product_stock(product):
    """ORM-computed stock. Returns {} if stock app fields are absent."""
    vals = {}
    for fname in ("qty_available", "virtual_available", "free_qty",
                  "incoming_qty", "outgoing_qty"):
        if has_field(product, fname):
            try:
                vals[fname] = float(product[fname] or 0.0)
            except Exception:
                vals[fname] = 0.0
    if has_field(product, "type"):
        try:
            vals["type"] = product.type
        except Exception:
            pass
    return vals

def serialize_product(p, pricelist=None, include_stock=False):
    tmpl = p.product_tmpl_id if has_field(p, "product_tmpl_id") else False
    categ_ids = tmpl.pos_categ_ids.ids if tmpl and has_field(tmpl, "pos_categ_ids") else []
    taxes = tmpl.taxes_id.ids if tmpl and has_field(tmpl, "taxes_id") else []
    vals = {"id": p.id, "name": p.display_name or p.name, "barcode": p.barcode if has_field(p,"barcode") else None, "default_code": p.default_code if has_field(p,"default_code") else None, "category_id": categ_ids[0] if categ_ids else None, "pos_categ_ids": categ_ids, "price": product_price(p, pricelist), "tax_ids": taxes, "active": bool(p.active), "write_date": iso_utc(p.write_date)}
    if tmpl:
        for f in ("available_in_pos", "to_weight"):
            if has_field(tmpl, f): vals[f] = bool(tmpl[f])
        if has_field(tmpl, "uom_id"): vals["uom_id"] = tmpl.uom_id.id if tmpl.uom_id else None
    if include_stock:
        vals["stock"] = product_stock(p)
    return vals
