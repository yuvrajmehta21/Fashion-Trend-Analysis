#!/usr/bin/env python3
"""
analyze_trends.py — Score what's new and what's rising, from the persistent catalog.

Reads data/catalog.json and uses pandas to answer two questions for the latest run:

  1. NEW THIS WEEK — which garments appeared for the first time this run
     (first_seen == this run's date).

  2. RISING ATTRIBUTES — for each attribute (garment_type, color, neckline, sleeve,
     pattern, fabric), how its SHARE of the live catalog changed vs the previous run.
     A positive delta = the attribute is gaining presence across competitors' catalogs.

"Live catalog this run" = every item whose last_seen == this run's date (i.e. still
on sale this run). Comparing share (not raw count) keeps it fair when the number of
items scraped changes between runs.

On the very first run there's no previous snapshot, so RISING is empty and the run is
marked a baseline. Trends become meaningful from the second weekly run onward.

Input:  data/catalog.json
Output: .tmp/trends_<run_date>.json   (consumed by build_pdf.py)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
TMP = ROOT / ".tmp"
CATALOG = ROOT / "data" / "catalog.json"

ATTRS = ["garment_type", "color", "neckline", "sleeve", "pattern", "fabric_guess"]


def _items_df(catalog: dict) -> pd.DataFrame:
    rows = []
    for pid, it in catalog["items"].items():
        attrs = it.get("attributes") or {}
        rows.append({
            "product_id":  pid,
            "store_key":   it.get("store_key"),
            "store_name":  it.get("store_name"),
            "title":       it.get("title"),
            "url":         it.get("url"),
            "price":       it.get("price"),
            "image_local": it.get("image_local"),
            "first_seen":  it.get("first_seen"),
            "last_seen":   it.get("last_seen"),
            "seen_dates":  it.get("seen_dates") or [],
            **{a: attrs.get(a) for a in ATTRS},
        })
    return pd.DataFrame(rows)


def _share_table(df: pd.DataFrame, attr: str) -> pd.Series:
    """Share (fraction) of each attribute value within a dataframe."""
    if df.empty:
        return pd.Series(dtype=float)
    return df[attr].value_counts(normalize=True)


def main():
    parser = argparse.ArgumentParser(description="Compute new + rising trends from the catalog.")
    parser.add_argument("--run-date", help="Run to analyze (default: latest run in catalog).")
    parser.add_argument("--top", type=int, default=6, help="Rising values to keep per attribute.")
    args = parser.parse_args()

    if not CATALOG.exists():
        print("ERROR: no data/catalog.json — run update_catalog.py first.")
        return
    catalog = json.loads(CATALOG.read_text())
    runs = catalog.get("runs", [])
    if not runs:
        print("ERROR: catalog has no runs recorded.")
        return

    run_dates = [r["date"] for r in runs]
    run_date = args.run_date or run_dates[-1]
    prev_date = None
    if run_date in run_dates:
        idx = run_dates.index(run_date)
        if idx > 0:
            prev_date = run_dates[idx - 1]

    df = _items_df(catalog)
    # "Live in run R" = item was scraped in run R (R is in its seen_dates). This is
    # reconstructable for any past run, unlike last_seen which later runs overwrite.
    live_now = df[df["seen_dates"].apply(lambda d: run_date in d)]
    new_items = df[df["first_seen"] == run_date]

    # --- New this week (most recent / highest-signal first: group by store) ---
    new_records = (
        new_items
        .sort_values(["store_name", "garment_type"])
        .to_dict(orient="records")
    )

    # --- Rising attributes: share delta vs previous run ---
    rising: dict[str, list] = {}
    snapshot: dict[str, list] = {}
    live_prev = (df[df["seen_dates"].apply(lambda d: prev_date in d)]
                 if prev_date else pd.DataFrame())

    for attr in ATTRS:
        cur = _share_table(live_now, attr)
        prev = _share_table(live_prev, attr) if not live_prev.empty else pd.Series(dtype=float)
        counts = live_now[attr].value_counts() if not live_now.empty else pd.Series(dtype=int)

        # current snapshot (top values now)
        snapshot[attr] = [
            {"value": v, "count": int(counts[v]), "share": round(float(cur[v]), 3)}
            for v in counts.index[:args.top]
        ]

        # rising = positive share delta vs previous run
        rows = []
        for v in cur.index:
            delta = float(cur[v]) - float(prev.get(v, 0.0))
            rows.append({
                "value":       v,
                "current_count": int(counts.get(v, 0)),
                "current_share": round(float(cur[v]), 3),
                "prev_share":    round(float(prev.get(v, 0.0)), 3),
                "delta":         round(delta, 3),
            })
        rows.sort(key=lambda r: r["delta"], reverse=True)
        rising[attr] = [r for r in rows if r["delta"] > 0][:args.top]

    out = {
        "run_date":        run_date,
        "previous_date":   prev_date,
        "is_baseline":     prev_date is None,
        "live_count":      int(len(live_now)),
        "prev_live_count": int(len(live_prev)) if prev_date else 0,
        "new_count":       int(len(new_items)),
        "stores":          catalog.get("runs", [])[-1] if runs else {},
        "new_items":       new_records,
        "rising":          rising,
        "snapshot":        snapshot,
    }
    out_file = TMP / f"trends_{run_date}.json"
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))

    print(f"Run {run_date} (prev: {prev_date or 'none — baseline'})")
    print(f"  live items: {len(live_now)} | new this week: {len(new_items)}")
    if not out["is_baseline"]:
        for attr in ATTRS:
            top = rising[attr][:3]
            if top:
                bits = ", ".join(f"{r['value']} (+{r['delta']:.0%})" for r in top)
                print(f"  rising {attr}: {bits}")
    print(f"Saved → {out_file}")


if __name__ == "__main__":
    main()
