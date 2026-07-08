# """
# inject.py — Seeded, logged error injection against a COPY of the clean baseline.

# Design rule: every corruption this script makes is recorded in a ground-truth
# table (data/dirty/ground_truth.csv) with the record's table, primary key, error
# type, severity, and what changed. Step 3's validators never see this file —
# it exists purely so we can measure precision/recall honestly at the end.

# Implements the 12 error types from the framework doc, each injected into a
# random ~5-10% sample of eligible records (see INJECTION_RATE / per-type notes).

# Run:  python3 src/inject.py
# In:   data/clean/*.csv        (untouched)
# Out:  data/dirty/*.csv        (corrupted copies)
#       data/dirty/ground_truth.csv
# """
# import os
# import sys
# import random
# from datetime import date, timedelta

# import numpy as np
# import pandas as pd

# sys.path.insert(0, os.path.dirname(__file__))
# import schema as S
# from barcode import is_valid_ean13

# SEED = 7  # deliberately different from the generator's seed (42)
# TODAY = date(2026, 7, 1)  # must match generate.py's TODAY

# CLEAN_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "clean")
# DIRTY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "dirty")

# # Severity tiers, matching the framework doc (tiered by downstream impact).
# SEVERITY = {
#     "referential_integrity": "Critical",
#     "referential_timing": "High",
#     "listing_conflict": "High",
#     "header_item_date_mismatch": "Medium",
#     "orphaned_cancelled_header": "Critical",
#     "uom_pack_mismatch": "Medium",
#     "tobacco_floor_breach": "Critical",
#     "margin_breach": "High",
#     "barcode_invalidity": "Critical",
#     "duplicate_near_duplicate": "Low",
#     "completeness": "Low",
#     "stale_status": "Low",
# }

# DOWNSTREAM = {
#     "referential_integrity": "Promo fails to load; price file rejects record",
#     "referential_timing": "Promo advertised on an article stores can no longer order",
#     "listing_conflict": "Advertised deal a customer physically can't buy in that store",
#     "header_item_date_mismatch": "Item prices live when the campaign isn't, or vice versa",
#     "orphaned_cancelled_header": "Old promo price still charged at POS",
#     "uom_pack_mismatch": "Mechanic can't be applied; POS error",
#     "tobacco_floor_breach": "Regulatory / compliance breach",
#     "margin_breach": "Unintended loss-making sale",
#     "barcode_invalidity": "Won't scan at POS; scan-and-go / self-checkout failure",
#     "duplicate_near_duplicate": "Split sales reporting; double replenishment",
#     "completeness": "Downstream tax/finance and ordering errors",
#     "stale_status": "Expired promo still treated as active",
# }


# def load_clean():
#     t = {n: pd.read_csv(os.path.join(CLEAN_DIR, f"{n}.csv")) for n in S.ALL_TABLES}
#     # barcode is all-digit -> pandas infers int64; force back to string so we can
#     # corrupt individual digits (and preserve leading behaviour) without dtype errors.
#     t["article_master"]["barcode"] = t["article_master"]["barcode"].astype(str)
#     return t


# class GroundTruth:
#     """Accumulates one row per injected error."""
#     def __init__(self):
#         self.rows = []
#         self._seq = 0

#     def log(self, table, record_id, error_type, field=None, old=None, new=None):
#         self._seq += 1
#         self.rows.append({
#             "gt_id": f"GT{self._seq:05d}",
#             "table_name": table,
#             "record_id": record_id,
#             "error_type": error_type,
#             "severity": SEVERITY[error_type],
#             "downstream_impact": DOWNSTREAM[error_type],
#             "field_changed": field,
#             "old_value": old,
#             "new_value": new,
#         })

#     def to_df(self):
#         return pd.DataFrame(self.rows, columns=[
#             "gt_id", "table_name", "record_id", "error_type", "severity",
#             "downstream_impact", "field_changed", "old_value", "new_value",
#         ])


# def sample_idx(df, frac, rng):
#     """Random sample of row indices, 5-10% by default, at least 1 if any exist."""
#     n = max(1, int(len(df) * frac)) if len(df) else 0
#     if n == 0:
#         return []
#     return list(rng.choice(df.index, size=min(n, len(df)), replace=False))


# # ---------------------------------------------------------------------
# # Each injector: takes the tables dict + GroundTruth logger, mutates
# # tables IN PLACE, logs every change. Returns nothing.
# # ---------------------------------------------------------------------

# def inject_referential_integrity(t, gt, rng):
#     """promotion_item.article_id points at an article that doesn't exist."""
#     items = t["promotion_item"]
#     idx = sample_idx(items, 0.06, rng)
#     for i in idx:
#         old = items.at[i, "article_id"]
#         fake = f"ART9{rng.integers(9000, 9999)}"
#         items.at[i, "article_id"] = fake
#         gt.log("promotion_item", items.at[i, "promo_item_id"],
#                 "referential_integrity", "article_id", old, fake)


