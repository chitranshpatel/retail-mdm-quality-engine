# Convenience Retail Master Data Quality Engine — Step 1

**Status:** Step 1 of 6 complete — schema + clean synthetic data generator.

This is a simulated framework. The data structures and business rules mirror
SAP ECC Retail, but nothing here runs in SAP. See the framework doc for the
full honesty framing.

## What step 1 delivers

A **seeded, reproducible, verifiably-clean** convenience-retail dataset across
six SAP-pattern tables. "Clean" means every foreign key resolves, every barcode
is a valid EAN-13, every promotion is internally consistent, and no business
rule is violated. This clean baseline is the foundation for step 2, which will
inject known errors against a ground-truth key.

## Files

| File | What it does |
|------|--------------|
| `src/schema.py` | Single source of truth: all six tables, their columns, controlled vocabularies, and the verified SAP-equivalent mapping. |
| `src/barcode.py` | Real EAN-13 check-digit maths (generate + validate). Self-tests when run directly. |
| `src/generate.py` | Seeded generator producing the clean dataset into `data/clean/`. |
| `src/verify_clean.py` | Ten assertions proving the baseline is actually clean. Exits non-zero if not. |

## How to run

```bash
cd mdq_engine
python3 src/generate.py       # writes data/clean/*.csv
python3 src/verify_clean.py   # proves the baseline is clean
```

## The six tables (and their SAP equivalents)

| Our table | SAP equivalent | Rows (seed 42) |
|-----------|----------------|----------------|
| article_master | MARA | 600 |
| article_site | MARC / MVKE | ~13k |
| listing | WLK1 | ~13k |
| promotion_header | WAKH | 120 |
| promotion_item | WAKP | ~500 |
| change_log | CDHDR / CDPOS | 720 |

## Design decisions worth being able to defend

1. **Article hierarchy is real.** Articles have a type (single / generic /
   variant / display / prepack) and variants point at a generic parent via
   `parent_article_id` — this mirrors SAP's MARA-SATNR. A flat article list
   would not read as SAP Retail.

2. **Fuel is always a single article.** Fuel is sold per-litre, not as
   generic/variant SKUs. Modelling it with variants would be a giveaway that
   the author doesn't know convenience retail.

3. **Tobacco carries a regulated floor price; other categories don't.** This
   sets up the compliance-breach check in step 3, which is the error type that
   separates this from a generic data-quality tool.

4. **Promos follow a 7-Eleven promo week: Thursday start, Wednesday end.** Every
   promotion starts on a Thursday and ends on a Wednesday, and durations are
   weekly-dominant (~70% one week, ~20% two weeks, ~10% three-to-four weeks).
   Random start days or an even spread of multi-week campaigns would read as
   supermarket data, not convenience. This also makes step 2's date-drift errors
   more realistic — a few days' slip on a 7-day promo is a plausible defect.

5. **The clean baseline is verified, not assumed.** `verify_clean.py` runs ten
   checks. If the generator ever drifts and starts producing a rule violation in
   the "clean" data, the ground-truth key in step 2 would be wrong — so this
   guardrail runs every time.

6. **Seeded (SEED=42).** The dataset regenerates identically, which is what
   makes "caught X% of injected errors" a reproducible number rather than a
   one-off hand-count.

## Next: step 2

Seeded, logged error-injection function that corrupts a *copy* of the clean data
and writes a ground-truth key (record id + error type injected), so step 3's
detection rate can be measured honestly.
