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
SOCIAL_HISTORY = ROOT / "data" / "social_history.json"

ATTRS = ["garment_type", "color", "neckline", "sleeve", "pattern", "fabric_guess"]

_ITEM_COLS = ["product_id", "store_key", "store_name", "title", "url", "price",
              "currency_symbol", "image_local", "first_seen", "last_seen", "seen_dates",
              "stock_ratio", "in_stock", "stock_history", *ATTRS]


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
            "currency_symbol": it.get("currency_symbol", ""),
            "image_local": it.get("image_local"),
            "first_seen":  it.get("first_seen"),
            "last_seen":   it.get("last_seen"),
            "seen_dates":  it.get("seen_dates") or [],
            "stock_ratio": it.get("stock_ratio"),
            "in_stock":    it.get("in_stock"),
            "stock_history": it.get("stock_history") or [],
            **{a: attrs.get(a) for a in ATTRS},
        })
    # explicit columns so an empty catalog still yields a usable (column-bearing) frame
    return pd.DataFrame(rows, columns=_ITEM_COLS)


def _ratio_at(stock_history: list, date: str):
    """Stock ratio recorded for a given run date, or None if not seen that run."""
    for pt in stock_history or []:
        if pt.get("date") == date:
            return pt.get("stock_ratio")
    return None


# A product counts as "selling through" if, while still listed this run, its share of
# buyable variants dropped by at least this much since the previous run (or it sold out).
SELL_THROUGH_DROP = 0.25


def _share_table(df: pd.DataFrame, attr: str) -> pd.Series:
    """Share (fraction) of each attribute value within a dataframe."""
    if df.empty:
        return pd.Series(dtype=float)
    return df[attr].value_counts(normalize=True)


def _load_keywords(run_date: str) -> dict:
    """Load this run's Google Trends snapshot, if google_trends.py produced one."""
    path = TMP / f"keywords_{run_date}.json"
    if path.exists():
        try:
            return json.loads(path.read_text()).get("keywords", {})
        except Exception:
            return {}
    return {}


# ---------------------------------------------------------------------------
# Social — emerging-trend detection (the early signal)
# ---------------------------------------------------------------------------
# An emerging trend is an attribute whose engagement SHARE is accelerating, even from
# a low base — small but climbing, ahead of the catalog. We measure each value's share
# of weighted engagement (weng) this run vs last run; positive delta = emerging.
SOCIAL_LOW_BASE_SHARE = 0.10   # "from a low base": previous engagement share under this


def _eng_shares(snapshot_attr: dict) -> tuple[dict, float]:
    """Given one snapshot's {value: {weng,...}} for an attribute, return
    {value: eng_share} and the total weighted engagement."""
    total = sum(c["weng"] for c in snapshot_attr.values()) or 1.0
    return {v: c["weng"] / total for v, c in snapshot_attr.items()}, total


def _social_analysis(run_date: str, top: int) -> dict | None:
    """Read data/social_history.json and compute, per attribute, what's emerging
    (engagement-share velocity vs the previous social run) plus a current snapshot.
    Returns None if there's no social history yet."""
    if not SOCIAL_HISTORY.exists():
        return None
    runs = json.loads(SOCIAL_HISTORY.read_text()).get("runs", [])
    if not runs:
        return None
    dates = [r["date"] for r in runs]
    idx = dates.index(run_date) if run_date in dates else len(runs) - 1
    cur = runs[idx]
    prev = runs[idx - 1] if idx > 0 else None
    is_baseline = prev is None

    snapshot: dict[str, list] = {}
    emerging: dict[str, list] = {}
    value_index: dict = {}   # (attr, value) -> metrics, for cross-source folding

    for attr in ATTRS:
        cur_attr = cur["attributes"].get(attr, {})
        cur_share, _ = _eng_shares(cur_attr) if cur_attr else ({}, 1.0)
        prev_attr = prev["attributes"].get(attr, {}) if prev else {}
        prev_share, _ = _eng_shares(prev_attr) if prev_attr else ({}, 1.0)

        # current engagement-weighted snapshot (top values now)
        snap_rows = sorted(cur_attr.items(), key=lambda kv: kv[1]["weng"], reverse=True)
        snapshot[attr] = [
            {"value": v, "posts": c["posts"], "engagement": c["engagement"],
             "eng_share": round(cur_share.get(v, 0.0), 3)}
            for v, c in snap_rows[:top]
        ]

        rows = []
        for v, c in cur_attr.items():
            cs = cur_share.get(v, 0.0)
            ps = prev_share.get(v, 0.0)
            delta = cs - ps
            metrics = {
                "value": v, "posts": c["posts"],
                "eng_share": round(cs, 3), "prev_share": round(ps, 3),
                "delta": round(delta, 3),
                "from_low_base": ps < SOCIAL_LOW_BASE_SHARE,
            }
            rows.append(metrics)
            value_index[(attr, v)] = metrics
        rows.sort(key=lambda r: r["delta"], reverse=True)
        emerging[attr] = [r for r in rows if r["delta"] > 0][:top] if prev else []

    return {
        "is_baseline":      is_baseline,
        "run_date":         cur["date"],
        "prev_date":        prev["date"] if prev else None,
        "posts":            cur["posts"],
        "total_engagement": cur["total_engagement"],
        "snapshot":         snapshot,
        "emerging":         emerging,
        "_value_index":     value_index,
    }


