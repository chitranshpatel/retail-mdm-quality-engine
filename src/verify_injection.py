"""
verify_injection.py — Prove the dirty dataset matches the ground-truth key.

Two things must both be true for step 3's precision/recall numbers to mean
anything:
  1. Every record flagged in ground_truth.csv genuinely violates the rule it
     claims to (the injector actually corrupted it).
  2. Records NOT in ground_truth.csv are otherwise still clean (the injector
     didn't accidentally break something it wasn't supposed to).

This script checks (1) directly. For (2), it re-runs the same clean-baseline
checks from verify_clean.py against the dirty data and confirms every failure
found is accounted for in the ground truth.
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import schema as S
from barcode import is_valid_ean13

DIRTY = os.path.join(os.path.dirname(__file__), "..", "data", "dirty")


def load():
    t = {n: pd.read_csv(os.path.join(DIRTY, f"{n}.csv")) for n in S.ALL_TABLES}
    t["article_master"]["barcode"] = t["article_master"]["barcode"].astype(str)
    gt = pd.read_csv(os.path.join(DIRTY, "ground_truth.csv"))
    return t, gt


def main():
    t, gt = load()
    art, items, headers, listing = (
        t["article_master"], t["promotion_item"], t["promotion_header"], t["listing"]
    )

    print(f"Ground truth: {len(gt)} logged errors across {gt.error_type.nunique()} types\n")

    problems = []

    def check(label, expected_ids, actual_bad_ids, error_type):
        expected_ids = set(expected_ids)
        actual_bad_ids = set(actual_bad_ids)
        missing = expected_ids - actual_bad_ids   # logged but data looks fine -> injector bug
        extra = actual_bad_ids - expected_ids      # data is bad but not logged -> leakage
        ok = not missing and not extra
        print(f"  {label:45s} {'OK' if ok else 'MISMATCH'}"
              f"{'' if ok else f'  (missing={len(missing)}, unlogged_extra={len(extra)})'}")
        if not ok:
            problems.append((error_type, missing, extra))

    # --- referential_integrity: promo items whose article_id doesn't exist
    gt_ri = gt[gt.error_type == "referential_integrity"].record_id
    actual = items[~items.article_id.isin(art.article_id)].promo_item_id
    check("referential_integrity", gt_ri, actual, "referential_integrity")

    # --- referential_timing: article discontinued before an item's start
    gt_rt = gt[gt.error_type == "referential_timing"].record_id
    m = items.merge(art, on="article_id")
    bad = m[(m.status == "discontinued") &
            (pd.to_datetime(m.discontinued_date) < pd.to_datetime(m.item_start))]
    check("referential_timing", gt_rt, bad.article_id, "referential_timing")

    # --- listing_conflict: promo item in a store group where article isn't listed
    # (exclude items whose article_id doesn't exist at all -- those are already
    # captured under referential_integrity; a nonexistent article isn't
    # meaningfully "unlisted", it's simply missing, which is a different defect)
    gt_lc = gt[gt.error_type == "listing_conflict"].record_id
    listed_pairs = set(zip(listing.article_id, listing.store_group))
    im = items.merge(headers[["promo_id", "store_group"]], on="promo_id")
    im = im[im.article_id.isin(art.article_id)]
    bad_mask = [(r.article_id, r.store_group) not in listed_pairs for r in im.itertuples()]
    actual = im.loc[bad_mask, "promo_item_id"]
    check("listing_conflict", gt_lc, actual, "listing_conflict")

    # --- header_item_date_mismatch: item window outside header window
    gt_hd = gt[gt.error_type == "header_item_date_mismatch"].record_id
    im2 = items.merge(headers[["promo_id", "header_start", "header_end"]], on="promo_id")
    for c in ["item_start", "item_end", "header_start", "header_end"]:
        im2[c] = pd.to_datetime(im2[c])
    bad = im2[(im2.item_start < im2.header_start) | (im2.item_end > im2.header_end)]
    check("header_item_date_mismatch", gt_hd, bad.promo_item_id, "header_item_date_mismatch")

    # --- orphaned_cancelled_header: cancelled header with items still active
    gt_oc = gt[gt.error_type == "orphaned_cancelled_header"].record_id
    cancelled = headers[headers.approval_status == "cancelled"].promo_id
    check("orphaned_cancelled_header", gt_oc, cancelled, "orphaned_cancelled_header")

    # --- uom_pack_mismatch: multibuy mechanic on non-EA article
    # (exclude nulls: a nulled base_uom is a completeness error, not a UOM mismatch;
    # NaN != 'EA' evaluates True in pandas, which would otherwise false-flag it)
    gt_um = gt[gt.error_type == "uom_pack_mismatch"].record_id
    mb = items[items.mechanic == "multibuy"].merge(
        art[["article_id", "base_uom"]], on="article_id")
    bad = mb[mb.base_uom.notna() & (mb.base_uom != "EA")]
    check("uom_pack_mismatch", gt_um, bad.article_id, "uom_pack_mismatch")

    # --- tobacco_floor_breach: promo price below tobacco floor
    gt_tf = gt[gt.error_type == "tobacco_floor_breach"].record_id
    m2 = items.merge(art[["article_id", "tobacco_floor_price"]], on="article_id")
    bad = m2[m2.tobacco_floor_price.notna() & (m2.promo_price < m2.tobacco_floor_price)]
    check("tobacco_floor_breach", gt_tf, bad.promo_item_id, "tobacco_floor_breach")

    # --- margin_breach: promo_price below cost_price
    gt_mb = gt[gt.error_type == "margin_breach"].record_id
    m3 = items.merge(art[["article_id", "cost_price"]], on="article_id")
    bad = m3[m3.mechanic.isin(["fixed_price", "multibuy"]) & (m3.promo_price < m3.cost_price)]
    check("margin_breach", gt_mb, bad.promo_item_id, "margin_breach")

    # --- barcode_invalidity
    gt_bi = gt[gt.error_type == "barcode_invalidity"].record_id
    bad = art[~art.barcode.map(is_valid_ean13)]
    check("barcode_invalidity", gt_bi, bad.article_id, "barcode_invalidity")

    # --- completeness: required fields null
    gt_c = gt[gt.error_type == "completeness"].record_id
    art_bad = art[art[["base_uom", "tax_code"]].isnull().any(axis=1)].article_id
    hdr_bad = headers[headers.approval_status.isnull()].promo_id
    check("completeness", gt_c, pd.concat([art_bad, hdr_bad]), "completeness")

    # --- stale_status: live but header_end has passed
    gt_ss = gt[gt.error_type == "stale_status"].record_id
    from datetime import date
    TODAY = date(2026, 7, 1)
    bad = headers[(headers.approval_status == "live") &
                  (pd.to_datetime(headers.header_end).dt.date < TODAY)]
    check("stale_status", gt_ss, bad.promo_id, "stale_status")

    # --- duplicate_near_duplicate: just confirm the logged new IDs exist
    gt_dd = gt[gt.error_type == "duplicate_near_duplicate"].record_id
    check("duplicate_near_duplicate", gt_dd, art[art.article_id.isin(gt_dd)].article_id, "duplicate_near_duplicate")

    print()
    if problems:
        print(f"INJECTION VERIFICATION FAILED — {len(problems)} type(s) mismatched.")
        sys.exit(1)
    print("All injected errors verified against ground truth. Safe to build validators in step 3.")


if __name__ == "__main__":
    main()
