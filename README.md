# Convenience Retail Master Data Quality Engine

**[Live demo](https://retail-data-quality-engine.streamlit.app)** · Python · pandas · RapidFuzz · Streamlit

A master data quality engine for promotion and article data, modelled on convenience retail.
It generates a realistic dataset, deliberately corrupts a known subset of it, then independently
detects those defects and scores itself against a ground-truth key it never sees.

**100% recall, 98.4% precision** across 12 validation checks and 1,127 records.

---

## What this is, and what it isn't

This project demonstrates how retail master data is structured, what breaks in it, and how to catch
that systematically rather than case by case.

**It is not built in SAP, and it contains no real company data.** The six tables mirror SAP ECC Retail
structures (MARA, WAKH/WAKP, WLK1) so the domain reasoning is visible, but everything here is
synthetic and written in Python. "Store24" is a fictional retailer.

That distinction is stated plainly rather than glossed over. The value is in the reasoning, not in a
claim of tool experience.

---

## The problem

A retail promotion touches article master data, pricing, listing/ranging, store operations, and
finance. When the underlying master data is wrong, the failure surfaces at the till: a deal that
won't scan, a promotion advertised where the product isn't stocked, an expired campaign still
charging its old price, or a discount that breaches regulation.

These defects are rarely dramatic. They're a wrong check digit, a date that slipped outside a
campaign window, a status nobody closed out. They're also cheap to catch upstream and expensive to
find in production.

---

## How it works

```
generate.py  →  clean, verified baseline (6 tables, 1,127 records)
     ↓
inject.py    →  246 seeded defects + ground-truth key
     ↓
validate.py  →  12 independent checks → 300 exceptions
     ↓
score.py     →  precision / recall vs. the hidden key
     ↓
app.py       →  Streamlit worklist + detection scorecard
```

**1 — Generate.** A seeded generator builds six SAP-pattern tables: articles with a real
single/generic/variant hierarchy, site-level data, listing conditions, promotion headers, promotion
items, and a change log. Convenience-retail realities are modelled deliberately: fuel priced per
litre, tobacco under regulatory constraint, promotions running Thursday-to-Wednesday promo weeks,
and franchise store groups that don't all range the same articles.

**2 — Verify the baseline.** Ten assertions confirm the clean data genuinely satisfies every rule
*before* anything is corrupted. Without this, the ground-truth key would be measured against data
that was already broken, and the detection score would mean nothing.

**3 — Inject.** A second seeded pass corrupts a copy with 12 defect types, logging every change. A
shared "touched" registry prevents two injectors from silently overwriting each other on the same
record — a bug found and fixed during development, and the reason the ground truth is trustworthy.

**4 — Validate.** Twelve independent checks scan the corrupted data. Each returns the affected
record, error type, severity tier, the downstream system that breaks, and a plain-English
description.

**5 — Score.** Detected exceptions are reconciled onto the ground-truth key's counting unit, then
compared.

---

## The twelve checks

| Check | Severity | What it catches |
|---|---|---|
| Referential integrity | Critical | Promotion references an article that doesn't exist |
| Barcode invalidity | Critical | EAN-13 check digit fails — won't scan at the till |
| Orphaned cancelled header | Critical | Cancelled campaign whose promotion lines still run |
| Tobacco on promotion | Critical | Tobacco promoted at all — not legal in Australia |
| Referential timing | High | Article discontinued *before* its promotion started |
| Listing conflict | High | Deal advertised where the article isn't ranged |
| Margin breach | High | Promotion priced below cost |
| Header/item date mismatch | Medium | Promotion line runs outside its campaign window |
| UOM / pack mismatch | Medium | "3 for $5" on an article sold only by the carton |
| Completeness | Low | Required fields missing — UOM, tax code, approval status |
| Duplicate / near-duplicate | Low | Same product entered twice under different IDs |
| Stale status | Low | Promotion still marked live after its end date passed |

**Severity is assigned by which downstream system breaks**, not by intuition. A tobacco promotion is
Critical because it's a compliance breach. An invalid barcode is Critical because the item physically
will not scan. A missing tax code is Low because it's wrong but self-limiting.

---

## Results

| | |
|---|---|
| Records scanned | 1,127 |
| Defects injected | 246 |
| Exceptions raised | 300 |
| True positives | 243 |
| False positives | 4 |
| **False negatives** | **0** |
| **Recall** | **100%** |
| **Precision** | **98.4%** |

**Why 300 exceptions from 246 defects?** The counting units differ, deliberately. One discontinued
article can sit on several promotion lines. The ground-truth key logs the single root-cause article;
the worklist reports every affected line, because that's what an analyst actually has to fix. The
scorer reconciles the two before comparing, so it's always comparing like with like.

**Where the 4 false positives come from.** All of them are in near-duplicate detection, and they
aren't noise. When one article is duplicated, the copy legitimately scores highly against *several*
existing sibling variants whose descriptions are near-identical. A stricter similarity threshold
would remove them — and would also start missing real duplicates. This engine is tuned to catch
every genuine defect rather than to report a flawless precision figure.

---

## Design decisions worth defending

**Barcode validation uses real EAN-13 check-digit arithmetic**, not a length or format test. A
transposed digit produces a number that looks valid and fails at the register.

**The clean baseline is verified before it's corrupted.** This is the difference between a detection
metric that means something and one that doesn't.

**Near-duplicate detection excludes legitimate parent/variant relationships.** A generic article and
its own size variants are *supposed* to share near-identical descriptions. Flagging them would be a
false positive created by the check itself, not found by it.

**Tobacco is treated as non-promotable outright.** The Public Health (Tobacco and Other Products)
Act 2023 bans tobacco promotion almost entirely in Australia. Appearing on a promotion *is* the
breach — not merely being priced below a floor. An earlier version of this project checked for a
floor-price breach; that was the wrong rule for this market.

**Everything is seeded.** The dataset, the corruption, and therefore the metrics are all
reproducible. `98.4%` is a number you can regenerate, not one you have to take on trust.

---

## Running it

```bash
pip install -r requirements.txt

python3 src/generate.py        # build the clean baseline
python3 src/verify_clean.py    # prove it's actually clean
python3 src/inject.py          # corrupt it, log ground truth
python3 src/verify_injection.py  # prove the ground truth is accurate
python3 src/validate.py        # run the 12 checks
python3 src/score.py           # precision / recall

streamlit run src/app.py       # dashboard
```

---

## Repository

```
src/
  schema.py            six-table model + SAP equivalents
  barcode.py           EAN-13 check-digit arithmetic (self-testing)
  generate.py          seeded clean-data generator
  verify_clean.py      ten assertions on the baseline
  inject.py            seeded corruption + ground-truth key
  verify_injection.py  proves the key matches the data
  validate.py          the twelve checks
  score.py             precision / recall reconciliation
  app.py               Streamlit dashboard
data/
  clean/               verified baseline
  dirty/               corrupted data, ground truth, exceptions, scorecard
```

---

## Governance note

A one-page governance note accompanies this project, tracing the twelve defect types back to five
root-cause process gaps and proposing eight preventive controls — the argument being that these are
process failures, not twelve unrelated mistakes, and that catching them at entry beats catching them
at the till.