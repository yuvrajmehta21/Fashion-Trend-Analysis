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
import sys
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
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        batch = r.json().get("products", [])
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


if __name__ == "__main__":
    main()