def _social_top_posts(run_date: str, n: int = 12) -> list[dict]:
    """Top social posts by raw engagement, for the report's visual grid."""
    path = TMP / f"tagged_social_{run_date}.json"
    if not path.exists():
        files = sorted(TMP.glob("tagged_social_*.json"), reverse=True)
        if not files:
            return []
        path = files[0]
    posts = json.loads(path.read_text()).get("posts", [])
    scored = []
    for p in posts:
        if not p.get("attributes") or not p.get("image_local"):
            continue
        eng = (p.get("like_count") or 0) + (p.get("comment_count") or 0)
        scored.append((eng, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for eng, p in scored[:n]:
        out.append({
            "handle":      p.get("source_handle"),
            "source_type": p.get("source_type"),
            "weight":      p.get("weight"),
            "likes":       p.get("like_count"),
            "comments":    p.get("comment_count"),
            "engagement":  eng,
            "image_local": p.get("image_local"),
            "permalink":   p.get("permalink"),
            "attributes":  p.get("attributes"),
        })
    return out


def main():
    parser = argparse.ArgumentParser(description="Compute new + rising trends from the catalog.")
    parser.add_argument("--run-date", help="Run to analyze (default: latest run in catalog).")
    parser.add_argument("--top", type=int, default=6, help="Rising values to keep per attribute.")
    args = parser.parse_args()

    catalog = json.loads(CATALOG.read_text()) if CATALOG.exists() else {"items": {}, "runs": []}
    runs = catalog.get("runs", [])
    run_dates = [r["date"] for r in runs]

    # The run we analyze: an explicit --run-date, else the latest catalog run, else the
    # latest social run (so the social report works before the first competitor run),
    # else today. The catalog being empty is NOT an error — social can stand alone.
    social_dates = []
    if SOCIAL_HISTORY.exists():
        social_dates = [r["date"] for r in json.loads(SOCIAL_HISTORY.read_text()).get("runs", [])]
    if args.run_date:
        run_date = args.run_date
    elif run_dates:
        run_date = run_dates[-1]
    elif social_dates:
        run_date = social_dates[-1]
    else:
        print("ERROR: no catalog runs and no social history — nothing to analyze.")
        return

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

    # --- Sell-through: what's actually MOVING (demand proxy) ----------------------
    # Among items listed both this run and last run, find those whose buyable-variant
    # share fell sharply (or sold out) while still listed → selling through.
    selling_out_records: list = []
    if prev_date and not live_now.empty:
        both = live_now[live_now["seen_dates"].apply(lambda d: prev_date in d)]
        for _, r in both.iterrows():
            now_ratio = _ratio_at(r["stock_history"], run_date)
            prev_ratio = _ratio_at(r["stock_history"], prev_date)
            if now_ratio is None or prev_ratio is None:
                continue
            drop = prev_ratio - now_ratio
            sold_out_now = (now_ratio == 0.0)
            if drop >= SELL_THROUGH_DROP or (sold_out_now and prev_ratio > 0):
                rec = r.drop(labels=["stock_history", "seen_dates"]).to_dict()
                rec["stock_drop"] = round(drop, 3)
                rec["now_ratio"] = now_ratio
                rec["prev_ratio"] = prev_ratio
                selling_out_records.append(rec)
        selling_out_records.sort(key=lambda x: x["stock_drop"], reverse=True)

    # Which attributes dominate the items that are selling through (the demand signal).
    sell_through_attrs: dict[str, list] = {}
    if selling_out_records:
        so_df = pd.DataFrame(selling_out_records)
        for attr in ATTRS:
            if attr in so_df:
                counts = so_df[attr].value_counts()
                sell_through_attrs[attr] = [
                    {"value": v, "count": int(counts[v])} for v in counts.index[:args.top]
                ]

    # --- Cross-source corroboration: search interest ⨯ catalog signal -------------
    # The highest-confidence trends are ones moving in BOTH the demand signal (Google
    # search interest rising) AND the supply signal (attribute rising in catalogs, or
    # showing up among items selling through). We bridge the two via each keyword's
    # maps_to attributes (config/trend_keywords.yaml).
    keywords = _load_keywords(run_date)
    rising_lookup = {(attr, r["value"]): r["delta"] for attr in ATTRS for r in rising.get(attr, [])}
    sellthrough_values = {(attr, r["value"]) for attr in ATTRS for r in sell_through_attrs.get(attr, [])}

    # Social signal (engagement velocity) — the earliest, leading source. Its per-value
    # index lets a keyword's mapped attribute also be corroborated by social momentum.
    social = _social_analysis(run_date, args.top)
    social_index = social.pop("_value_index") if social else {}

    cross_source = []
    for term, kd in keywords.items():
        maps_to = kd.get("maps_to") or {}
        if not maps_to:
            continue
        vel = kd.get("velocity")
        # Require real search volume (interest ≥ 10) before trusting a velocity as a
        # demand signal — low-volume niche terms produce noisy percentages.
        search_rising = (vel is not None and vel > 0 and (kd.get("interest") or 0) >= 10)
        catalog_delta = None
        in_sellthrough = False
        social_delta = None
        for attr, val in maps_to.items():
            d = rising_lookup.get((attr, val))
            if d is not None and (catalog_delta is None or d > catalog_delta):
                catalog_delta = d
            if (attr, val) in sellthrough_values:
                in_sellthrough = True
            sm = social_index.get((attr, val))
            if sm and (social_delta is None or sm["delta"] > social_delta):
                social_delta = sm["delta"]
        catalog_rising = (catalog_delta is not None and catalog_delta > 0) or in_sellthrough
        social_rising = social_delta is not None and social_delta > 0
        # Count agreeing signals; the more sources point the same way, the higher confidence.
        signals = sum([bool(search_rising), bool(catalog_rising), bool(social_rising)])
        cross_source.append({
            "term":            term,
            "search_velocity": vel,
            "search_interest": kd.get("interest"),
            "low_volume":      kd.get("low_volume", False),
            "maps_to":         maps_to,
            "catalog_delta":   catalog_delta,
            "in_sellthrough":  in_sellthrough,
            "social_delta":    social_delta,
            "search_rising":   search_rising,
            "catalog_rising":  catalog_rising,
            "social_rising":   social_rising,
            "signals":         signals,
            # corroborated = the demand signal (search) agrees with a supply/leading
            # signal (catalog/sell-through OR social engagement momentum).
            "corroborated":    bool(search_rising and (catalog_rising or social_rising)),
        })
    # most agreeing signals first, then corroborated, then by search velocity
    cross_source.sort(
        key=lambda x: (x["signals"], x["corroborated"], x["search_velocity"] or -1),
        reverse=True)

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
        "selling_out":     selling_out_records[:args.top * 3],
        "selling_out_count": len(selling_out_records),
        "sell_through_attrs": sell_through_attrs,
        "search_keywords": keywords,
        "cross_source":    cross_source,
        "social":          social,
        "social_top_posts": _social_top_posts(run_date) if social else [],
    }
    out_file = TMP / f"trends_{run_date}.json"
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))

    print(f"Run {run_date} (prev: {prev_date or 'none — baseline'})")
    print(f"  live items: {len(live_now)} | new this week: {len(new_items)} | "
          f"selling through: {len(selling_out_records)}")
    if social:
        sb = "baseline" if social["is_baseline"] else f"vs {social['prev_date']}"
        print(f"  social: {social['posts']} posts ({sb}), "
              f"engagement {int(social['total_engagement']):,}")
        if social["is_baseline"]:
            for attr in ("garment_type", "pattern"):
                top = social["snapshot"].get(attr, [])[:3]
                if top:
                    bits = ", ".join(f"{r['value']} ({r['eng_share']:.0%})" for r in top)
                    print(f"    social {attr} (engagement share): {bits}")
        else:
            for attr in ("garment_type", "pattern", "color"):
                top = social["emerging"].get(attr, [])[:3]
                if top:
                    bits = ", ".join(f"{r['value']} (+{r['delta']:.0%})" for r in top)
                    print(f"    emerging {attr}: {bits}")
    if not out["is_baseline"]:
        for attr in ATTRS:
            top = rising[attr][:3]
            if top:
                bits = ", ".join(f"{r['value']} (+{r['delta']:.0%})" for r in top)
                print(f"  rising {attr}: {bits}")
        for attr in ("garment_type", "color"):
            if sell_through_attrs.get(attr):
                bits = ", ".join(f"{r['value']} ({r['count']})" for r in sell_through_attrs[attr][:3])
                print(f"  selling-out {attr}: {bits}")
        corro = [c for c in cross_source if c["corroborated"]]
        if corro:
            print(f"  cross-source corroborated: " +
                  ", ".join(c["term"] for c in corro[:5]))
    print(f"Saved → {out_file}")


if __name__ == "__main__":
    main()
