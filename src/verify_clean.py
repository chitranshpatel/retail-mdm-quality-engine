"""
verify_clean.py — Prove the generated baseline is actually clean.

If any check here fails, the 'clean' dataset isn't clean, which would poison the
ground-truth key when we inject errors in step 2. This is a guardrail, not
decoration: run it every time the generator changes.
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import schema as S
from barcode import is_valid_ean13

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "clean")


def load():
    return {n: pd.read_csv(os.path.join(DATA, f"{n}.csv")) for n in S.ALL_TABLES}


def main():
    t = load()
    art = t["article_master"]
    items = t["promotion_item"]
    headers = t["promotion_header"]
    listing = t["listing"]

    failures = []

    def check(name, bad_count):
        status = "OK" if bad_count == 0 else f"FAIL ({bad_count})"
        print(f"  {name:38s} {status}")
        if bad_count:
            failures.append(name)

    print("Verifying clean baseline...")

    # 1. Referential integrity: every promo item article exists
    check("promo item -> article exists",
          (~items.article_id.isin(art.article_id)).sum())

    # 2. Referential integrity: every promo item header exists
    check("promo item -> header exists",
          (~items.promo_id.isin(headers.promo_id)).sum())

    # 3. Hierarchy: every variant's parent exists and is a generic
    variants = art[art.article_type == "variant"]
    parent_ok = variants.parent_article_id.isin(
        art[art.article_type == "generic"].article_id
    )
    check("variant -> generic parent exists", (~parent_ok).sum())

    # 4. Barcodes all valid EAN-13
    check("barcode check-digit valid",
          (~art.barcode.astype(str).map(is_valid_ean13)).sum())

    # 5. No margin breach: fixed_price / multibuy unit price >= cost
    m = items.merge(art[["article_id", "cost_price", "list_price"]], on="article_id")
    fp = m[m.mechanic == "fixed_price"]
    margin_bad = (fp.promo_price < fp.cost_price).sum()
    check("fixed_price >= cost (no margin breach)", margin_bad)

    # 6. Item window inside header window
    im = items.merge(headers[["promo_id", "header_start", "header_end"]], on="promo_id")
    for c in ["item_start", "item_end", "header_start", "header_end"]:
        im[c] = pd.to_datetime(im[c])
    outside = ((im.item_start < im.header_start) | (im.item_end > im.header_end)).sum()
    check("item window inside header window", outside)

    # 7. Listing: every promoted (article, store_group) is listed
    listed_pairs = set(zip(listing.article_id, listing.store_group))
    im2 = items.merge(headers[["promo_id", "store_group"]], on="promo_id")
    not_listed = sum(
        (r.article_id, r.store_group) not in listed_pairs
        for r in im2.itertuples()
    )
    check("promoted article listed in store group", not_listed)

    # 8. No tobacco on promo (tobacco is non-promotable in clean data)
    tob_ids = set(art[art.merch_category == "TOBACCO"].article_id)
    check("no tobacco articles on promo",
          items.article_id.isin(tob_ids).sum())

    # 9. Multibuy only on EA articles
    mb = items[items.mechanic == "multibuy"].merge(
        art[["article_id", "base_uom"]], on="article_id")
    check("multibuy only on EA base_uom",
          (mb.base_uom != "EA").sum())

    # 10. Completeness: no nulls in required article fields
    req = ["article_id", "article_description", "article_type",
           "merch_category", "base_uom", "barcode", "tax_code",
           "list_price", "cost_price", "status"]
    check("required article fields populated",
          art[req].isnull().any(axis=1).sum())

    print()
    if failures:
        print(f"BASELINE NOT CLEAN — {len(failures)} check(s) failed:", failures)
        sys.exit(1)
    print("Baseline is clean. Safe to inject errors in step 2.")


if __name__ == "__main__":
    main()
