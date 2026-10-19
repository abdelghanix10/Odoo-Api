# Part of La Madeleine.
"""Shared helpers: envelopes, UTC time, auth, small ORM-safe serializers."""
import uuid
from datetime import datetime, timezone

from odoo import fields


API_VERSION = "1.0.0"


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_utc(value):
    """Return ISO8601 UTC '...Z' string for datetime/date/str or None."""
    if not value:
        return None
    if isinstance(value, str):
        return value
    try:
        dt = value
        if isinstance(value, datetime) and value.tzinfo is None:
            import pytz
            dt = pytz.utc.localize(value)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(value)


def request_id():
    return uuid.uuid4().hex[:16]


def ok(data=None, meta=None, req_id=None):
    meta = dict(meta or {})
    meta.setdefault("server_time", iso_utc(utcnow()))
    meta.setdefault("api_version", API_VERSION)
    if req_id:
        meta.setdefault("request_id", req_id)
    return {"success": True, "data": data if data is not None else {}, "meta": meta}


def err(code, message, status=400, retryable=False, details=None, req_id=None):
    payload = {
        "success": False,
        "error": {"code": code, "message": message, "retryable": bool(retryable)},
    }
    if details:
        payload["error"]["details"] = details
    payload["meta"] = {
        "server_time": iso_utc(utcnow()),
        "api_version": API_VERSION,
    }
    if req_id:
        payload["meta"]["request_id"] = req_id
    return payload, status


def parse_since(value):
    """Parse ISO8601 UTC input into naive UTC datetime for ORM domains."""
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def has_field(model, fname):
    try:
        return fname in model._fields
    except Exception:
        return False


def serialize_tax(tax):
    vals = {
        "id": tax.id,
        "name": tax.name,
        "active": bool(getattr(tax, "active", True)),
        "write_date": iso_utc(getattr(tax, "write_date", None)),
    }
    for fname in ("amount", "amount_type", "price_include",
                  "include_base_amount", "is_base_affected",
                  "company_id", "sequence"):
        if has_field(tax, fname):
            v = tax[fname]
            if fname == "company_id":
                vals["company_id"] = v.id if v else None
            else:
                vals[fname] = v
    children = getattr(tax, "children_tax_ids", None)
    try:
        vals["children_tax_ids"] = children.ids if children is not None else []
    except Exception:
        vals["children_tax_ids"] = []
    return vals


def serialize_uom(u):
    return {
        "id": u.id,
        "name": u.name,
        "factor": float(getattr(u, "factor", 1.0) or 1.0),
        "rounding": float(getattr(u, "rounding", 0.01) or 0.01),
    }


def serialize_category(cat, pos_model_name="pos.category"):
    vals = {
        "id": cat.id,
        "name": cat.name,
        "parent_id": cat.parent_id.id if cat.parent_id else None,
        "sequence": int(getattr(cat, "sequence", 0) or 0),
        "active": True,
        "write_date": iso_utc(getattr(cat, "write_date", None)),
    }
    if pos_model_name == "pos.category":
        if has_field(cat, "child_ids"):
            try:
                vals["child_ids"] = cat.child_ids.ids
            except Exception:
                vals["child_ids"] = []
        if has_field(cat, "has_image"):
            vals["has_image"] = bool(cat.has_image)
    else:
        if has_field(cat, "active"):
            vals["active"] = bool(cat.active)
        if has_field(cat, "parent_id"):
            vals["parent_id"] = cat.parent_id.id if cat.parent_id else None
    return vals
