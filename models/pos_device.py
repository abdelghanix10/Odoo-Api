# Part of La Madeleine.
import hashlib
import hmac
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


def _generate_raw_token():
    return secrets.token_urlsafe(48)


def hash_token(raw):
    if not raw:
        return False
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PosDevice(models.Model):
    _name = "lm.pos.device"
    _description = "Windows POS Device"
    _order = "name"

    name = fields.Char(required=True)
    device_uuid = fields.Char(required=True, copy=False, index=True)
    api_token_hash = fields.Char(string="Token hash", readonly=True, copy=False, index=True)
    token_last4 = fields.Char(string="Token suffix", readonly=True, copy=False)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    user_id = fields.Many2one("res.users", string="POS User", required=True, ondelete="restrict")
    pos_config_id = fields.Many2one("pos.config", string="POS Config", required=True, ondelete="restrict")
    last_sync_at = fields.Datetime(readonly=True, copy=False)
    last_seen_at = fields.Datetime(readonly=True, copy=False)
    notes = fields.Text()
    last_raw_token = fields.Char(
        string="Last raw token (transient)", store=False, readonly=True,
        help="Holds the generated token only in memory right after create/regenerate. Never stored.")

    _sql_constraints = [
        ("device_uuid_unique", "UNIQUE(device_uuid)", "A device with this UUID already exists."),
        ("api_token_hash_unique", "UNIQUE(api_token_hash)", "The API token hash must be unique."),
    ]

    @api.constrains("pos_config_id", "company_id")
    def _check_config_company(self):
        for rec in self:
            if rec.pos_config_id and rec.company_id and rec.pos_config_id.company_id != rec.company_id:
                raise ValidationError(_("POS Config company must match device company."))

    @api.constrains("user_id", "company_id")
    def _check_user_company(self):
        for rec in self:
            if rec.user_id and rec.company_id and rec.company_id not in rec.user_id.company_ids:
                raise ValidationError(_("POS user must have access to the device company."))

    @api.model_create_multi
    def create(self, vals_list):
        cleaned = []
        raw_tokens = []
        for original in vals_list:
            vals = dict(original)
            raw = vals.pop("api_token_raw", None) or _generate_raw_token()
            vals["api_token_hash"] = hash_token(raw)
            vals["token_last4"] = raw[-4:]
            cleaned.append(vals)
            raw_tokens.append(raw)
        records = super().create(cleaned)
        for rec, raw in zip(records, raw_tokens):
            rec.last_raw_token = raw
        return records

    def _get_raw_token_once(self):
        self.ensure_one()
        return self.last_raw_token or None

    def action_regenerate_token(self):
        self.ensure_one()
        raw = _generate_raw_token()
        self.write({"api_token_hash": hash_token(raw), "token_last4": raw[-4:]})
        self.last_raw_token = raw
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("New token generated"),
                "message": _("Raw token (copy now, shown once): %s") % raw,
                "type": "warning",
                "sticky": True,
            },
        }

    def _verify_token(self, raw_token):
        self.ensure_one()
        if not raw_token or not self.api_token_hash:
            return False
        return hmac.compare_digest(hash_token(raw_token), self.api_token_hash)

    def _touch_seen(self):
        self.sudo().write({"last_seen_at": fields.Datetime.now()})
