#!/usr/bin/env python3
"""
google_trends.py — Free search-interest signal via Google Trends (pytrends).

This is the demand-side complement to the retail catalog: what shoppers are actually
SEARCHING for. For each keyword in config/trend_keywords.yaml we pull the last ~90 days
of search interest for India, record the current interest level (0–100) and a VELOCITY
(recent vs earlier mean), and persist the history to data/keywords.json so trends can be
tracked across weekly runs.

Search interest is a LAGGING / confirmation signal — it corroborates a trend rather than
discovering it. analyze_trends.py cross-checks these against catalog/sell-through trends.

DESIGN: defensive on purpose. Google Trends has no official API and rate-limits the
unofficial endpoint, so every request is retried with backoff and a failure is FAIL-SOFT
(we keep prior history and carry on) — a Google hiccup must never break the weekly run.

Output: data/keywords.json (persistent history) + .tmp/keywords_<run_date>.json (snapshot)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "trend_keywords.yaml"
TMP = ROOT / ".tmp"
DATA = ROOT / "data"
STORE = DATA / "keywords.json"

TODAY = str(date.today())

BATCH_SIZE = 5        # Google Trends compares max 5 terms per request
BATCH_DELAY = 2.0     # polite pause between batches
MAX_RETRIES = 3


def _load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


# Google Trends interest is 0–100. Below this floor the search volume is too small for
# a percentage change to mean anything (a 0→1 blip reads as "+infinite%"), so we treat
# the term as low-volume / emerging and don't headline its velocity. Niche English style
# terms genuinely have low volume in India, so this floor matters here.
MIN_VOLUME = 10.0


CURRENT_WINDOW = 7      # days averaged into "current interest" — see below
MAX_PARTIAL_TAIL = 2    # trailing zero-days treated as an incomplete bucket, not a signal


def _drop_partial_tail(vals: list) -> list:
    """Strip a SHORT run of trailing zeros — Google's still-accumulating final bucket(s).

    Bounded deliberately: a term that genuinely falls to zero for a fortnight is real
    signal and must survive. Only a 1–2 day tail on an otherwise non-zero series is
    treated as an artifact. Belt-and-braces with the isPartial filter in main(); this
    also protects velocity, whose 14-day mean was being dragged down by that same zero.
    """
    if not any(vals):
        return vals
    tail = 0
    while tail < len(vals) and vals[len(vals) - 1 - tail] == 0:
        tail += 1
    return vals[:len(vals) - tail] if 0 < tail <= MAX_PARTIAL_TAIL else vals


def _velocity(series) -> tuple:
    """Return (current_interest, velocity_pct, low_volume). Velocity = recent 14-day mean
    vs the prior 14-day mean, as a fraction — but only when there's enough search volume
    to trust it; otherwise velocity is None and low_volume is True.

    `current` is the mean of the last CURRENT_WINDOW days, NOT the final day. A single
    day of a `today 3-m` (daily) series is noisy, and the final bucket is often partial —
    reading it directly gave interest=0 on 87% of runs (Jun–Aug 2026), which silently
    made `search_rising` in analyze_trends impossible and killed cross-source
    corroboration for 10 straight weeks. Partial rows are dropped upstream in main();
    the window is the second line of defence against a single flaky day.
    """
    vals = [v for v in series.tolist() if v is not None]
    vals = _drop_partial_tail(vals)
    if not vals:
        return None, None, True
    window = vals[-CURRENT_WINDOW:]
    current = round(sum(window) / len(window), 1)
    if len(vals) < 28:
        return current, None, current < MIN_VOLUME
    recent = sum(vals[-14:]) / 14.0
    earlier = sum(vals[-28:-14]) / 14.0
    low_volume = max(recent, earlier) < MIN_VOLUME
    if low_volume or earlier <= 0:
        return current, None, low_volume
    return current, round((recent - earlier) / earlier, 3), False


def _fetch_batch(pytrends, terms: list[str], geo: str, timeframe: str):
    """Fetch interest_over_time for up to 5 terms, with retry + backoff. Returns the
    DataFrame, or None on persistent failure (fail-soft)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            pytrends.build_payload(terms, geo=geo, timeframe=timeframe)
            df = pytrends.interest_over_time()
            return df
        except Exception as e:
            wait = attempt * 5
            print(f"   ! batch {terms} failed (attempt {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    print(f"   ! giving up on batch {terms} (fail-soft — keeping prior history)")
    return None


def main():
    parser = argparse.ArgumentParser(description="Pull Google Trends search interest for style keywords.")
    parser.add_argument("--run-date", default=TODAY)
    args = parser.parse_args()
    run_date = args.run_date

    cfg = _load_config()
    geo = cfg.get("geo", "IN")
    timeframe = cfg.get("timeframe", "today 3-m")
    kw_defs = cfg.get("keywords", [])
    terms = [k["term"] for k in kw_defs]
    maps = {k["term"]: (k.get("maps_to") or {}) for k in kw_defs}

    # Persistent store
    store = json.loads(STORE.read_text()) if STORE.exists() else {"terms": {}, "runs": []}

    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("ERROR: pytrends not installed. `pip install pytrends`. Skipping (fail-soft).")
        return 1

    pytrends = TrendReq(hl="en-US", tz=330, timeout=(10, 25))   # tz 330 = IST

    print(f"Google Trends — {len(terms)} keywords, geo={geo}, timeframe={timeframe}")
    snapshot = {}
    fetched = 0
    for i in range(0, len(terms), BATCH_SIZE):
        batch = terms[i:i + BATCH_SIZE]
        print(f"  batch {i//BATCH_SIZE + 1}: {batch}")
        df = _fetch_batch(pytrends, batch, geo, timeframe)
        if df is None or df.empty:
            continue
        # Google marks the still-accumulating final bucket isPartial=True. Its value is
        # a fraction of the real one (usually 0), so it must never be read as interest.
        if "isPartial" in df.columns:
            df = df[~df["isPartial"].astype(bool)]
            if df.empty:
                print(f"   ! batch {batch}: every row partial — skipping (fail-soft)")
                continue
        for term in batch:
            if term not in df.columns:
                continue
            current, vel, low_volume = _velocity(df[term])
            entry = store["terms"].setdefault(term, {"maps_to": maps.get(term, {}), "history": []})
            entry["maps_to"] = maps.get(term, {})
            # one reading per run date (replace if re-run same day)
            entry["history"] = [h for h in entry["history"] if h.get("date") != run_date]
            entry["history"].append({"date": run_date, "interest": current,
                                     "velocity": vel, "low_volume": low_volume})
            snapshot[term] = {"interest": current, "velocity": vel,
                              "low_volume": low_volume, "maps_to": maps.get(term, {})}
            fetched += 1
        time.sleep(BATCH_DELAY)

    if fetched:
        if run_date not in store["runs"]:
            store["runs"].append(run_date)
        DATA.mkdir(exist_ok=True)
        STORE.write_text(json.dumps(store, indent=2, ensure_ascii=False))

    out = {"run_date": run_date, "geo": geo, "timeframe": timeframe, "keywords": snapshot}
    TMP.mkdir(exist_ok=True)
    (TMP / f"keywords_{run_date}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"\nFetched {fetched}/{len(terms)} keywords.")
    if not fetched:
        # Don't claim to have saved a store we never touched, and don't let a total
        # blackout read as a clean phase — Google 429s whole IPs for hours at a time.
        print("No keyword data returned (Google is likely rate-limiting this IP).")
        print(f"data/keywords.json left UNCHANGED — prior history preserved.")
        return 1
    # show the strongest movers
    movers = sorted(
        [(t, d["velocity"], d["interest"]) for t, d in snapshot.items() if d.get("velocity") is not None],
        key=lambda x: x[1], reverse=True,
    )
    for t, v, interest in movers[:6]:
        print(f"   {t}: interest {interest:.0f}, velocity {v:+.0%}")
    print(f"Saved → data/keywords.json + .tmp/keywords_{run_date}.json")
    # A partial fetch is worth banking but still worth flagging.
    return 0 if fetched == len(terms) else 3


if __name__ == "__main__":
    sys.exit(main() or 0)
