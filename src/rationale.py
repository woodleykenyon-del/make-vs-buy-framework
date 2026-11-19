"""Deterministic explanations of completed make-or-buy decisions."""

from __future__ import annotations

from decision_engine import (
    DecisionResult,
    ECONOMIC_WEIGHTS,
    STRATEGIC_WEIGHTS,
)

# Human-readable factor labels for narratives.
FACTOR_LABELS = {
    "cost_delta": "make-vs-buy cost",
    "capital_burden": "capital/NRE burden",
    "capacity": "internal capacity",
    "volume_stability": "volume stability",
    "criticality": "part criticality",
    "ip_control": "IP / design control",
    "supply_risk": "supply market risk",
    "regulatory": "regulatory / export status",
    "roadmap": "technology roadmap fit",
    "lifecycle": "program lifecycle stage",
}


def _top_drivers(result: DecisionResult, n: int = 2) -> list[str]:
    """Identify the factors contributing most strongly toward the recommended
    direction, weighted by intra-layer weight.

    For Make-leaning recommendations, only factors above neutral (favoring
    Make) are considered drivers; for Buy-leaning, only factors below neutral.
    This prevents naming a strong Buy-signal as a 'driver' of a Make decision.
    """
    # Buy and Buy / Qualify Second Source are fundamentally buy recommendations;
    # their drivers point toward Buy. Domestic Make / Qualified-Source Only is a
    # constraint-driven outcome but still a make-side path, so it stays make-leaning.
    make_leaning = result.recommendation not in (
        "Buy", "Buy / Qualify Second Source",
    )
    contributions: dict[str, float] = {}
    for k, v in result.economic_factors.items():
        directional = (v - 50) if make_leaning else (50 - v)
        if directional > 0:
            contributions[FACTOR_LABELS[k]] = directional * ECONOMIC_WEIGHTS[k]
    for k, v in result.strategic_factors.items():
        directional = (v - 50) if make_leaning else (50 - v)
        if directional > 0:
            contributions[FACTOR_LABELS[k]] = directional * STRATEGIC_WEIGHTS[k]
    if not contributions:
        # Fall back to largest-magnitude factors if nothing points the chosen way.
        allf = {**{FACTOR_LABELS[k]: abs(v - 50) * ECONOMIC_WEIGHTS[k]
                   for k, v in result.economic_factors.items()},
                **{FACTOR_LABELS[k]: abs(v - 50) * STRATEGIC_WEIGHTS[k]
                   for k, v in result.strategic_factors.items()}}
        contributions = allf
    ranked = sorted(contributions.items(), key=lambda x: x[1], reverse=True)
    return [name for name, _ in ranked[:n]]


def deterministic_narrative(result: DecisionResult) -> str:
    """Explain the engine recommendation and its supporting evidence."""
    drivers = _top_drivers(result)
    driver_text = " and ".join(drivers)
    delta = result.annual_cost_delta
    if delta > 0:
        cost_line = f"Making is about ${abs(delta):,.0f}/yr cheaper all-in."
    elif delta < 0:
        cost_line = f"Buying is about ${abs(delta):,.0f}/yr cheaper all-in."
    else:
        cost_line = "Make and buy costs are roughly even."

    rec = result.recommendation
    if rec == "Strategic Make":
        lead = (
            f"Economics lean toward Buy ({result.economic_score:.0f}/100), but "
            f"strategic factors strongly favor making in-house "
            f"({result.strategic_score:.0f}/100)."
        )
        close = f"The decision is driven by {driver_text}, which justify the cost premium."
    elif rec == "Make":
        lead = (
            f"Both economics ({result.economic_score:.0f}/100) and strategy "
            f"({result.strategic_score:.0f}/100) favor making in-house."
        )
        close = f"{driver_text.capitalize()} reinforce a clear make case."
    elif rec == "Buy":
        # A Buy can now arise from a mode-tipped close call where one layer still
        # favors Make. The copy must not claim both favor buying when they don't.
        econ_make = result.economic_score >= 50
        strat_make = result.strategic_score >= 50
        if not econ_make and not strat_make:
            lead = (
                f"Economics ({result.economic_score:.0f}/100) and strategy "
                f"({result.strategic_score:.0f}/100) both favor buying."
            )
            close = f"There is no strategic reason to insource; {driver_text} point to Buy."
        elif econ_make and not strat_make:
            lead = (
                f"Economics favor making ({result.economic_score:.0f}/100), but "
                f"strategic lock-in is low ({result.strategic_score:.0f}/100)."
            )
            close = (
                "Under the selected decision lens the lack of strategic justification "
                "outweighs the cost advantage, so the call is to buy."
            )
        else:  # strategic favors make, economics favor buy
            lead = (
                f"A strategic pull exists ({result.strategic_score:.0f}/100), but the "
                f"economics favor buying ({result.economic_score:.0f}/100)."
            )
            close = (
                "Under the selected decision lens, cost, lifecycle, or mode logic "
                "outweighs the strategic pull, so the call is to buy."
            )
    elif rec.startswith("Opportunistic"):
        lead = (
            f"Economics favor making now ({result.economic_score:.0f}/100), but "
            f"strategic lock-in is low ({result.strategic_score:.0f}/100)."
        )
        close = (
            "Make while favorable, but treat it as reversible and consider "
            "dual-sourcing as a hedge if capacity tightens."
        )
    elif rec.startswith("Buy / Qualify"):
        lead = (
            f"The economics do not favor making ({result.economic_score:.0f}/100), "
            "so the recommendation is to buy."
        )
        close = (
            "Single-source or constrained-source exposure on a critical part means "
            "the buy should be hedged by qualifying a second source rather than "
            "relying on one supplier."
        )
    elif rec.startswith("Domestic"):
        lead = (
            f"Economics favor Buy, but export control rules out an unrestricted "
            f"buy (strategy {result.strategic_score:.0f}/100)."
        )
        close = "Any buy must go to a domestic, qualified source."
    else:  # Marginal
        lead = (
            f"Economics ({result.economic_score:.0f}/100) and strategy "
            f"({result.strategic_score:.0f}/100) are both near-neutral."
        )
        close = "The signals do not support a confident call; gather more data before deciding."

    flag_text = ""
    if result.flags:
        flag_text = " " + " ".join(result.flags)

    return f"{lead} {cost_line} {close}{flag_text}"
