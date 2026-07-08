"""
generate.py — Seeded generator for a CLEAN convenience-retail dataset.

Produces six internally-consistent tables:
  - every foreign key resolves
  - every barcode has a valid EAN-13 check digit
  - every promotion item sits inside its header's window
  - promoted articles are listed in the promo's store group
  - no tobacco floor breach, no margin breach

Cleanliness is the point. Step 2 (inject.py) corrupts a copy of this against a
logged ground-truth key, so detection metrics are honest and reproducible.

Run:  python3 src/generate.py
Out:  data/clean/*.csv
"""

import os
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

# allow running as `python3 src/generate.py` from project root
import sys
sys.path.insert(0, os.path.dirname(__file__))

import schema as S
from barcode import make_valid_ean13

SEED = 42
N_ARTICLES = 600          # target article-master row count (approx; hierarchy adds children)
N_PROMOS = 120            # promotion headers
N_STORE_GROUPS = 40       # franchise store groups
TODAY = date(2026, 7, 1)  # a fixed "today" so the dataset is reproducible

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "clean")


def _rng():
    random.seed(SEED)
    np.random.seed(SEED)


def _d(d: date) -> str:
    return d.isoformat()


def _rand_date(start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=random.randint(0, max(span, 0)))


# 7-Eleven promo weeks run Thursday -> Wednesday. Promos therefore start on a
# Thursday and end on a Wednesday. weekday(): Mon=0 ... Thu=3 ... Sun=6.
def _next_thursday(d: date) -> date:
    """Snap forward to the nearest Thursday (same day if already Thursday)."""
    return d + timedelta(days=(3 - d.weekday()) % 7)


def _promo_week_window():
    """Return (start_thursday, end_wednesday, n_weeks) with a weekly-dominant mix.

    ~70% one week, ~20% two weeks, ~10% three-to-four weeks. A one-week promo is
    Thu -> the following Wed (7 days inclusive), so end = start + 7*weeks - 1.
    """
    n_weeks = int(np.random.choice([1, 2, 3, 4], p=[0.70, 0.20, 0.06, 0.04]))
    raw_start = _rand_date(TODAY - timedelta(days=120), TODAY + timedelta(days=60))
    start = _next_thursday(raw_start)
    end = start + timedelta(days=7 * n_weeks - 1)  # lands on a Wednesday
    return start, end, n_weeks


# --------------------------------------------------------------------------
# Store groups
# --------------------------------------------------------------------------
def make_store_groups():
    # e.g. SG_METRO_01 ... realistic-ish franchise grouping names
    regions = ["METRO", "REGIONAL", "HWY", "CBD"]
    groups = []
    for i in range(N_STORE_GROUPS):
        region = regions[i % len(regions)]
        groups.append(f"SG_{region}_{i:02d}")
    return groups


