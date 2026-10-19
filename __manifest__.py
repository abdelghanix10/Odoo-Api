{
    "name": "lm_pos_api",
    "version": "19.0.3.0.0",
    "summary": "Native Windows POS API for Odoo 19 Community",
    "description": "Secure versioned API for an offline-first C#/.NET POS using native Odoo POS workflows.",
    "author": "La Madeleine",
    "category": "Point of Sale",
    "license": "LGPL-3",
    "depends": ["base", "point_of_sale", "product", "account"],
    "data": ["security/security.xml", "security/ir.model.access.csv", "views/pos_device_views.xml"],
    "installable": True,
    "application": False,
    "auto_install": False
}
