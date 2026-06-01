"""Deterministic Make vs. Buy decision engine.

Tool 5 of the Strategic Sourcing Decision Suite.

Design principles (locked):
- Fully deterministic. Same inputs always produce identical outputs.
- Cost is one weighted input, never the answer. Two-layer engine:
  Economic layer + Strategic layer, each scored 0-100 where
  higher = favors MAKE, lower = favors BUY, 50 = neutral.
- The recommendation is derived from a 2x2 quadrant (economic x strategic),
  modified by explicit, visible override flags.
- No AI in the scoring. An AI narrative layer (separate module) only
  EXPLAINS the recommendation this engine produces.

Nothing in this module is hidden: every category->score mapping, every
weight, and every threshold is a named constant so the UI can render the
full "how scoring works" reference directly from these tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Locked assumptions
# ---------------------------------------------------------------------------

AMORTIZATION_YEARS: int = 5  # Defense/aerospace program horizon. Stated in UI.

NEUTRAL: float = 50.0
NEUTRAL_BAND: tuple[float, float] = (45.0, 55.0)  # inclusive band for "Marginal"
# How close to neutral a mode-weighted blend must be for the scoring mode to
# tip an off-diagonal recommendation. Beyond this margin the case is decisive
# and mode does not override the quadrant.
CLOSE_CALL_MARGIN: float = 12.0

# ---------------------------------------------------------------------------
# Economic layer
# ---------------------------------------------------------------------------
# Intra-layer factor weights (sum to 1.0). Cost delta leads; capital burden
# second. Capacity and volume stability are situational modifiers.
ECONOMIC_WEIGHTS: dict[str, float] = {
    "cost_delta": 0.45,
    "capital_burden": 0.25,
    "capacity": 0.15,
    "volume_stability": 0.15,
}

# Capacity: idle internal capacity makes the marginal cost of making low, so
# it favors Make. Over-capacity means making would require investment/overtime
# or displace other work, favoring Buy.
CAPACITY_SCORES: dict[str, float] = {
    "Idle": 85.0,
    "Available": 65.0,
    "Tight": 35.0,
    "Over-capacity": 15.0,
}

# Volume profile: high stable volume justifies absorbing fixed make costs
# (favors Make). Low or erratic volume favors Buy (avoid fixed commitment).
VOLUME_STABILITY_SCORES: dict[str, float] = {
    "High & stable": 80.0,
    "Moderate": 50.0,
    "Low or erratic": 20.0,
}

# ---------------------------------------------------------------------------
# Strategic layer
# ---------------------------------------------------------------------------
# Criticality and IP lead: in defense they most often drive the decision.
# Lifecycle is included because a program's stage gates capital decisions: you
# do not invest tooling into a sunsetting program regardless of how critical
# the part is. (Lifecycle also drives a separate hard override in evaluate().)
STRATEGIC_WEIGHTS: dict[str, float] = {
    "criticality": 0.23,
    "ip_control": 0.20,
    "supply_risk": 0.20,
    "regulatory": 0.16,
    "roadmap": 0.11,
    "lifecycle": 0.10,
}

# Program / part lifecycle stage. Growing programs justify building capability
# (favors Make); sunsetting programs argue against capital investment (favors
# Buy). Beyond the score weight, "Sunsetting" can trigger a hard override when
# the economics do not already favor making (see evaluate()).
LIFECYCLE_SCORES: dict[str, float] = {
    "Growing": 80.0,
    "Stable": 55.0,
    "Declining": 30.0,
    "Sunsetting": 12.0,
}

# IP / design control: proprietary differentiating IP favors keeping it
# in-house (Make). Commodity COTS favors Buy.
IP_CONTROL_SCORES: dict[str, float] = {
    "Core proprietary": 90.0,
    "Sensitive": 70.0,
    "Standard": 40.0,
    "Commodity": 15.0,
}

# Part criticality: flight/safety-critical favors Make (control quality,
# traceability, configuration). Non-critical favors Buy.
CRITICALITY_SCORES: dict[str, float] = {
    "Flight-critical": 90.0,
    "Mission-critical": 72.0,
    "Important": 45.0,
    "Non-critical": 20.0,
}

# Supply market risk: single-source / fragile / concentrated markets favor
# insourcing to de-risk (Make). Deep competitive markets favor Buy.
SUPPLY_RISK_SCORES: dict[str, float] = {
    "Single-source": 85.0,
    "Limited": 65.0,
    "Competitive": 35.0,
    "Commodity": 15.0,
}

# Regulatory / export control: ITAR / export-sensitive / controlled-process
# work favors domestic Make (or at minimum domestic qualified source).
REGULATORY_SCORES: dict[str, float] = {
    "ITAR-controlled": 88.0,
    "Export-sensitive": 70.0,
    "Regulated-process": 55.0,
    "Unrestricted": 30.0,
}

# Technology roadmap alignment: a capability strategic to own for the future
# favors Make; a declining / non-core technology favors Buy.
ROADMAP_SCORES: dict[str, float] = {
    "Strategic-to-own": 85.0,
    "Useful": 60.0,
    "Neutral": 45.0,
    "Divesting": 20.0,
}

# ---------------------------------------------------------------------------
# Scoring modes: re-weight the BLEND of the two layers, not factors within.
# (economic_weight, strategic_weight)
# ---------------------------------------------------------------------------
MODE_BLENDS: dict[str, tuple[float, float]] = {
    "Balanced": (0.50, 0.50),
    "Cost-Driven": (0.70, 0.30),
    "Strategic-Driven": (0.30, 0.70),
}

# ---------------------------------------------------------------------------
# Recommendation labels and deterministic sort priority (lower = surfaces
# first in the comparison table). Strategic Make leads so the cases a
# spreadsheet would get wrong rise to the top.
# ---------------------------------------------------------------------------
REC_STRATEGIC_MAKE = "Strategic Make"
REC_MAKE = "Make"
REC_OPPORTUNISTIC = "Opportunistic Make / Dual-Source"
REC_QUALIFY_SECOND = "Buy / Qualify Second Source"
REC_MARGINAL = "Marginal - Gather More Data"
REC_BUY = "Buy"
REC_DOMESTIC_ONLY = "Domestic Make / Qualified-Source Only"

RECOMMENDATION_SORT_PRIORITY: dict[str, int] = {
    REC_STRATEGIC_MAKE: 0,
    REC_DOMESTIC_ONLY: 1,
    REC_MAKE: 2,
    REC_OPPORTUNISTIC: 3,
    REC_QUALIFY_SECOND: 4,
    REC_MARGINAL: 5,
    REC_BUY: 6,
}

# Valid category lists, exposed for UI dropdowns and validation.
VALID_CATEGORIES: dict[str, list[str]] = {
    "capacity": list(CAPACITY_SCORES),
    "volume_stability": list(VOLUME_STABILITY_SCORES),
    "ip_control": list(IP_CONTROL_SCORES),
    "criticality": list(CRITICALITY_SCORES),
    "supply_risk": list(SUPPLY_RISK_SCORES),
    "regulatory": list(REGULATORY_SCORES),
    "roadmap": list(ROADMAP_SCORES),
    "lifecycle": list(LIFECYCLE_SCORES),
}

Mode = Literal["Balanced", "Cost-Driven", "Strategic-Driven"]


# ---------------------------------------------------------------------------
# Input / output containers
# ---------------------------------------------------------------------------
@dataclass
class PartInput:
    """All inputs required to evaluate one part."""

    part_name: str
    annual_volume: int
    make_unit_cost: float
    buy_unit_quote: float
    nonrecurring_investment: float
    capacity: str
    volume_stability: str
    ip_control: str
    criticality: str
    supply_risk: str
    regulatory: str
    roadmap: str
    lifecycle: str = "Stable"
    mode: Mode = "Balanced"
    description: str = ""


@dataclass
class DecisionResult:
    """Full deterministic output for one part."""

    part_name: str
    description: str
    mode: str
    economic_score: float
    strategic_score: float
    blended_score: float
    recommendation: str
    quadrant: str
    flags: list[str] = field(default_factory=list)
    # Economic detail
    annual_make_cost: float = 0.0
    annual_buy_cost: float = 0.0
    amortized_nre_annual: float = 0.0
    annual_cost_delta: float = 0.0  # positive => buying costs more (Make cheaper)
    breakeven_volume: float | None = None  # units/yr where make == buy all-in
    breakeven_note: str = ""
    sensitivity: str = ""  # "robust" or "sensitive" qualitative flag
    # Per-factor scores for breakdown charts
    economic_factors: dict[str, float] = field(default_factory=dict)
    strategic_factors: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _validate_category(field_name: str, value: str) -> None:
    valid = VALID_CATEGORIES[field_name]
    if value not in valid:
        raise ValueError(
            f"Invalid {field_name}: {value!r}. Expected one of {valid}."
        )


def validate_input(part: PartInput) -> None:
    """Raise ValueError if any input is out of range or an unknown category."""
    if part.mode not in MODE_BLENDS:
        raise ValueError(f"Invalid mode: {part.mode!r}. Expected one of {list(MODE_BLENDS)}.")
    if part.annual_volume < 1:
        raise ValueError("annual_volume must be >= 1. Zero volume is not a sourcing decision.")
    if part.make_unit_cost < 0:
        raise ValueError("make_unit_cost must be >= 0.")
    if part.buy_unit_quote <= 0:
        raise ValueError("buy_unit_quote must be > 0. A zero quote indicates a missing or invalid input.")
    if part.nonrecurring_investment < 0:
        raise ValueError("nonrecurring_investment must be >= 0.")
    for fname in ("capacity", "volume_stability", "ip_control",
                  "criticality", "supply_risk", "regulatory", "roadmap",
                  "lifecycle"):
        _validate_category(fname, getattr(part, fname))


# ---------------------------------------------------------------------------
# Economic layer
# ---------------------------------------------------------------------------
def cost_delta_score(annual_make_cost: float, annual_buy_cost: float) -> float:
    """Directional 0-100 score from the make/buy cost comparison.

    higher = making is cheaper (favors Make), lower = buying is cheaper.
    Uses a bounded ratio so the score normalizes across part values rather
    than swinging on raw dollar magnitude. A make/buy ratio of 1.0 -> 50.
    The score saturates: making >= ~40% cheaper -> ~100; >= ~40% pricier -> ~0.
    """
    if annual_make_cost <= 0 and annual_buy_cost <= 0:
        return NEUTRAL
    if annual_buy_cost <= 0:
        # Buying is free-ish; strongly favors Buy.
        return 0.0
    if annual_make_cost <= 0:
        return 100.0
    ratio = annual_make_cost / annual_buy_cost  # <1 means make is cheaper
    # Map ratio 0.6 -> 100, 1.0 -> 50, 1.4 -> 0 (linear, then clipped).
    score = 50.0 + (1.0 - ratio) * 125.0
    return _clip(score)


def economic_layer(part: PartInput) -> tuple[float, dict[str, float], dict[str, float]]:
    """Return (economic_score, factor_scores, cost_detail)."""
    annual_make = part.make_unit_cost * part.annual_volume
    amortized_nre = (part.nonrecurring_investment / AMORTIZATION_YEARS
                     if part.nonrecurring_investment else 0.0)
    annual_make_loaded = annual_make + amortized_nre
    annual_buy = part.buy_unit_quote * part.annual_volume

    f_cost = cost_delta_score(annual_make_loaded, annual_buy)

    # Capital burden: amortized NRE as a share of annual buy spend. Heavier
    # burden favors Buy (lower score). Rests at NEUTRAL when no investment is
    # required (zero NRE neither favors nor opposes making). Saturates toward 0
    # as amortized NRE approaches ~25% of annual buy spend.
    if amortized_nre <= 0:
        f_capital = NEUTRAL
    elif annual_buy > 0:
        burden_ratio = amortized_nre / annual_buy
        f_capital = _clip(NEUTRAL - burden_ratio * 200.0)
    else:
        f_capital = 0.0  # investment required but no buy alternative spend basis

    f_capacity = CAPACITY_SCORES[part.capacity]
    f_volume = VOLUME_STABILITY_SCORES[part.volume_stability]

    factors = {
        "cost_delta": f_cost,
        "capital_burden": f_capital,
        "capacity": f_capacity,
        "volume_stability": f_volume,
    }
    score = sum(factors[k] * ECONOMIC_WEIGHTS[k] for k in ECONOMIC_WEIGHTS)
    cost_detail = {
        "annual_make_cost": annual_make_loaded,
        "annual_buy_cost": annual_buy,
        "amortized_nre_annual": amortized_nre,
        "annual_cost_delta": annual_buy - annual_make_loaded,
    }
    return _clip(score), factors, cost_detail


# ---------------------------------------------------------------------------
# Strategic layer
# ---------------------------------------------------------------------------
def strategic_layer(part: PartInput) -> tuple[float, dict[str, float]]:
    factors = {
        "criticality": CRITICALITY_SCORES[part.criticality],
        "ip_control": IP_CONTROL_SCORES[part.ip_control],
        "supply_risk": SUPPLY_RISK_SCORES[part.supply_risk],
        "regulatory": REGULATORY_SCORES[part.regulatory],
        "roadmap": ROADMAP_SCORES[part.roadmap],
        "lifecycle": LIFECYCLE_SCORES[part.lifecycle],
    }
    score = sum(factors[k] * STRATEGIC_WEIGHTS[k] for k in STRATEGIC_WEIGHTS)
    return _clip(score), factors


# ---------------------------------------------------------------------------
# Break-even volume and sensitivity
# ---------------------------------------------------------------------------
def breakeven_volume(part: PartInput) -> tuple[float | None, str]:
    """Annual volume at which all-in make cost equals buy cost.

    make_total(v)  = make_unit_cost * v + amortized_nre
    buy_total(v)   = buy_unit_quote * v
    Setting equal:  v* = amortized_nre / (buy_unit_quote - make_unit_cost)

    Only defined when making is cheaper per unit (positive denominator); the
    fixed NRE is then recovered by per-unit savings above v* units/year.
    Returns (volume, note). volume is None when no finite break-even exists.
    """
    amortized_nre = (part.nonrecurring_investment / AMORTIZATION_YEARS
                     if part.nonrecurring_investment else 0.0)
    unit_savings = part.buy_unit_quote - part.make_unit_cost  # >0 => make cheaper per unit

    if unit_savings <= 0:
        # Making is not cheaper per unit; NRE never pays back through volume.
        return None, "Making is not cheaper per unit, so volume alone never makes it pay back."
    if amortized_nre <= 0:
        return 0.0, "Making is cheaper per unit with no tooling to recover; favorable at any volume."

    v_star = amortized_nre / unit_savings
    if part.annual_volume >= v_star:
        note = (f"Make pays back above ~{v_star:,.0f} units/yr. "
                f"At the current {part.annual_volume:,} units, making is favorable.")
    else:
        note = (f"Make pays back above ~{v_star:,.0f} units/yr. "
                f"The current {part.annual_volume:,} units is below break-even, so buying is cheaper.")
    return v_star, note


def sensitivity_flag(part: PartInput, econ_score: float) -> str:
    """Qualitative robustness flag: would a 10% move in the buy quote flip the
    economic layer across the neutral line? If so, the economics are 'sensitive'."""
    lo, hi = NEUTRAL_BAND
    for factor in (0.9, 1.1):
        bumped = PartInput(**{**part.__dict__, "buy_unit_quote": part.buy_unit_quote * factor})
        bumped_score, _, _ = economic_layer(bumped)
        # Flip across neutral, or move from outside the band to the other side.
        if (econ_score >= NEUTRAL) != (bumped_score >= NEUTRAL):
            return "sensitive"
    # Also flag if the economic score simply sits inside the neutral band.
    if lo <= econ_score <= hi:
        return "sensitive"
    return "robust"


# ---------------------------------------------------------------------------
# Quadrant + recommendation
# ---------------------------------------------------------------------------
def assign_quadrant(economic: float, strategic: float) -> str:
    """Name the 2x2 quadrant. Neutral band on BOTH axes -> Marginal."""
    lo, hi = NEUTRAL_BAND
    if lo <= economic <= hi and lo <= strategic <= hi:
        return "Marginal"
    econ_make = economic >= NEUTRAL
    strat_make = strategic >= NEUTRAL
    if econ_make and strat_make:
        return "Make"
    if not econ_make and not strat_make:
        return "Buy"
    if not econ_make and strat_make:
        return "Strategic Make"
    return "Opportunistic Make / Dual-Source"


def evaluate(part: PartInput) -> DecisionResult:
    """Full deterministic evaluation of one part.

    Recommendation logic, in order:
      1. Base recommendation from the quadrant (economic x strategic).
      2. Mode resolves CLOSE CALLS only. In the two off-diagonal quadrants,
         the blended score (which mode shifts) crossing neutral tips the call.
         Clear-agreement quadrants (Make, Buy) and Marginal never flex.
      3. Sunsetting override: a sunsetting program whose economics do not
         already favor making is forced off Make (capital discipline). Lands
         on Buy, or Buy / Qualify Second Source when single-source risk exists,
         except a Commodity market (where second-sourcing is automatic) stays Buy.
      4. ITAR override (hardest): a controlled part never returns an
         unrestricted Buy; it is floored to a domestic qualified source.
    Overrides are recorded as explicit flags, never folded silently into a score.
    """
    validate_input(part)

    econ_score, econ_factors, cost_detail = economic_layer(part)
    strat_score, strat_factors = strategic_layer(part)

    e_w, s_w = MODE_BLENDS[part.mode]
    blended = _clip(econ_score * e_w + strat_score * s_w)

    quadrant = assign_quadrant(econ_score, strat_score)
    flags: list[str] = []

    single_source_risk = (
        part.supply_risk in ("Single-source", "Limited")
        and part.criticality in ("Flight-critical", "Mission-critical")
    )

    # --- 1 + 2: quadrant base, with mode resolving the off-diagonal cases ----
    if quadrant == "Marginal":
        recommendation = REC_MARGINAL
    elif quadrant == "Make":
        recommendation = REC_MAKE
    elif quadrant == "Buy":
        recommendation = REC_BUY
    elif quadrant == "Strategic Make":
        # Cheap to buy, strategic reasons to make. Under Balanced this stands as
        # Strategic Make. Cost-Driven can step it down ONLY when its cost-weighted
        # blend is a genuine close call below neutral AND Balanced was near the
        # line. It must NOT step down an ITAR-controlled part: export control is
        # exactly why such a part is held in-house, so a cost posture cannot
        # talk it out of Strategic Make.
        #
        # When a non-ITAR strategic part is tipped: it does not become
        # "Opportunistic" (that means cheap-to-make / low-lock-in, the opposite
        # corner). It steps down to a hedged Buy. Single-source/critical risk
        # warrants qualifying a second source; otherwise plain Buy.
        balanced_blend = _clip(econ_score * 0.5 + strat_score * 0.5)
        tippable = (
            part.mode == "Cost-Driven"
            and part.regulatory != "ITAR-controlled"
            and NEUTRAL - CLOSE_CALL_MARGIN <= blended < NEUTRAL
            and balanced_blend < NEUTRAL + CLOSE_CALL_MARGIN
        )
        if tippable:
            if part.supply_risk == "Single-source" or single_source_risk:
                recommendation = REC_QUALIFY_SECOND
            else:
                recommendation = REC_BUY
            flags.append(
                "Cost-Driven mode tipped a close call: the strategic pull is real, "
                "but under cost priority the blend favors buying over insourcing."
            )
        else:
            recommendation = REC_STRATEGIC_MAKE
    else:  # Opportunistic Make / Dual-Source quadrant
        # Cheap to make, low strategic lock-in. Under Balanced this stands as
        # Opportunistic. Strategic-Driven can step it down to Buy ONLY when its
        # strategy-weighted blend is a genuine close call below neutral and
        # Balanced was near the line.
        balanced_blend = _clip(econ_score * 0.5 + strat_score * 0.5)
        if (part.mode == "Strategic-Driven"
                and NEUTRAL - CLOSE_CALL_MARGIN <= blended < NEUTRAL
                and balanced_blend < NEUTRAL + CLOSE_CALL_MARGIN):
            recommendation = REC_BUY
            flags.append(
                "Strategic-Driven mode tipped a close call: making is cheaper now, "
                "but under strategic priority the lack of lock-in favors buying."
            )
        else:
            recommendation = REC_OPPORTUNISTIC

    # --- 3: Sunsetting override (capital discipline) -------------------------
    # A sunsetting program whose economics do not already favor making should
    # not absorb tooling investment, regardless of strategic flags.
    making_favored = econ_score >= NEUTRAL
    if (part.lifecycle == "Sunsetting" and not making_favored
            and recommendation in (REC_MAKE, REC_STRATEGIC_MAKE, REC_OPPORTUNISTIC)):
        if part.supply_risk == "Single-source" or single_source_risk:
            recommendation = REC_QUALIFY_SECOND
        else:
            # Competitive / commodity / limited markets without true single-source
            # risk: no second-source qualification project needed, just buy.
            recommendation = REC_BUY
        flags.append(
            "Sunsetting program with unfavorable make economics: capital "
            "investment in tooling is not justified for a program being retired."
        )

    # --- 4: ITAR override (hard constraint, outranks everything above) -------
    if part.regulatory == "ITAR-controlled":
        flags.append(
            "ITAR-controlled: unrestricted Buy not permitted. "
            "Any buy must be a domestic, qualified source."
        )
        if recommendation in (REC_BUY, REC_QUALIFY_SECOND):
            recommendation = REC_DOMESTIC_ONLY

    # Strategic supply-risk flag (informational; does not change the rec here).
    if part.supply_risk == "Single-source" and part.criticality == "Flight-critical":
        flags.append(
            "Strategic supply risk: single-source market for a flight-critical "
            "part. Continuity exposure even where economics favor Buy."
        )

    be_vol, be_note = breakeven_volume(part)
    sens = sensitivity_flag(part, econ_score)

    return DecisionResult(
        part_name=part.part_name,
        description=part.description,
        mode=part.mode,
        economic_score=round(econ_score, 1),
        strategic_score=round(strat_score, 1),
        blended_score=round(blended, 1),
        recommendation=recommendation,
        quadrant=quadrant,
        flags=flags,
        annual_make_cost=round(cost_detail["annual_make_cost"], 2),
        annual_buy_cost=round(cost_detail["annual_buy_cost"], 2),
        amortized_nre_annual=round(cost_detail["amortized_nre_annual"], 2),
        annual_cost_delta=round(cost_detail["annual_cost_delta"], 2),
        breakeven_volume=(round(be_vol, 0) if be_vol is not None else None),
        breakeven_note=be_note,
        sensitivity=sens,
        economic_factors={k: round(v, 1) for k, v in econ_factors.items()},
        strategic_factors={k: round(v, 1) for k, v in strat_factors.items()},
    )


def recommendation_sort_key(recommendation: str) -> int:
    """Deterministic ordering for the comparison table (Strategic Make first)."""
    return RECOMMENDATION_SORT_PRIORITY.get(recommendation, 99)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