# def inject_referential_timing(t, gt, rng):
#     """Article was discontinued BEFORE the promo item's start date."""
#     items = t["promotion_item"]
#     art = t["article_master"]
#     active_items = items.index.tolist()
#     idx = sample_idx(items.loc[active_items], 0.05, rng)
#     for i in idx:
#         aid = items.at[i, "article_id"]
#         match = art.index[art.article_id == aid]
#         if len(match) == 0:
#             continue
#         ai = match[0]
#         old_status = art.at[ai, "status"]
#         item_start = pd.to_datetime(items.at[i, "item_start"]).date()
#         disc_date = item_start - timedelta(days=int(rng.integers(5, 60)))
#         art.at[ai, "status"] = "discontinued"
#         art.at[ai, "discontinued_date"] = disc_date.isoformat()
#         gt.log("article_master", aid, "referential_timing",
#                 "status", old_status, "discontinued (after promo item_start)")


# def inject_listing_conflict(t, gt, rng):
#     """Promo item runs in a store group where the article isn't listed.

#     Removing a listing row for (article, store_group) is a genuine conflict for
#     EVERY promo_item that references that same pair, not just the one we sampled
#     -- so we log all of them, or the ground truth would under-count real defects.
#     """
#     items = t["promotion_item"]
#     headers = t["promotion_header"]
#     listing = t["listing"]
#     listed_pairs = set(zip(listing.article_id, listing.store_group))
#     im = items.merge(headers[["promo_id", "store_group"]], on="promo_id")

#     idx = sample_idx(items, 0.05, rng)
#     pairs_to_remove = set()
#     for i in idx:
#         aid = items.at[i, "article_id"]
#         pid = items.at[i, "promo_id"]
#         h = headers.index[headers.promo_id == pid]
#         if len(h) == 0:
#             continue
#         sg = headers.at[h[0], "store_group"]
#         if (aid, sg) in listed_pairs:
#             pairs_to_remove.add((aid, sg))

#     drop_mask = pd.Series(False, index=listing.index)
#     for aid, sg in pairs_to_remove:
#         hit = listing.index[(listing.article_id == aid) & (listing.store_group == sg)]
#         drop_mask.loc[hit] = True
#         # log every promo_item that references this now-delisted (article, store_group)
#         affected = im[(im.article_id == aid) & (im.store_group == sg)]
#         for pit in affected.promo_item_id:
#             gt.log("promotion_item", pit, "listing_conflict",
#                     "listing_row", "listed", "removed (delisted)")
#     t["listing"] = listing.loc[~drop_mask].reset_index(drop=True)


# def inject_header_item_date_mismatch(t, gt, rng):
#     """Item validity dates fall outside the header campaign window."""
#     items = t["promotion_item"]
#     headers = t["promotion_header"].set_index("promo_id")
#     idx = sample_idx(items, 0.06, rng)
#     for i in idx:
#         pid = items.at[i, "promo_id"]
#         if pid not in headers.index:
#             continue
#         hend = pd.to_datetime(headers.at[pid, "header_end"]).date()
#         old = items.at[i, "item_end"]
#         new_end = hend + timedelta(days=int(rng.integers(2, 10)))
#         items.at[i, "item_end"] = new_end.isoformat()
#         gt.log("promotion_item", items.at[i, "promo_item_id"],
#                 "header_item_date_mismatch", "item_end", old, new_end.isoformat())


# def inject_orphaned_cancelled_header(t, gt, rng):
#     """Header is cancelled/expired but its item(s) are still 'live' (future/current dates)."""
#     headers = t["promotion_header"]
#     items = t["promotion_item"]
#     candidates = headers.index[headers.approval_status.isin(["live", "approved"])]
#     # eligible pool here is naturally small (~30 of 120 headers), so use a higher
#     # rate than the general 5-10% guideline to keep this Critical-severity check
#     # meaningfully testable in step 3.
#     idx = sample_idx(headers.loc[candidates], 0.25, rng)
#     for h in idx:
#         pid = headers.at[h, "promo_id"]
#         old = headers.at[h, "approval_status"]
#         headers.at[h, "approval_status"] = "cancelled"
#         gt.log("promotion_header", pid, "orphaned_cancelled_header",
#                 "approval_status", old, "cancelled (items still active)")


