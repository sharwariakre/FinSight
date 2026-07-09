# FinSight

A financial variance analyst skill for OpenClaw. FinSight ingests a transactions
CSV, computes income and expense statistics by category, flags transactions that
deviate beyond a configurable standard-deviation threshold, and hands the
results to an OpenClaw agent that writes the prose a CFO actually wants to read.


## Project structure

```
fin-sight/
├── SKILL.md            # OpenClaw skill manifest: when and how to invoke FinSight
├── analyze.py          # Deterministic compute layer (CSV -> stats -> anomalies -> JSON)
├── sample_data.csv     # Six months of realistic small-business transactions
├── analysis.json       # Latest run snapshot (overwritten each run)
├── audit_log.jsonl     # Append-only history, one JSON object per run
└── README.md           # This file
```

## What FinSight is

FinSight is a self-contained OpenClaw skill that turns raw bookkeeping data into
a board-ready financial review. It answers questions like "what looks off in my
books this quarter?", "where is the money going?", and "which transactions
should I verify before close?"

The design goal is separation of concerns: keep everything that must be correct
and repeatable in Python, and let the agent handle everything that benefits from
judgment and language. This makes the statistical output testable and the
narrative output flexible, without letting the model invent numbers or the
script editorialize.

## Two-layer architecture

FinSight is built as two distinct layers with a clean handoff.

### Layer 1 — Deterministic compute (`analyze.py`)

Pure Python 3, standard library only, no API key, no network access. This layer:

- Parses and validates the transactions CSV.
- Groups transactions by `type` and `category`.
- Computes totals, means, population standard deviations, and min/max per
  category.
- Detects anomalies via z-score against each category's distribution.
- Assigns a confidence score to every flagged anomaly.
- Writes a structured `analysis.json` and appends an audit record.

Every number in the output is computed here. The layer is deterministic: the
same CSV and the same `--sigma` produce the same statistics every time.

### Layer 2 — Agent reasoning (OpenClaw)

The OpenClaw agent reads `analysis.json` and uses Claude's reasoning to produce
the human-facing report. It does not recompute anything; it interprets. From the
structured stats it generates:

1. A plain-English executive narrative.
2. Remediation recommendations, one per flagged anomaly.
3. A board-ready, single-paragraph summary.

The contract between the layers is the JSON schema. If the agent's prose ever
disagrees with the JSON, the JSON wins.

| Concern | Owner |
|---|---|
| Totals, means, standard deviations, z-scores, anomaly flags, confidence | `analyze.py` (deterministic) |
| Narrative, recommendations, board summary, framing | OpenClaw agent (reasoning) |

## Input format

FinSight expects a CSV with a header row and these five required columns:

| Column | Type | Description |
|---|---|---|
| `date` | `YYYY-MM-DD` | Transaction date. Unparseable dates are tolerated but excluded from the reporting period range. |
| `description` | text | Human-readable line item (vendor, deposit source, etc.). Used by the agent for context. |
| `category` | text | The bucket the transaction belongs to (e.g. `payroll`, `marketing`). Compared case-insensitively. |
| `type` | `income` or `expense` | Whether the amount is money in or money out. Drives the totals and the income/expense split. |
| `amount` | positive number | The transaction amount. Always positive; direction comes from `type`, not the sign. |

Rows with an unparseable `amount` are skipped with a warning to stderr rather
than aborting the run. A complete working example ships in `sample_data.csv`
(six months across payroll, software subscriptions, office supplies, marketing,
and revenue, with a few intentional outliers).

## Output

### `analysis.json` (latest snapshot)

Overwritten on every run so the agent always reads the most recent result. Shape:

```jsonc
{
  "schema_version": "1.0",
  "run_id": "21f99a32-4c0e-4662-95b4-7d4c11badfaa",  // UUID, unique per run
  "generated_at": "2026-06-17T17:50:35",
  "source":     { "file": "sample_data.csv", "transaction_count": 104 },
  "parameters": { "sigma_threshold": 2.0, "stddev_type": "population" },
  "period":     { "start": "2026-01-03", "end": "2026-06-30" },
  "totals":     { "income": 496823.2, "expense": 329330.63,
                  "net": 167492.57, "net_margin_pct": 33.7 },
  "categories": {
    "income":  [ { "category", "count", "total", "mean", "stddev", "min", "max" } ],
    "expense": [ { /* same shape */ } ]
  },
  "anomalies": [
    {
      "date", "description", "category", "type", "amount",
      "category_mean", "category_stddev", "deviation", "pct_from_mean",
      "z_score", "direction", "category_sample_size", "confidence"
    }
  ],
  "anomaly_summary": { "total_flagged", "high_confidence",
                       "moderate_confidence", "low_confidence" },
  "notes": [ "...citable methodology notes..." ]
}
```

All figures are pre-rounded and final. The agent cites them as-is.

### `audit_log.jsonl` (compliance history)

