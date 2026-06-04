#!/usr/bin/env python3
"""
update_social.py — Aggregate this run's tagged Instagram posts into persistent
engagement-weighted social memory (data/social_history.json).

WHY this file exists: catching a trend EARLY is a velocity question, not a volume one.
A single social snapshot only tells you what's popular right now; the early signal is an
attribute whose *engagement is accelerating from a low base* — small but climbing fast,
before competitors stock it. Velocity needs history, so each social run appends a dated
snapshot here (mirroring data/catalog.json for retail and data/keywords.json for search).
analyze_trends.py then reads the last two snapshots to compute what's emerging.

For each post we credit its attribute values with:
  * post count
  * engagement       = likes + comments
  * weighted engagement (weng) = engagement × source weight, so trend-LEADERS (intl
    brands / influencers, weight 1.0) count far more than the confirmation layer
    (competitors, weight 0.4). The whole point is to listen to early adopters loudest.

Snapshots are keyed by run date and idempotent — re-running the same date replaces it.

Input:  .tmp/tagged_social_<date>.json   (from tag_garments.py --social)
Output: data/social_history.json         (updated in place)
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
TMP = ROOT / ".tmp"
DATA = ROOT / "data"
HISTORY = DATA / "social_history.json"
TODAY = str(date.today())

ATTRS = ["garment_type", "color", "neckline", "sleeve", "pattern", "fabric_guess"]


def load_history() -> dict:
    if HISTORY.exists():
        return json.loads(HISTORY.read_text())
    return {"runs": []}


def save_history(history: dict) -> None:
    DATA.mkdir(exist_ok=True)
    HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False))


def aggregate(posts: list[dict]) -> dict:
    """Build an engagement-weighted snapshot of attribute values for one run."""
    # attr -> value -> {posts, engagement, weng}
    agg = {a: defaultdict(lambda: {"posts": 0, "engagement": 0.0, "weng": 0.0}) for a in ATTRS}
    total_engagement = 0.0
    counted = 0
    for p in posts:
        attrs = p.get("attributes")
        if not attrs:
            continue
        counted += 1
        weight = float(p.get("weight") or 1.0)
        likes = p.get("like_count") or 0
        comments = p.get("comment_count") or 0
        engagement = float(likes) + float(comments)
        total_engagement += engagement
        for a in ATTRS:
            v = attrs.get(a)
            if v is None:
                continue
            cell = agg[a][v]
            cell["posts"] += 1
            cell["engagement"] += engagement
            cell["weng"] += engagement * weight
    # plain dicts + rounding for a clean JSON file
    attributes = {
        a: {v: {"posts": c["posts"],
                "engagement": round(c["engagement"], 1),
                "weng": round(c["weng"], 1)}
            for v, c in agg[a].items()}
        for a in ATTRS
    }
    return {
        "posts": counted,
        "total_engagement": round(total_engagement, 1),
        "attributes": attributes,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate tagged social posts into persistent engagement-weighted memory.")
    parser.add_argument("--input", type=Path,
                        help="tagged_social_<date>.json (default: most recent in .tmp/).")
    parser.add_argument("--run-date", default=None,
                        help="Date to stamp this snapshot (default: the file's scraped_date).")
    args = parser.parse_args()

    in_file = args.input
    if not in_file:
        files = sorted(TMP.glob("tagged_social_*.json"), reverse=True)
        if not files:
            print("ERROR: no tagged_social_*.json in .tmp/ — run tag_garments.py --social first.")
            return
        in_file = files[0]

    print(f"Reading: {in_file}")
    data = json.loads(in_file.read_text())
    posts = data.get("posts", [])
    run_date = args.run_date or data.get("scraped_date", TODAY)

    snapshot = aggregate(posts)
    snapshot["date"] = run_date

    history = load_history()
    # idempotent per date: drop any existing snapshot for this run_date, then append
    history["runs"] = [r for r in history["runs"] if r.get("date") != run_date]
    history["runs"].append(snapshot)
    history["runs"].sort(key=lambda r: r["date"])
    save_history(history)

    # quick console read-out of the engagement leaders this run
    print(f"Run {run_date}: {snapshot['posts']} posts, "
          f"total engagement {int(snapshot['total_engagement']):,}.")
    for a in ("garment_type", "pattern"):
        vals = snapshot["attributes"][a]
        top = sorted(vals.items(), key=lambda kv: kv[1]["weng"], reverse=True)[:4]
        bits = ", ".join(f"{v} ({int(c['weng']):,})" for v, c in top)
        print(f"  top {a} by weighted engagement: {bits}")
    print(f"History now holds {len(history['runs'])} run(s) → {HISTORY}")


if __name__ == "__main__":
    main()
