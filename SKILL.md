---
name: finsight
description: >-
  Financial variance analyst. Use when a user provides a transactions CSV (or
  points to one) and wants income/expense totals broken down by category,
  detection of spending or revenue anomalies, or a plain-English financial
  report. Trigger on phrases like "analyze these transactions", "what's off in
  my books", "variance report", "flag unusual spending", "categorize my
  income and expenses", or "build me a CFO summary".
version: 1.0.0
---

# FinSight — Financial Variance Analyst

FinSight turns a raw transactions CSV into a CFO-ready variance report. It
computes income and expense totals by category, flags any transaction that
deviates more than 2 standard deviations from its category average, and writes
a plain-English markdown summary with per-anomaly confidence scores.

## When to use this skill

Invoke FinSight when the user wants any of:

- Income/expense totals grouped by category (payroll, software, marketing, etc.)
- Detection of unusual or outlier transactions ("what looks off?")
- A written financial summary, variance report, or board/CFO update
- A second look at bookkeeping before a monthly or quarterly close

If the user has not yet supplied data, ask them for a CSV with these columns:
`date, description, category, type, amount` — where `type` is `income` or
`expense` and `amount` is a positive number. A working example ships in
`sample_data.csv`.

## How to run it

The analyzer is pure Python 3 (standard library only — no `pip install` needed).

```bash
# Analyze the bundled sample data
python analyze.py

# Analyze a user-provided file and choose where the report goes
python analyze.py path/to/transactions.csv -o report.md

# Tighten or loosen the anomaly threshold (default is 2.0 sigma)
python analyze.py transactions.csv --sigma 2.5
```

The script prints the full markdown report to stdout and also writes it to
`report.md` next to the input CSV (or to the `-o` path). Surface the report
contents back to the user, and mention where the file was saved.

## What the report contains

1. **Executive summary** — total revenue, total expenses, net result, and
   margin, plus a one-line count of flagged anomalies.
2. **Income & expense by category** — totals, transaction counts, average per
   transaction, and standard deviation for each category.
3. **Flagged anomalies** — a table of every transaction beyond the sigma
   threshold, with its deviation, z-score, and confidence score, followed by a
   plain-English explanation of what each one likely means and what to check.
4. **Methodology & confidence** — how the thresholds and confidence scores are
   derived, so the numbers are defensible in a finance review.

## How to present results

- Lead with the executive summary and the net result.
- Call out high-confidence anomalies (≥70%) first; treat sub-45% flags as
  advisory and say so.
- Keep the framing decision-oriented: for each anomaly, point to what the user
  should verify (an invoice, a contract, a one-off deal) rather than just
  restating the number.
- If the user asks follow-ups (e.g. "ignore one-time items" or "only show
  expenses"), re-run with adjusted data or `--sigma` rather than guessing.

## Files

- `SKILL.md` — this file.
- `analyze.py` — the analysis engine (CSV → stats → anomalies → markdown).
- `sample_data.csv` — six months of realistic small-business transactions
  across payroll, software subscriptions, office supplies, marketing, and
  revenue, with a few intentional outliers for demonstration.
