"""
schema.py — Single source of truth for the six-table data model.

Every table here mirrors a real SAP ECC Retail structure. The `SAP_EQUIVALENT`
mapping is kept explicit so the README and dashboard can surface it, and so that
in an interview you can point to the exact SAP object each of our tables imitates.

IMPORTANT (honesty constraint): these are SAP-*pattern* tables built in pandas,
not extracts from a real SAP system. The mapping demonstrates understanding of
the structure, not hands-on SAP experience.
"""

# --- SAP equivalents, verified against SAP documentation ------------------
SAP_EQUIVALENT = {
    "article_master":   "MARA (general article data)",
    "article_site":     "MARC / MVKE (plant & sales-org data)",
    "listing":          "WLK1 (listing conditions / assortments)",
    "promotion_header": "WAKH (promotion header, IS-R)",
    "promotion_item":   "WAKP (promotion item)",
    "change_log":       "CDHDR / CDPOS (change documents)",
}

# --- Controlled vocabularies (used by the generator and the validators) ---

# Article structure types. Drives the hierarchy. Mirrors MARA-ATTYP.
ARTICLE_TYPES = ["single", "generic", "variant", "display", "prepack"]

# Convenience-retail merchandise hierarchy. Each category carries the traits
# that make its data-quality problems distinct (see notes per category).
MERCH_CATEGORIES = {
    "FUEL": {
        "sub": ["Unleaded 91", "Premium 95", "Premium 98", "Diesel"],
        "base_uom": "L",
        "tax_code": "GST",            # fuel is GST-applicable in AU
        "tobacco": False,
        "price_range": (1.60, 2.35),  # per litre, changes daily in reality
        "promotable": True,
    },
    "TOBACCO": {
        "sub": ["Cigarettes", "Rolling Tobacco", "Cigars"],
        "base_uom": "EA",
        "tax_code": "GST",
        "tobacco": True,              # triggers the floor-price rule
        "price_range": (35.00, 75.00),
        "promotable": False,          # tobacco is generally NOT discountable
    },
    "DRINKS_COLD": {
        "sub": ["Soft Drink", "Water", "Energy Drink", "Slurpee", "Juice"],
        "base_uom": "EA",
        "tax_code": "GST",
        "tobacco": False,
        "price_range": (2.50, 7.50),
        "promotable": True,
    },
    "FOOD_TO_GO": {
        "sub": ["Hot Food", "Sandwiches", "Bakery", "Pies"],
        "base_uom": "EA",
        "tax_code": "GST_FREE",       # many basic foods are GST-free in AU
        "tobacco": False,
        "price_range": (3.00, 12.00),
        "promotable": True,
    },
    "CONFECTIONERY": {
        "sub": ["Chocolate", "Chips", "Lollies", "Gum"],
        "base_uom": "EA",
        "tax_code": "GST",
        "tobacco": False,
        "price_range": (1.50, 6.50),
        "promotable": True,
    },
}

# Base units of measure. Mirrors the idea of MARA base UOM + alternative UOMs.
BASE_UOMS = ["EA", "L", "PACK", "CTN"]

# Article lifecycle status.
ARTICLE_STATUS = ["active", "discontinued", "pending"]

# Promotion mechanics. Mirrors the condition-type idea in WAKP.
PROMO_MECHANICS = ["fixed_price", "percent_off", "dollar_off", "multibuy"]

# Promotion approval lifecycle. Mirrors WAKH status handling.
PROMO_STATUS = ["draft", "approved", "live", "expired", "cancelled"]

# --- Column definitions per table -----------------------------------------
# These lists double as documentation and as a schema check the generator and
# validators can assert against (so a typo in a column name fails loudly).

ARTICLE_MASTER_COLS = [
    "article_id",          # unique ID, e.g. ART000123
    "article_description",
    "article_type",        # one of ARTICLE_TYPES
    "parent_article_id",   # FK to article_master.article_id; null for singles (SAP: MARA-SATNR)
    "merch_category",      # one of MERCH_CATEGORIES
    "sub_category",
    "base_uom",            # one of BASE_UOMS
    "barcode",             # EAN-13, valid check digit in the clean dataset
    "tax_code",            # GST / GST_FREE
    "list_price",          # standard (non-promo) price
    "cost_price",          # for margin validation
    "tobacco_floor_price", # regulated minimum; null unless tobacco
    "status",              # one of ARTICLE_STATUS
    "discontinued_date",   # set only when status == discontinued
    "created_date",
    "last_modified_date",
]

ARTICLE_SITE_COLS = [
    "article_id",          # FK to article_master
    "store_group",         # which store group this row is for
    "site_list_price",     # local price (franchisee variation)
    "listed",              # bool: is it ranged here (redundant convenience flag)
    "stock_status",        # in_stock / out_of_stock / not_ranged
    "last_modified_date",
]

LISTING_COLS = [
    "store_group",         # assortment / store group
    "article_id",          # FK to article_master
    "valid_from",
    "valid_to",
]

PROMOTION_HEADER_COLS = [
    "promo_id",            # unique ID, e.g. PRM00045
    "promo_theme",         # e.g. "Summer Slurpee Deal"
    "header_start",
    "header_end",
    "store_group",         # store group the campaign targets
    "approval_status",     # one of PROMO_STATUS
    "created_by",
    "created_date",
]

PROMOTION_ITEM_COLS = [
    "promo_item_id",       # unique ID for the line
    "promo_id",            # FK to promotion_header
    "article_id",          # FK to article_master
    "mechanic",            # one of PROMO_MECHANICS
    "promo_price",         # used for fixed_price / multibuy unit price
    "discount_value",      # used for percent_off (e.g. 25) / dollar_off (e.g. 2.00)
    "multibuy_qty",        # used for multibuy (e.g. 2 for "2 for $6")
    "item_start",
    "item_end",
]

CHANGE_LOG_COLS = [
    "change_id",
    "table_name",          # which table the change hit
    "record_id",           # the PK of the changed record
    "change_type",         # create / update
    "field_changed",       # null for create
    "old_value",
    "new_value",
    "changed_by",
    "changed_at",
]

ALL_TABLES = {
    "article_master":   ARTICLE_MASTER_COLS,
    "article_site":     ARTICLE_SITE_COLS,
    "listing":          LISTING_COLS,
    "promotion_header": PROMOTION_HEADER_COLS,
    "promotion_item":   PROMOTION_ITEM_COLS,
    "change_log":       CHANGE_LOG_COLS,
}


def assert_schema(df, table_name):
    """Fail loudly if a dataframe's columns drift from the schema."""
    expected = ALL_TABLES[table_name]
    actual = list(df.columns)
    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]
    if missing or extra:
        raise ValueError(
            f"[{table_name}] schema mismatch. Missing: {missing} | Unexpected: {extra}"
        )