# def inject_uom_pack_mismatch(t, gt, rng):
#     """Multibuy mechanic on an article that isn't sold as EA (e.g. CTN/PACK)."""
#     items = t["promotion_item"]
#     art = t["article_master"].set_index("article_id")
#     candidates = items.index[items.mechanic == "multibuy"]
#     idx = sample_idx(items.loc[candidates], 0.30, rng)  # 30% of the (small) multibuy pool
#     for i in idx:
#         aid = items.at[i, "article_id"]
#         if aid not in art.index:
#             continue
#         old_uom = art.at[aid, "base_uom"]
#         art.at[aid, "base_uom"] = rng.choice(["CTN", "PACK"])
#         gt.log("article_master", aid, "uom_pack_mismatch",
#                 "base_uom", old_uom, art.at[aid, "base_uom"])
#     t["article_master"] = art.reset_index()


# def inject_tobacco_floor_breach(t, gt, rng):
#     """A promo item on a tobacco article priced below its regulated floor."""
#     art = t["article_master"]
#     headers = t["promotion_header"]
#     items = t["promotion_item"]
#     tobacco = art[(art.merch_category == "TOBACCO") & (art.status == "active")]
#     idx = sample_idx(tobacco, 0.08, rng)
#     listing = t["listing"]
#     for ti in idx:
#         aid = art.at[ti, "article_id"]
#         floor = art.at[ti, "cost_price"]  # fallback
#         floor = art.at[ti, "tobacco_floor_price"]
#         if pd.isna(floor):
#             continue
#         # find (or fabricate) a store group where it's listed
#         rows = listing[listing.article_id == aid]
#         if rows.empty:
#             continue
#         sg = rows.iloc[0].store_group
#         # use an existing live header in that store group, else the first header
#         h = headers[headers.store_group == sg]
#         if h.empty:
#             h = headers.iloc[[0]]
#         pid = h.iloc[0].promo_id
#         new_id = f"PIT9{rng.integers(90000, 99999)}"
#         cost = art.at[ti, "cost_price"]
#         # keep the breach price strictly between cost and floor, so this is a
#         # clean tobacco-floor violation only -- not one that also silently
#         # trips the margin_breach check (that would conflate two error types).
#         lo = float(cost) * 1.02
#         hi = float(floor) * 0.97
#         if lo >= hi:
#             lo, hi = float(floor) * 0.90, float(floor) * 0.97
#         breach_price = round(rng.uniform(lo, hi), 2)
#         new_row = {
#             "promo_item_id": new_id, "promo_id": pid, "article_id": aid,
#             "mechanic": "fixed_price", "promo_price": breach_price,
#             "discount_value": None, "multibuy_qty": None,
#             "item_start": h.iloc[0].header_start, "item_end": h.iloc[0].header_end,
#         }
#         items.loc[len(items)] = new_row
#         gt.log("promotion_item", new_id, "tobacco_floor_breach",
#                 "promo_price", f"floor={floor}", breach_price)


# def inject_margin_breach(t, gt, rng):
#     """promo_price set below the article's cost_price."""
#     items = t["promotion_item"]
#     art = t["article_master"].set_index("article_id")
#     candidates = items.index[items.mechanic.isin(["fixed_price", "multibuy"])]
#     idx = sample_idx(items.loc[candidates], 0.05, rng)
#     for i in idx:
#         aid = items.at[i, "article_id"]
#         if aid not in art.index:
#             continue
#         cost = art.at[aid, "cost_price"]
#         old = items.at[i, "promo_price"]
#         new_price = round(float(cost) * rng.uniform(0.6, 0.9), 2)
#         items.at[i, "promo_price"] = new_price
#         gt.log("promotion_item", items.at[i, "promo_item_id"],
#                 "margin_breach", "promo_price", old, new_price)


# def inject_barcode_invalidity(t, gt, rng):
#     """Flip the EAN-13 check digit so it no longer validates."""
#     art = t["article_master"]
#     idx = sample_idx(art, 0.05, rng)
#     for i in idx:
#         old = art.at[i, "barcode"]
#         bc = str(old)
#         wrong_digit = str((int(bc[-1]) + rng.integers(1, 9)) % 10)
#         new = bc[:-1] + wrong_digit
#         if is_valid_ean13(new):  # extremely rare collision guard
#             new = bc[:-1] + str((int(wrong_digit) + 1) % 10)
#         art.at[i, "barcode"] = new
#         gt.log("article_master", art.at[i, "article_id"],
#                 "barcode_invalidity", "barcode", old, new)


# def inject_duplicate_near_duplicate(t, gt, rng, corrupted_barcodes=None):
#     """Append a near-duplicate article: same product, slightly different text/supplier.

