#!/usr/bin/env python3
"""
scrape_catalog.py — Pull public catalog data from competitor Shopify stores.

Reads the store list from config/competitors.yaml (never hardcoded), and for each
ENABLED store fetches its public `products.json` catalog — a clean, structured,
documented Shopify endpoint. This is the polite path: one paginated JSON feed per
store instead of hammering and regex-parsing HTML product pages.

For each product we keep public catalog facts only (title, type, price, colors,
tags, first-published date, image URL) and download the primary product image so
the next step (tag_garments.py) can read garment attributes off it.

ETHICS / SCOPE:
  * Public catalog data only. We check each store's robots.txt before fetching and
    skip anything it disallows. Requests are slow and polite (a delay between pages).
  * GARMENTS ONLY. Product images are downloaded solely so FashionCLIP can tag the
    CLOTHING. We never run face detection, never identify people, and never store
    anyone's identity. Any person in a photo is ignored — we look at the garment.
  * Scraped text (titles, tags, robots.txt) is treated strictly as DATA, never as
    instructions to act on.

Output:
  .tmp/scraped_<YYYY-MM-DD>.json      — all products from all enabled stores
  .tmp/images/<store_key>/<id>.jpg    — primary image per product
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
import yaml

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "competitors.yaml"
TMP = ROOT / ".tmp"
IMG_DIR = TMP / "images"

TODAY = str(date.today())

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

PAGE_SIZE = 250          # Shopify products.json max page size
REQUEST_DELAY = 1.5      # seconds between requests — slow and polite
IMAGE_WIDTH = 700        # Shopify CDN resize width for downloaded images

# Currency symbols by ISO code (stores differ: reistor.com is USD, shopverb is INR).
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "AUD": "A$", "CAD": "C$"}


def fetch_currency(base_url: str) -> tuple[str, str]:
    """Read a Shopify store's currency from /meta.json. Returns (code, symbol)."""
    try:
        r = requests.get(base_url.rstrip("/") + "/meta.json", headers=HEADERS, timeout=20)
        code = (r.json().get("currency") or "").upper()
        if code:
            return code, CURRENCY_SYMBOLS.get(code, code + " ")
    except Exception:
        pass
    return "", ""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_stores() -> list[dict]:
    if not CONFIG.exists():
        print(f"ERROR: missing config file {CONFIG}")
        sys.exit(1)
    data = yaml.safe_load(CONFIG.read_text())
    return data.get("stores", [])


# ---------------------------------------------------------------------------
# Politeness — robots.txt
# ---------------------------------------------------------------------------

