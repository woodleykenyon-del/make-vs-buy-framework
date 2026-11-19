# Make vs. Buy Decision Framework

Tool 5 of the Strategic Sourcing Decision Suite.

A deterministic decision-support tool that evaluates a single part across an
**economic layer** and a **strategic layer**, places it on a Make/Buy quadrant,
and produces a defensible recommendation with a plain-language rationale. Cost is
one weighted input, not the answer.

## Why it exists

The cheapest option is often the wrong one, and the most strategic option is not
always worth the capital. A make-vs-buy decision that ignores IP control,
criticality, single-source exposure, export status, and where a program sits in
its lifecycle is an accounting exercise, not a sourcing decision. This tool makes
those factors explicit and surfaces the cases a cost-only analysis gets wrong, in
both directions: the part that is more expensive to make but should be made
anyway, and the strategically attractive part that should not absorb tooling
capital because its program is winding down.

## How it works

- **Economic layer** (favors Make when making is cheaper / capacity is idle):
  make-vs-buy cost, capital/NRE burden (amortized over 5 years), capacity,
  volume stability.
- **Strategic layer** (favors Make when control/risk/criticality demand it):
  part criticality, IP control, supply market risk, regulatory/export status,
  technology roadmap fit, and program lifecycle stage.
- Each layer scores 0-100 (higher favors Make, 50 neutral). The two scores place
  the part on a 2x2 quadrant: **Make**, **Buy**, **Strategic Make**,
  **Opportunistic Make / Dual-Source**, or **Marginal** (neutral band on both
  axes returns "gather more data").
- **Scoring mode** (Balanced / Cost-Driven / Strategic-Driven) re-weights the
  blend of the two layers. Clear-cut cases are unaffected; on genuine close calls
  the mode can tip the recommendation, expressing whether the priority this cycle
  is cost or strategic positioning.
- **Overrides, in precedence order:**
  1. A **sunsetting** program whose make economics are below neutral is forced
     off Make: capital should not fund tooling for a program being retired. It
     lands on Buy, or **Buy / Qualify Second Source** when single-source risk
     exists, except a commodity market where a second source is automatic.
  2. **ITAR-controlled** parts never return an unrestricted Buy; they are floored
     to a domestic qualified source, outranking the lifecycle override.
- **Break-even volume** and a **sensitivity** flag (robust vs. sensitive to a 10%
  buy-quote move) accompany the economics.
- The explanation is generated from the engine results. It names the dominant
  drivers, compares annual costs, and surfaces any active overrides.

## Run locally

```
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

The app runs without an API key. Use the built-in fictional parts to try
different cases in the public demo.

## Tests

```
python tests/test_engine.py
```

## Boundaries within the suite

- **Should-Cost Model (Tool 3)** answers "what should it cost to make." This
  tool consumes a make-cost figure as one input and asks the higher-order
  question.
- **Supplier Scorecard (Tool 4)** evaluates a specific supplier. This tool
  treats "buy" as a sourcing strategy, not a vendor.