#     Samples from articles NOT already hit by barcode_invalidity, so a duplicate
#     doesn't silently carry a corrupted barcode into a new, unlogged article_id.
#     """
#     art = t["article_master"]
#     corrupted_barcodes = corrupted_barcodes or set()
#     pool = art[~art.article_id.isin(corrupted_barcodes)]
#     idx = sample_idx(pool, 0.04, rng)
#     new_rows = []
#     for i in idx:
#         src = art.loc[i].copy()
#         new_id = f"ART9{rng.integers(8000, 8999)}"
#         suffix = rng.choice([" - NEW", " (Promo Pack)", " V2", ""])
#         src["article_id"] = new_id
#         src["article_description"] = str(src["article_description"]) + suffix
#         src["created_date"] = TODAY.isoformat()
#         src["last_modified_date"] = TODAY.isoformat()
#         new_rows.append(src)
#         gt.log("article_master", new_id, "duplicate_near_duplicate",
#                 "article_id", art.at[i, "article_id"], new_id)
#     if new_rows:
#         t["article_master"] = pd.concat(
#             [art, pd.DataFrame(new_rows)], ignore_index=True
#         )


# def inject_completeness(t, gt, rng):
#     """Null out a required field on article_master or promotion_header."""
#     art = t["article_master"]
#     headers = t["promotion_header"]
#     idx_a = sample_idx(art, 0.04, rng)
#     for i in idx_a:
#         field = rng.choice(["base_uom", "tax_code"])
#         old = art.at[i, field]
#         art.at[i, field] = None
#         gt.log("article_master", art.at[i, "article_id"], "completeness",
#                 field, old, None)
#     idx_h = sample_idx(headers, 0.03, rng)
#     for i in idx_h:
#         old = headers.at[i, "approval_status"]
#         headers.at[i, "approval_status"] = None
#         gt.log("promotion_header", headers.at[i, "promo_id"], "completeness",
#                 "approval_status", old, None)


# def inject_stale_status(t, gt, rng):
#     """approval_status = 'live' but header_end has already passed."""
#     headers = t["promotion_header"]
#     past = headers.index[pd.to_datetime(headers.header_end).dt.date < TODAY]
#     idx = sample_idx(headers.loc[past], 0.20, rng)  # 20% of past promos
#     for i in idx:
#         old = headers.at[i, "approval_status"]
#         if old == "live":
#             continue
#         headers.at[i, "approval_status"] = "live"
#         gt.log("promotion_header", headers.at[i, "promo_id"], "stale_status",
#                 "approval_status", old, "live")


# INJECTORS = [
#     inject_referential_integrity,
#     inject_referential_timing,
#     inject_listing_conflict,
#     inject_header_item_date_mismatch,
#     inject_orphaned_cancelled_header,
#     inject_uom_pack_mismatch,
#     inject_tobacco_floor_breach,
#     inject_margin_breach,
#     inject_barcode_invalidity,
#     inject_duplicate_near_duplicate,
#     inject_completeness,
#     inject_stale_status,
# ]


# def main():
#     rng = np.random.default_rng(SEED)
#     random.seed(SEED)

#     t = load_clean()
#     gt = GroundTruth()

#     for fn in INJECTORS:
#         if fn is inject_duplicate_near_duplicate:
#             corrupted = set(gt.to_df().query("error_type == 'barcode_invalidity'").record_id) \
#                 if gt.rows else set()
#             fn(t, gt, rng, corrupted_barcodes=corrupted)
#         else:
#             fn(t, gt, rng)

#     os.makedirs(DIRTY_DIR, exist_ok=True)
#     for name, df in t.items():
#         df.to_csv(os.path.join(DIRTY_DIR, f"{name}.csv"), index=False)

#     gt_df = gt.to_df()
#     gt_df.to_csv(os.path.join(DIRTY_DIR, "ground_truth.csv"), index=False)

#     print(f"Injected {len(gt_df)} errors (seed={SEED}) across {gt_df.error_type.nunique()} types:")
#     print(gt_df.groupby(["error_type", "severity"]).size().to_string())
#     print(f"\nWritten to {DIRTY_DIR}/")


# if __name__ == "__main__":
#     main()



"""
inject.py — Seeded, logged error injection against a COPY of the clean baseline.

Design rule: every corruption this script makes is recorded in a ground-truth
table (data/dirty/ground_truth.csv) with the record's table, primary key, error
type, severity, and what changed. Step 3's validators never see this file —
it exists purely so we can measure precision/recall honestly at the end.

Implements the 12 error types from the framework doc, each injected into a
random ~5-10% sample of eligible records (see INJECTION_RATE / per-type notes).

Run:  python3 src/inject.py
In:   data/clean/*.csv        (untouched)
Out:  data/dirty/*.csv        (corrupted copies)
      data/dirty/ground_truth.csv
"""
import os
import sys
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import schema as S
from barcode import is_valid_ean13

SEED = 7  # deliberately different from the generator's seed (42)
TODAY = date(2026, 7, 1)  # must match generate.py's TODAY

CLEAN_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "clean")
DIRTY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "dirty")

