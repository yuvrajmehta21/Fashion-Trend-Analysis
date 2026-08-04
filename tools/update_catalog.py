#!/usr/bin/env python3
"""
update_catalog.py — Merge this run's tagged items into the persistent catalog.

The catalog (data/catalog.json) is the project's MEMORY: it accumulates every
garment we've ever seen, each stamped with the date we FIRST saw it. That first-seen
date is what makes week-over-week trend analysis possible — newly appeared items and
rising attributes are computed from it. Unlike .tmp/ (disposable), this file persists
across runs, so it lives in data/ (gitignored — local state, not code).

For each tagged product:
    * never seen before → add it, set first_seen = run date, mark new this run
    * seen before       → update last_seen + seen_count, keep the original first_seen

Input:  .tmp/tagged_<date>.json   (from tag_garments.py)
Output: data/catalog.json         (updated in place)
        .tmp/run_summary_<date>.json (what changed this run, for logging/PDF)

REFUSES to run on an input whose date doesn't match the run date. On 2026-08-03 every
store 429'd, tag_garments wrote no file, and the "newest tagged_*.json" default silently
picked up the PREVIOUS week's file — recording 2,352 items as live on a day nothing was
scraped. That poisons seen_dates and flatlines sell-through, invisibly. Stamping the
wrong date into memory is worse than skipping a week, so a mismatch is now a hard error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
TMP = ROOT / ".tmp"
DATA = ROOT / "data"
CATALOG = DATA / "catalog.json"

TODAY = str(date.today())


_DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


def input_date(path: Path) -> str | None:
    """The run date encoded in a tagged_<date>.json filename, if any."""
    m = _DATE_IN_NAME.search(path.name)
    return m.group(1) if m else None


def load_catalog() -> dict:
    if CATALOG.exists():
        return json.loads(CATALOG.read_text())
    return {"items": {}, "runs": []}


def save_catalog(catalog: dict) -> None:
    DATA.mkdir(exist_ok=True)
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Merge tagged items into the persistent catalog.")
    parser.add_argument("--input", type=Path,
                        help="tagged_<date>.json (default: most recent in .tmp/).")
    parser.add_argument("--run-date", default=TODAY,
                        help="Date to stamp as first_seen for new items (default: today).")
    parser.add_argument("--allow-stale", action="store_true",
                        help="Permit an input whose date differs from --run-date. Only for "
                             "back-dated replays; never in the scheduled pipeline.")
    args = parser.parse_args()

    in_file = args.input
    if not in_file:
        # Exclude tagged_social_*.json — that's the Instagram feed (has `posts`, not
        # `products`) and belongs to update_social.py, not the catalog.
        files = [f for f in sorted(TMP.glob("tagged_*.json"), reverse=True)
                 if "social" not in f.name]
        if not files:
            print("ERROR: no tagged_*.json in .tmp/ — run tag_garments.py first.")
            return 1
        in_file = files[0]

    run_date = args.run_date

    # --- Guards: never write a run we can't stand behind -------------------------
    # A mismatch means this run's scrape or tagging didn't produce a file and we've
    # fallen back to an older one. Recording it would fabricate a week of history.
    src_date = input_date(in_file)
    if src_date and src_date != run_date and not args.allow_stale:
        print(f"ERROR: {in_file.name} is from {src_date}, but the run date is {run_date}.")
        print("       Refusing to stamp stale data as this run — the upstream phase")
        print("       (scrape or tag) most likely failed. Fix that, or pass")
        print("       --allow-stale/--run-date deliberately for a back-dated replay.")
        return 1

    print(f"Reading: {in_file}")
    data = json.loads(in_file.read_text())
    products = data.get("products", [])

    # An empty scrape is an outage, not a market with zero garments in it. Writing it
    # would flatline sell-through and report "0 new" as if it were a finding.
    if not products:
        print(f"ERROR: {in_file.name} holds 0 products — treating as a failed scrape,")
        print("       not an empty market. Catalog left untouched.")
        return 1

    catalog = load_catalog()
    items = catalog["items"]

    new_ids, returning_ids = [], []
    for p in products:
        pid = p["product_id"]
        record = {
            # public catalog facts
            "store_key":    p.get("store_key"),
            "store_name":   p.get("store_name"),
            "tier":         p.get("tier"),
            "title":        p.get("title"),
            "url":          p.get("url"),
            "price":        p.get("price"),
            "currency_symbol": p.get("currency_symbol", ""),
            "image_local":  p.get("image_local"),
            "published_at": p.get("published_at"),
            # current stock state (sell-through proxy)
            "in_stock":           p.get("in_stock"),
            "stock_ratio":        p.get("stock_ratio"),
            "variants_total":     p.get("variants_total"),
            "variants_available": p.get("variants_available"),
            # tagged attributes
            "attributes":   p.get("attributes"),
            "needs_review": p.get("needs_review", False),
        }
        # One stock reading per run, so sell-through can be measured over time.
        stock_point = {"date": run_date, "stock_ratio": p.get("stock_ratio"),
                       "in_stock": p.get("in_stock")}
        if pid in items:
            existing = items[pid]
            existing.update(record)                       # refresh facts/tags
            existing["last_seen"]  = run_date
            existing["seen_count"] = existing.get("seen_count", 1) + 1
            # seen_dates lets us reconstruct any past run's live catalog exactly,
            # even after later runs touch the item — needed for share-over-time.
            if run_date not in existing.setdefault("seen_dates", []):
                existing["seen_dates"].append(run_date)
            existing.setdefault("stock_history", []).append(stock_point)
            returning_ids.append(pid)
        else:
            record["first_seen"] = run_date
            record["last_seen"]  = run_date
            record["seen_count"] = 1
            record["seen_dates"] = [run_date]
            record["stock_history"] = [stock_point]
            items[pid] = record
            new_ids.append(pid)

    catalog["runs"].append({
        "date":        run_date,
        "scraped":     len(products),
        "new":         len(new_ids),
        "returning":   len(returning_ids),
        "catalog_size": len(items),
    })
    save_catalog(catalog)

    summary = {
        "run_date":     run_date,
        "scraped":      len(products),
        "new":          len(new_ids),
        "returning":    len(returning_ids),
        "catalog_size": len(items),
        "new_ids":      new_ids,
    }
    (TMP / f"run_summary_{run_date}.json").write_text(json.dumps(summary, indent=2))

    print(f"Run {run_date}: {len(products)} scraped — "
          f"{len(new_ids)} new, {len(returning_ids)} returning.")
    print(f"Catalog now holds {len(items)} items → {CATALOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
