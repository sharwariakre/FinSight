#!/usr/bin/env python3
"""
FinSight — financial variance analyst.

Reads a transactions CSV, computes income/expense totals by category,
flags transactions that deviate more than 2 standard deviations from their
category's mean, and writes a plain-English markdown report a CFO can act on.

Standard library only — no external dependencies.

Usage:
    python analyze.py [path/to/transactions.csv] [-o report.md] [--sigma 2.0]

Defaults to sample_data.csv in the script directory and writes report.md
next to it. The report is also printed to stdout.

Expected CSV columns (header row required):
    date, description, category, type, amount
where `type` is "income" or "expense" and `amount` is a positive number.
"""

import argparse
import csv
import math
import os
import sys
from collections import defaultdict
from datetime import datetime


def parse_args():
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description="FinSight financial variance analyst")
    p.add_argument(
        "csv_path",
        nargs="?",
        default=os.path.join(here, "sample_data.csv"),
        help="Path to the transactions CSV (default: bundled sample_data.csv)",
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="Path to write the markdown report (default: report.md beside the CSV)",
    )
    p.add_argument(
        "--sigma",
        type=float,
        default=2.0,
        help="Standard-deviation threshold for flagging anomalies (default: 2.0)",
    )
    return p.parse_args()


def load_transactions(path):
    required = {"date", "description", "category", "type", "amount"}
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SystemExit(f"Error: {path} is empty.")
        missing = required - {h.strip().lower() for h in reader.fieldnames}
        if missing:
            raise SystemExit(
                f"Error: CSV is missing required column(s): {', '.join(sorted(missing))}"
            )
        for i, raw in enumerate(reader, start=2):  # line 1 is the header
            row = {k.strip().lower(): (v.strip() if v else "") for k, v in raw.items()}
            try:
                amount = float(row["amount"])
            except (ValueError, KeyError):
                print(f"  ! Skipping line {i}: unparseable amount {row.get('amount')!r}",
                      file=sys.stderr)
                continue
            try:
                date = datetime.strptime(row["date"], "%Y-%m-%d").date()
            except ValueError:
                date = None
            rows.append(
                {
                    "date": date,
                    "date_raw": row["date"],
                    "description": row["description"],
                    "category": row["category"].lower(),
                    "type": row["type"].lower(),
                    "amount": amount,
                }
            )
    if not rows:
        raise SystemExit("Error: no valid transactions found.")
    return rows


def mean(values):
    return sum(values) / len(values)


def stddev(values):
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def summarize_categories(rows):
    """Return per-category stats keyed by (type, category)."""
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r["type"], r["category"])].append(r)

    stats = {}
    for key, items in buckets.items():
        amounts = [r["amount"] for r in items]
        stats[key] = {
            "count": len(items),
            "total": sum(amounts),
            "mean": mean(amounts),
            "stddev": stddev(amounts),
            "min": min(amounts),
            "max": max(amounts),
            "items": items,
        }
    return stats


def confidence_for(z, n):
    """
    Confidence (0-100) that a flagged point is a genuine outlier rather than
    noise. Grows with the z-score magnitude and is discounted when the
    category has too few samples to trust its mean/stddev.

    - z drives a logistic curve centered just above the 2-sigma threshold.
    - small samples (n < 6) are penalized because the stats are shaky.
    """
    z = abs(z)
    base = 1.0 / (1.0 + math.exp(-1.6 * (z - 2.0)))  # ~0.5 at z=2, ~0.83 at z=3
    if n < 4:
        sample_factor = 0.55
    elif n < 6:
        sample_factor = 0.78
    elif n < 10:
        sample_factor = 0.92
    else:
        sample_factor = 1.0
    return round(100 * base * sample_factor, 1)


def find_anomalies(stats, sigma):
    anomalies = []
    for (txn_type, category), s in stats.items():
        sd = s["stddev"]
        if sd == 0 or s["count"] < 2:
            continue  # cannot define variance with no spread / one point
        for r in s["items"]:
            z = (r["amount"] - s["mean"]) / sd
            if abs(z) > sigma:
                anomalies.append(
                    {
                        "txn": r,
                        "type": txn_type,
                        "category": category,
                        "z": z,
                        "mean": s["mean"],
                        "stddev": sd,
                        "delta": r["amount"] - s["mean"],
                        "confidence": confidence_for(z, s["count"]),
                    }
                )
    anomalies.sort(key=lambda a: abs(a["z"]), reverse=True)
    return anomalies


def money(x):
    return f"${x:,.2f}"


def signed_money(x):
    return f"{'+' if x >= 0 else '-'}{money(abs(x))}"


