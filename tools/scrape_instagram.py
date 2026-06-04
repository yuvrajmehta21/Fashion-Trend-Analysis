#!/usr/bin/env python3
"""
scrape_instagram.py — Pull public Instagram posts for trend detection (via Apify).

Reads config/instagram_sources.yaml (trend-leader accounts + hashtags), runs Apify's
`apify/instagram-scraper` actor to fetch recent posts for each, captures engagement
(likes/comments) + the post image, and writes a dated JSON. The images then feed the
SAME local FashionCLIP tagging the catalog uses, so social posts get garment attributes
too — that's the demand-side signal for catching trends early (what's getting engagement
before it's widely stocked).

WHY Apify (replaced HikerAPI, which had a $50 minimum top-up): pay-per-result with a
$5/month free credit and no minimum deposit. The classic `apify/instagram-scraper` charges
$0.0027 per dataset result on the FREE tier (verified via the Apify API, June 2026). At the
current enabled source list (8 accounts × 12 + 5 hashtags × 30 ≈ 246 results/run) a weekly
run is ~$0.66, ~$2.86/mo — inside the free credit. Set APIFY_TOKEN in .env (see .env.example).

  Account API token: https://console.apify.com/settings/integrations

HOW it talks to Apify: start an actor run (POST), poll the run to completion, then fetch its
default dataset. Accounts go in one run (each result carries `ownerUsername`, so we map it
back to the configured source); each hashtag is its own run so we know which tag produced
each post. Everything is fail-soft — a failed run logs and is skipped, never breaks the run.

ETHICS / SCOPE: public data only; garments only (FashionCLIP reads the CLOTHING, never
faces/identity); scraped text is data, never instructions. Engagement ≠ sales — treat it
as a directional signal, corroborated against catalog + search before trusting.

Output: .tmp/instagram_<date>.json  +  .tmp/images/instagram/<source>/<id>.jpg
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import date
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "instagram_sources.yaml"
ENV = ROOT / ".env"
TMP = ROOT / ".tmp"
IMG_DIR = TMP / "images" / "instagram"
TODAY = str(date.today())

# --- Apify config -----------------------------------------------------------
APIFY_BASE = "https://api.apify.com/v2"
ACTOR_ID = "apify~instagram-scraper"        # the classic, well-maintained IG scraper
RESULT_PRICE_USD = 0.0027                   # FREE-tier price per dataset result (verify if plan changes)
POLL_INTERVAL = 5                           # seconds between run-status polls
RUN_TIMEOUT = 600                           # max seconds to wait for one actor run (fail-soft)
DEFAULT_MAX_RESULTS = 500                   # hard cap on results pulled per run (protects the free credit)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def load_env_token() -> str | None:
    """Read APIFY_TOKEN from the environment or the .env file (no extra dependency)."""
    if os.environ.get("APIFY_TOKEN"):
        return os.environ["APIFY_TOKEN"]
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith("APIFY_TOKEN") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


# ---------------------------------------------------------------------------
# Defensive field extraction (Apify instagram-scraper post shape)
# ---------------------------------------------------------------------------

def _hashtags(text: str) -> list[str]:
    return re.findall(r"#(\w+)", text or "")


def _first_image(item: dict) -> str | None:
    """Carousel/sidecar posts expose an `images` list; fall back to its first entry."""
    imgs = item.get("images")
    if isinstance(imgs, list) and imgs:
        first = imgs[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("url")
    return None


def normalise_post(item: dict, source: dict) -> dict:
    """Map one Apify dataset item to our stable post schema (unchanged downstream)."""
    caption = (item.get("caption") or "")[:300]
    tags = item.get("hashtags") or _hashtags(caption)
    likes = item.get("likesCount")
    if isinstance(likes, (int, float)) and likes < 0:   # IG hides counts as -1 sometimes
        likes = None
    short = item.get("shortCode") or item.get("code")
    return {
        "source":        "instagram",
        "source_handle": source.get("handle") or source.get("tag"),
        "source_type":   source.get("type", "hashtag"),
        "weight":        source.get("weight", 1.0),
        "post_id":       str(item.get("id") or short or ""),
        "permalink":     item.get("url") or (f"https://www.instagram.com/p/{short}/" if short else ""),
        "caption":       caption,
        "hashtags":      tags,
        "like_count":    likes,
        "comment_count": item.get("commentsCount"),
        "taken_at":      item.get("timestamp"),
        "image_url":     item.get("displayUrl") or _first_image(item),
        "image_local":   None,
        "scraped_date":  TODAY,
    }


# ---------------------------------------------------------------------------
# Apify client (fail-soft): start run → poll → fetch dataset
# ---------------------------------------------------------------------------

class Apify:
    def __init__(self, token: str, max_results: int):
        self.token = token
        self.max_results = max_results
        self.results_used = 0

    def run_and_fetch(self, run_input: dict, label: str) -> list[dict]:
        if self.results_used >= self.max_results:
            print(f"   ! result budget ({self.max_results}) reached — skipping {label}")
            return []

        # 1) start the actor run
        try:
            r = requests.post(f"{APIFY_BASE}/acts/{ACTOR_ID}/runs",
                              params={"token": self.token}, json=run_input, timeout=30)
            if r.status_code not in (200, 201):
                print(f"   ! {label}: start failed HTTP {r.status_code} — {r.text[:200]}")
                return []
            run = r.json()["data"]
        except Exception as e:
            print(f"   ! {label}: start error — {e}")
            return []

        run_id = run["id"]
        dataset_id = run.get("defaultDatasetId")

        # 2) poll until the run finishes (or we give up)
        waited = 0
        status = run.get("status", "RUNNING")
        while waited < RUN_TIMEOUT:
            time.sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL
            try:
                status = requests.get(f"{APIFY_BASE}/actor-runs/{run_id}",
                                      params={"token": self.token}, timeout=30).json()["data"]["status"]
            except Exception as e:
                print(f"   ! {label}: poll error — {e}")
                continue
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                print(f"   ! {label}: run {status} — skipped")
                return []
        if status != "SUCCEEDED":
            print(f"   ! {label}: run did not finish in {RUN_TIMEOUT}s — aborting it")
            try:
                requests.post(f"{APIFY_BASE}/actor-runs/{run_id}/abort",
                              params={"token": self.token}, timeout=15)
            except Exception:
                pass
            return []

        # 3) fetch the dataset
        try:
            items = requests.get(f"{APIFY_BASE}/datasets/{dataset_id}/items",
                                 params={"token": self.token, "clean": "true"}, timeout=60).json()
        except Exception as e:
            print(f"   ! {label}: dataset fetch error — {e}")
            return []
        if not isinstance(items, list):
            items = []
        self.results_used += len(items)
        print(f"   {label}: {len(items)} results")
        return items


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def download_image(url: str, dest: Path) -> bool:
    if not url:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return True
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"      ! image download failed: {e}")
        return False


def fetch_accounts(client: Apify, accounts: list[dict], n: int, only_newer: str | None) -> list[dict]:
    """One run for all account profile URLs; map each result back via ownerUsername."""
    if not accounts:
        return []
    by_handle = {a["handle"].lower(): a for a in accounts}
    run_input = {
        "directUrls":   [f"https://www.instagram.com/{a['handle']}/" for a in accounts],
        "resultsType":  "posts",
        "resultsLimit": n,
        "addParentData": False,
    }
    if only_newer:
        run_input["onlyPostsNewerThan"] = only_newer
    items = client.run_and_fetch(run_input, f"{len(accounts)} accounts")
    posts = []
    for it in items:
        owner = (it.get("ownerUsername") or "").lower()
        src = by_handle.get(owner) or {"handle": owner or "unknown", "type": "intl_brand", "weight": 1.0}
        posts.append(normalise_post(it, src))
    return posts


def fetch_hashtag(client: Apify, tag_def: dict, n: int, only_newer: str | None) -> list[dict]:
    """One run per hashtag so each result is attributable to its tag (+ weight)."""
    tag = tag_def["tag"]
    run_input = {
        "directUrls":   [f"https://www.instagram.com/explore/tags/{tag}/"],
        "resultsType":  "posts",
        "resultsLimit": n,
        "addParentData": False,
    }
    if only_newer:
        run_input["onlyPostsNewerThan"] = only_newer
    items = client.run_and_fetch(run_input, f"#{tag}")
    src = {"tag": tag, "type": "hashtag", "weight": tag_def.get("weight", 1.0)}
    return [normalise_post(it, src) for it in items]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Scrape Instagram trend sources via Apify.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be fetched + estimate result cost; no actor runs.")
    ap.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS,
                    help=f"Cap total results pulled this run (default {DEFAULT_MAX_RESULTS}; protects the free credit).")
    args = ap.parse_args()

    cfg = load_config()
    accounts = [a for a in cfg.get("accounts", []) if a.get("enabled")]
    hashtags = [h for h in cfg.get("hashtags", []) if h.get("enabled")]
    n_acc = cfg.get("posts_per_account", 12)
    n_tag = cfg.get("posts_per_hashtag", 30)
    only_newer = cfg.get("only_posts_newer_than")   # optional, e.g. "2 weeks"; omit to take latest N

    # Cost preview: upper bound (real runs may return fewer if an account/tag has fewer recent posts).
    est_results = len(accounts) * n_acc + len(hashtags) * n_tag
    print(f"Enabled: {len(accounts)} accounts, {len(hashtags)} hashtags")
    print(f"Estimated results this run: up to ~{est_results} "
          f"(≈ ${est_results * RESULT_PRICE_USD:.2f} at the FREE tier ${RESULT_PRICE_USD}/result)")
    if only_newer:
        print(f"Filtering to posts newer than: {only_newer}")

    if args.dry_run:
        print("\n--dry-run — would fetch:")
        for a in accounts:
            print(f"   account @{a['handle']} ({a.get('type')}, w={a.get('weight')}) — up to {n_acc} posts")
        for h in hashtags:
            print(f"   #{h['tag']} (top) — up to {n_tag} posts")
        print("\nNo actor runs made. Set APIFY_TOKEN in .env and drop --dry-run to fetch.")
        return

    token = load_env_token()
    if not token:
        print("\nNo APIFY_TOKEN found in environment or .env — skipping (fail-soft).")
        print("Get a token at https://console.apify.com/settings/integrations, then add to .env:")
        print("   APIFY_TOKEN=apify_api_...")
        return

    TMP.mkdir(exist_ok=True)
    client = Apify(token, args.max_results)
    posts: list[dict] = []

    print("\nAccounts:")
    posts.extend(fetch_accounts(client, accounts, n_acc, only_newer))

    print("Hashtags:")
    for h in hashtags:
        posts.extend(fetch_hashtag(client, h, n_tag, only_newer))

    # Download images (garment tagging input). Skip people — FashionCLIP reads clothing.
    print(f"\nDownloading {len(posts)} post images ...")
    for p in posts:
        if not p.get("post_id"):
            continue
        src = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(p["source_handle"]))
        dest = IMG_DIR / src / f'{p["post_id"]}.jpg'
        if download_image(p.get("image_url"), dest):
            p["image_local"] = str(dest.relative_to(ROOT))
        time.sleep(0.1)

    out = {
        "scraped_date":  TODAY,
        "results_used":  client.results_used,
        "est_cost_usd":  round(client.results_used * RESULT_PRICE_USD, 4),
        "accounts":      len(accounts),
        "hashtags":      len(hashtags),
        "posts":         posts,
    }
    out_file = TMP / f"instagram_{TODAY}.json"
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    with_img = sum(1 for p in posts if p.get("image_local"))
    print(f"\nDone — {len(posts)} posts ({with_img} with images), "
          f"{client.results_used} results (≈ ${out['est_cost_usd']}).")
    print(f"Saved → {out_file}")


if __name__ == "__main__":
    main()