# Severity tiers, matching the framework doc (tiered by downstream impact).
SEVERITY = {
    "referential_integrity": "Critical",
    "referential_timing": "High",
    "listing_conflict": "High",
    "header_item_date_mismatch": "Medium",
    "orphaned_cancelled_header": "Critical",
    "uom_pack_mismatch": "Medium",
    "tobacco_floor_breach": "Critical",
    "margin_breach": "High",
    "barcode_invalidity": "Critical",
    "duplicate_near_duplicate": "Low",
    "completeness": "Low",
    "stale_status": "Low",
}

DOWNSTREAM = {
    "referential_integrity": "Promo fails to load; price file rejects record",
    "referential_timing": "Promo advertised on an article stores can no longer order",
    "listing_conflict": "Advertised deal a customer physically can't buy in that store",
    "header_item_date_mismatch": "Item prices live when the campaign isn't, or vice versa",
    "orphaned_cancelled_header": "Old promo price still charged at POS",
    "uom_pack_mismatch": "Mechanic can't be applied; POS error",
    "tobacco_floor_breach": "Regulatory / compliance breach",
    "margin_breach": "Unintended loss-making sale",
    "barcode_invalidity": "Won't scan at POS; scan-and-go / self-checkout failure",
    "duplicate_near_duplicate": "Split sales reporting; double replenishment",
    "completeness": "Downstream tax/finance and ordering errors",
    "stale_status": "Expired promo still treated as active",
}


def load_clean():
    t = {n: pd.read_csv(os.path.join(CLEAN_DIR, f"{n}.csv")) for n in S.ALL_TABLES}
    # barcode is all-digit -> pandas infers int64; force back to string so we can
    # corrupt individual digits (and preserve leading behaviour) without dtype errors.
    t["article_master"]["barcode"] = t["article_master"]["barcode"].astype(str)
    return t


class GroundTruth:
    """Accumulates one row per injected error."""
    def __init__(self):
        self.rows = []
        self._seq = 0

    def log(self, table, record_id, error_type, field=None, old=None, new=None):
        self._seq += 1
        self.rows.append({
            "gt_id": f"GT{self._seq:05d}",
            "table_name": table,
            "record_id": record_id,
            "error_type": error_type,
            "severity": SEVERITY[error_type],
            "downstream_impact": DOWNSTREAM[error_type],
            "field_changed": field,
            "old_value": old,
            "new_value": new,
        })

    def to_df(self):
        return pd.DataFrame(self.rows, columns=[
            "gt_id", "table_name", "record_id", "error_type", "severity",
            "downstream_impact", "field_changed", "old_value", "new_value",
        ])


class Touched:
    """Tracks which primary keys have already been corrupted, per table.

    Every injector that MODIFIES an existing record (not just appends new rows)
    must (1) exclude already-touched pks from its candidate pool, and (2) mark
    its own pks as touched afterwards. This is what stops two injectors from
    silently overwriting each other's corruption on the same record -- the bug
    that caused orphaned_cancelled_header and uom_pack_mismatch to be
    clobbered by completeness in an earlier version of this script.
    """
    def __init__(self):
        self.sets = {
            "article_master": set(),
            "promotion_header": set(),
            "promotion_item": set(),
        }

    def untouched(self, df, pk_col, table):
        return df[~df[pk_col].isin(self.sets[table])]

    def mark(self, table, pks):
        self.sets[table].update(pks)


def sample_idx(df, frac, rng):
    """Random sample of row indices, 5-10% by default, at least 1 if any exist."""
    n = max(1, int(len(df) * frac)) if len(df) else 0
    if n == 0:
        return []
    return list(rng.choice(df.index, size=min(n, len(df)), replace=False))


# ---------------------------------------------------------------------
# Each injector: takes the tables dict + GroundTruth logger, mutates
# tables IN PLACE, logs every change. Returns nothing.
# ---------------------------------------------------------------------

def inject_referential_integrity(t, gt, rng, touched):
    """promotion_item.article_id points at an article that doesn't exist.

    Fake IDs use a distinct 'ARTFAKE' prefix -- deliberately outside the
    namespace used for real articles (ART00000-ART00599) and for
    duplicate_near_duplicate's new IDs (ART99000+), so a "nonexistent" fake ID
    can never accidentally collide with a real one.
    """
    items = t["promotion_item"]
    idx = sample_idx(items, 0.06, rng)
    for n, i in enumerate(idx):
        old = items.at[i, "article_id"]
        fake = f"ARTFAKE{n:03d}"
        items.at[i, "article_id"] = fake
        gt.log("promotion_item", items.at[i, "promo_item_id"],
                "referential_integrity", "article_id", old, fake)


