---
name: finsight
description: >-
  Financial variance analyst. Use when a user provides a transactions CSV (or
  points to one) and wants income/expense totals broken down by category,
  detection of spending or revenue anomalies, or a plain-English financial
  report with recommendations. Trigger on phrases like "analyze these
  transactions", "what's off in my books", "variance report", "flag unusual
  spending", "categorize my income and expenses", or "build me a CFO summary".
version: 2.0.0
---

# FinSight — Financial Variance Analyst

FinSight splits the work in two: **Python does the deterministic math, you (the
agent) do the reasoning.** `analyze.py` computes income/expense totals by
category and flags transactions that deviate beyond a sigma threshold from
their category average, then writes everything to a structured `analysis.json`.
You read that JSON and write the narrative, the per-anomaly recommendations, and
a board-ready summary. No API key is needed inside the script — you already have
Claude reasoning available.

## When to use this skill

Invoke FinSight when the user wants any of:

- Income/expense totals grouped by category (payroll, software, marketing, etc.)
- Detection of unusual or outlier transactions ("what looks off?")
- A written financial summary, variance report, or board/CFO update
- A second look at bookkeeping before a monthly or quarterly close

If the user has not yet supplied data, ask for a CSV with these columns:
`date, description, category, type, amount` — where `type` is `income` or
`expense` and `amount` is a positive number. A working example ships in
`sample_data.csv`.

## Step 1 — Run the analyzer

The analyzer is pure Python 3 (standard library only — no `pip install`).

```bash
# Analyze the bundled sample data
python analyze.py

# Analyze a user-provided file and choose where the JSON goes
python analyze.py path/to/transactions.csv -o analysis.json

# Tighten or loosen the anomaly threshold (default is 2.0 sigma)
python analyze.py transactions.csv --sigma 2.5
```

The script prints the JSON to stdout and writes `analysis.json` next to the
input CSV (or to the `-o` path). **Do not invent or recompute any of these
numbers yourself** — read them from the JSON.

## Step 2 — Read analysis.json

The JSON has this shape:

```jsonc
{
  "schema_version": "1.0",
  "generated_at": "...",
  "source":     { "file": "...", "transaction_count": 104 },
  "parameters": { "sigma_threshold": 2.0, "stddev_type": "population" },
  "period":     { "start": "2026-01-03", "end": "2026-06-30" },
  "totals":     { "income": ..., "expense": ..., "net": ..., "net_margin_pct": ... },
  "categories": {
    "income":  [ { "category", "count", "total", "mean", "stddev", "min", "max" } ],
    "expense": [ { ...same shape... } ]
  },
  "anomalies": [
    {
      "date", "description", "category", "type", "amount",
      "category_mean", "category_stddev", "deviation", "pct_from_mean",
      "z_score", "direction", "category_sample_size", "confidence"
    }
  ],
  "anomaly_summary": { "total_flagged", "high_confidence", "moderate_confidence", "low_confidence" },
  "notes": [ "...methodology notes you can cite..." ]
}
```

All figures are pre-rounded and final. Cite them as-is.

## Step 3 — Generate the report (your reasoning)

Using only the values in `analysis.json`, produce a markdown report with these
three parts, in this order:

### 1. Executive narrative (plain English)
A few short paragraphs a CFO would actually read. Lead with the net result and
margin from `totals`. Summarize where money came from and went using the
`categories` breakdown. State how many anomalies were flagged and at what
confidence (`anomaly_summary`). Keep it decision-oriented, not a data dump.
Optionally include the category tables verbatim for reference.

### 2. Remediation recommendations (one per anomaly)
For **each** entry in `anomalies`, write a short, specific recommendation. Use
its `z_score`, `pct_from_mean`, `direction`, and `confidence` to set the tone,
and reason about what the `description`/`category` implies:
- **Expense, above average** → likely an unbudgeted spike; recommend verifying
  against an invoice/contract, checking for duplicate or misclassified charges,
  and whether it's recurring vs. one-off (e.g. an AWS spike → check for a
  runaway resource or a reserved-instance opportunity).
- **Expense, below average** → likely a partial period, credit, or missed
  payment; recommend confirming the charge wasn't skipped.
- **Revenue, above average** → attribute to a specific deal/one-off so forecasts
  aren't inflated.
- **Revenue, below average** → investigate churn, timing, or a delayed payout.
Order recommendations by confidence (high first) and explicitly mark anything
below 45% confidence as advisory only.

### 3. Board-ready summary (one paragraph)
A single tight paragraph (3–5 sentences) suitable for a board deck or investor
update: the period, headline revenue/expense/net/margin, the one or two most
material anomalies and their business implication, and the overall health
takeaway. No tables, no jargon.

## How to present results

- Show the executive narrative first, then recommendations, then the board
  paragraph.
- Tell the user where `analysis.json` and any report file were saved.
- If the user asks follow-ups ("ignore one-time items", "only expenses",
  "tighter threshold"), re-run `analyze.py` with adjusted data or `--sigma`
  rather than editing numbers by hand.

## Division of responsibility

| Concern | Owner |
|---|---|
| Totals, means, std dev, z-scores, anomaly flags, confidence | `analyze.py` (deterministic) |
| Narrative, recommendations, board summary, framing | You (the agent) |

Never recompute the math in prose; never let the script editorialize. If the
JSON and your narrative disagree, the JSON wins — re-read it.

## Files

- `SKILL.md` — this file.
- `analyze.py` — the compute layer (CSV → stats → anomalies → `analysis.json`).
- `sample_data.csv` — six months of realistic small-business transactions
  across payroll, software subscriptions, office supplies, marketing, and
  revenue, with a few intentional outliers for demonstration.
- `analysis.json` — generated output (created when you run the script).
