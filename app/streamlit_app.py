"""Streamlit UI for the Make vs. Buy Decision Framework.

Tool 5 of the Strategic Sourcing Decision Suite.

Run locally:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless backend for Streamlit Cloud reliability
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
for sub in ("src", "data"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

# Bridge a Streamlit Cloud secret to the environment. Streamlit secrets land in
# st.secrets, not os.environ, but the narrative layer reads ANTHROPIC_API_KEY
# from the environment. This makes the key work when set in the Cloud secrets
# manager, while locally (no secret, no env var) the deterministic fallback runs.
try:
    if "ANTHROPIC_API_KEY" in st.secrets and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    # st.secrets raises if no secrets file exists at all (common locally). The
    # deterministic narrative handles the no-key case, so this is safe to ignore.
    pass

import decision_engine as eng  # noqa: E402
from decision_engine import PartInput, evaluate, recommendation_sort_key  # noqa: E402
from ai_narrative import ai_narrative, FACTOR_LABELS  # noqa: E402
from sample_parts import SAMPLE_PARTS  # noqa: E402

# --- Design system (consistent with the rest of the suite) -----------------
CREAM = "#f5f4f0"
INK = "#1c1b18"
ACCENT = "#c94a1e"
MUTED = "#6b6760"
MAKE_COLOR = "#2f6b4f"
BUY_COLOR = "#9c5b1f"
STRATEGIC_COLOR = "#c94a1e"
MARGINAL_COLOR = "#6b6760"
GRID = "#d9d6cf"

REC_STYLE = {
    eng.REC_STRATEGIC_MAKE: (STRATEGIC_COLOR, "Make in-house despite the cost premium. Strategic factors override the economics."),
    eng.REC_MAKE: (MAKE_COLOR, "Make in-house. Economics and strategy both support insourcing."),
    eng.REC_OPPORTUNISTIC: (MAKE_COLOR, "Make while economics are favorable; hold dual-source as a hedge. Low strategic lock-in."),
    eng.REC_QUALIFY_SECOND: (BUY_COLOR, "Buy, but qualify a second source. Economics favor buying, yet single-source exposure on a critical part needs hedging."),
    eng.REC_MARGINAL: (MARGINAL_COLOR, "Signals are near-even. Gather more data before committing."),
    eng.REC_BUY: (BUY_COLOR, "Buy under the selected decision lens. Cost, strategy, lifecycle, and mode logic do not justify committing internal production."),
    eng.REC_DOMESTIC_ONLY: (STRATEGIC_COLOR, "Economics favor buying, but export control requires a domestic, qualified source."),
}

st.set_page_config(page_title="Make vs. Buy Decision Framework", layout="wide")

st.markdown(
    f"""
    <style>
      .stApp {{ background-color: {CREAM}; }}
      /* Force readable text regardless of the viewer's device theme. */
      .stApp, .stApp p, .stApp li, .stApp label,
      h1, h2, h3, h4, h5, h6 {{ color: {INK}; }}
      h1, h2, h3 {{ font-family: 'Inter', sans-serif; }}
      .mono {{ font-family: 'Space Mono', monospace; }}
      /* Metric labels and values, captions, and markdown text. */
      [data-testid="stMetricLabel"], [data-testid="stMetricValue"] {{ color: {INK}; }}
      [data-testid="stCaptionContainer"], .stCaption, small {{ color: {MUTED} !important; }}
      [data-testid="stMarkdownContainer"] {{ color: {INK}; }}
      /* Sidebar surface a touch off-cream for separation. */
      [data-testid="stSidebar"] {{ background-color: #eceae4; }}
    </style>
    """,
    unsafe_allow_html=True,
)

if "comparison" not in st.session_state:
    st.session_state.comparison = {}  # part_name -> DecisionResult


# --- Header ----------------------------------------------------------------
st.title("Make vs. Buy Decision Framework")
st.markdown(
    f"<p style='color:{MUTED};font-size:1.02rem;margin-top:-8px'>"
    "Evaluates a part across an economic layer and a strategic layer, places it "
    "on a Make/Buy quadrant, and produces a defensible recommendation. "
    "Cost is one input, not the answer.</p>",
    unsafe_allow_html=True,
)
st.info(
    "Decision support, not a decision. The recommendation is fully deterministic; "
    "verify capacity, compliance, and capture context before acting.",
    icon=None,
)


# --- Sidebar: intake -------------------------------------------------------
def categorical(label: str, field: str, default_index: int = 0):
    return st.selectbox(label, eng.VALID_CATEGORIES[field], index=default_index)


with st.sidebar:
    st.header("Part Intake")

    sample_choice = st.selectbox(
        "Load a sample part",
        ["(custom entry)"] + list(SAMPLE_PARTS.keys()),
    )
    seed = SAMPLE_PARTS.get(sample_choice)

    mode = st.radio(
        "Scoring mode",
        list(eng.MODE_BLENDS.keys()),
        index=list(eng.MODE_BLENDS).index(seed.mode) if seed else 0,
        help="Re-weights the blend between the economic and strategic layers. "
             "Clear-cut cases are unaffected; on genuinely close calls, mode can "
             "tip the recommendation (e.g. Cost-Driven hedges a borderline "
             "Strategic Make).",
    )

    st.subheader("Identification")
    part_name = st.text_input("Part name", seed.part_name if seed else "New Part")
    description = st.text_area("Description", seed.description if seed else "", height=80)

    st.subheader("Economic inputs")
    annual_volume = st.number_input(
        "Annual volume (units)", min_value=1,
        value=seed.annual_volume if seed else 1000, step=100)
    make_unit_cost = st.number_input(
        "Fully-loaded make unit cost ($)", min_value=0.0,
        value=float(seed.make_unit_cost) if seed else 100.0, step=1.0,
        help="Can be supplied by your should-cost model.")
    buy_unit_quote = st.number_input(
        "Buy unit quote ($)", min_value=0.01,
        value=float(seed.buy_unit_quote) if seed else 100.0, step=1.0,
        help="Must be greater than zero. A zero quote indicates a missing input.")
    nonrecurring_investment = st.number_input(
        "Non-recurring make investment ($)", min_value=0.0,
        value=float(seed.nonrecurring_investment) if seed else 0.0, step=1000.0,
        help=f"Tooling, NRE, capital, qualification. Amortized over "
             f"{eng.AMORTIZATION_YEARS} years.")
    capacity = categorical(
        "Internal capacity", "capacity",
        eng.VALID_CATEGORIES["capacity"].index(seed.capacity) if seed else 1)
    volume_stability = categorical(
        "Volume profile", "volume_stability",
        eng.VALID_CATEGORIES["volume_stability"].index(seed.volume_stability) if seed else 1)

    st.subheader("Strategic inputs")
    ip_control = categorical(
        "IP / design control", "ip_control",
        eng.VALID_CATEGORIES["ip_control"].index(seed.ip_control) if seed else 2)
    criticality = categorical(
        "Part criticality", "criticality",
        eng.VALID_CATEGORIES["criticality"].index(seed.criticality) if seed else 2)
    supply_risk = categorical(
        "Supply market", "supply_risk",
        eng.VALID_CATEGORIES["supply_risk"].index(seed.supply_risk) if seed else 1)
    regulatory = categorical(
        "Regulatory status", "regulatory",
        eng.VALID_CATEGORIES["regulatory"].index(seed.regulatory) if seed else 3)
    roadmap = categorical(
        "Technology roadmap", "roadmap",
        eng.VALID_CATEGORIES["roadmap"].index(seed.roadmap) if seed else 2)
    lifecycle = categorical(
        "Program lifecycle", "lifecycle",
        eng.VALID_CATEGORIES["lifecycle"].index(seed.lifecycle) if seed else 1)


part = PartInput(
    part_name=part_name, description=description, annual_volume=int(annual_volume),
    make_unit_cost=make_unit_cost, buy_unit_quote=buy_unit_quote,
    nonrecurring_investment=nonrecurring_investment, capacity=capacity,
    volume_stability=volume_stability, ip_control=ip_control,
    criticality=criticality, supply_risk=supply_risk, regulatory=regulatory,
    roadmap=roadmap, lifecycle=lifecycle, mode=mode,
)
result = evaluate(part)


# --- Recommendation card ---------------------------------------------------
color, summary = REC_STYLE.get(result.recommendation, (MUTED, ""))
st.markdown(
    f"""
    <div style="border-left:7px solid {color};padding:16px 20px;background:#fffdf9;
                border-radius:8px;margin:6px 0 14px">
      <div style="font-family:'Space Mono',monospace;color:{MUTED};font-size:0.8rem;
                  letter-spacing:0.08em;text-transform:uppercase">Recommendation</div>
      <div style="font-size:1.9rem;font-weight:700;color:{color};margin:2px 0 6px">
          {result.recommendation}</div>
      <div style="color:{INK};font-size:0.97rem">{summary}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if result.flags:
    for f in result.flags:
        st.warning(f, icon=None)

m1, m2, m3 = st.columns(3)
m1.metric("Economic score (favors Make →)", f"{result.economic_score:.0f}/100")
m2.metric("Strategic score (favors Make →)", f"{result.strategic_score:.0f}/100")
m3.metric(f"Blended ({result.mode})", f"{result.blended_score:.0f}/100")


# --- Quadrant chart --------------------------------------------------------
def quadrant_figure(current: eng.DecisionResult,
                    others: list[eng.DecisionResult] | None = None):
    fig, ax = plt.subplots(figsize=(7, 6.2))
    fig.patch.set_facecolor(CREAM)
    ax.set_facecolor("#fffdf9")

    # Quadrant tint
    ax.axhspan(50, 100, xmin=0.0, xmax=0.5, color=STRATEGIC_COLOR, alpha=0.06)
    ax.axhspan(50, 100, xmin=0.5, xmax=1.0, color=MAKE_COLOR, alpha=0.06)
    ax.axhspan(0, 50, xmin=0.5, xmax=1.0, color=MAKE_COLOR, alpha=0.03)

    ax.axhline(50, color=GRID, lw=1.2, zorder=1)
    ax.axvline(50, color=GRID, lw=1.2, zorder=1)
    # Neutral band
    ax.axhspan(45, 55, color=MARGINAL_COLOR, alpha=0.05, zorder=0)
    ax.axvspan(45, 55, color=MARGINAL_COLOR, alpha=0.05, zorder=0)

    labels = [
        (25, 92, "STRATEGIC MAKE", STRATEGIC_COLOR),
        (75, 92, "MAKE", MAKE_COLOR),
        (25, 6, "BUY", BUY_COLOR),
        (75, 6, "OPPORTUNISTIC\nMAKE / DUAL-SOURCE", MAKE_COLOR),
    ]
    for x, y, text, c in labels:
        ax.text(x, y, text, ha="center", va="center", fontsize=9,
                fontweight="bold", color=c, alpha=0.65,
                family="monospace")

    others = others or []
    for o in others:
        if o.part_name == current.part_name:
            continue
        ax.scatter(o.economic_score, o.strategic_score, s=70, color=MUTED,
                   alpha=0.55, zorder=3, edgecolor="white", linewidth=1)
        ax.annotate(o.part_name, (o.economic_score, o.strategic_score),
                    fontsize=7, color=MUTED, xytext=(6, 4),
                    textcoords="offset points")

    ax.scatter(current.economic_score, current.strategic_score, s=240,
               color=ACCENT, zorder=5, edgecolor="white", linewidth=2)
    ax.annotate(current.part_name,
                (current.economic_score, current.strategic_score),
                fontsize=9, fontweight="bold", color=INK,
                xytext=(8, 8), textcoords="offset points")

    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Economic layer  (Buy  ←→  Make)", fontsize=10, color=INK)
    ax.set_ylabel("Strategic layer  (Buy  ←→  Make)", fontsize=10, color=INK)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    fig.tight_layout()
    return fig


left, right = st.columns([3, 2])
with left:
    st.subheader("Decision Quadrant")
    others = list(st.session_state.comparison.values())
    st.pyplot(quadrant_figure(result, others))

with right:
    st.subheader("Rationale")
    narrative, used_ai = ai_narrative(result)
    st.markdown(
        f"<div class='mono' style='color:{MUTED};font-size:0.8rem;"
        f"letter-spacing:0.04em'>ENGINE RECOMMENDATION: "
        f"<b style='color:{color}'>{result.recommendation}</b></div>",
        unsafe_allow_html=True,
    )
    st.write(narrative)
    st.caption(
        ("AI-generated explanation of a deterministic recommendation."
         if used_ai else
         "Deterministic explanation. (Set ANTHROPIC_API_KEY for an AI-written rationale.)")
        + " The recommendation above is always computed by the engine, never AI-generated."
    )

    if st.button("➕ Add to comparison", use_container_width=True):
        if len(st.session_state.comparison) >= 6 and result.part_name not in st.session_state.comparison:
            st.warning("Comparison holds up to 6 parts. Clear it to add more.", icon=None)
        else:
            st.session_state.comparison[result.part_name] = result
    if st.session_state.comparison and st.button("Clear comparison", use_container_width=True):
        st.session_state.comparison = {}


# --- Economic + strategic breakdowns --------------------------------------
st.subheader("Economic Breakdown")
ec1, ec2 = st.columns([1, 1])
with ec1:
    sens_color = ACCENT if result.sensitivity == "sensitive" else MAKE_COLOR
    breakeven_line = (
        f"Break-even volume: <b style='color:{INK}'>~{result.breakeven_volume:,.0f} units/yr</b><br>"
        if result.breakeven_volume is not None else
        "Break-even volume: <b style='color:{INK}'>n/a (make not cheaper per unit)</b><br>".replace("{INK}", INK)
    )
    st.markdown(
        f"<div class='mono' style='color:{MUTED};font-size:0.85rem'>"
        f"Annual make (loaded): <b style='color:{INK}'>${result.annual_make_cost:,.0f}</b><br>"
        f"Annual buy: <b style='color:{INK}'>${result.annual_buy_cost:,.0f}</b><br>"
        f"Amortized NRE/yr ({eng.AMORTIZATION_YEARS}-yr): "
        f"<b style='color:{INK}'>${result.amortized_nre_annual:,.0f}</b><br>"
        f"Annual delta: <b style='color:{ACCENT}'>${result.annual_cost_delta:,.0f}</b> "
        f"({'make cheaper' if result.annual_cost_delta > 0 else 'buy cheaper' if result.annual_cost_delta < 0 else 'even'})<br>"
        f"{breakeven_line}"
        f"Economics: <b style='color:{sens_color}'>{result.sensitivity}</b>"
        "</div>",
        unsafe_allow_html=True,
    )
    if result.breakeven_note:
        st.caption(result.breakeven_note)
with ec2:
    edf = pd.DataFrame(
        {"factor": [FACTOR_LABELS[k] for k in result.economic_factors],
         "score": list(result.economic_factors.values())}
    ).set_index("factor")
    st.bar_chart(edf, height=180, color=MAKE_COLOR)

st.subheader("Strategic Breakdown")
sdf = pd.DataFrame(
    {"factor": [FACTOR_LABELS[k] for k in result.strategic_factors],
     "score": list(result.strategic_factors.values())}
).set_index("factor")
st.bar_chart(sdf, height=200, color=STRATEGIC_COLOR)


# --- Comparison table ------------------------------------------------------
if st.session_state.comparison:
    st.subheader("Comparison")
    rows = []
    for r in st.session_state.comparison.values():
        rows.append({
            "Part": r.part_name,
            "Recommendation": r.recommendation,
            "Economic": r.economic_score,
            "Strategic": r.strategic_score,
            "Annual delta ($)": r.annual_cost_delta,
            "_sort": recommendation_sort_key(r.recommendation),
        })
    cdf = pd.DataFrame(rows).sort_values(
        ["_sort", "Strategic"], ascending=[True, False]).drop(columns="_sort")
    st.caption("Sorted by recommendation priority. Strategic Make surfaces first.")
    st.dataframe(cdf, hide_index=True, width="stretch")


# --- How scoring works -----------------------------------------------------
with st.expander("How scoring works"):
    st.markdown(
        f"Each layer is scored 0-100 where **higher favors Make**, 50 is neutral. "
        f"The quadrant uses the two layer scores; the neutral band "
        f"({eng.NEUTRAL_BAND[0]:.0f}-{eng.NEUTRAL_BAND[1]:.0f} on both axes) returns "
        f"*Marginal*. NRE is amortized over **{eng.AMORTIZATION_YEARS} years**."
    )
    st.markdown("**Layer blend by mode**")
    st.dataframe(pd.DataFrame(
        [{"Mode": m, "Economic": f"{e:.0%}", "Strategic": f"{s:.0%}"}
         for m, (e, s) in eng.MODE_BLENDS.items()]),
        hide_index=True, width="stretch")

    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Economic factor weights**")
        st.dataframe(pd.DataFrame(
            [{"Factor": FACTOR_LABELS[k], "Weight": f"{w:.0%}"}
             for k, w in eng.ECONOMIC_WEIGHTS.items()]),
            hide_index=True, width="stretch")
    with cc2:
        st.markdown("**Strategic factor weights**")
        st.dataframe(pd.DataFrame(
            [{"Factor": FACTOR_LABELS[k], "Weight": f"{w:.0%}"}
             for k, w in eng.STRATEGIC_WEIGHTS.items()]),
            hide_index=True, width="stretch")

    st.markdown("**Category score lookups**")
    lookup_tables = {
        "Internal capacity": eng.CAPACITY_SCORES,
        "Volume profile": eng.VOLUME_STABILITY_SCORES,
        "IP / design control": eng.IP_CONTROL_SCORES,
        "Part criticality": eng.CRITICALITY_SCORES,
        "Supply market": eng.SUPPLY_RISK_SCORES,
        "Regulatory status": eng.REGULATORY_SCORES,
        "Technology roadmap": eng.ROADMAP_SCORES,
        "Program lifecycle": eng.LIFECYCLE_SCORES,
    }
    for title, table in lookup_tables.items():
        st.markdown(f"*{title}*")
        st.dataframe(pd.DataFrame(
            [{"Category": k, "Score": v} for k, v in table.items()]),
            hide_index=True, width="stretch")

    st.markdown(
        "**How scoring mode works.** Balanced gives the structural read. "
        "Cost-Driven and Strategic-Driven re-weight the blended score and can "
        "tip the recommendation only on genuine close calls (blend within "
        f"{eng.CLOSE_CALL_MARGIN:.0f} points of neutral). Decisive cases and the "
        "Marginal band never flex with mode."
    )
    st.markdown(
        "**Overrides, in precedence order.** "
        "(1) Sunsetting program with make economics below neutral is forced off "
        "Make: capital should not fund tooling for a program being retired. It "
        "lands on Buy, or Buy / Qualify Second Source when single-source risk "
        "exists, except a commodity market (where a second source is automatic). "
        "(2) ITAR-controlled parts never return an unrestricted Buy; they are "
        "floored to a domestic qualified source, outranking the lifecycle "
        "override. Overrides are shown explicitly and never folded silently into "
        "a score."
    )
