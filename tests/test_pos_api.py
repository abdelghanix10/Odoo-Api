import uuid
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from odoo.addons.lm_pos_api.models.pos_device import hash_token

class TestLmPosApi(TransactionCase):
    def _make_device(self, name="POS-01"):
        company = self.env.company
        user = self.env["res.users"].create({"name": name + " user", "login": "lm_%s_%s" % (name.lower(), uuid.uuid4().hex[:6])})
        config = self.env["pos.config"].create({"name": name + " config", "company_id": company.id})
        raw = "tok-" + uuid.uuid4().hex
        dev = self.env["lm.pos.device"].create({"name": name, "device_uuid": str(uuid.uuid4()), "company_id": company.id, "user_id": user.id, "pos_config_id": config.id, "api_token_raw": raw})
        return dev, raw

    def test_token_is_hashed(self):
        dev, raw = self._make_device()
        self.assertEqual(dev.api_token_hash, hash_token(raw)); self.assertNotEqual(dev.api_token_hash, raw)

    def test_verify_token(self):
        dev, raw = self._make_device()
        self.assertTrue(dev._verify_token(raw)); self.assertFalse(dev._verify_token("wrong"))

    def test_uuid_unique(self):
        dev, _ = self._make_device()
        with self.assertRaises(Exception):
            self.env["lm.pos.device"].create({"name":"DUP","device_uuid":dev.device_uuid,"company_id":dev.company_id.id,"user_id":dev.user_id.id,"pos_config_id":dev.pos_config_id.id})

    def test_config_company_guard(self):
        dev, _ = self._make_device()
        other = self.env["res.company"].create({"name":"Other Co"})
        with self.assertRaises(ValidationError): dev.write({"company_id": other.id})

    def test_raw_token_is_not_a_model_field(self):
        dev, raw = self._make_device("POS-RAW")
        self.assertFalse("_raw_token_tmp" in dev._fields)
        self.assertTrue(dev._verify_token(raw))
        self.assertIn("last_raw_token", dev._fields)
