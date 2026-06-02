# Fashion Trend Analysis

A private trend-analysis system for **Style Island**. It tracks what garments and
styles competitors are putting in market, so collections can be planned from data
instead of guesswork.

Built on the **WAT framework** (Workflows · Agents · Tools): markdown SOPs in
`workflows/` describe what to do, Python scripts in `tools/` do the deterministic
work, and an agent orchestrates.

> Separate from the Best Sellers Scraping Agent. It borrows that project's *shape*
> (polite scraping, dated JSON in `.tmp/`, the editorial PDF builder) but shares no
> code — both may later pull common bits into shared helpers.

## Multi-Source Competitor Trend Tracker

Each week, three signal types feed one scoring + report layer:

- **Supply** — scrape ~7 competitor Shopify catalogs → tag every garment with
  **FashionCLIP** (local, free) → track *new* items + *rising attributes*.
- **Demand (retail)** — **sell-through**: which listed items go out of stock over time
  (the real popularity signal; `products.json` has no bestseller rank).
- **Demand (search)** — **Google Trends** (free) search interest in style keywords.

…then **pandas** scores it all, flags **cross-source** trends (search ⨯ catalog), and a
**PDF** report renders in Style Island's brand palette: New This Week · Selling Out ·
Rising Attributes · Search Interest · Cross-Source.

Deferred (needs budget): Instagram/social-image analysis — the official IG API can't see
competitor posts. See the SOP for the slot-in plan.

See **[workflows/catalog_tracker.md](workflows/catalog_tracker.md)** for the full SOP,
and **[STYLE_ISLAND_PROFILE.md](STYLE_ISLAND_PROFILE.md)** for the brand profile and
competitor landscape that informed it.

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# edit config/competitors.yaml to choose stores, then:
bash run_tracker.sh            # full run
LIMIT=20 bash run_tracker.sh   # quick capped run
```

The report lands at `.tmp/trend_report_<date>.pdf`.

## Layout

```
config/competitors.yaml     # competitor store list (edit this; never hardcoded)
config/trend_keywords.yaml   # style keywords tracked in Google Trends
workflows/                  # markdown SOPs
tools/                      # scrape → tag → catalog → trends(search) → analyze → pdf
data/catalog.json           # persistent memory: items + first_seen + stock history (gitignored)
data/keywords.json          # persistent search-interest history (gitignored)
.tmp/                       # disposable: scrapes, images, logs, the rendered PDF
run_tracker.sh              # runs the whole weekly pipeline
STYLE_ISLAND_PROFILE.md     # brand profile + competitor research (reusable)
```

## Principles

- **Public data only**, robots.txt respected, slow and polite requests.
- **Garments only** — never faces or identities. People in photos are ignored.
- **No paid APIs without sign-off** — the optional vision fallback is off by default.
- Secrets live in `.env` (gitignored), never in git. `data/` and `.tmp/` are gitignored.
