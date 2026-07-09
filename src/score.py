"""
score.py — Score the validation engine's exceptions against ground truth.

Some checks report at promo_item level (Option A: one row per operationally
affected line -- e.g. one flag per promo line still charging a stale price)
while ground truth logs the root-cause record instead (one article, one
promo header). To score fairly, each such error type is reconciled onto
whichever key ground truth actually used, before comparing sets.

Run:  python3 src/score.py
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from validate import load_dirty, CHECKS

DIRTY = os.path.join(os.path.dirname(__file__), "..", "data", "dirty")

# error types where our check reports promo_item_id, but ground truth logs a
# DIFFERENT key -- map each promo_item_id back onto that key before scoring.
RECONCILE_TO_ARTICLE = {"referential_timing", "uom_pack_mismatch"}
RECONCILE_TO_PROMO_HEADER = {"orphaned_cancelled_header"}

# our check was renamed after the AU tobacco-law correction; ground truth
# (generated before the rename) still uses the old name.
NAME_ALIASES = {"tobacco_on_promotion": "tobacco_floor_breach"}


def reconcile_key(row, items_lookup):
    et = row["error_type"]
    rid = row["record_id"]
    if et in RECONCILE_TO_ARTICLE:
        return items_lookup.get(rid, {}).get("article_id", rid)
    if et in RECONCILE_TO_PROMO_HEADER:
        return items_lookup.get(rid, {}).get("promo_id", rid)
    return rid


def main():
    t = load_dirty()
    items = t["promotion_item"]
    items_lookup = items.set_index("promo_item_id")[["article_id", "promo_id"]].to_dict("index")

    exceptions = pd.concat([fn(t) for fn in CHECKS], ignore_index=True)
    exceptions["gt_key"] = exceptions.apply(lambda r: reconcile_key(r, items_lookup), axis=1)
    exceptions["gt_error_type"] = exceptions["error_type"].replace(NAME_ALIASES)

    gt = pd.read_csv(os.path.join(DIRTY, "ground_truth.csv"))

    results = []
    for et in sorted(set(gt.error_type) | set(exceptions.gt_error_type)):
        found = set(exceptions.loc[exceptions.gt_error_type == et, "gt_key"])
        actual = set(gt.loc[gt.error_type == et, "record_id"])

        tp = len(found & actual)
        fp = len(found - actual)
        fn_ = len(actual - found)

        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn_) if (tp + fn_) else float("nan")

        results.append({
            "error_type": et,
            "ground_truth": len(actual),
            "found": len(found),
            "TP": tp, "FP": fp, "FN": fn_,
            "precision": round(precision, 3) if precision == precision else None,
            "recall": round(recall, 3) if recall == recall else None,
        })

    results_df = pd.DataFrame(results)
    results_df.to_csv(os.path.join(DIRTY, "scorecard.csv"), index=False)
    print(results_df.to_string(index=False))

    tp_total = results_df.TP.sum()
    fp_total = results_df.FP.sum()
    fn_total = results_df.FN.sum()
    overall_p = tp_total / (tp_total + fp_total)
    overall_r = tp_total / (tp_total + fn_total)
    f1 = 2 * overall_p * overall_r / (overall_p + overall_r)

    print()
    print(f"OVERALL  precision={overall_p:.1%}  recall={overall_r:.1%}  f1={f1:.1%}  "
          f"(TP={tp_total}, FP={fp_total}, FN={fn_total})")

    return results_df


if __name__ == "__main__":
    main()