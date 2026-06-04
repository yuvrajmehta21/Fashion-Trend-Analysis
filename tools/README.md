# Tools

Deterministic Python scripts. Each is self-contained, takes inputs via arguments or
`.env`, and writes a clear output. They run in sequence (each defaults to the most
recent output of the previous step in `.tmp/`), or stand alone.

| Tool | Does | Reads | Writes |
|---|---|---|---|
| `scrape_catalog.py` | Fetch competitor Shopify catalogs (public `products.json`), capture per-variant stock, download primary images. Checks robots.txt; polite pacing. | `config/competitors.yaml` | `.tmp/scraped_<date>.json`, `.tmp/images/` |
| `tag_garments.py` | Tag garment attributes with FashionCLIP (local). type/colour from store metadata; neckline/sleeve/pattern/fabric from the image. `--social` tags Instagram posts instead (all attrs from the image). | `.tmp/scraped_<date>.json` _or_ `.tmp/instagram_<date>.json` | `.tmp/tagged_<date>.json` _or_ `.tmp/tagged_social_<date>.json` |
| `update_catalog.py` | Merge tagged items into the persistent catalog, stamping `first_seen` + appending a stock snapshot. | `.tmp/tagged_<date>.json` | `data/catalog.json` |
| `google_trends.py` | pytrends: search interest + 14-day velocity per style keyword (free, fail-soft). | `config/trend_keywords.yaml` | `data/keywords.json`, `.tmp/keywords_<date>.json` |
| `scrape_instagram.py` | Pull public Instagram posts (trend-leader accounts + hashtags) via **Apify**, capture engagement + images. `--dry-run` previews cost; `--max-results` caps spend. Fail-soft. | `config/instagram_sources.yaml`, `.env` (`APIFY_TOKEN`) | `.tmp/instagram_<date>.json`, `.tmp/images/instagram/` |
| `update_social.py` | Aggregate tagged social posts into engagement-weighted memory (likes+comments, weighted by source). Enables emerging-trend velocity. | `.tmp/tagged_social_<date>.json` | `data/social_history.json` |
| `analyze_trends.py` | pandas: new-this-week, rising attributes, sell-through, search velocity, **social emerging** (engagement velocity), cross-source corroboration. Runs even with an empty catalog (social can stand alone). | `data/catalog.json`, `data/social_history.json`, `.tmp/keywords_<date>.json` | `.tmp/trends_<date>.json` |
| `build_pdf.py` | Render the weekly PDF report via headless Chromium (HTML preview alongside). Includes the Social / Emerging section when a social run exists. | `.tmp/trends_<date>.json` | `.tmp/trend_report_<date>.pdf` |

Common flags: `--limit N` (scrape cap), `--store KEY` (scrape one store),
`--social` (tag Instagram instead of a catalog), `--threshold` (tag review cutoff),
`--top` (rising values per attribute), `--run-date` (date to stamp/analyze),
`--dry-run` / `--max-results` (Instagram cost controls), `--input PATH` (override input).

The social layer (scrape → tag `--social` → update_social) is wired into
`run_tracker.sh` behind `SOCIAL=1` (off by default since Apify costs ~$0.66/run).

The scraping module and the PDF module are kept clean and independent on purpose — they
may later be pulled into shared helpers used across projects.