def inject_referential_timing(t, gt, rng, touched):
    """Article was discontinued BEFORE the promo item's start date."""
    items = t["promotion_item"]
    art = t["article_master"]
    idx = sample_idx(items, 0.05, rng)
    touched_this_round = []
    for i in idx:
        aid = items.at[i, "article_id"]
        if aid in touched.sets["article_master"]:
            continue
        match = art.index[art.article_id == aid]
        if len(match) == 0:
            continue
        ai = match[0]
        old_status = art.at[ai, "status"]
        item_start = pd.to_datetime(items.at[i, "item_start"]).date()
        disc_date = item_start - timedelta(days=int(rng.integers(5, 60)))
        art.at[ai, "status"] = "discontinued"
        art.at[ai, "discontinued_date"] = disc_date.isoformat()
        gt.log("article_master", aid, "referential_timing",
                "status", old_status, "discontinued (after promo item_start)")
        touched_this_round.append(aid)
    touched.mark("article_master", touched_this_round)


def inject_listing_conflict(t, gt, rng, touched):
    """Promo item runs in a store group where the article isn't listed.

    Removing a listing row for (article, store_group) is a genuine conflict for
    EVERY promo_item that references that same pair, not just the one we sampled
    -- so we log all of them, or the ground truth would under-count real defects.
    """
    items = t["promotion_item"]
    headers = t["promotion_header"]
    listing = t["listing"]
    listed_pairs = set(zip(listing.article_id, listing.store_group))
    im = items.merge(headers[["promo_id", "store_group"]], on="promo_id")

    idx = sample_idx(items, 0.05, rng)
    pairs_to_remove = set()
    for i in idx:
        aid = items.at[i, "article_id"]
        pid = items.at[i, "promo_id"]
        h = headers.index[headers.promo_id == pid]
        if len(h) == 0:
            continue
        sg = headers.at[h[0], "store_group"]
        if (aid, sg) in listed_pairs:
            pairs_to_remove.add((aid, sg))

    drop_mask = pd.Series(False, index=listing.index)
    for aid, sg in pairs_to_remove:
        hit = listing.index[(listing.article_id == aid) & (listing.store_group == sg)]
        drop_mask.loc[hit] = True
        # log every promo_item that references this now-delisted (article, store_group)
        affected = im[(im.article_id == aid) & (im.store_group == sg)]
        for pit in affected.promo_item_id:
            gt.log("promotion_item", pit, "listing_conflict",
                    "listing_row", "listed", "removed (delisted)")
    t["listing"] = listing.loc[~drop_mask].reset_index(drop=True)


def inject_header_item_date_mismatch(t, gt, rng, touched):
    """Item validity dates fall outside the header campaign window."""
    items = t["promotion_item"]
    headers = t["promotion_header"].set_index("promo_id")
    idx = sample_idx(items, 0.06, rng)
    for i in idx:
        pid = items.at[i, "promo_id"]
        if pid not in headers.index:
            continue
        hend = pd.to_datetime(headers.at[pid, "header_end"]).date()
        old = items.at[i, "item_end"]
        new_end = hend + timedelta(days=int(rng.integers(2, 10)))
        items.at[i, "item_end"] = new_end.isoformat()
        gt.log("promotion_item", items.at[i, "promo_item_id"],
                "header_item_date_mismatch", "item_end", old, new_end.isoformat())


def inject_orphaned_cancelled_header(t, gt, rng, touched):
    """Header is cancelled/expired but its item(s) are still 'live' (future/current dates)."""
    headers = t["promotion_header"]
    candidates = headers.index[
        headers.approval_status.isin(["live", "approved"]) &
        ~headers.promo_id.isin(touched.sets["promotion_header"])
    ]
    # eligible pool here is naturally small (~30 of 120 headers), so use a higher
    # rate than the general 5-10% guideline to keep this Critical-severity check
    # meaningfully testable in step 3.
    idx = sample_idx(headers.loc[candidates], 0.25, rng)
    touched_this_round = []
    for h in idx:
        pid = headers.at[h, "promo_id"]
        old = headers.at[h, "approval_status"]
        headers.at[h, "approval_status"] = "cancelled"
        gt.log("promotion_header", pid, "orphaned_cancelled_header",
                "approval_status", old, "cancelled (items still active)")
        touched_this_round.append(pid)
    touched.mark("promotion_header", touched_this_round)


