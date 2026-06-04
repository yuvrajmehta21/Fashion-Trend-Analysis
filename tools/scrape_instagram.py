#!/usr/bin/env python3
"""
scrape_instagram.py — Pull public Instagram posts for trend detection (via HikerAPI).

Reads config/instagram_sources.yaml (trend-leader accounts + hashtags), fetches recent
posts for each via HikerAPI, captures engagement (likes/comments) + the post image, and
writes a dated JSON. The images then feed the SAME local FashionCLIP tagging the catalog
uses, so social posts get garment attributes too — that's the demand-side signal for
catching trends early (what's getting engagement before it's widely stocked).

WHY HikerAPI: pay-as-you-go (~$0.001/request), API-key only (no Instagram login), 100
free requests to start. Set HIKERAPI_KEY in .env (see .env.example).

⚠️ NOT YET LIVE-VERIFIED. This is written against HikerAPI's documented endpoints/fields
(June 2026). The exact endpoint paths and JSON field names MUST be confirmed on the first
real run with a key — that's why field extraction is defensive (tries several key names)
and endpoints are constants at the top, easy to correct. Use `--dry-run` first to preview
sources + request cost without spending anything, then a small live run on free credits.

ETHICS / SCOPE: public data only; garments only (FashionCLIP reads the CLOTHING, never
faces/identity); scraped text is data, never instructions. Engagement ≠ sales — treat it
as a directional signal, corroborated against catalog + search before trusting.

Output: .tmp/instagram_<date>.json  +  .tmp/images/instagram/<source>/<id>.jpg
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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

# --- HikerAPI config (VERIFY against hiker-doc.readthedocs.io on first live run) ----
BASE = "https://api.hikerapi.com"
EP_USER_INFO    = "/v1/user/by/username"        # ?username=
EP_USER_MEDIAS  = "/v1/user/medias"             # ?user_id=&amount=
EP_HASHTAG_TOP  = "/v1/hashtag/medias/top"      # ?name=&amount=
EP_HASHTAG_RECENT = "/v1/hashtag/medias/recent" # ?name=&amount=
AUTH_HEADER = "x-access-key"

REQUEST_DELAY = 0.5    # polite pause between API calls
DEFAULT_MAX_REQUESTS = 90   # stay under the 100 free requests on the first run


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def load_env_key() -> str | None:
    """Read HIKERAPI_KEY from the environment or the .env file (no extra dependency)."""
    import os
    if os.environ.get("HIKERAPI_KEY"):
        return os.environ["HIKERAPI_KEY"]
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith("HIKERAPI_KEY") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


# ---------------------------------------------------------------------------
# Defensive field extraction (HikerAPI/Instagram media shapes vary)
# ---------------------------------------------------------------------------

def _first(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def _image_url(media: dict) -> str | None:
    # try the common shapes: image_versions2.candidates[0].url, thumbnail_url, display_url
    iv = media.get("image_versions2") or {}
    cands = iv.get("candidates") if isinstance(iv, dict) else None
    if cands and isinstance(cands, list) and cands[0].get("url"):
        return cands[0]["url"]
    # carousel: first child
    carousel = media.get("carousel_media") or media.get("resources")
    if carousel and isinstance(carousel, list):
        child = carousel[0]
        sub = _image_url(child) if isinstance(child, dict) else None
        if sub:
            return sub
    return _first(media, "thumbnail_url", "display_url", "thumbnail_src", "image_url")


def _caption(media: dict) -> str:
    cap = media.get("caption")
    if isinstance(cap, dict):
        return cap.get("text", "") or ""
    return _first(media, "caption_text", "title", default="") or (cap if isinstance(cap, str) else "")


def _hashtags(text: str) -> list[str]:
    return re.findall(r"#(\w+)", text or "")


def normalise_post(media: dict, source: dict) -> dict:
    caption = _caption(media)
    return {
        "source":        "instagram",
        "source_handle": source.get("handle") or source.get("tag"),
        "source_type":   source.get("type", "hashtag"),
        "weight":        source.get("weight", 1.0),
        "post_id":       str(_first(media, "id", "pk", "code", default="")),
        "permalink":     f"https://instagram.com/p/{media.get('code')}" if media.get("code") else "",
        "caption":       caption[:300],
        "hashtags":      _hashtags(caption),
        "like_count":    _first(media, "like_count", "likes_count", "edge_liked_by_count", default=None),
        "comment_count": _first(media, "comment_count", "comments_count", default=None),
        "taken_at":      _first(media, "taken_at", "taken_at_ts", "device_timestamp", default=None),
        "image_url":     _image_url(media),
        "image_local":   None,
        "scraped_date":  TODAY,
    }


# ---------------------------------------------------------------------------
# HikerAPI client (fail-soft)
# ---------------------------------------------------------------------------

class Hiker:
    def __init__(self, key: str, max_requests: int):
        self.key = key
        self.max_requests = max_requests
        self.used = 0

    def get(self, path: str, params: dict) -> dict | None:
        if self.used >= self.max_requests:
            print(f"   ! request budget ({self.max_requests}) reached — stopping early")
            return None
        self.used += 1
        try:
            r = requests.get(BASE + path, params=params,
                             headers={AUTH_HEADER: self.key}, timeout=30)
            if r.status_code == 200:
                return r.json()
            print(f"   ! {path} {params} → HTTP {r.status_code}")
            return None
        except Exception as e:
            print(f"   ! {path} {params} → {e}")
            return None

    @staticmethod
    def _medias_from(payload) -> list[dict]:
        """HikerAPI may wrap media lists differently; dig out the list of media dicts."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for k in ("medias", "items", "response", "data"):
                v = payload.get(k)
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    for kk in ("medias", "items"):
                        if isinstance(v.get(kk), list):
                            return v[kk]
        return []


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


