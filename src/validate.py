"""
validate.py — Validation rule engine.

Each check is a function: takes the loaded tables, returns a DataFrame of
exceptions with a standard shape (so the dashboard in step 4 can treat every
check the same way, and so we can score all of them against ground truth the
same way in one pass).

Standard exception row shape:
    table_name, record_id, error_type, severity, downstream_impact, description

We build this one check at a time. First: referential integrity.
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import schema as S

DIRTY = os.path.join(os.path.dirname(__file__), "..", "data", "dirty")

EXCEPTION_COLS = ["table_name", "record_id", "error_type", "severity",
                   "downstream_impact", "description"]


def load_dirty():
    t = {n: pd.read_csv(os.path.join(DIRTY, f"{n}.csv")) for n in S.ALL_TABLES}
    t["article_master"]["barcode"] = t["article_master"]["barcode"].astype(str)
    return t


def check_referential_integrity(t):
    """Every promotion_item.article_id must exist in article_master."""
    items, art = t["promotion_item"], t["article_master"]
    bad = items[~items.article_id.isin(art.article_id)]

    rows = []
    for _, r in bad.iterrows():
        rows.append({
            "table_name": "promotion_item",
            "record_id": r.promo_item_id,
            "error_type": "referential_integrity",
            "severity": "Critical",
            "downstream_impact": "Promo fails to load; price file rejects record",
            "description": f"promo_item {r.promo_item_id} references article_id "
                            f"'{r.article_id}', which does not exist in article_master.",
        })
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_referential_timing(t):
    """Article was discontinued before the promo item it's on actually started."""
    items, art = t["promotion_item"], t["article_master"]

    merged = items.merge(art, on="article_id", how="inner")
    merged["discontinued_date"] = pd.to_datetime(merged["discontinued_date"])
    merged["item_start"] = pd.to_datetime(merged["item_start"])

    bad = merged[
        (merged["status"] == "discontinued") &
        (merged["discontinued_date"] < merged["item_start"])
    ]

    rows = []
    for _, r in bad.iterrows():
        rows.append({
            "table_name": "promotion_item",
            "record_id": r.promo_item_id,
            "error_type": "referential_timing",
            "severity": "High",
            "downstream_impact": "Promo advertised on an article stores can no longer order",
            "description": f"promo_item {r.promo_item_id} promotes article "
                            f"'{r.article_id}', discontinued on {r.discontinued_date.date()}, "
                            f"before the promo item started on {r.item_start.date()}.",
        })
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


CHECKS = [
    check_referential_integrity,
    check_referential_timing,
]


def main():
    t = load_dirty()
    all_exceptions = pd.concat([fn(t) for fn in CHECKS], ignore_index=True)

    print(f"Ran {len(CHECKS)} check(s). Found {len(all_exceptions)} exceptions.\n")
    print(all_exceptions.head(10).to_string(index=False))
    return all_exceptions


if __name__ == "__main__":
    main()