def inject_uom_pack_mismatch(t, gt, rng, touched):
    """Multibuy mechanic on an article that isn't sold as EA (e.g. CTN/PACK)."""
    items = t["promotion_item"]
    art = t["article_master"].set_index("article_id")
    candidates = items.index[
        (items.mechanic == "multibuy") &
        ~items.article_id.isin(touched.sets["article_master"])
    ]
    idx = sample_idx(items.loc[candidates], 0.30, rng)  # 30% of the (small) multibuy pool
    touched_this_round = []
    for i in idx:
        aid = items.at[i, "article_id"]
        if aid not in art.index:
            continue
        old_uom = art.at[aid, "base_uom"]
        art.at[aid, "base_uom"] = rng.choice(["CTN", "PACK"])
        gt.log("article_master", aid, "uom_pack_mismatch",
                "base_uom", old_uom, art.at[aid, "base_uom"])
        touched_this_round.append(aid)
    t["article_master"] = art.reset_index()
    touched.mark("article_master", touched_this_round)


def inject_tobacco_floor_breach(t, gt, rng, touched):
    """A promo item on a tobacco article priced below its regulated floor."""
    art = t["article_master"]
    headers = t["promotion_header"]
    items = t["promotion_item"]
    tobacco = art[(art.merch_category == "TOBACCO") & (art.status == "active")]
    idx = sample_idx(tobacco, 0.08, rng)
    listing = t["listing"]
    next_new_id = 99500
    for ti in idx:
        aid = art.at[ti, "article_id"]
        floor = art.at[ti, "cost_price"]  # fallback
        floor = art.at[ti, "tobacco_floor_price"]
        if pd.isna(floor):
            continue
        # find (or fabricate) a store group where it's listed
        rows = listing[listing.article_id == aid]
        if rows.empty:
            continue
        sg = rows.iloc[0].store_group
        # use an existing live header in that store group, else the first header
        h = headers[headers.store_group == sg]
        if h.empty:
            h = headers.iloc[[0]]
        pid = h.iloc[0].promo_id
        new_id = f"PIT{next_new_id}"
        next_new_id += 1
        cost = art.at[ti, "cost_price"]
        # keep the breach price strictly between cost and floor, so this is a
        # clean tobacco-floor violation only -- not one that also silently
        # trips the margin_breach check (that would conflate two error types).
        lo = float(cost) * 1.02
        hi = float(floor) * 0.97
        if lo >= hi:
            lo, hi = float(floor) * 0.90, float(floor) * 0.97
        breach_price = round(rng.uniform(lo, hi), 2)
        new_row = {
            "promo_item_id": new_id, "promo_id": pid, "article_id": aid,
            "mechanic": "fixed_price", "promo_price": breach_price,
            "discount_value": None, "multibuy_qty": None,
            "item_start": h.iloc[0].header_start, "item_end": h.iloc[0].header_end,
        }
        items.loc[len(items)] = new_row
        gt.log("promotion_item", new_id, "tobacco_floor_breach",
                "promo_price", f"floor={floor}", breach_price)


def inject_margin_breach(t, gt, rng, touched):
    """promo_price set below the article's cost_price."""
    items = t["promotion_item"]
    art = t["article_master"].set_index("article_id")
    candidates = items.index[items.mechanic.isin(["fixed_price", "multibuy"])]
    idx = sample_idx(items.loc[candidates], 0.05, rng)
    for i in idx:
        aid = items.at[i, "article_id"]
        if aid not in art.index:
            continue
        cost = art.at[aid, "cost_price"]
        old = items.at[i, "promo_price"]
        new_price = round(float(cost) * rng.uniform(0.6, 0.9), 2)
        items.at[i, "promo_price"] = new_price
        gt.log("promotion_item", items.at[i, "promo_item_id"],
                "margin_breach", "promo_price", old, new_price)


def inject_barcode_invalidity(t, gt, rng, touched):
    """Flip the EAN-13 check digit so it no longer validates."""
    art = t["article_master"]
    idx = sample_idx(art, 0.05, rng)
    touched_this_round = []
    for i in idx:
        old = art.at[i, "barcode"]
        bc = str(old)
        wrong_digit = str((int(bc[-1]) + rng.integers(1, 9)) % 10)
        new = bc[:-1] + wrong_digit
        if is_valid_ean13(new):  # extremely rare collision guard
            new = bc[:-1] + str((int(wrong_digit) + 1) % 10)
        art.at[i, "barcode"] = new
        gt.log("article_master", art.at[i, "article_id"],
                "barcode_invalidity", "barcode", old, new)
        touched_this_round.append(art.at[i, "article_id"])
    touched.mark("article_master", touched_this_round)