def build_report(rows, stats, anomalies, sigma, csv_path):
    dates = [r["date"] for r in rows if r["date"]]
    period = (
        f"{min(dates).strftime('%b %d, %Y')} – {max(dates).strftime('%b %d, %Y')}"
        if dates
        else "unknown period"
    )

    income_total = sum(s["total"] for k, s in stats.items() if k[0] == "income")
    expense_total = sum(s["total"] for k, s in stats.items() if k[0] == "expense")
    net = income_total - expense_total
    margin = (net / income_total * 100) if income_total else 0.0

    L = []
    L.append("# FinSight Financial Variance Report")
    L.append("")
    L.append(f"**Reporting period:** {period}  ")
    L.append(f"**Source:** `{os.path.basename(csv_path)}` ({len(rows)} transactions)  ")
    L.append(f"**Anomaly threshold:** {sigma:.1f}σ from category mean")
    L.append("")
    L.append("---")
    L.append("")

    # ---- Executive summary -------------------------------------------------
    L.append("## Executive Summary")
    L.append("")
    high_conf = [a for a in anomalies if a["confidence"] >= 70]
    if net >= 0:
        health = f"The business is **net positive**, generating {money(net)} in surplus"
    else:
        health = f"The business is **net negative**, burning {money(abs(net))}"
    L.append(
        f"Over this period the business booked {money(income_total)} in revenue "
        f"against {money(expense_total)} in expenses. {health} "
        f"on a {margin:.1f}% net margin."
    )
    L.append("")
    if anomalies:
        L.append(
            f"FinSight flagged **{len(anomalies)} transaction(s)** that deviate beyond "
            f"{sigma:.1f} standard deviations from their category norm "
            f"({len(high_conf)} at high confidence). These are itemized below and "
            f"warrant a closer look before close."
        )
    else:
        L.append(
            "No transactions breached the variance threshold. Spending and revenue "
            "were consistent with each category's historical pattern this period."
        )
    L.append("")

    # ---- Totals by category ------------------------------------------------
    L.append("## Income & Expense by Category")
    L.append("")
    for txn_type, heading in (("income", "Revenue"), ("expense", "Expenses")):
        cats = sorted(
            ((k[1], s) for k, s in stats.items() if k[0] == txn_type),
            key=lambda kv: kv[1]["total"],
            reverse=True,
        )
        if not cats:
            continue
        subtotal = sum(s["total"] for _, s in cats)
        L.append(f"### {heading} — {money(subtotal)}")
        L.append("")
        L.append("| Category | Transactions | Total | Avg / txn | Std dev |")
        L.append("|---|---:|---:|---:|---:|")
        for cat, s in cats:
            L.append(
                f"| {cat.title()} | {s['count']} | {money(s['total'])} | "
                f"{money(s['mean'])} | {money(s['stddev'])} |"
            )
        L.append("")

    L.append(f"**Net result:** {signed_money(net)}  ({margin:.1f}% margin)")
    L.append("")
    L.append("---")
    L.append("")

    # ---- Anomalies ---------------------------------------------------------
    L.append("## Flagged Anomalies")
    L.append("")
    if not anomalies:
        L.append("None. Every transaction fell within the expected range for its category.")
        L.append("")
    else:
        L.append(
            "| # | Date | Category | Description | Amount | Category avg | Deviation | σ | Confidence |"
        )
        L.append("|---|---|---|---|---:|---:|---:|---:|---:|")
        for i, a in enumerate(anomalies, 1):
            t = a["txn"]
            L.append(
                f"| {i} | {t['date_raw']} | {a['category'].title()} | {t['description']} | "
                f"{money(t['amount'])} | {money(a['mean'])} | {signed_money(a['delta'])} | "
                f"{a['z']:+.1f}σ | {a['confidence']:.0f}% |"
            )
        L.append("")

        L.append("### What this means")
        L.append("")
        for i, a in enumerate(anomalies, 1):
            t = a["txn"]
            direction = "above" if a["delta"] > 0 else "below"
            pct = (a["delta"] / a["mean"] * 100) if a["mean"] else 0.0
            conf_word = (
                "High" if a["confidence"] >= 70
                else "Moderate" if a["confidence"] >= 45
                else "Low"
            )
            lens = (
                "an unusually large outflow worth confirming against an invoice or contract"
                if a["type"] == "expense" and a["delta"] > 0
                else "a smaller-than-usual outflow — likely a partial period or credit"
                if a["type"] == "expense"
                else "a revenue spike worth attributing to a specific deal or one-off"
                if a["delta"] > 0
                else "a revenue dip worth investigating for churn or timing"
            )
            L.append(
                f"**{i}. {t['description']}** ({a['category'].title()}, {t['date_raw']}) — "
                f"{money(t['amount'])} is {abs(pct):.0f}% {direction} the category average of "
                f"{money(a['mean'])}, {a['z']:+.1f}σ from the mean. This is {lens}. "
                f"_Confidence: {conf_word} ({a['confidence']:.0f}%)._"
            )
            L.append("")

    # ---- Methodology -------------------------------------------------------
    L.append("---")
    L.append("")
    L.append("## Methodology & Confidence")
    L.append("")
    L.append(
        f"- Transactions are grouped by `type` and `category`. A point is flagged when "
        f"its amount lies more than **{sigma:.1f}σ** from its category mean "
        f"(population standard deviation)."
    )
    L.append(
        "- **Confidence** scales with the size of the deviation (a logistic curve on the "
        "z-score) and is discounted for categories with few transactions, where the mean "
        "and standard deviation are less reliable. Treat sub-45% flags as advisory."
    )
    L.append(
        "- Categories with fewer than 2 transactions or zero variance are reported in the "
        "totals but excluded from anomaly detection."
    )
    L.append("")
    L.append(f"_Generated by FinSight on {datetime.now().strftime('%Y-%m-%d %H:%M')}._")
    L.append("")
    return "\n".join(L)


def main():
    args = parse_args()
    if not os.path.exists(args.csv_path):
        raise SystemExit(f"Error: file not found: {args.csv_path}")

    rows = load_transactions(args.csv_path)
    stats = summarize_categories(rows)
    anomalies = find_anomalies(stats, args.sigma)
    report = build_report(rows, stats, anomalies, args.sigma, args.csv_path)

    out_path = args.output or os.path.join(
        os.path.dirname(os.path.abspath(args.csv_path)), "report.md"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\n[FinSight] Report written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
