#!/usr/bin/env python3
"""
FinSight — financial variance analyst (compute layer).

Reads a transactions CSV, computes income/expense totals by category, and
flags transactions that deviate more than N standard deviations from their
category's mean. Emits a structured JSON file (analysis.json) with every
computed number. It deliberately does NOT write prose — the deterministic math
lives here; the narrative, recommendations, and board summary are produced by
the calling agent from this JSON.

Standard library only — no external dependencies, no API key.

Usage:
    python analyze.py [path/to/transactions.csv] [-o analysis.json] [--sigma 2.0]

Defaults to sample_data.csv in the script directory and writes analysis.json
beside it. The JSON is also printed to stdout.

Expected CSV columns (header row required):
    date, description, category, type, amount
where `type` is "income" or "expense" and `amount` is a positive number.
"""

import argparse
import csv
import json
import math
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path


SCHEMA_VERSION = "1.0"
SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args():
    p = argparse.ArgumentParser(description="FinSight financial variance analyzer")
    p.add_argument(
        "csv_path",
        nargs="?",
        default=str(SCRIPT_DIR / "sample_data.csv"),
        help="Path to the transactions CSV (default: bundled sample_data.csv)",
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="Path to write analysis.json (default: analysis.json next to analyze.py)",
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
    """Return per-(type, category) stats."""
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
                delta = r["amount"] - s["mean"]
                anomalies.append(
                    {
                        "date": r["date_raw"],
                        "description": r["description"],
                        "category": category,
                        "type": txn_type,
                        "amount": round(r["amount"], 2),
                        "category_mean": round(s["mean"], 2),
                        "category_stddev": round(sd, 2),
                        "deviation": round(delta, 2),
                        "pct_from_mean": round((delta / s["mean"] * 100), 1) if s["mean"] else None,
                        "z_score": round(z, 2),
                        "direction": "above" if delta > 0 else "below",
                        "category_sample_size": s["count"],
                        "confidence": confidence_for(z, s["count"]),
                    }
                )
    anomalies.sort(key=lambda a: abs(a["z_score"]), reverse=True)
    return anomalies


def build_payload(rows, stats, anomalies, sigma, csv_path):
    dates = [r["date"] for r in rows if r["date"]]
    income_total = sum(s["total"] for k, s in stats.items() if k[0] == "income")
    expense_total = sum(s["total"] for k, s in stats.items() if k[0] == "expense")
    net = income_total - expense_total

    def category_block(txn_type):
        cats = sorted(
            ((k[1], s) for k, s in stats.items() if k[0] == txn_type),
            key=lambda kv: kv[1]["total"],
            reverse=True,
        )
        return [
            {
                "category": cat,
                "count": s["count"],
                "total": round(s["total"], 2),
                "mean": round(s["mean"], 2),
                "stddev": round(s["stddev"], 2),
                "min": round(s["min"], 2),
                "max": round(s["max"], 2),
            }
            for cat, s in cats
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "file": os.path.basename(csv_path),
            "transaction_count": len(rows),
        },
        "parameters": {
            "sigma_threshold": sigma,
            "stddev_type": "population",
        },
        "period": {
            "start": min(dates).isoformat() if dates else None,
            "end": max(dates).isoformat() if dates else None,
        },
        "totals": {
            "income": round(income_total, 2),
            "expense": round(expense_total, 2),
            "net": round(net, 2),
            "net_margin_pct": round((net / income_total * 100), 1) if income_total else None,
        },
        "categories": {
            "income": category_block("income"),
            "expense": category_block("expense"),
        },
        "anomalies": anomalies,
        "anomaly_summary": {
            "total_flagged": len(anomalies),
            "high_confidence": sum(1 for a in anomalies if a["confidence"] >= 70),
            "moderate_confidence": sum(1 for a in anomalies if 45 <= a["confidence"] < 70),
            "low_confidence": sum(1 for a in anomalies if a["confidence"] < 45),
        },
        "notes": [
            "Anomalies are transactions beyond the sigma threshold from their "
            "category mean, using population standard deviation.",
            "confidence scales with z-score magnitude and is discounted for "
            "categories with few transactions; treat sub-45 as advisory.",
            "Categories with fewer than 2 transactions or zero variance are "
            "included in totals but excluded from anomaly detection.",
        ],
    }


def main():
    args = parse_args()
    if not os.path.exists(args.csv_path):
        raise SystemExit(f"Error: file not found: {args.csv_path}")

    rows = load_transactions(args.csv_path)
    stats = summarize_categories(rows)
    anomalies = find_anomalies(stats, args.sigma)
    payload = build_payload(rows, stats, anomalies, args.sigma, args.csv_path)

    out_path = args.output or str(SCRIPT_DIR / "analysis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    # Append an immutable, one-line-per-run history alongside the latest snapshot.
    audit_path = SCRIPT_DIR / "audit_log.jsonl"
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")

    json.dump(payload, sys.stdout, indent=2)
    print()
    print(f"[FinSight] run {payload['run_id']}", file=sys.stderr)
    print(f"[FinSight] latest snapshot -> {out_path}", file=sys.stderr)
    print(f"[FinSight] appended to audit log -> {audit_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
