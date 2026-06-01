"""Test suite for the Make vs. Buy decision engine.

Run: python tests/test_engine.py
Counts assertions and reports pass/fail. No external test framework needed,
consistent with the rest of the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "data"))

import decision_engine as eng  # noqa: E402
from decision_engine import PartInput, evaluate  # noqa: E402
from sample_parts import SAMPLE_PARTS, EXPECTED_RECOMMENDATIONS  # noqa: E402

_passed = 0
_failed = 0


def check(label: str, condition: bool) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {label}")


def base_part(**overrides) -> PartInput:
    """A neutral-ish baseline part; override fields per test."""
    defaults = dict(
        part_name="Test Part",
        annual_volume=1000,
        make_unit_cost=100.0,
        buy_unit_quote=100.0,
        nonrecurring_investment=0.0,
        capacity="Available",
        volume_stability="Moderate",
        ip_control="Standard",
        criticality="Important",
        supply_risk="Limited",
        regulatory="Unrestricted",
        roadmap="Neutral",
        lifecycle="Stable",
        mode="Balanced",
    )
    defaults.update(overrides)
    return PartInput(**defaults)


# --- Cost math -------------------------------------------------------------
def test_cost_math() -> None:
    # Make cheaper per unit at volume high enough that amortized NRE doesn't
    # flip the all-in comparison: 8 vs 12 over 10k units = 40k/yr unit savings
    # against 10k/yr amortized NRE.
    p = base_part(make_unit_cost=8.0, buy_unit_quote=12.0,
                  annual_volume=10000, nonrecurring_investment=50000.0)
    r = evaluate(p)
    check("annual make cost includes amortized NRE",
          r.annual_make_cost == 8.0 * 10000 + 50000.0 / eng.AMORTIZATION_YEARS)
    check("annual buy cost correct", r.annual_buy_cost == 12.0 * 10000)
    check("amortized NRE over 5 years", r.amortized_nre_annual == 50000.0 / 5)
    check("cost delta positive when make is cheaper all-in", r.annual_cost_delta > 0)

    p2 = base_part(make_unit_cost=15.0, buy_unit_quote=10.0, annual_volume=500,
                   nonrecurring_investment=0.0)
    r2 = evaluate(p2)
    check("cost delta negative when buy is cheaper", r2.annual_cost_delta < 0)
    check("zero NRE -> zero amortized", r2.amortized_nre_annual == 0.0)


# --- Directional cost scoring ---------------------------------------------
def test_cost_delta_direction() -> None:
    cheaper_make = eng.cost_delta_score(60.0, 100.0)
    cheaper_buy = eng.cost_delta_score(140.0, 100.0)
    equal = eng.cost_delta_score(100.0, 100.0)
    check("cheaper to make -> score > 50", cheaper_make > 50)
    check("cheaper to buy -> score < 50", cheaper_buy < 50)
    check("equal cost -> score ~50", abs(equal - 50.0) < 0.01)
    check("cost score clipped to 0-100", 0 <= eng.cost_delta_score(1000.0, 1.0) <= 100)
    check("cost score clipped high", eng.cost_delta_score(1.0, 1000.0) == 100.0)
    check("both zero cost -> neutral", eng.cost_delta_score(0.0, 0.0) == 50.0)


# --- Category lookups complete and correct ---------------------------------
def test_category_lookups() -> None:
    tables = [
        eng.CAPACITY_SCORES, eng.VOLUME_STABILITY_SCORES, eng.IP_CONTROL_SCORES,
        eng.CRITICALITY_SCORES, eng.SUPPLY_RISK_SCORES, eng.REGULATORY_SCORES,
        eng.ROADMAP_SCORES,
    ]
    for t in tables:
        for v in t.values():
            check("every lookup value in 0-100", 0 <= v <= 100)
    # Directional sanity on the headline strategic factors.
    check("flight-critical scores highest criticality",
          eng.CRITICALITY_SCORES["Flight-critical"] == max(eng.CRITICALITY_SCORES.values()))
    check("commodity IP scores lowest",
          eng.IP_CONTROL_SCORES["Commodity"] == min(eng.IP_CONTROL_SCORES.values()))
    check("single-source scores highest supply risk",
          eng.SUPPLY_RISK_SCORES["Single-source"] == max(eng.SUPPLY_RISK_SCORES.values()))
    check("ITAR scores highest regulatory",
          eng.REGULATORY_SCORES["ITAR-controlled"] == max(eng.REGULATORY_SCORES.values()))
    check("idle capacity scores highest",
          eng.CAPACITY_SCORES["Idle"] == max(eng.CAPACITY_SCORES.values()))


def test_invalid_category_raises() -> None:
    raised = False
    try:
        evaluate(base_part(criticality="Super-critical"))
    except ValueError:
        raised = True
    check("invalid category raises ValueError", raised)

    raised_mode = False
    try:
        evaluate(base_part(mode="Turbo"))
    except ValueError:
        raised_mode = True
    check("invalid mode raises ValueError", raised_mode)

    raised_neg = False
    try:
        evaluate(base_part(annual_volume=-5))
    except ValueError:
        raised_neg = True
    check("negative volume raises ValueError", raised_neg)

    raised_zero_vol = False
    try:
        evaluate(base_part(annual_volume=0))
    except ValueError:
        raised_zero_vol = True
    check("zero volume raises ValueError", raised_zero_vol)

    raised_zero_quote = False
    try:
        evaluate(base_part(buy_unit_quote=0.0))
    except ValueError:
        raised_zero_quote = True
    check("zero buy quote raises ValueError", raised_zero_quote)

    raised_lifecycle = False
    try:
        evaluate(base_part(lifecycle="Brand-new"))
    except ValueError:
        raised_lifecycle = True
    check("invalid lifecycle raises ValueError", raised_lifecycle)


# --- Weights sum to 1.0 ----------------------------------------------------
def test_weights_sum() -> None:
    check("economic weights sum to 1.0", abs(sum(eng.ECONOMIC_WEIGHTS.values()) - 1.0) < 1e-9)
    check("strategic weights sum to 1.0", abs(sum(eng.STRATEGIC_WEIGHTS.values()) - 1.0) < 1e-9)
    for mode, (e, s) in eng.MODE_BLENDS.items():
        check(f"mode blend sums to 1.0 ({mode})", abs(e + s - 1.0) < 1e-9)


# --- Layer aggregation on a known fixture ---------------------------------
def test_layer_aggregation() -> None:
    # All strategic factors at their max-category should yield a high score.
    p = base_part(ip_control="Core proprietary", criticality="Flight-critical",
                  supply_risk="Single-source", regulatory="ITAR-controlled",
                  roadmap="Strategic-to-own", lifecycle="Growing")
    score, factors = eng.strategic_layer(p)
    manual = sum(factors[k] * eng.STRATEGIC_WEIGHTS[k] for k in eng.STRATEGIC_WEIGHTS)
    check("strategic layer equals manual weighted sum", abs(score - manual) < 0.01)
    check("all-make-favoring strategic inputs -> high score", score > 80)
    check("lifecycle included in strategic factors", "lifecycle" in factors)

    p2 = base_part(ip_control="Commodity", criticality="Non-critical",
                   supply_risk="Commodity", regulatory="Unrestricted",
                   roadmap="Divesting", lifecycle="Sunsetting")
    score2, _ = eng.strategic_layer(p2)
    check("all-buy-favoring strategic inputs -> low score", score2 < 30)


# --- Mode weighting --------------------------------------------------------
def test_modes() -> None:
    # A part with high strategic, low economic should score higher blended
    # under Strategic-Driven than under Cost-Driven.
    kw = dict(make_unit_cost=140.0, buy_unit_quote=100.0,  # buy cheaper -> low econ
              ip_control="Core proprietary", criticality="Flight-critical",
              supply_risk="Single-source", regulatory="Export-sensitive",
              roadmap="Strategic-to-own")
    r_cost = evaluate(base_part(mode="Cost-Driven", **kw))
    r_strat = evaluate(base_part(mode="Strategic-Driven", **kw))
    r_bal = evaluate(base_part(mode="Balanced", **kw))
    check("strategic-driven blended > cost-driven for strategic part",
          r_strat.blended_score > r_cost.blended_score)
    check("balanced blended between the two",
          r_cost.blended_score <= r_bal.blended_score <= r_strat.blended_score)
    check("mode does not change economic factor scores",
          r_cost.economic_score == r_strat.economic_score)
    check("mode does not change strategic factor scores",
          r_cost.strategic_score == r_strat.strategic_score)


# --- Quadrant assignment ---------------------------------------------------
def test_quadrants() -> None:
    check("high/high -> Make", eng.assign_quadrant(80, 80) == "Make")
    check("low/low -> Buy", eng.assign_quadrant(20, 20) == "Buy")
    check("low econ/high strat -> Strategic Make",
          eng.assign_quadrant(20, 80) == "Strategic Make")
    check("high econ/low strat -> Opportunistic",
          eng.assign_quadrant(80, 20) == "Opportunistic Make / Dual-Source")
    check("both in neutral band -> Marginal",
          eng.assign_quadrant(50, 50) == "Marginal")
    check("neutral band edges inclusive",
          eng.assign_quadrant(45, 55) == "Marginal")
    check("just outside band not Marginal",
          eng.assign_quadrant(44, 80) != "Marginal")


# --- Overrides -------------------------------------------------------------
def test_overrides() -> None:
    # ITAR part that would otherwise be a Buy must not be unrestricted Buy.
    itar_buy = base_part(
        make_unit_cost=140.0, buy_unit_quote=100.0,  # buy cheaper
        ip_control="Commodity", criticality="Non-critical",
        supply_risk="Commodity", regulatory="ITAR-controlled",
        roadmap="Divesting")
    r = evaluate(itar_buy)
    check("ITAR never returns unrestricted Buy", r.recommendation != "Buy")
    check("ITAR buy converted to domestic-only",
          r.recommendation == eng.REC_DOMESTIC_ONLY)
    check("ITAR flag present", any("ITAR" in f for f in r.flags))

    # Single-source + flight-critical raises strategic supply risk flag.
    risky = base_part(supply_risk="Single-source", criticality="Flight-critical")
    r2 = evaluate(risky)
    check("single-source flight-critical raises supply risk flag",
          any("Strategic supply risk" in f for f in r2.flags))

    # Non-ITAR plain commodity Buy keeps the Buy recommendation.
    plain_buy = base_part(
        make_unit_cost=140.0, buy_unit_quote=100.0,
        ip_control="Commodity", criticality="Non-critical",
        supply_risk="Commodity", regulatory="Unrestricted", roadmap="Divesting")
    r3 = evaluate(plain_buy)
    check("non-ITAR commodity stays Buy", r3.recommendation == "Buy")


# --- Sample regression lock ------------------------------------------------
def test_sample_recommendations() -> None:
    for name, part in SAMPLE_PARTS.items():
        r = evaluate(part)
        expected = EXPECTED_RECOMMENDATIONS[name]
        check(f"sample '{name}' -> {expected} (got {r.recommendation})",
              r.recommendation == expected)


# --- Determinism -----------------------------------------------------------
def test_determinism() -> None:
    p = base_part(ip_control="Core proprietary", criticality="Flight-critical")
    r1 = evaluate(p)
    r2 = evaluate(p)
    check("same input -> identical economic score", r1.economic_score == r2.economic_score)
    check("same input -> identical strategic score", r1.strategic_score == r2.strategic_score)
    check("same input -> identical recommendation", r1.recommendation == r2.recommendation)
    check("same input -> identical flags", r1.flags == r2.flags)


# --- Sort key --------------------------------------------------------------
def test_sort_key() -> None:
    check("Strategic Make sorts first",
          eng.recommendation_sort_key("Strategic Make") <
          eng.recommendation_sort_key("Make"))
    check("Make sorts before Buy",
          eng.recommendation_sort_key("Make") < eng.recommendation_sort_key("Buy"))
    check("Marginal sorts before Buy",
          eng.recommendation_sort_key("Marginal - Gather More Data") <
          eng.recommendation_sort_key("Buy"))


# --- Boundaries ------------------------------------------------------------
def test_boundaries() -> None:
    r_min_vol = evaluate(base_part(annual_volume=1, nonrecurring_investment=0.0))
    check("volume of 1 evaluates without error", isinstance(r_min_vol.recommendation, str))
    r_equal = evaluate(base_part(make_unit_cost=50.0, buy_unit_quote=50.0,
                                 nonrecurring_investment=0.0))
    check("equal cost gives near-neutral economic", 45 <= r_equal.economic_score <= 55)
    r_zero_nre = evaluate(base_part(nonrecurring_investment=0.0))
    check("zero NRE evaluates", r_zero_nre.amortized_nre_annual == 0.0)
    r_big_nre = evaluate(base_part(nonrecurring_investment=10_000_000.0))
    check("very large NRE evaluates without error", isinstance(r_big_nre.recommendation, str))


# --- Lifecycle factor + sunsetting override --------------------------------
def test_lifecycle() -> None:
    check("growing scores highest lifecycle",
          eng.LIFECYCLE_SCORES["Growing"] == max(eng.LIFECYCLE_SCORES.values()))
    check("sunsetting scores lowest lifecycle",
          eng.LIFECYCLE_SCORES["Sunsetting"] == min(eng.LIFECYCLE_SCORES.values()))

    # Sunsetting + unfavorable economics + single-source/critical -> Qualify Second Source.
    p = base_part(make_unit_cost=470.0, buy_unit_quote=410.0, annual_volume=600,
                  nonrecurring_investment=300000.0, criticality="Flight-critical",
                  supply_risk="Single-source", regulatory="Export-sensitive",
                  roadmap="Divesting", lifecycle="Sunsetting")
    r = evaluate(p)
    check("sunsetting + critical + single-source -> Qualify Second Source",
          r.recommendation == eng.REC_QUALIFY_SECOND)
    check("sunsetting override flag present",
          any("Sunsetting program" in f for f in r.flags))

    # Sunsetting + unfavorable + commodity market -> plain Buy (no second-source project).
    p2 = base_part(make_unit_cost=60.0, buy_unit_quote=45.0, annual_volume=1000,
                   nonrecurring_investment=200000.0, criticality="Non-critical",
                   supply_risk="Commodity", regulatory="Unrestricted",
                   roadmap="Divesting", lifecycle="Sunsetting")
    r2 = evaluate(p2)
    check("sunsetting + commodity -> plain Buy", r2.recommendation == eng.REC_BUY)

    # Sunsetting + unfavorable + COMPETITIVE market, no single-source risk ->
    # plain Buy, NOT Qualify Second Source (regression lock for the override bug).
    p_comp = base_part(make_unit_cost=60.0, buy_unit_quote=45.0, annual_volume=1000,
                       nonrecurring_investment=200000.0, criticality="Important",
                       supply_risk="Competitive", regulatory="Unrestricted",
                       roadmap="Divesting", lifecycle="Sunsetting")
    r_comp = evaluate(p_comp)
    check("sunsetting + competitive (no single-source) -> plain Buy",
          r_comp.recommendation == eng.REC_BUY)

    # Sunsetting but economics FAVOR making -> override does NOT fire.
    p3 = base_part(make_unit_cost=20.0, buy_unit_quote=40.0, annual_volume=5000,
                   nonrecurring_investment=10000.0, capacity="Idle",
                   volume_stability="High & stable", criticality="Important",
                   supply_risk="Limited", lifecycle="Sunsetting")
    r3 = evaluate(p3)
    check("sunsetting with favorable economics does NOT force off make",
          r3.economic_score >= eng.NEUTRAL and "Sunsetting program" not in " ".join(r3.flags))


# --- Mode drives recommendation on close calls -----------------------------
def test_mode_drives_recommendation() -> None:
    from sample_parts import SAMPLE_PARTS
    from dataclasses import replace

    # Titanium fitting is ITAR-controlled and a Strategic Make. Under the
    # corrected logic, ITAR suppresses the Cost-Driven tip-down: it stays
    # Strategic Make in every mode (export control is why it's held in-house).
    tf = SAMPLE_PARTS["Titanium Structural Fitting (flight-critical, ITAR)"]
    r_bal = evaluate(replace(tf, mode="Balanced"))
    r_cost = evaluate(replace(tf, mode="Cost-Driven"))
    r_strat = evaluate(replace(tf, mode="Strategic-Driven"))
    check("titanium Balanced -> Strategic Make", r_bal.recommendation == eng.REC_STRATEGIC_MAKE)
    check("titanium Cost-Driven stays Strategic Make (ITAR suppresses tip-down)",
          r_cost.recommendation == eng.REC_STRATEGIC_MAKE)
    check("titanium Strategic-Driven stays Strategic Make", r_strat.recommendation == eng.REC_STRATEGIC_MAKE)

    # Fastener kit: Opportunistic under Balanced/Cost, tips to Buy under Strategic-Driven.
    fk = SAMPLE_PARTS["Fastener Kit (high-volume, idle capacity)"]
    check("fastener Balanced -> Opportunistic",
          evaluate(replace(fk, mode="Balanced")).recommendation == eng.REC_OPPORTUNISTIC)
    check("fastener Strategic-Driven tips to Buy",
          evaluate(replace(fk, mode="Strategic-Driven")).recommendation == eng.REC_BUY)

    # Mode never changes the underlying layer scores.
    check("mode does not change economic score", r_cost.economic_score == r_strat.economic_score)
    check("mode does not change strategic score", r_cost.strategic_score == r_strat.strategic_score)

    # The Cost-Driven tip-down of a Strategic Make must NOT use the Opportunistic
    # label (that is the opposite quadrant's meaning). It lands on a buy-side
    # recommendation. The titanium fitting is ITAR, so test a non-ITAR strategic
    # part that tips: it should be Qualify Second Source (single-source) or Buy.
    check("Cost-Driven tip-down is not mislabeled Opportunistic",
          r_cost.recommendation != eng.REC_OPPORTUNISTIC)

    # ITAR Strategic Make must NOT be tipped down by Cost-Driven mode at all:
    # export control is why it is held in-house. Titanium fitting is ITAR.
    check("ITAR Strategic Make stays Strategic Make under Cost-Driven",
          r_cost.recommendation == eng.REC_STRATEGIC_MAKE)

    # A non-ITAR strategic part that tips under Cost-Driven: build one explicitly.
    # Sensor housing is Export-sensitive (not ITAR) and single-source-ish via
    # "Limited" + Mission-critical; under Cost-Driven it should tip to a buy-side
    # recommendation, never Opportunistic.
    sh = SAMPLE_PARTS["Proprietary Sensor Housing (core IP)"]
    r_sh_cost = evaluate(replace(sh, mode="Cost-Driven"))
    check("non-ITAR strategic tip-down lands buy-side, not Opportunistic",
          r_sh_cost.recommendation in (eng.REC_BUY, eng.REC_QUALIFY_SECOND, eng.REC_STRATEGIC_MAKE)
          and r_sh_cost.recommendation != eng.REC_OPPORTUNISTIC)

    # A decisive case is immune to mode: clean commodity Buy stays Buy in all modes.
    cb = SAMPLE_PARTS["Machined Aluminum Bracket (commodity)"]
    for m in eng.MODE_BLENDS:
        check(f"decisive Buy immune to mode ({m})",
              evaluate(replace(cb, mode=m)).recommendation == eng.REC_BUY)


# --- Break-even volume -----------------------------------------------------
def test_breakeven() -> None:
    # Make cheaper per unit with NRE: finite positive break-even.
    p = base_part(make_unit_cost=8.0, buy_unit_quote=12.0, annual_volume=10000,
                  nonrecurring_investment=50000.0)
    r = evaluate(p)
    # v* = (50000/5) / (12-8) = 10000/4 = 2500
    check("break-even volume computed correctly", abs(r.breakeven_volume - 2500) < 1)

    # Make NOT cheaper per unit: no finite break-even.
    p2 = base_part(make_unit_cost=15.0, buy_unit_quote=12.0, annual_volume=1000,
                   nonrecurring_investment=50000.0)
    r2 = evaluate(p2)
    check("no break-even when make is pricier per unit", r2.breakeven_volume is None)

    # Make cheaper per unit, zero NRE: break-even at 0 (favorable any volume).
    p3 = base_part(make_unit_cost=8.0, buy_unit_quote=12.0, annual_volume=100,
                   nonrecurring_investment=0.0)
    r3 = evaluate(p3)
    check("zero NRE + cheaper make -> break-even 0", r3.breakeven_volume == 0.0)


# --- Deterministic narrative copy honesty ----------------------------------
def test_narrative_copy() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
    from ai_narrative import deterministic_narrative
    from sample_parts import SAMPLE_PARTS
    from dataclasses import replace

    # Strategic-Driven Fastener Kit -> Buy. Economics favor MAKE here, so the
    # narrative must NOT claim economics favor buying.
    fk = evaluate(replace(SAMPLE_PARTS["Fastener Kit (high-volume, idle capacity)"],
                          mode="Strategic-Driven"))
    txt_fk = deterministic_narrative(fk).lower()
    check("mode-tipped Buy narrative does not claim both favor buying",
          "both favor buying" not in txt_fk)
    check("mode-tipped Buy narrative acknowledges economics favor making",
          fk.recommendation == eng.REC_BUY and "economics favor making" in txt_fk)

    # Cost-Driven Sensor Housing -> Buy / Qualify. Narrative should say
    # constrained-source, not strictly single-source.
    sh = evaluate(replace(SAMPLE_PARTS["Proprietary Sensor Housing (core IP)"],
                          mode="Cost-Driven"))
    txt_sh = deterministic_narrative(sh).lower()
    check("Qualify Second Source narrative uses constrained-source language",
          sh.recommendation == eng.REC_QUALIFY_SECOND and "constrained-source" in txt_sh)

    # Plain commodity Buy -> normal both-favor-buy language is fine.
    cb = evaluate(SAMPLE_PARTS["Machined Aluminum Bracket (commodity)"])
    txt_cb = deterministic_narrative(cb).lower()
    check("decisive commodity Buy keeps both-favor-buying language",
          cb.recommendation == eng.REC_BUY and "both favor buying" in txt_cb)


# --- Sensitivity flag ------------------------------------------------------
def test_sensitivity() -> None:
    # Equal cost, no NRE: economic score sits near neutral -> sensitive.
    p = base_part(make_unit_cost=100.0, buy_unit_quote=100.0, nonrecurring_investment=0.0)
    r = evaluate(p)
    check("near-neutral economics flagged sensitive", r.sensitivity == "sensitive")

    # Strongly make-favorable economics -> robust.
    p2 = base_part(make_unit_cost=40.0, buy_unit_quote=100.0, annual_volume=5000,
                   nonrecurring_investment=0.0, capacity="Idle",
                   volume_stability="High & stable")
    r2 = evaluate(p2)
    check("strong economics flagged robust", r2.sensitivity == "robust")


def main() -> int:
    tests = [
        test_cost_math, test_cost_delta_direction, test_category_lookups,
        test_invalid_category_raises, test_weights_sum, test_layer_aggregation,
        test_modes, test_quadrants, test_overrides, test_sample_recommendations,
        test_determinism, test_sort_key, test_boundaries,
        test_lifecycle, test_mode_drives_recommendation, test_breakeven,
        test_sensitivity, test_narrative_copy,
    ]
    print("Running Make vs. Buy engine tests...\n")
    for t in tests:
        t()
    total = _passed + _failed
    print(f"\n{_passed}/{total} assertions passed, {_failed} failed.")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