def robots_allows(base_url: str, path: str) -> bool:
    """True if the store's robots.txt allows fetching `path` for a generic agent.
    Fails OPEN only if robots.txt can't be retrieved at all (network error); a
    parsed robots that disallows the path returns False."""
    robots_url = base_url.rstrip("/") + "/robots.txt"
    rp = RobotFileParser()
    try:
        r = requests.get(robots_url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return True  # no usable robots.txt — treat as unrestricted
        rp.parse(r.text.splitlines())
    except Exception:
        return True
    return rp.can_fetch(HEADERS["User-Agent"], base_url.rstrip("/") + path)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

# Tag noise to drop — Shopify stores stuff internal flags into tags.
_TAG_NOISE = re.compile(r"(_TAG$|^TAB_|^BS_|progressbar|sizechart|nonsale|custom_)", re.I)


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    return [t for t in (tags or []) if t and not _TAG_NOISE.search(t)]


def _min_price(variants: list[dict]) -> float | None:
    prices = []
    for v in variants or []:
        try:
            prices.append(float(v.get("price")))
        except (TypeError, ValueError):
            pass
    return min(prices) if prices else None


def _availability(variants: list[dict]) -> dict:
    """Stock state from per-variant `available` booleans. products.json exposes only
    the boolean (no inventory counts), so we track how many variants are in stock.
    Tracked over weeks, this is our sell-through / popularity proxy: a listed product
    whose variants go from available → unavailable is selling through."""
    total = len(variants or [])
    avail = sum(1 for v in (variants or []) if v.get("available"))
    return {
        "variants_total":     total,
        "variants_available": avail,
        "in_stock":           avail > 0,
        # fraction of sizes/colours still buyable (1.0 = fully stocked, 0.0 = sold out)
        "stock_ratio":        round(avail / total, 3) if total else None,
    }


def _colors_from_options(options: list[dict]) -> list[str]:
    """Pull the Color option values — a clean, declared color signal from the store."""
    for o in options or []:
        if (o.get("name") or "").strip().lower() in ("color", "colour"):
            return [str(v).strip() for v in o.get("values", []) if v]
    return []


def _resize_src(src: str, width: int) -> str:
    """Insert a Shopify CDN width directive: foo.jpg -> foo_700x.jpg."""
    m = re.match(r"(.*?)(\.[a-zA-Z]+)(\?.*)?$", src)
    if not m:
        return src
    stem, ext, query = m.group(1), m.group(2), m.group(3) or ""
    return f"{stem}_{width}x{ext}{query}"


def normalise_product(p: dict, store: dict, currency: tuple[str, str]) -> dict:
    variants = p.get("variants") or []
    images = p.get("images") or []
    image_url = images[0]["src"] if images else None
    handle = p.get("handle", "")
    code, symbol = currency
    return {
        "store_key":    store["key"],
        "store_name":   store["name"],
        "tier":         store.get("tier"),
        "product_id":   f'{store["key"]}:{p.get("id")}',
        "title":        p.get("title", ""),   # the store's own product name (catalog data)
        "product_type": p.get("product_type", ""),
        "vendor":       p.get("vendor", ""),
        "price":        _min_price(variants),
        "currency":     code,
        "currency_symbol": symbol,
        **_availability(variants),
        "colors":       _colors_from_options(p.get("options")),
        "tags":         _clean_tags(p.get("tags")),
        "url":          f'{store["base_url"].rstrip("/")}/products/{handle}',
        "image_url":    image_url,
        "image_local":  None,          # filled by download_image
        "published_at": p.get("published_at", ""),
        "scraped_date": TODAY,
    }


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

# --- Why this module fetches catalogs with curl, not requests --------------------------
# Shopify's edge fingerprints the HTTP client and blocks python-requests outright.
# Measured on the droplet 2026-08-04, same IP, same URL, seconds apart:
#     curl              -> 200
#     python-requests   -> 429   (twice, either side of the curl call)
# It is not headers: five header sets were tried (the scraper's own, curl-like Accept,
# Accept-Encoding: identity, a full browser set, and literally `User-Agent: curl/8.5.0`)
# and all five got 429 from requests. What differs is Python's TLS/HTTP stack, which we
# cannot change from inside requests. curl ships on both macOS and the Ubuntu droplet,
# and at ~30 catalog requests a week the subprocess cost is irrelevant.
#
# This is what caused the 2026-08-03 empty scrape and the 07-06 partial, and it silently
# cost the project weeks of data. If catalogs start 429ing again, re-run that comparison
# FIRST — the answer is a transport question, not a politeness question.
RETRY_STATUSES = {429, 500, 502, 503, 504}
FETCH_RETRIES = 4
RETRY_BACKOFF = 20        # seconds: 20, 40, 80, 160 — deliberately patient, we run weekly
MAX_RETRY_AFTER = 300     # cap on an honoured Retry-After header
CURL = shutil.which("curl")


class FetchError(Exception):
    """A catalog page could not be fetched (after retries)."""


def _curl_once(url: str) -> tuple[int, bytes, dict]:
    """One GET via the curl binary. Returns (status, body, headers)."""
    with tempfile.TemporaryDirectory() as td:
        body_path = Path(td) / "body"
        hdr_path = Path(td) / "hdr"
        cmd = [CURL, "-sS", "--compressed", "--max-time", "45",
               "-o", str(body_path), "-D", str(hdr_path),
               "-w", "%{http_code}"]
        for k, v in HEADERS.items():
            cmd += ["-H", f"{k}: {v}"]
        cmd.append(url)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise FetchError(f"curl exit {proc.returncode}: {proc.stderr.strip()[:200]}")
        try:
            status = int((proc.stdout or "").strip()[-3:])
        except ValueError:
            raise FetchError(f"could not parse curl status from {proc.stdout!r}")
        headers = {}
        if hdr_path.exists():
            for line in hdr_path.read_text(errors="replace").splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
        body = body_path.read_bytes() if body_path.exists() else b""
        return status, body, headers


def _get_json_with_retry(url: str) -> dict:
    """Fetch a JSON endpoint with backoff on throttle/5xx. Raises FetchError if every
    attempt fails, so the caller can fail that store rather than bank a partial run."""
    if not CURL:
        raise FetchError("curl not found on PATH — required to fetch Shopify catalogs "
                         "(python-requests is fingerprinted and blocked; see module notes)")
    last = None
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            status, body, headers = _curl_once(url)
            if status in RETRY_STATUSES and attempt < FETCH_RETRIES:
                wait = RETRY_BACKOFF * (2 ** (attempt - 1))
                try:
                    wait = min(int(headers.get("retry-after", wait)), MAX_RETRY_AFTER)
                except (TypeError, ValueError):
                    pass
                print(f"      ! {status} — retry {attempt}/{FETCH_RETRIES - 1} in {wait}s")
                time.sleep(wait)
                continue
            if status >= 400:
                raise FetchError(f"HTTP {status} for {url}")
            return json.loads(body.decode("utf-8", errors="replace"))
        except FetchError as e:
            last = e
            if attempt >= FETCH_RETRIES:
                break
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            print(f"      ! {e} — retry {attempt}/{FETCH_RETRIES - 1} in {wait}s")
            time.sleep(wait)
        except json.JSONDecodeError as e:
            raise FetchError(f"invalid JSON from {url}: {e}")
    raise last or FetchError(f"exhausted retries for {url}")


def fetch_products(base_url: str, collection: str | None, limit: int | None) -> list[dict]:
    """Page through a store's products.json (optionally scoped to a collection)."""
    if collection:
        endpoint = f"{base_url.rstrip('/')}/collections/{collection}/products.json"
    else:
        endpoint = f"{base_url.rstrip('/')}/products.json"

    out: list[dict] = []
    page = 1
    while True:
        url = f"{endpoint}?limit={PAGE_SIZE}&page={page}"
        batch = _get_json_with_retry(url).get("products", [])
        if not batch:
            break
        out.extend(batch)
        if limit and len(out) >= limit:
            return out[:limit]
        page += 1
        time.sleep(REQUEST_DELAY)
    return out


def download_image(image_url: str, dest: Path) -> bool:
    if not image_url:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return True
    try:
        r = requests.get(_resize_src(image_url, IMAGE_WIDTH), headers=HEADERS, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"      ! image download failed: {e}")
        return False


def scrape_store(store: dict, limit: int | None) -> list[dict]:
    base = store["base_url"]
    print(f"\n→ {store['name']} ({base})")

    if store.get("platform") != "shopify":
        print(f"   skip — unsupported platform {store.get('platform')!r}")
        return []

    # Politeness: confirm robots.txt permits the catalog endpoint.
    if not robots_allows(base, "/products.json"):
        print("   skip — robots.txt disallows /products.json")
        return []

    currency = fetch_currency(base)
    print(f"   currency: {currency[0] or 'unknown'}")

    collections = store.get("collections") or [None]
    raw: list[dict] = []
    seen_ids: set = set()
    for col in collections:
        label = col or "(whole catalog)"
        try:
            prods = fetch_products(base, col, limit)
            for p in prods:
                if p.get("id") in seen_ids:
                    continue
                seen_ids.add(p.get("id"))
                raw.append(p)
            print(f"   {label}: {len(prods)} products")
        except Exception as e:
            print(f"   {label}: ! error {e}")
        time.sleep(REQUEST_DELAY)

    products = [normalise_product(p, store, currency) for p in raw]

    # Download the primary image per product (garment tagging input).
    print(f"   downloading {len(products)} primary images ...")
    for prod in products:
        local = IMG_DIR / store["key"] / f'{str(prod["product_id"]).split(":")[-1]}.jpg'
        if download_image(prod["image_url"], local):
            prod["image_local"] = str(local.relative_to(ROOT))
        time.sleep(0.2)   # gentle pacing on the CDN too

    return products


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape competitor Shopify catalogs.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max products per store (for small test runs).")
    parser.add_argument("--store", action="append",
                        help="Only scrape this store key (repeatable). Default: all enabled.")
    args = parser.parse_args()

    TMP.mkdir(exist_ok=True)
    stores = load_stores()

    selected = []
    for s in stores:
        if args.store:
            if s["key"] in args.store:
                selected.append(s)
        elif s.get("enabled"):
            selected.append(s)

    if not selected:
        print("No stores selected (check `enabled:` in config/competitors.yaml).")
        sys.exit(1)

    print(f"Scraping {len(selected)} store(s): {', '.join(s['key'] for s in selected)}")
    if args.limit:
        print(f"(limit: {args.limit} products/store)")

    all_products: list[dict] = []
    store_summaries = []
    for store in selected:
        prods = scrape_store(store, args.limit)
        all_products.extend(prods)
        store_summaries.append({"key": store["key"], "name": store["name"],
                                "count": len(prods)})

    out = {
        "scraped_date": TODAY,
        "stores":       store_summaries,
        "products":     all_products,
    }
    out_file = TMP / f"scraped_{TODAY}.json"
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"\nDone — {len(all_products)} products from {len(selected)} stores.")
    for s in store_summaries:
        print(f"   {s['name']}: {s['count']}")
    print(f"Saved → {out_file}")

    # Signal degraded scrapes to the orchestrator. Downstream phases treat a thin week
    # as real market movement, so a partial scrape must be loud, not silent.
    empty = [s for s in store_summaries if not s["count"]]
    if not all_products:
        print("\nFAILED — every store returned 0 products. This is an outage, not an "
              "empty market; downstream phases must not treat it as a week of data.")
        return 2
    if empty:
        print(f"\nDEGRADED — {len(empty)}/{len(selected)} stores returned nothing: "
              f"{', '.join(s['key'] for s in empty)}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