# --------------------------------------------------------------------------
# Article master (with real hierarchy)
# --------------------------------------------------------------------------
def make_articles():
    rows = []
    barcode_seq = 100000000  # 9-digit body counter; prefix keeps 12-digit bodies
    art_seq = 0

    def next_barcode():
        nonlocal barcode_seq
        body = f"93{barcode_seq:010d}"  # 12 digits: '93' + 10
        barcode_seq += 1
        return make_valid_ean13(body)

    def next_id():
        nonlocal art_seq
        aid = f"ART{art_seq:05d}"
        art_seq += 1
        return aid

    cats = list(S.MERCH_CATEGORIES.keys())

    while len(rows) < N_ARTICLES:
        cat = random.choice(cats)
        meta = S.MERCH_CATEGORIES[cat]
        sub = random.choice(meta["sub"])

        # decide structure: mostly singles, some generic+variants, a few displays/prepacks.
        # Fuel is always a single per-litre article (no variants/multipacks/displays) —
        # a convenience retailer would never model fuel as a generic with variants.
        if cat == "FUEL":
            structure = "single"
        else:
            roll = random.random()
            if roll < 0.72:
                structure = "single"
            elif roll < 0.90:
                structure = "generic_with_variants"
            elif roll < 0.96:
                structure = "prepack"
            else:
                structure = "display"

        lo, hi = meta["price_range"]

        def make_prices():
            cost = round(random.uniform(lo, hi) * random.uniform(0.55, 0.80), 2)
            markup = random.uniform(1.25, 1.9)
            listp = round(cost * markup, 2)
            return cost, listp

        def base_row(aid, desc, atype, parent, uom):
            cost, listp = make_prices()
            floor = None
            if meta["tobacco"]:
                # regulated minimum sits just under list price
                floor = round(listp * random.uniform(0.90, 0.97), 2)
            # status: mostly active, some discontinued/pending
            status = np.random.choice(
                S.ARTICLE_STATUS, p=[0.85, 0.10, 0.05]
            )
            disc_date = None
            if status == "discontinued":
                disc_date = _d(_rand_date(TODAY - timedelta(days=365), TODAY))
            created = _rand_date(date(2022, 1, 1), TODAY - timedelta(days=30))
            modified = _rand_date(created, TODAY)
            return {
                "article_id": aid,
                "article_description": desc,
                "article_type": atype,
                "parent_article_id": parent,
                "merch_category": cat,
                "sub_category": sub,
                "base_uom": uom,
                "barcode": next_barcode(),
                "tax_code": meta["tax_code"],
                "list_price": listp,
                "cost_price": cost,
                "tobacco_floor_price": floor,
                "status": status,
                "discontinued_date": disc_date,
                "created_date": _d(created),
                "last_modified_date": _d(modified),
            }

        if structure == "single":
            aid = next_id()
            desc = f"{sub} {random.choice(['Reg','Std','Classic','Large','Small'])} {random.randint(100,999)}"
            rows.append(base_row(aid, desc, "single", None, meta["base_uom"]))

        elif structure == "generic_with_variants":
            gid = next_id()
            gdesc = f"{sub} Range {random.randint(100,999)}"
            rows.append(base_row(gid, gdesc, "generic", None, meta["base_uom"]))
            # variant descriptors that make sense for the category
            variant_sizes = {
                "DRINKS_COLD": ["375ml", "600ml", "1.25L", "Can", "Multipack"],
                "FOOD_TO_GO": ["Single", "Twin Pack", "Family", "Regular", "Large"],
                "CONFECTIONERY": ["Fun Size", "Standard", "Share Pack", "King Size"],
                "TOBACCO": ["20s", "25s", "30s", "40s"],
            }
            sizes = variant_sizes.get(cat, ["Standard", "Large", "Multipack"])
            n_var = random.randint(2, min(4, len(sizes)))
            for vsize in random.sample(sizes, n_var):
                if len(rows) >= N_ARTICLES:
                    break
                vid = next_id()
                vdesc = f"{gdesc} - {vsize}"
                rows.append(base_row(vid, vdesc, "variant", gid, meta["base_uom"]))

        elif structure == "prepack":
            aid = next_id()
            desc = f"{sub} Prepack {random.randint(6,24)}pk {random.randint(100,999)}"
            rows.append(base_row(aid, desc, "prepack", None, "PACK"))

        else:  # display
            aid = next_id()
            desc = f"{sub} Counter Display {random.randint(100,999)}"
            rows.append(base_row(aid, desc, "display", None, "CTN"))

    df = pd.DataFrame(rows, columns=S.ARTICLE_MASTER_COLS)
    S.assert_schema(df, "article_master")
    return df


