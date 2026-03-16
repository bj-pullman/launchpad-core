# profiles.py

# Determine information before uploading

PROFILES = {
    "Acer Spin 311": {
        "display_name": "Acer Spin 311",
        "model_id": 57,
        "status_id": 5,
        "location_id": 47,
        "supplier_id": 2,
        "depreciation_id": 1,

        "purchase_cost": 289.00,
        "purchase_date": "2026-02-26",
        "order_number": "PO-123456",
        "warranty_months": 36,

        # If you use custom fields (recommended for EOL, PO, etc.)
        "custom_fields": {
            # Example keys – these MUST match your Snipe custom field DB field names
            # "_snipeit_po_number_12": "PO-123456",
            # "_snipeit_eol_date_14": "2029-06-30",
        },

        "notes_prefix": "FY26 Chromebook intake",
    }
}