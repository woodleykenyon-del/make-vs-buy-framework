"""Locked sample parts for the Make vs. Buy Decision Framework.

Each scenario is deliberately engineered to land in a different region of the
quadrant / trigger a different rule, demonstrating a distinct lesson. These
double as regression fixtures: the test suite asserts each produces its
intended recommendation under the default (Balanced) mode.

Synthetic-data design note: the spread is intentional (clean Buy, two
different Strategic Make drivers, an opportunistic-capacity case, a genuinely
marginal case, and a sunsetting-program case that triggers the lifecycle
override) to demonstrate domain reasoning, not just tool mechanics.
"""

from __future__ import annotations

from decision_engine import PartInput

SAMPLE_PARTS: dict[str, PartInput] = {
    # 1. Commodity machined bracket -> clean BUY.
    "Machined Aluminum Bracket (commodity)": PartInput(
        part_name="Machined Aluminum Bracket",
        description=(
            "Standard 6061-T6 bracket, no proprietary features. Mature "
            "competitive supply base, non-critical structural support."
        ),
        annual_volume=5000,
        make_unit_cost=42.0,
        buy_unit_quote=31.0,
        nonrecurring_investment=60000.0,
        capacity="Tight",
        volume_stability="Moderate",
        ip_control="Commodity",
        criticality="Non-critical",
        supply_risk="Competitive",
        regulatory="Unrestricted",
        roadmap="Neutral",
        lifecycle="Stable",
        mode="Balanced",
    ),

    # 2. Flight-critical titanium fitting, ITAR, growing program -> STRATEGIC MAKE.
    "Titanium Structural Fitting (flight-critical, ITAR)": PartInput(
        part_name="Titanium Structural Fitting",
        description=(
            "Flight-critical machined Ti-6Al-4V primary structure fitting. "
            "ITAR-controlled, single qualified source in market, on a growing "
            "program. Making in-house costs more per unit but controls a "
            "critical, restricted item with a long production runway."
        ),
        annual_volume=800,
        make_unit_cost=620.0,
        buy_unit_quote=540.0,
        nonrecurring_investment=350000.0,
        capacity="Available",
        volume_stability="High & stable",
        ip_control="Sensitive",
        criticality="Flight-critical",
        supply_risk="Single-source",
        regulatory="ITAR-controlled",
        roadmap="Strategic-to-own",
        lifecycle="Growing",
        mode="Balanced",
    ),

    # 3. Proprietary sensor housing -> STRATEGIC MAKE driven by IP, not regs.
    "Proprietary Sensor Housing (core IP)": PartInput(
        part_name="Proprietary Sensor Housing",
        description=(
            "Houses a differentiating sensor design with core proprietary IP. "
            "Currently cheaper to buy, but outsourcing risks exposing the design. "
            "Strategic-to-own capability on a stable program."
        ),
        annual_volume=1200,
        make_unit_cost=185.0,
        buy_unit_quote=150.0,
        nonrecurring_investment=120000.0,
        capacity="Available",
        volume_stability="Moderate",
        ip_control="Core proprietary",
        criticality="Mission-critical",
        supply_risk="Limited",
        regulatory="Export-sensitive",
        roadmap="Strategic-to-own",
        lifecycle="Stable",
        mode="Balanced",
    ),

    # 4. High-volume fastener kit, idle capacity -> OPPORTUNISTIC / DUAL-SOURCE.
    "Fastener Kit (high-volume, idle capacity)": PartInput(
        part_name="Fastener Kit",
        description=(
            "High-volume commodity fastener kit. We have idle capacity that "
            "makes in-house production cheaper right now, but the part carries "
            "no strategic lock-in. Hedge with dual-sourcing."
        ),
        annual_volume=40000,
        make_unit_cost=2.10,
        buy_unit_quote=3.05,
        nonrecurring_investment=25000.0,
        capacity="Idle",
        volume_stability="High & stable",
        ip_control="Commodity",
        criticality="Non-critical",
        supply_risk="Commodity",
        regulatory="Unrestricted",
        roadmap="Neutral",
        lifecycle="Stable",
        mode="Balanced",
    ),

    # 5. Mid-tier electronic assembly, mixed signals -> MARGINAL.
    "Electronic Assembly (mixed signals)": PartInput(
        part_name="Electronic Assembly",
        description=(
            "Mid-tier electronic sub-assembly. Costs are close to even, and "
            "strategic factors are mixed. The tool declines to force a call."
        ),
        annual_volume=2000,
        make_unit_cost=96.0,
        buy_unit_quote=95.0,
        nonrecurring_investment=40000.0,
        capacity="Available",
        volume_stability="Moderate",
        ip_control="Standard",
        criticality="Important",
        supply_risk="Limited",
        regulatory="Regulated-process",
        roadmap="Neutral",
        lifecycle="Stable",
        mode="Balanced",
    ),

    # 6. Flight-critical fitting on a SUNSETTING program -> lifecycle override.
    "Sunsetting Actuator Housing (flight-critical, winding down)": PartInput(
        part_name="Sunsetting Actuator Housing",
        description=(
            "Flight-critical actuator housing on a program being retired within "
            "a few years. One qualified supplier in market. More expensive to "
            "make in-house, and the program no longer justifies tooling capital. "
            "Keep buying, but qualify a second source for the sustainment tail."
        ),
        annual_volume=600,
        make_unit_cost=470.0,
        buy_unit_quote=410.0,
        nonrecurring_investment=300000.0,
        capacity="Available",
        volume_stability="Low or erratic",
        ip_control="Sensitive",
        criticality="Flight-critical",
        supply_risk="Single-source",
        regulatory="Export-sensitive",
        roadmap="Divesting",
        lifecycle="Sunsetting",
        mode="Balanced",
    ),
}

# Intended recommendations under Balanced mode, used as the regression lock.
EXPECTED_RECOMMENDATIONS: dict[str, str] = {
    "Machined Aluminum Bracket (commodity)": "Buy",
    "Titanium Structural Fitting (flight-critical, ITAR)": "Strategic Make",
    "Proprietary Sensor Housing (core IP)": "Strategic Make",
    "Fastener Kit (high-volume, idle capacity)": "Opportunistic Make / Dual-Source",
    "Electronic Assembly (mixed signals)": "Marginal - Gather More Data",
    "Sunsetting Actuator Housing (flight-critical, winding down)": "Buy / Qualify Second Source",
}