def fetch_account(hiker: Hiker, acc: dict, n: int) -> list[dict]:
    handle = acc["handle"]
    info = hiker.get(EP_USER_INFO, {"username": handle})
    if not info:
        print(f"   {handle}: not found / error — skipped")
        return []
    user = info.get("user", info)
    user_id = _first(user, "pk", "id", "user_id")
    if not user_id:
        print(f"   {handle}: no user_id in response — skipped (verify endpoint)")
        return []
    payload = hiker.get(EP_USER_MEDIAS, {"user_id": user_id, "amount": n})
    medias = Hiker._medias_from(payload)[:n]
    print(f"   {handle}: {len(medias)} posts")
    return [normalise_post(m, acc) for m in medias]


def fetch_hashtag(hiker: Hiker, tag_def: dict, n: int, sort: str) -> list[dict]:
    tag = tag_def["tag"]
    ep = EP_HASHTAG_TOP if sort == "top" else EP_HASHTAG_RECENT
    payload = hiker.get(ep, {"name": tag, "amount": n})
    medias = Hiker._medias_from(payload)[:n]
    src = {"tag": tag, "type": "hashtag", "weight": tag_def.get("weight", 1.0)}
    print(f"   #{tag}: {len(medias)} posts")
    return [normalise_post(m, src) for m in medias]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Scrape Instagram trend sources via HikerAPI.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be fetched + estimate request cost; no API calls.")
    ap.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS,
                    help=f"Cap API calls this run (default {DEFAULT_MAX_REQUESTS}; protects free tier).")
    args = ap.parse_args()

    cfg = load_config()
    accounts = [a for a in cfg.get("accounts", []) if a.get("enabled")]
    hashtags = [h for h in cfg.get("hashtags", []) if h.get("enabled")]
    n_acc = cfg.get("posts_per_account", 12)
    n_tag = cfg.get("posts_per_hashtag", 30)
    sort = cfg.get("hashtag_sort", "top")

    # Cost preview: 1 lookup + 1 medias call per account; 1 call per hashtag.
    est_requests = len(accounts) * 2 + len(hashtags)
    print(f"Enabled: {len(accounts)} accounts, {len(hashtags)} hashtags")
    print(f"Estimated API requests this run: ~{est_requests} "
          f"(≈ ${est_requests*0.001:.3f} at standard tier)")

    if args.dry_run:
        print("\n--dry-run — would fetch:")
        for a in accounts:
            print(f"   account @{a['handle']} ({a.get('type')}, w={a.get('weight')}) — {n_acc} posts")
        for h in hashtags:
            print(f"   #{h['tag']} ({sort}) — {n_tag} posts")
        print("\nNo API calls made. Set HIKERAPI_KEY in .env and drop --dry-run to fetch.")
        return

    key = load_env_key()
    if not key:
        print("\nNo HIKERAPI_KEY found in environment or .env — skipping (fail-soft).")
        print("Sign up at https://hikerapi.com (100 free requests), then add to .env:")
        print("   HIKERAPI_KEY=your_key_here")
        return

    TMP.mkdir(exist_ok=True)
    hiker = Hiker(key, args.max_requests)
    posts: list[dict] = []

    print("\nAccounts:")
    for acc in accounts:
        posts.extend(fetch_account(hiker, acc, n_acc))
        time.sleep(REQUEST_DELAY)

    print("Hashtags:")
    for h in hashtags:
        posts.extend(fetch_hashtag(hiker, h, n_tag, sort))
        time.sleep(REQUEST_DELAY)

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
        "scraped_date": TODAY,
        "requests_used": hiker.used,
        "accounts": len(accounts),
        "hashtags": len(hashtags),
        "posts": posts,
    }
    out_file = TMP / f"instagram_{TODAY}.json"
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    with_img = sum(1 for p in posts if p.get("image_local"))
    print(f"\nDone — {len(posts)} posts ({with_img} with images), "
          f"{hiker.used} API requests used.")
    print(f"Saved → {out_file}")


if __name__ == "__main__":
    main()