# --------------------------------------------------------------------------
# Listing (which articles ranged in which store groups)
# --------------------------------------------------------------------------
def make_listing(articles, store_groups):
    rows = []
    active = articles[articles.status != "discontinued"]
    for _, art in active.iterrows():
        # each active article listed in a random subset of store groups
        k = random.randint(max(1, N_STORE_GROUPS // 4), N_STORE_GROUPS)
        chosen = random.sample(store_groups, k)
        for sg in chosen:
            vf = _rand_date(date(2023, 1, 1), TODAY - timedelta(days=60))
            rows.append({
                "store_group": sg,
                "article_id": art.article_id,
                "valid_from": _d(vf),
                "valid_to": _d(date(2099, 12, 31)),  # open-ended listing
            })
    df = pd.DataFrame(rows, columns=S.LISTING_COLS)
    S.assert_schema(df, "listing")
    return df


# --------------------------------------------------------------------------
# Article-site (local price / stock per store group) — kept lean
# --------------------------------------------------------------------------
def make_article_site(articles, listing):
    rows = []
    # one row per (article, store_group) that is listed
    for _, l in listing.iterrows():
        art = articles.loc[articles.article_id == l.article_id].iloc[0]
        # local price = list price +/- small franchisee variation
        local = round(float(art.list_price) * random.uniform(0.98, 1.06), 2)
        rows.append({
            "article_id": l.article_id,
            "store_group": l.store_group,
            "site_list_price": local,
            "listed": True,
            "stock_status": np.random.choice(
                ["in_stock", "out_of_stock"], p=[0.9, 0.1]
            ),
            "last_modified_date": _d(_rand_date(date(2024, 1, 1), TODAY)),
        })
    df = pd.DataFrame(rows, columns=S.ARTICLE_SITE_COLS)
    S.assert_schema(df, "article_site")
    return df


# --------------------------------------------------------------------------
# Promotions (header + item), all clean & consistent
# --------------------------------------------------------------------------
def make_promotions(articles, listing, store_groups):
    headers, items = [], []
    item_seq = 0

    # only promote articles that are (a) active, (b) in a promotable category
    promotable_cats = [c for c, m in S.MERCH_CATEGORIES.items() if m["promotable"]]
    promo_pool = articles[
        (articles.status == "active") &
        (articles.merch_category.isin(promotable_cats))
    ]

    # index listing for quick "is this article listed in this store group" checks
    listed_pairs = set(zip(listing.article_id, listing.store_group))

    themes = ["Summer Cooler", "Meal Deal", "Snack Attack", "Fuel Saver",
              "Winter Warmer", "Grab & Go", "Weekend Special", "Thirsty Thursday"]

    for p in range(N_PROMOS):
        sg = random.choice(store_groups)
        # 7-Eleven promo week: Thursday start, Wednesday end, weekly-dominant length
        hstart, hend, n_weeks = _promo_week_window()

        # approval status consistent with dates
        if hend < TODAY:
            status = "expired"
        elif hstart > TODAY:
            status = np.random.choice(["draft", "approved"], p=[0.4, 0.6])
        else:
            status = "live"

        pid = f"PRM{p:05d}"
        headers.append({
            "promo_id": pid,
            "promo_theme": f"{random.choice(themes)} {hstart.year}",
            "header_start": _d(hstart),
            "header_end": _d(hend),
            "store_group": sg,
            "approval_status": status,
            "created_by": random.choice(["jchen", "mpatel", "swilson", "rkhan"]),
            "created_date": _d(_rand_date(hstart - timedelta(days=30), hstart)),
        })

        # pick 2-6 articles for this promo that ARE listed in this store group
        eligible = [a for a in promo_pool.article_id
                    if (a, sg) in listed_pairs]
        if not eligible:
            continue
        n_items = min(len(eligible), random.randint(2, 6))
        chosen = random.sample(eligible, n_items)

        for aid in chosen:
            art = articles.loc[articles.article_id == aid].iloc[0]
            mech = random.choice(S.PROMO_MECHANICS)

            promo_price = discount_value = multibuy_qty = None
            listp, cost = float(art.list_price), float(art.cost_price)

            if mech == "fixed_price":
                # between cost and list (never below cost -> no margin breach)
                promo_price = round(random.uniform(cost * 1.02, listp * 0.95), 2)
            elif mech == "percent_off":
                discount_value = random.choice([10, 15, 20, 25])
                # ensure resulting price stays >= cost
                if listp * (1 - discount_value / 100) < cost:
                    discount_value = 10
            elif mech == "dollar_off":
                max_off = max(0.5, round(listp - cost - 0.5, 2))
                discount_value = round(random.uniform(0.5, max(0.5, max_off)), 2)
            else:  # multibuy — only valid on EA-based articles in clean data
                if art.base_uom != "EA":
                    mech = "fixed_price"
                    promo_price = round(random.uniform(cost * 1.02, listp * 0.95), 2)
                else:
                    multibuy_qty = random.choice([2, 3])
                    promo_price = round(listp * multibuy_qty * random.uniform(0.75, 0.9), 2)

            # In real weekly promos, items almost always run the full promo week.
            # Default: item window == header window. On multi-week promos, a small
            # share of items legitimately join for only part of the run (still
            # inside the header, so still clean).
            istart, iend = hstart, hend
            if n_weeks > 1 and random.random() < 0.15:
                # a later "week 2" start, still ending on the header end (Wednesday)
                istart = hstart + timedelta(days=7 * random.randint(1, n_weeks - 1))
            if iend < istart:
                istart, iend = hstart, hend

            items.append({
                "promo_item_id": f"PIT{item_seq:06d}",
                "promo_id": pid,
                "article_id": aid,
                "mechanic": mech,
                "promo_price": promo_price,
                "discount_value": discount_value,
                "multibuy_qty": multibuy_qty,
                "item_start": _d(istart),
                "item_end": _d(iend),
            })
            item_seq += 1

    hdf = pd.DataFrame(headers, columns=S.PROMOTION_HEADER_COLS)
    idf = pd.DataFrame(items, columns=S.PROMOTION_ITEM_COLS)
    S.assert_schema(hdf, "promotion_header")
    S.assert_schema(idf, "promotion_item")
    return hdf, idf


# --------------------------------------------------------------------------
# Change log (audit trail) — a 'create' row per master record + some updates
# --------------------------------------------------------------------------
def make_change_log(articles, headers):
    rows = []
    cid = 0
    for _, a in articles.iterrows():
        rows.append({
            "change_id": f"CHG{cid:07d}", "table_name": "article_master",
            "record_id": a.article_id, "change_type": "create",
            "field_changed": None, "old_value": None, "new_value": None,
            "changed_by": random.choice(["jchen", "mpatel", "swilson", "rkhan"]),
            "changed_at": a.created_date,
        })
        cid += 1
    for _, h in headers.iterrows():
        rows.append({
            "change_id": f"CHG{cid:07d}", "table_name": "promotion_header",
            "record_id": h.promo_id, "change_type": "create",
            "field_changed": None, "old_value": None, "new_value": None,
            "changed_by": h.created_by, "changed_at": h.created_date,
        })
        cid += 1
    df = pd.DataFrame(rows, columns=S.CHANGE_LOG_COLS)
    S.assert_schema(df, "change_log")
    return df


# --------------------------------------------------------------------------
def main():
    _rng()
    os.makedirs(OUT_DIR, exist_ok=True)

    store_groups = make_store_groups()
    articles = make_articles()
    listing = make_listing(articles, store_groups)
    article_site = make_article_site(articles, listing)
    headers, items = make_promotions(articles, listing, store_groups)
    change_log = make_change_log(articles, headers)

    tables = {
        "article_master": articles,
        "article_site": article_site,
        "listing": listing,
        "promotion_header": headers,
        "promotion_item": items,
        "change_log": change_log,
    }
    for name, df in tables.items():
        path = os.path.join(OUT_DIR, f"{name}.csv")
        df.to_csv(path, index=False)

    print("Clean dataset generated (seed = %d):" % SEED)
    for name, df in tables.items():
        print(f"  {name:18s} {len(df):6d} rows -> {S.SAP_EQUIVALENT[name]}")
    return tables


if __name__ == "__main__":
    main()
