# Convenience Retail Master Data Quality Engine — Step 2

**Status:** Step 2 of 6 complete — seeded error injection + verified ground truth.

## What step 2 delivers

`src/inject.py` takes the clean baseline from step 1, corrupts a copy of it with
all 12 error types from the framework doc, and logs every single change to
`data/dirty/ground_truth.csv`. `src/verify_injection.py` then independently
re-derives every violation from the dirty data and checks it against the
ground truth — proving the key is accurate before step 3 (the validators) is
allowed to depend on it.

## Files

| File | What it does |
|------|--------------|
| `src/inject.py` | Seeded (SEED=7) injector. 12 functions, one per error type, each sampling ~5–30% of its eligible pool (rate varies where the eligible pool is naturally small — see code comments). |
| `src/verify_injection.py` | Independently re-checks every error type against the dirty data. Fails loudly on any mismatch between what's logged and what's actually there. |

## How to run

```bash
python3 src/inject.py             # writes data/dirty/*.csv + ground_truth.csv
python3 src/verify_injection.py   # proves the ground truth is accurate
python3 src/verify_clean.py       # re-confirm data/clean/ was never touched
```

## Result (seed=7)

251 errors injected across all 12 types, e.g.:

| Error type | Severity | Count |
|---|---|---|
| barcode_invalidity | Critical | 30 |
| referential_integrity | Critical | 29 |
| orphaned_cancelled_header | Critical | 7 |
| tobacco_floor_breach | Critical | 7 |
| listing_conflict | High | 26 |
| referential_timing | High | 23 |
| margin_breach | High | 11 |
| header_item_date_mismatch | Medium | 29 |
| uom_pack_mismatch | Medium | 27 |
| completeness | Low | 27 |
| stale_status | Low | 13 |
| duplicate_near_duplicate | Low | 22 |

All 12 independently re-verified as an exact match against ground truth.

## The debugging story (worth knowing for interview)

The first pass of `verify_injection.py` found **4 real mismatches** — not
calculation slips, but genuine cascading side effects between injectors
corrupting the same underlying data from two directions at once:

1. **Listing conflicts cascaded silently.** Removing one listing row for
   (article, store_group) is a real conflict for *every* promo item that
   references that same pair — not just the one row I'd sampled. Fixed by
   logging every affected promo item when a listing pair is removed.

2. **UOM check false positive.** My *verification* logic flagged nulled
   `base_uom` values (from the `completeness` injector) as UOM mismatches,
   because `NaN != 'EA'` evaluates `True` in pandas. Not an injector bug — a
   check-script bug. Fixed by excluding nulls, which are already a different,
   correctly-logged error type.

3. **Tobacco floor-breach items accidentally also breached margin.** The
   synthetic below-floor price sometimes landed below cost too, silently
   tripping an unlogged margin_breach. Fixed by clamping the injected price to
   sit strictly between cost and floor, keeping each error type's example
   clean and singular.

4. **Duplicates could inherit a corrupted barcode.** If `duplicate_near_duplicate`
   copied an article that `barcode_invalidity` had already corrupted, the new
   duplicate silently carried the bad barcode into an unlogged article_id.
   Fixed by excluding already-corrupted articles from the duplicate sampling
   pool.

5. **A referential-integrity fake article_id looked like a listing conflict
   too.** A promo item pointing at a nonexistent article trivially has no
   listing rows either — my check was initially counting that as a *second*,
   independent defect. Fixed by excluding nonexistent articles from the
   listing_conflict check's scope (that gap is already captured under
   referential_integrity).

This is the actual value of building a ground-truth verification step: it
surfaces exactly the kind of cross-contamination that a real messy dataset
also has, and forces a decision about how to count it. Being able to explain
*why* four checks initially failed and how each was reasoned through is a
stronger interview answer than a clean run that never had to explain anything.

## Next: step 3

The validation rule engine — pandas/SQL checks that scan `data/dirty/` and
independently rediscover these errors, scored for precision/recall against
`ground_truth.csv`.
