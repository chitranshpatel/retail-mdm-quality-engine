# 



"""
validate.py — Validation rule engine. All 12 checks, final version.
"""
import os
import sys
from datetime import date
import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, os.path.dirname(__file__))
import schema as S
from barcode import is_valid_ean13

DIRTY = os.path.join(os.path.dirname(__file__), "..", "data", "dirty")
TODAY = date(2026, 7, 1)

EXCEPTION_COLS = ["table_name", "record_id", "error_type", "severity",
                   "downstream_impact", "description"]


def load_dirty():
    t = {n: pd.read_csv(os.path.join(DIRTY, f"{n}.csv")) for n in S.ALL_TABLES}
    t["article_master"]["barcode"] = t["article_master"]["barcode"].astype(str)
    return t


def check_referential_integrity(t):
    items, art = t["promotion_item"], t["article_master"]
    bad = items[~items.article_id.isin(art.article_id)]
    rows = [{
        "table_name": "promotion_item", "record_id": r.promo_item_id,
        "error_type": "referential_integrity", "severity": "Critical",
        "downstream_impact": "Promo fails to load; price file rejects record",
        "description": f"promo_item {r.promo_item_id} references article_id "
                        f"'{r.article_id}', which does not exist in article_master.",
    } for _, r in bad.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_referential_timing(t):
    items, art = t["promotion_item"], t["article_master"]
    merged = items.merge(art, on="article_id", how="inner")
    merged["discontinued_date"] = pd.to_datetime(merged["discontinued_date"])
    merged["item_start"] = pd.to_datetime(merged["item_start"])
    bad = merged[
        (merged["status"] == "discontinued") &
        (merged["discontinued_date"] < merged["item_start"])
    ]
    rows = [{
        "table_name": "promotion_item", "record_id": r.promo_item_id,
        "error_type": "referential_timing", "severity": "High",
        "downstream_impact": "Promo advertised on an article stores can no longer order",
        "description": f"promo_item {r.promo_item_id} promotes article '{r.article_id}', "
                        f"discontinued on {r.discontinued_date.date()}, before the promo "
                        f"item started on {r.item_start.date()}.",
    } for _, r in bad.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_listing_conflict(t):
    items, headers, listing, art = (t["promotion_item"], t["promotion_header"],
                                     t["listing"], t["article_master"])
    merged = items.merge(headers[["promo_id", "store_group"]], on="promo_id", how="inner")
    merged = merged[merged.article_id.isin(art.article_id)]
    final_df = merged.merge(listing, on=["article_id", "store_group"], how="left")
    wrong_promo = final_df[final_df["valid_from"].isna()]
    rows = [{
        "table_name": "promotion_item", "record_id": r.promo_item_id,
        "error_type": "listing_conflict", "severity": "High",
        "downstream_impact": "Advertised deal a customer physically can't buy in that store",
        "description": f"promo_item {r.promo_item_id} promotes article '{r.article_id}' "
                        f"in store_group '{r.store_group}', but the article isn't listed there.",
    } for _, r in wrong_promo.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_header_item_date_mismatch(t):
    items, headers = t["promotion_item"], t["promotion_header"]
    merged = items.merge(headers[["promo_id", "header_start", "header_end"]],
                          on="promo_id", how="inner")
    for col in ["item_start", "item_end", "header_start", "header_end"]:
        merged[col] = pd.to_datetime(merged[col])
    bad = merged[
        ~merged["item_start"].between(merged["header_start"], merged["header_end"]) |
        ~merged["item_end"].between(merged["header_start"], merged["header_end"])
    ]
    rows = [{
        "table_name": "promotion_item", "record_id": r.promo_item_id,
        "error_type": "header_item_date_mismatch", "severity": "Medium",
        "downstream_impact": "Item prices live when the campaign isn't, or vice versa",
        "description": f"promo_item {r.promo_item_id} runs {r.item_start.date()} to "
                        f"{r.item_end.date()}, outside header window "
                        f"{r.header_start.date()} to {r.header_end.date()}.",
    } for _, r in bad.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_orphaned_cancelled_header(t):
    items, headers = t["promotion_item"], t["promotion_header"]
    merged = items.merge(headers[["promo_id", "approval_status"]], on="promo_id", how="inner")
    merged["item_end"] = pd.to_datetime(merged["item_end"])
    bad = merged[
        (merged["approval_status"] == "cancelled") &
        (merged["item_end"].dt.date >= TODAY)
    ]
    rows = [{
        "table_name": "promotion_item", "record_id": r.promo_item_id,
        "error_type": "orphaned_cancelled_header", "severity": "Critical",
        "downstream_impact": "Old promo price still charged at POS",
        "description": f"promo_item {r.promo_item_id}'s header ({r.promo_id}) is cancelled, "
                        f"but the item still runs until {r.item_end.date()}.",
    } for _, r in bad.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_uom_pack_mismatch(t):
    items, art = t["promotion_item"], t["article_master"]
    multibuy = items[items["mechanic"] == "multibuy"]
    merged = pd.merge(multibuy, art, on="article_id", how="inner")
    bad = merged[merged["base_uom"].notna() & (merged["base_uom"] != "EA")]
    rows = [{
        "table_name": "promotion_item", "record_id": r.promo_item_id,
        "error_type": "uom_pack_mismatch", "severity": "Medium",
        "downstream_impact": "Mechanic can't be applied; POS error",
        "description": f"promo_item {r.promo_item_id} uses multibuy on article "
                        f"'{r.article_id}', sold as {r.base_uom}, not EA.",
    } for _, r in bad.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_tobacco_on_promotion(t):
    items, art = t["promotion_item"], t["article_master"]
    merged = items.merge(art[["article_id", "merch_category"]], on="article_id", how="inner")
    bad = merged[merged["merch_category"] == "TOBACCO"]
    rows = [{
        "table_name": "promotion_item", "record_id": r.promo_item_id,
        "error_type": "tobacco_on_promotion", "severity": "Critical",
        "downstream_impact": "Regulatory / compliance breach: tobacco promotion is not legal in Australia",
        "description": f"promo_item {r.promo_item_id} promotes tobacco article '{r.article_id}'.",
    } for _, r in bad.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_margin_breach(t):
    items, art = t["promotion_item"], t["article_master"]
    priced = items[items["mechanic"].isin(["fixed_price", "multibuy"])]
    merged = priced.merge(art[["article_id", "cost_price"]], on="article_id", how="inner")
    bad = merged[merged["promo_price"] < merged["cost_price"]]
    rows = [{
        "table_name": "promotion_item", "record_id": r.promo_item_id,
        "error_type": "margin_breach", "severity": "High",
        "downstream_impact": "Unintended loss-making sale",
        "description": f"promo_item {r.promo_item_id} prices article '{r.article_id}' at "
                        f"${r.promo_price:.2f}, below cost ${r.cost_price:.2f}.",
    } for _, r in bad.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_barcode_invalidity(t):
    art = t["article_master"]
    bad = art[~art.barcode.map(is_valid_ean13)]
    rows = [{
        "table_name": "article_master", "record_id": r.article_id,
        "error_type": "barcode_invalidity", "severity": "Critical",
        "downstream_impact": "Won't scan at POS; scan-and-go / self-checkout failure",
        "description": f"article '{r.article_id}' has barcode '{r.barcode}', invalid check digit.",
    } for _, r in bad.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_duplicate_near_duplicate(t, threshold=97):
    art = t["article_master"]
    rows = []
    for category, group in art.groupby("merch_category"):
        records = group[["article_id", "article_description", "parent_article_id"]].to_dict("records")
        n = len(records)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = records[i], records[j]
                if a["article_id"] == b["parent_article_id"] or b["article_id"] == a["parent_article_id"]:
                    continue
                score = fuzz.token_set_ratio(a["article_description"], b["article_description"])
                if score >= threshold:
                    rows.append({
                        "table_name": "article_master", "record_id": b["article_id"],
                        "error_type": "duplicate_near_duplicate", "severity": "Low",
                        "downstream_impact": "Split sales reporting; double replenishment",
                        "description": f"article '{b['article_id']}' looks like a near-duplicate "
                                        f"of '{a['article_id']}', similarity {score:.0f}%.",
                    })
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_completeness(t):
    art, headers = t["article_master"], t["promotion_header"]
    rows = []
    bad_art = art[art["base_uom"].isna() | art["tax_code"].isna()]
    for _, r in bad_art.iterrows():
        missing = [f for f in ["base_uom", "tax_code"] if pd.isna(r[f])]
        rows.append({
            "table_name": "article_master", "record_id": r.article_id,
            "error_type": "completeness", "severity": "Low",
            "downstream_impact": "Downstream tax/finance and ordering errors",
            "description": f"article '{r.article_id}' missing: {', '.join(missing)}.",
        })
    bad_hdr = headers[headers["approval_status"].isna()]
    for _, r in bad_hdr.iterrows():
        rows.append({
            "table_name": "promotion_header", "record_id": r.promo_id,
            "error_type": "completeness", "severity": "Low",
            "downstream_impact": "Downstream tax/finance and ordering errors",
            "description": f"promotion_header '{r.promo_id}' missing approval_status.",
        })
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


def check_stale_status(t):
    headers = t["promotion_header"].copy()
    headers["header_end"] = pd.to_datetime(headers["header_end"])
    bad = headers[
        (headers["approval_status"] == "live") &
        (headers["header_end"].dt.date < TODAY)
    ]
    rows = [{
        "table_name": "promotion_header", "record_id": r.promo_id,
        "error_type": "stale_status", "severity": "Low",
        "downstream_impact": "Expired promo still treated as active",
        "description": f"promotion_header '{r.promo_id}' marked live but "
                        f"header_end ({r.header_end.date()}) has passed.",
    } for _, r in bad.iterrows()]
    return pd.DataFrame(rows, columns=EXCEPTION_COLS)


CHECKS = [
    check_referential_integrity,
    check_referential_timing,
    check_listing_conflict,
    check_header_item_date_mismatch,
    check_orphaned_cancelled_header,
    check_uom_pack_mismatch,
    check_tobacco_on_promotion,
    check_margin_breach,
    check_barcode_invalidity,
    check_duplicate_near_duplicate,
    check_completeness,
    check_stale_status,
]


def main():
    t = load_dirty()
    all_exceptions = pd.concat([fn(t) for fn in CHECKS], ignore_index=True)
    print(f"Ran {len(CHECKS)} check(s). Found {len(all_exceptions)} exceptions.")
    return all_exceptions


if __name__ == "__main__":
    main()