# Tools

Deterministic Python scripts. Each is self-contained, takes inputs via arguments or
`.env`, and writes a clear output. They run in sequence (each defaults to the most
recent output of the previous step in `.tmp/`), or stand alone.

| Tool | Does | Reads | Writes |
|---|---|---|---|
| `scrape_catalog.py` | Fetch competitor Shopify catalogs (public `products.json`), download primary images. Checks robots.txt; polite pacing. | `config/competitors.yaml` | `.tmp/scraped_<date>.json`, `.tmp/images/` |
| `tag_garments.py` | Tag garment attributes with FashionCLIP (local). type/colour from store metadata; neckline/sleeve/pattern/fabric from the image. | `.tmp/scraped_<date>.json` | `.tmp/tagged_<date>.json` |
| `update_catalog.py` | Merge tagged items into the persistent catalog, stamping `first_seen`. | `.tmp/tagged_<date>.json` | `data/catalog.json` |
| `analyze_trends.py` | pandas: new-this-week + rising attributes (share delta vs previous run). | `data/catalog.json` | `.tmp/trends_<date>.json` |
| `build_pdf.py` | Render the weekly PDF report via headless Chromium (HTML preview alongside). | `.tmp/trends_<date>.json` | `.tmp/trend_report_<date>.pdf` |

Common flags: `--limit N` (scrape cap), `--store KEY` (scrape one store),
`--threshold` (tag review cutoff), `--top` (rising values per attribute),
`--input PATH` (override the auto-picked input).

The scraping module and the PDF module are kept clean and independent on purpose — they
may later be pulled into shared helpers used across projects.