Append-only. Every run writes one compact, single-line JSON object — the exact
same payload as `analysis.json` — to the end of the file. This builds a complete,
tamper-evident history of every analysis ever run, each uniquely identifiable by
its `run_id`. Useful for compliance, reproducibility, and diffing how the books
changed run over run.

```
{"schema_version":"1.0","run_id":"21f99a32-...","generated_at":"...", ...}
{"schema_version":"1.0","run_id":"9d9cb41d-...","generated_at":"...", ...}
```

### Agent-generated report

Produced by the OpenClaw reasoning layer from `analysis.json`:

- **Executive narrative** — a few short paragraphs leading with net result and
  margin, summarizing where money came from and went.
- **Remediation recommendations** — one per anomaly, with concrete next actions
  (verify against invoice, check for duplicate or misclassified charges,
  attribute a revenue spike to a specific deal, etc.), ordered by confidence.
- **Board-ready summary** — a single tight paragraph suitable for a board deck
  or investor update.

## How anomaly detection works

The detector is intentionally simple, transparent, and defensible.

1. **Category grouping.** Transactions are bucketed by `(type, category)`. Each
   category is scored against its own distribution, so a 4,000 dollar software
   bill is judged against other software bills, not against payroll.

2. **Population standard deviation.** For each category, FinSight computes the
   mean and the population standard deviation (dividing by N, not N-1). The
   population estimator is used because the CSV is treated as the complete record
   of the period under review, not a sample drawn from a larger set.

3. **Z-score threshold.** For every transaction, the z-score is
   `(amount - category_mean) / category_stddev`. Any transaction whose absolute
   z-score exceeds the threshold (default `2.0`, configurable via `--sigma`) is
   flagged. Categories with fewer than two transactions or zero variance are
   included in the totals but excluded from detection, since variance is
   undefined.

4. **Confidence scoring.** A raw z-score is not enough — a 2.1-sigma deviation in
   a category of five transactions is far less trustworthy than the same
   deviation across thirty. Confidence is therefore a logistic curve on the
   z-score magnitude, discounted for small samples:

   ```
   base = 1 / (1 + e^(-1.6 * (|z| - 2.0)))      # ~0.50 at z=2, ~0.83 at z=3
   sample_factor = 0.55  if n < 4
                   0.78  if n < 6
                   0.92  if n < 10
                   1.00  otherwise
   confidence = round(100 * base * sample_factor, 1)
   ```

   The logistic curve is centered just above the 2-sigma threshold so that
   borderline flags score around 50 percent and clear outliers approach 100
   percent. The small-sample discount keeps the tool honest about thin data.
   Scores below 45 are treated as advisory.

## Running FinSight

### Standalone

The compute layer runs on its own with no dependencies:

```bash
# Analyze the bundled sample data
python analyze.py

# Analyze your own file
python analyze.py path/to/transactions.csv

# Write the snapshot somewhere specific
python analyze.py transactions.csv -o analysis.json

# Tighten or loosen the threshold (default 2.0 sigma)
python analyze.py transactions.csv --sigma 2.5
```

The script prints `analysis.json` to stdout, overwrites the snapshot file next
to `analyze.py`, and appends one line to `audit_log.jsonl`. Progress and paths
are logged to stderr.

### Inside OpenClaw

When invoked as a skill, OpenClaw reads `SKILL.md`, which directs the agent to:

1. Run `analyze.py` against the user's CSV.
2. Read the resulting `analysis.json`.
3. Generate the executive narrative, remediation recommendations, and
   board-ready summary from the structured stats.

Trigger phrases include "analyze these transactions", "what's off in my books",
"variance report", "flag unusual spending", and "build me a CFO summary".

## Sample output

Running `python analyze.py` on `sample_data.csv` (104 transactions, January
through June 2026) reports 496,823.20 dollars in revenue against 329,330.63
dollars in expenses — a net of 167,492.57 dollars at a 33.7 percent margin — and
flags three anomalies, all high confidence:

| Date | Category | Description | Amount | Category avg | Deviation | Z-score | Confidence |
|---|---|---|---:|---:|---:|---:|---:|
| 2026-04-20 | Software Subscriptions | AWS usage - April | $4,980.60 | $580.98 | +$4,399.62 | +4.8σ | 98.8% |
| 2026-05-23 | Marketing | Influencer partnership payout | $8,500.00 | $2,610.00 | +$5,890.00 | +3.6σ | 92% |
| 2026-03-31 | Revenue | ACH deposit - Wingtip New Contract | $31,500.00 | $16,560.77 | +$14,939.23 | +3.0σ | 84% |

The agent then explains each: the AWS spike (757 percent above the category
average) likely signals a runaway resource or a missed reserved-instance
opportunity and should be checked against the invoice; the influencer payout is a
one-off marketing spend worth confirming against a contract; and the Wingtip
deposit is a genuine revenue event that should be attributed to a specific deal
so forecasts are not inflated.


