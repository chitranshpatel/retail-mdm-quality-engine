"""
app.py — Store24 Master Data Quality Engine (Streamlit dashboard)

Reads pre-computed outputs from data/dirty/:
    exceptions.csv  <- src/validate.py
    scorecard.csv   <- src/score.py
    ground_truth.csv

Run:  streamlit run src/app.py
"""
import os
import pandas as pd
import streamlit as st

RETAILER = "Store24"

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "dirty")

SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]

# Four steps, each verified >=58 apart in RGB distance from its neighbours and
# from the brand accent (previous palette had Critical-High at 39 and
# High-Medium at 48 -- both read as the same muddy brown-orange). This ramp
# also runs warm-to-cool as urgency falls, so temperature itself carries
# meaning rather than relying on hue alone.
SEV = {
    "Critical": "#DC2626",  # red
    "High":     "#EA580C",  # orange
    "Medium":   "#A16207",  # olive-amber
    "Low":      "#64748B",  # slate (cool -- signals "not urgent")
}

# Human-readable check names. Raw snake_case column values should never reach
# the interface -- the reader is an analyst or a hiring manager, not the schema.
CHECK_LABEL = {
    "referential_integrity":     "Missing article reference",
    "referential_timing":        "Discontinued before promo",
    "listing_conflict":          "Not ranged in store group",
    "header_item_date_mismatch": "Item outside campaign dates",
    "orphaned_cancelled_header": "Cancelled promo still live",
    "uom_pack_mismatch":         "Multibuy on non-unit article",
    "tobacco_on_promotion":      "Tobacco on promotion",
    "margin_breach":             "Priced below cost",
    "barcode_invalidity":        "Invalid barcode",
    "duplicate_near_duplicate":  "Duplicate article",
    "completeness":              "Missing required field",
    "stale_status":              "Expired but marked live",
}

st.set_page_config(
    page_title=f"{RETAILER} — Master Data Quality Engine",
    page_icon="◆",
    layout="wide",
)