def inject_duplicate_near_duplicate(t, gt, rng, touched):
    """Append a near-duplicate article: same product, slightly different text/supplier.

    Samples from articles that haven't been touched by any prior injector, so a
    duplicate never silently inherits someone else's corruption (a bad barcode,
    a flipped status, a nulled field) into a new, unlogged article_id.

    New IDs are handed out sequentially (ART99000, ART99001, ...) rather than
    drawn randomly from a small range -- a random draw over ~1000 possible
    values with ~24 samples has a real chance of two different source articles
    colliding onto the same new article_id, which would duplicate a "primary
    key" and silently corrupt any join on article_id. Sequential IDs guarantee
    uniqueness.
    """
    art = t["article_master"]
    pool = art[~art.article_id.isin(touched.sets["article_master"])]
    idx = sample_idx(pool, 0.04, rng)
    new_rows = []
    new_ids = []
    next_new_id = 99000
    for i in idx:
        src = art.loc[i].copy()
        new_id = f"ART{next_new_id}"
        next_new_id += 1
        suffix = rng.choice([" - NEW", " (Promo Pack)", " V2", ""])
        src["article_id"] = new_id
        src["article_description"] = str(src["article_description"]) + suffix
        src["created_date"] = TODAY.isoformat()
        src["last_modified_date"] = TODAY.isoformat()
        new_rows.append(src)
        new_ids.append(new_id)
        gt.log("article_master", new_id, "duplicate_near_duplicate",
                "article_id", art.at[i, "article_id"], new_id)
    if new_rows:
        t["article_master"] = pd.concat(
            [art, pd.DataFrame(new_rows)], ignore_index=True
        )
    touched.mark("article_master", new_ids)


def inject_completeness(t, gt, rng, touched):
    """Null out a required field on article_master or promotion_header."""
    art = t["article_master"]
    headers = t["promotion_header"]
    art_pool = art[~art.article_id.isin(touched.sets["article_master"])]
    hdr_pool = headers[~headers.promo_id.isin(touched.sets["promotion_header"])]

    idx_a = sample_idx(art_pool, 0.04, rng)
    touched_articles = []
    for i in idx_a:
        field = rng.choice(["base_uom", "tax_code"])
        old = art.at[i, field]
        art.at[i, field] = None
        gt.log("article_master", art.at[i, "article_id"], "completeness",
                field, old, None)
        touched_articles.append(art.at[i, "article_id"])
    touched.mark("article_master", touched_articles)

    idx_h = sample_idx(hdr_pool, 0.03, rng)
    touched_headers = []
    for i in idx_h:
        old = headers.at[i, "approval_status"]
        headers.at[i, "approval_status"] = None
        gt.log("promotion_header", headers.at[i, "promo_id"], "completeness",
                "approval_status", old, None)
        touched_headers.append(headers.at[i, "promo_id"])
    touched.mark("promotion_header", touched_headers)


def inject_stale_status(t, gt, rng, touched):
    """approval_status = 'live' but header_end has already passed."""
    headers = t["promotion_header"]
    past = headers.index[
        (pd.to_datetime(headers.header_end).dt.date < TODAY) &
        ~headers.promo_id.isin(touched.sets["promotion_header"])
    ]
    idx = sample_idx(headers.loc[past], 0.20, rng)  # 20% of past promos
    touched_this_round = []
    for i in idx:
        old = headers.at[i, "approval_status"]
        if old == "live":
            continue
        headers.at[i, "approval_status"] = "live"
        gt.log("promotion_header", headers.at[i, "promo_id"], "stale_status",
                "approval_status", old, "live")
        touched_this_round.append(headers.at[i, "promo_id"])
    touched.mark("promotion_header", touched_this_round)


INJECTORS = [
    inject_referential_integrity,
    inject_referential_timing,
    inject_listing_conflict,
    inject_header_item_date_mismatch,
    inject_orphaned_cancelled_header,
    inject_uom_pack_mismatch,
    inject_tobacco_floor_breach,
    inject_margin_breach,
    inject_barcode_invalidity,
    inject_duplicate_near_duplicate,
    inject_completeness,
    inject_stale_status,
]


def main():
    rng = np.random.default_rng(SEED)
    random.seed(SEED)

    t = load_clean()
    gt = GroundTruth()
    touched = Touched()

    for fn in INJECTORS:
        fn(t, gt, rng, touched)

    os.makedirs(DIRTY_DIR, exist_ok=True)
    for name, df in t.items():
        df.to_csv(os.path.join(DIRTY_DIR, f"{name}.csv"), index=False)

    gt_df = gt.to_df()
    gt_df.to_csv(os.path.join(DIRTY_DIR, "ground_truth.csv"), index=False)

    print(f"Injected {len(gt_df)} errors (seed={SEED}) across {gt_df.error_type.nunique()} types:")
    print(gt_df.groupby(["error_type", "severity"]).size().to_string())
    print(f"\nWritten to {DIRTY_DIR}/")


if __name__ == "__main__":
    main()

     
    import sys; sys.path.insert(0,'src')
    from validate import load_dirty, CHECKS
    t = load_dirty()
    import pandas as pd
    allx = pd.concat([fn(t) for fn in CHECKS], ignore_index=True)
    print(allx.error_type.value_counts())
    