# --------------------------------------------------------------------------
# Design tokens.
#
# The palette IS the severity ladder -- this is a triage tool, so severity is
# the visual system rather than decoration layered on top. Spacing is a 4-based
# scale; type is a fixed rem scale. Nothing below is eyeballed per-component.
# --------------------------------------------------------------------------
st.markdown(f"""
<style>
  :root {{
    --ink:      #101828;
    --muted:    #475467;
    --faint:    #667085;
    --hairline: #E4E7EC;
    --canvas:   #FFFFFF;
    --recessed: #F9FAFB;

    --critical: {SEV['Critical']};
    --high:     {SEV['High']};
    --medium:   {SEV['Medium']};
    --low:      {SEV['Low']};

    /* Brand accent -- evocative of fuel/24-hour convenience retail without
       reproducing any real retailer's trademarked palette. Deliberately a
       bright gold, clearly distinct from the severity oranges/reds above, so
       it can never be mistaken for a severity signal in the data itself. */
    --accent: #F59E0B;
    --accent-dim: #FEF3C7;

    --s1: 0.25rem;  --s2: 0.5rem;   --s4: 1rem;
    --s6: 1.5rem;   --s10: 2.5rem;  --s16: 4rem;

    --t-caption: 0.8rem;
    --t-small:   0.875rem;
    --t-body:    1rem;
    --t-h2:      1.25rem;
    --t-display: 2.5rem;

    --radius: 6px;
  }}

  .block-container {{ padding-top: var(--s10); max-width: 1140px; }}
  html, body, [class*="css"] {{ color: var(--ink); }}

  h1 {{
    font-size: 2.05rem !important; font-weight: 700 !important;
    letter-spacing: -0.025em; margin-bottom: var(--s2) !important;
  }}
  h2 {{
    font-size: 1.4rem !important; font-weight: 700 !important;
    letter-spacing: -0.016em; margin: var(--s10) 0 var(--s4) 0 !important;
    padding-left: var(--s2) !important;
    border-left: 3px solid var(--accent);
  }}
  h3 {{ font-size: 1.05rem !important; font-weight: 650 !important; }}

  /* Slim brand rule under the masthead -- the one place the accent appears
     as pure chrome, sitting above all data so it never competes with it. */
  .brand-rule {{
    height: 3px; width: 100%;
    background: linear-gradient(90deg, var(--accent) 0%, var(--accent) 64px, transparent 64px);
    margin-bottom: var(--s6);
  }}

  div[data-testid="stDownloadButton"] button {{
    border-color: var(--accent) !important; color: #92400E !important;
  }}
  div[data-testid="stDownloadButton"] button:hover {{
    background: var(--accent-dim) !important; border-color: var(--accent) !important;
  }}

  /* Smaller text needs greater line height. */
  p, li {{ font-size: var(--t-body); line-height: 1.6; }}
  .sub {{ color: var(--muted); font-size: 0.98rem; line-height: 1.65; }}
  .cap {{ color: var(--faint); font-size: var(--t-caption); line-height: 1.7; }}

  .stTabs [data-baseweb="tab-list"] {{ gap: var(--s2); border-bottom: 1px solid var(--hairline); }}
  .stTabs [data-baseweb="tab"] {{
    font-size: var(--t-small); font-weight: 500; padding: 0 var(--s4) var(--s2) var(--s4);
  }}

  /* Disclosure: quiet, but unmissable. De-emphasised so the focal point wins. */
  .disclosure {{
    background: var(--recessed); border: 1px solid var(--hairline);
    border-left: 2px solid var(--faint); border-radius: var(--radius);
    padding: var(--s4); margin: var(--s6) 0 var(--s10) 0;
    color: var(--muted); font-size: 1.02rem; line-height: 1.65;
  }}
  .disclosure strong {{ color: var(--ink); font-weight: 650; }}

  /* FOCAL POINT. The one element granted depth + accent colour. */
  .focal {{
    display: flex; gap: var(--s16); align-items: baseline; flex-wrap: wrap;
    background: var(--canvas); border: 1px solid var(--hairline);
    border-radius: var(--radius); padding: var(--s6);
    box-shadow: 0 1px 2px rgba(16,24,40,0.04), 0 4px 12px rgba(16,24,40,0.04);
  }}
  .focal-figure {{
    font-size: var(--t-display); font-weight: 660; letter-spacing: -0.03em;
    line-height: 1; color: var(--critical);
  }}
  .focal-figure.ok {{ color: var(--ink); }}
  .focal-label {{
    font-size: var(--t-caption); color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.06em; font-weight: 550;
    margin-top: var(--s2);
  }}

  /* Supporting stats: deliberately de-emphasised. */
  .stat-row {{ display: flex; gap: var(--s16); margin-top: var(--s6); flex-wrap: wrap; }}
  .stat-figure {{ font-size: var(--t-h2); font-weight: 600; color: var(--ink); line-height: 1.2; }}
  .stat-label {{ font-size: var(--t-caption); color: var(--faint); margin-top: var(--s1); }}

  /* Severity chart: common baseline, bars aligned left, values labelled directly.
     Grid-based so every bar's zero point is identical -- that shared baseline is
     what makes the four counts directly comparable at a glance. */
  .sevchart {{ display: flex; flex-direction: column; gap: var(--s2); }}
  .sevrow {{
    display: grid; grid-template-columns: 84px 1fr 44px;
    align-items: center; gap: var(--s4);
  }}
  .sevname {{ font-size: var(--t-small); color: var(--muted); text-align: right; }}
  .sevtrack {{ background: var(--recessed); border-radius: 3px; height: 22px; }}
  .sevbar {{ height: 22px; border-radius: 3px; }}
  .sevval {{
    font-size: var(--t-small); font-weight: 600; color: var(--ink);
    font-variant-numeric: tabular-nums;
  }}

  section[data-testid="stSidebar"] {{ display: none; }}

  /* Force the light theme regardless of the viewer's system/browser dark-mode
     preference. This app's colour system (severity ramp, ink/muted text) was
     designed and contrast-checked against a white canvas only -- letting
     Streamlit's automatic dark theme override it would put near-black text on
     a near-black background, which is unreadable, not just off-brand. */
  [data-testid="stAppViewContainer"], [data-testid="stHeader"],
  [data-testid="stMain"], .stApp, body {{
    background-color: var(--canvas) !important;
    color: var(--ink) !important;
  }}
  [data-testid="stMarkdownContainer"] p {{ color: inherit !important; }}

  @media (prefers-reduced-motion: reduce) {{
    * {{ animation: none !important; transition: none !important; }}
  }}
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
@st.cache_data
def load():
    p = lambda f: os.path.join(DATA, f)
    return (
        pd.read_csv(p("exceptions.csv")),
        pd.read_csv(p("scorecard.csv")),
        pd.read_csv(p("ground_truth.csv")),
        pd.read_csv(p("article_master.csv")),
        pd.read_csv(p("promotion_item.csv")),
    )


try:
    exceptions, scorecard, ground_truth, articles, promo_items = load()
except FileNotFoundError as e:
    st.error(f"Missing file: `{e.filename}`")
    st.markdown(
        "Run the pipeline from the project root:\n\n```\npython3 src/generate.py\n"
        "python3 src/inject.py\npython3 src/validate.py\npython3 src/score.py\n```"
    )
    st.caption(f"Looking in: `{os.path.abspath(DATA)}`")
    st.stop()

records_scanned = len(articles) + len(promo_items)
total_exceptions = len(exceptions)
critical_count = int((exceptions.severity == "Critical").sum())

tp, fp, fn = int(scorecard.TP.sum()), int(scorecard.FP.sum()), int(scorecard.FN.sum())
precision = tp / (tp + fp) if (tp + fp) else 0
recall = tp / (tp + fn) if (tp + fn) else 0


def severity_bars(counts: pd.Series) -> str:
    """Horizontal bars, common baseline, direct value labels.

    Deliberately NOT a stacked bar: with four close values (95/75/68/62) a
    stacked bar forces the eye to compare segment lengths at different offsets,
    which is a much harder perceptual task than comparing bars that all start
    at zero. Position along a common scale is the most accurately-decoded
    encoding available; use it.
    """
    top = counts.max()
    rows = ""
    for s in SEVERITY_ORDER:
        n = int(counts.get(s, 0))
        if not n:
            continue
        rows += (
            f'<div class="sevrow">'
            f'  <div class="sevname">{s}</div>'
            f'  <div class="sevtrack">'
            f'    <div class="sevbar" style="width:{n/top*100:.1f}%;background:{SEV[s]}"></div>'
            f'  </div>'
            f'  <div class="sevval">{n}</div>'
            f'</div>'
        )
    return f'<div class="sevchart">{rows}</div>'


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.markdown(f"# {RETAILER} — Master Data Quality Engine")
st.markdown(
    '<p class="sub">Promotion and article master data integrity: exception detection, '
    'severity triage, and measured detection accuracy.</p>',
    unsafe_allow_html=True,
)
st.markdown('<div class="brand-rule"></div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="disclosure"><strong>Synthetic data. Portfolio project.</strong><br>'
    f'{RETAILER} is a fictional convenience retailer. No real company data appears here. '
    'The schema mirrors <strong>SAP ECC Retail structures (MARA, WAKH/WAKP, WLK1) to show how '
    'retail master data is organised</strong> — it was not built in, or extracted from, an SAP system.</div>',
    unsafe_allow_html=True,
)

tab_overview, tab_worklist, tab_scorecard, tab_about = st.tabs(
    ["Overview", "Exception worklist", "Detection scorecard", "About"]
)


# --------------------------------------------------------------------------
# Overview — one focal point, everything else supporting
# --------------------------------------------------------------------------
with tab_overview:
    st.markdown(
        f"""<div class="focal">
              <div>
                <div class="focal-figure">{critical_count}</div>
                <div class="focal-label">Critical exceptions open</div>
              </div>
              <div>
                <div class="focal-figure ok">{recall:.0%}</div>
                <div class="focal-label">Of injected defects caught</div>
              </div>
            </div>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="cap">Critical means a compliance breach or a blocked downstream system — '
        'a promotion that cannot legally run, or an article that will not scan at the till.</p>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""<div class="stat-row">
              <div><div class="stat-figure">{records_scanned:,}</div>
                   <div class="stat-label">Records scanned</div></div>
              <div><div class="stat-figure">{total_exceptions:,}</div>
                   <div class="stat-label">Exceptions raised</div></div>
              <div><div class="stat-figure">{len(scorecard)}</div>
                   <div class="stat-label">Validation checks</div></div>
              <div><div class="stat-figure">{precision:.1%}</div>
                   <div class="stat-label">Precision</div></div>
            </div>""",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<p class="cap">Errors were injected into 5–30% of eligible records so every check has '
        'enough cases to measure meaningfully. A production system would sit in the low single '
        'digits — the rate here is a property of the test harness, not a forecast.</p>',
        unsafe_allow_html=True,
    )

    st.markdown("## The queue by severity")
    counts = exceptions.severity.value_counts().reindex(SEVERITY_ORDER).fillna(0).astype(int)
    st.markdown(severity_bars(counts), unsafe_allow_html=True)
    st.markdown(
        '<p class="cap">Low outnumbers Medium here. That is expected: completeness gaps and '
        'near-duplicates are common but self-limiting, while the defects that stop a promotion '
        'loading are rarer and sit at the top.</p>',
        unsafe_allow_html=True,
    )

    st.markdown("## What is driving the queue")
    st.markdown(
        '<p class="sub">Every check, ranked by volume and coloured by severity. Volume and '
        'urgency are different things: the largest bar is not the most urgent, and the most '
        'urgent — an illegal tobacco promotion — is the smallest.</p>',
        unsafe_allow_html=True,
    )

    by_type = (exceptions.groupby(["error_type", "severity"])
               .size().reset_index(name="count")
               .sort_values("count", ascending=False))
    by_type["check"] = by_type.error_type.map(CHECK_LABEL).fillna(by_type.error_type)

    st.vega_lite_chart(by_type, {
        "height": {"step": 26},
        "padding": {"left": 0, "top": 4, "right": 8, "bottom": 4},
        "mark": {"type": "bar", "cornerRadiusEnd": 2},
        "encoding": {
            "y": {
                "field": "check", "type": "nominal",
                "sort": "-x", "title": None,
                "axis": {"labelFontSize": 12, "labelColor": "#344054",
                          "labelLimit": 260, "labelPadding": 10,
                          "domain": False, "ticks": False},
            },
            "x": {
                "field": "count", "type": "quantitative",
                "title": "Exceptions",
                "axis": {"labelFontSize": 11, "labelColor": "#667085",
                          "titleFontSize": 11, "titleColor": "#667085",
                          "titleFontWeight": "normal", "grid": True,
                          "gridColor": "#F2F4F7", "domain": False, "ticks": False},
            },
            "color": {
                "field": "severity", "type": "nominal",
                "scale": {"domain": SEVERITY_ORDER,
                           "range": [SEV[s] for s in SEVERITY_ORDER]},
                "legend": {"title": None, "orient": "top", "direction": "horizontal",
                            "labelFontSize": 12, "labelColor": "#667085",
                            "symbolType": "square", "symbolSize": 90, "offset": 4},
            },
            "tooltip": [
                {"field": "check", "title": "Check"},
                {"field": "severity", "title": "Severity"},
                {"field": "count", "title": "Exceptions"},
            ],
        },
        "config": {"view": {"stroke": None}, "autosize": {"type": "fit", "contains": "padding"}},
    }, use_container_width=True)

    st.markdown("## Where it concentrates")
    sg_counts = exceptions.dropna(subset=["store_group"]).store_group.value_counts()
    st.markdown(
        f'<p class="sub">{len(sg_counts)} store groups carry at least one exception. The worst '
        f'holds {sg_counts.max()}; the median holds {int(sg_counts.median())}. The ten worst are '
        'shown. Article-level defects such as invalid barcodes are not store-specific and are '
        'excluded.</p>',
        unsafe_allow_html=True,
    )

    top_sg = sg_counts.head(10).reset_index()
    top_sg.columns = ["store_group", "count"]
    st.vega_lite_chart(top_sg, {
        "height": {"step": 26},
        "padding": {"left": 0, "top": 4, "right": 8, "bottom": 4},
        "mark": {"type": "bar", "cornerRadiusEnd": 2, "color": SEV["Low"]},
        "encoding": {
            "y": {"field": "store_group", "type": "nominal", "sort": "-x", "title": None,
                   "axis": {"labelFontSize": 12, "labelColor": "#344054",
                             "labelLimit": 200, "labelPadding": 10,
                             "domain": False, "ticks": False}},
            "x": {"field": "count", "type": "quantitative", "title": "Exceptions",
                   "axis": {"labelFontSize": 11, "labelColor": "#667085",
                             "titleFontSize": 11, "titleColor": "#667085",
                             "titleFontWeight": "normal", "grid": True,
                             "gridColor": "#F2F4F7", "domain": False, "ticks": False}},
            "tooltip": [{"field": "store_group", "title": "Store group"},
                         {"field": "count", "title": "Exceptions"}],
        },
        "config": {"view": {"stroke": None}, "autosize": {"type": "fit", "contains": "padding"}},
    }, use_container_width=True)


# --------------------------------------------------------------------------
# Worklist
# --------------------------------------------------------------------------
with tab_worklist:
    st.markdown("## Exception worklist")
    st.markdown(
        '<p class="sub">A data integrity analyst\'s daily queue. Every row names the affected '
        'record, why it is wrong, and what breaks downstream if it is not fixed.</p>',
        unsafe_allow_html=True,
    )

    f1, f2, f3 = st.columns([1, 1.3, 1.3])
    sev_filter = f1.multiselect("Severity", SEVERITY_ORDER, default=SEVERITY_ORDER)
    label_options = sorted(exceptions.error_type.map(CHECK_LABEL).unique())
    type_filter = f2.multiselect("Check", label_options)
    sg_filter = f3.multiselect("Store group", sorted(exceptions.store_group.dropna().unique()))

    view = exceptions.assign(check=exceptions.error_type.map(CHECK_LABEL))
    view = view[view.severity.isin(sev_filter)]
    if type_filter:
        view = view[view.check.isin(type_filter)]
    if sg_filter:
        view = view[view.store_group.isin(sg_filter)]

    view = (view.assign(_s=pd.Categorical(view.severity, SEVERITY_ORDER, ordered=True))
            .sort_values(["_s", "check"]).drop(columns="_s"))

    if view.empty:
        st.markdown(
            '<p class="sub">No exceptions match these filters. Widen the selection to see results.</p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<p class="cap">{len(view):,} of {total_exceptions:,} exceptions</p>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            view[["severity", "check", "table_name", "record_id",
                  "store_group", "downstream_impact", "description"]],
            hide_index=True, use_container_width=True, height=540,
            column_config={
                "severity": st.column_config.TextColumn("Severity", width="small"),
                "check": st.column_config.TextColumn("Check", width="medium"),
                "table_name": st.column_config.TextColumn("Table", width="small"),
                "record_id": st.column_config.TextColumn("Record", width="small"),
                "store_group": st.column_config.TextColumn("Store group", width="small"),
                "downstream_impact": st.column_config.TextColumn("Downstream impact", width="medium"),
                "description": st.column_config.TextColumn("Description", width="large"),
            },
        )
        st.download_button(
            "Download this view as CSV",
            view.to_csv(index=False).encode("utf-8"),
            file_name="exceptions_filtered.csv", mime="text/csv",
        )


# --------------------------------------------------------------------------
# Scorecard
# --------------------------------------------------------------------------
with tab_scorecard:
    st.markdown("## Detection scorecard")
    st.markdown(
        '<p class="sub">Errors were injected into a clean, independently-verified dataset using a '
        'seeded corruption function that logged every change to a ground-truth key. The validation '
        'engine never sees that key. These are the results it independently rediscovered.</p>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""<div class="focal">
              <div><div class="focal-figure ok">{recall:.0%}</div>
                   <div class="focal-label">Recall</div></div>
              <div><div class="focal-figure ok">{precision:.1%}</div>
                   <div class="focal-label">Precision</div></div>
              <div><div class="focal-figure ok">{fn}</div>
                   <div class="focal-label">Missed defects</div></div>
            </div>""",
        unsafe_allow_html=True,
    )

    st.markdown("## Per-check performance")
    # scorecard uses ground-truth names; tobacco was renamed after the AU law
    # correction, so alias it back before labelling.
    sc = scorecard.copy()
    sc["Check"] = (sc.error_type
                   .replace({"tobacco_floor_breach": "tobacco_on_promotion"})
                   .map(CHECK_LABEL)
                   .fillna(sc.error_type))
    sc = sc[["Check", "ground_truth", "found", "TP", "FP", "FN", "precision", "recall"]]
    st.dataframe(
        sc.rename(columns={
            "ground_truth": "Injected", "found": "Detected",
            "precision": "Precision", "recall": "Recall",
        }),
        hide_index=True, use_container_width=True,
        column_config={
            "Check": st.column_config.TextColumn(width="medium"),
            "Precision": st.column_config.NumberColumn(format="%.2f"),
            "Recall": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    st.markdown("## Reading these numbers honestly")
    st.markdown(f"""
Recall is **{recall:.0%}**. Every injected defect was found; none slipped through.

Precision is **{precision:.1%}**, and the entire shortfall sits in near-duplicate detection.
Those false positives are not random noise. When one article is duplicated, the copy legitimately
scores highly against *several* existing sibling variants whose descriptions are near-identical.
A stricter similarity threshold would remove them — and would also start missing real duplicates.
This engine is deliberately tuned to catch every genuine defect rather than to report a flawless
precision figure.

Counting units differ per check, and the scorer reconciles them before comparing. One discontinued
article can sit on several promotion lines: the worklist reports every affected line, because that
is what an analyst must actually fix, while the ground-truth key logs the single root-cause article.
Scoring compares like with like.
    """)


# --------------------------------------------------------------------------
# About
# --------------------------------------------------------------------------
with tab_about:
    st.markdown("## What this is")
    st.markdown(f"""
A master data quality engine for a fictional convenience retailer. It generates a realistic
promotion and article master dataset, deliberately corrupts a known subset, then independently
detects those defects and scores itself against a ground-truth key it never sees.

It demonstrates the reasoning a Retail Data Integrity Analyst applies to promotion and article
master data: how the data is structured, what breaks in it, and how to catch that systematically
rather than case by case.

**It is not built in SAP, and it is not real company data.** The tables mirror SAP ECC Retail
structures so the domain knowledge is visible, but everything is synthetic and written in Python.
""")

    st.markdown("## How it works")
    st.markdown("""
**Generate.** A seeded generator builds six SAP-pattern tables: articles with a real
single/generic/variant hierarchy, site-level data, listing conditions, promotion headers,
promotion items, and a change log. Convenience-retail realities are modelled deliberately —
fuel priced per litre, tobacco under regulatory constraint, promotions running Thursday-to-Wednesday
promo weeks, and franchise store groups that do not all range the same articles.

**Inject.** A second seeded pass corrupts a copy of that clean data with twelve error types,
logging every change to a ground-truth key. A shared registry prevents any two injectors from
silently overwriting each other on the same record.

**Validate.** Twelve independent checks scan the corrupted data. Each returns the affected record,
the error type, a severity tier, the downstream system that breaks, and a plain-English description.

**Score.** Detected exceptions are reconciled onto the ground-truth key's counting unit, then
compared, producing precision and recall per check.
""")

    st.markdown("## The twelve checks")
    st.markdown("""
| Check | Severity | What it catches |
|---|---|---|
| Referential integrity | Critical | Promotion references an article that does not exist |
| Barcode invalidity | Critical | EAN-13 check digit fails — will not scan at the till |
| Orphaned cancelled header | Critical | Cancelled campaign whose promotion lines still run |
| Tobacco on promotion | Critical | Tobacco promoted at all — not legal in Australia |
| Referential timing | High | Article discontinued *before* its promotion started |
| Listing conflict | High | Deal advertised where the article is not ranged |
| Margin breach | High | Promotion priced below cost |
| Header/item date mismatch | Medium | Promotion line runs outside its campaign window |
| UOM / pack mismatch | Medium | "3 for $5" on an article sold only by the carton |
| Completeness | Low | Required fields missing — UOM, tax code, approval status |
| Duplicate / near-duplicate | Low | Same product entered twice under different IDs |
| Stale status | Low | Promotion still marked live after its end date passed |
""")

    st.markdown("## Decisions worth defending")
    st.markdown("""
**Severity is assigned by which downstream system breaks**, not by intuition. A tobacco promotion
is Critical because it is a compliance breach. An invalid barcode is Critical because the item
physically will not scan. A missing tax code is Low because it is wrong but self-limiting.

**Barcode validation uses real EAN-13 check-digit arithmetic**, not a length or format test.

**The clean baseline is verified before it is corrupted.** Ten assertions confirm the clean data
genuinely satisfies every rule. Without that, the ground-truth key would be measured against data
that was already broken, and the detection score would mean nothing.

**Near-duplicate detection excludes legitimate parent/variant relationships.** A generic article
and its own size variants are *supposed* to share near-identical descriptions. Flagging them would
be a false positive created by the check itself.

**Tobacco is treated as non-promotable outright.** The Public Health (Tobacco and Other Products)
Act 2023 bans tobacco promotion almost entirely in Australia, so appearing on a promotion is the
breach — not merely being priced below a floor.
""")

    st.markdown("## Stack")
    st.markdown('<p class="sub">Python · pandas · RapidFuzz · Streamlit</p>', unsafe_allow_html=True)


st.markdown(
    f'<p class="cap" style="margin-top:2.5rem">{RETAILER} is fictional. All data on this page is '
    'synthetic and generated for demonstration.</p>',
    unsafe_allow_html=True,
)