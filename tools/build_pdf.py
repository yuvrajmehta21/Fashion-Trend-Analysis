#!/usr/bin/env python3
"""
build_pdf.py — Render the weekly competitor trend report into a PDF.

Self-contained module (HTML + CSS + Chromium render), modelled on the editorial PDF
builder from the Best Sellers Scraping Agent: build one self-contained HTML document
with base64-embedded images, render it to PDF via headless Chromium (Playwright), and
write an HTML preview alongside so layout can be tuned without re-running the pipeline.

Styled in Style Island's brand palette (warm sand / clay / terracotta — see
STYLE_ISLAND_PROFILE.md) so the deliverable feels on-brand.

Report structure:
    Cover  →  New This Week (image grid)  →  Rising Attributes (or, on a baseline
    week, the Current Snapshot of the live catalog).

Input:  .tmp/trends_<date>.json   (from analyze_trends.py)
Output: .tmp/trend_report_<date>.pdf  (+ .html preview)
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
TMP = ROOT / ".tmp"

ATTR_LABEL = {
    "garment_type": "Garment Type",
    "color":        "Colour",
    "neckline":     "Neckline",
    "sleeve":       "Sleeve",
    "pattern":      "Pattern",
    "fabric_guess": "Fabric (guess)",
}
GRID_PER_PAGE = 6   # 2 rows × 3 cols per "New This Week" page (fits A4 landscape cleanly)


# ---------------------------------------------------------------------------
# Image helper (base64 embed — same approach as the reference builder)
# ---------------------------------------------------------------------------

def _img_data_uri(rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    path = ROOT / rel_path
    if not path.exists():
        return None
    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        ext = path.suffix.lstrip(".").lower() or "jpg"
        if ext == "jpg":
            ext = "jpeg"
        return f"data:image/{ext};base64,{b64}"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def _cover(data: dict) -> str:
    run = html.escape(str(data.get("run_date", "")))
    live = data.get("live_count", 0)
    new = data.get("new_count", 0)
    baseline = data.get("is_baseline")
    prev = data.get("previous_date")
    period = ("Baseline edition — first reading"
              if baseline else f"Versus {html.escape(str(prev))}")
    return f"""
<section class="cover">
  <div class="cover-left">
    <div class="cover-eyebrow">Competitor Trend Report · {run}</div>
    <h1 class="cover-title">Style Island<br/><span class="it">Trend Intelligence</span></h1>
    <div class="cover-subtitle">A weekly read on what competitors are putting in
      market — newly dropped garments and the attributes gaining ground across their
      catalogs.</div>
    <hr class="cover-rule"/>
    <div class="cover-footer">{period}</div>
  </div>
  <div class="cover-summary">
    <div class="cover-summary-heading">This edition</div>
    <div class="cover-summary-row"><span class="cat-name">Live items tracked</span><span class="cat-count">{live}</span></div>
    <div class="cover-summary-row"><span class="cat-name">New this week</span><span class="cat-count">{new}</span></div>
  </div>
</section>
"""


def _section_divider(title: str, subtitle: str) -> str:
    return f"""
<section class="divider-page">
  <div class="divider-eyebrow">{html.escape(subtitle)}</div>
  <h1 class="divider-name">{html.escape(title)}</h1>
</section>
"""


def _attr_line(a: dict) -> str:
    gt = html.escape(str(a.get("garment_type") or ""))
    col = html.escape(str(a.get("color") or ""))
    pat = html.escape(str(a.get("pattern") or ""))
    nl = html.escape(str(a.get("neckline") or ""))
    sl = html.escape(str(a.get("sleeve") or ""))
    fab = html.escape(str(a.get("fabric_guess") or ""))
    return f"{col} {gt} · {nl} · {sl} · {pat} · {fab}"


def _new_card(item: dict) -> str:
    img = _img_data_uri(item.get("image_local"))
    img_html = (f'<div class="card-img"><img src="{img}"/></div>' if img
                else '<div class="card-img placeholder"></div>')
    store = html.escape(str(item.get("store_name") or ""))
    title = html.escape(str(item.get("title") or "")[:48])
    price = item.get("price")
    sym = html.escape(str(item.get("currency_symbol") or ""))
    price_html = f'<div class="card-price">{sym}{int(price):,}</div>' if price else ""
    attrs = item.get("attributes") or {}
    return f"""
<div class="card">
  {img_html}
  <div class="card-store">{store}</div>
  <div class="card-title">{title}</div>
  {price_html}
  <div class="card-attrs">{html.escape(_attr_line(attrs))}</div>
</div>
"""


def _new_this_week_pages(data: dict) -> str:
    items = data.get("new_items", [])
    if not items:
        return ('<section class="grid-page"><div class="empty-note">'
                'No newly dropped garments detected this week.</div></section>')
    pages = []
    for start in range(0, len(items), GRID_PER_PAGE):
        chunk = items[start:start + GRID_PER_PAGE]
        cards = "".join(_new_card(it) for it in chunk)
        pages.append(f'<section class="grid-page"><div class="grid">{cards}</div></section>')
    return "".join(pages)


def _bar_row(r: dict, baseline: bool) -> str:
    value = html.escape(str(r["value"]))
    share = r.get("current_share", 0)
    count = r.get("current_count", r.get("count", 0))
    width = max(2, round(share * 100))
    if baseline:
        delta_html = f'<span class="metric">{share:.0%} · {count} items</span>'
    else:
        d = r.get("delta", 0)
        sign = "+" if d >= 0 else ""
        delta_html = f'<span class="metric">{share:.0%} <span class="delta">({sign}{d:.0%})</span></span>'
    return f"""
<div class="bar-row">
  <div class="bar-label">{value}</div>
  <div class="bar-track"><div class="bar-fill" style="width:{width}%"></div></div>
  {delta_html}
</div>
"""


def _trend_pages(data: dict) -> str:
    baseline = data.get("is_baseline")
    source = data.get("snapshot") if baseline else data.get("rising")
    blocks = []
    for attr, label in ATTR_LABEL.items():
        rows = (source or {}).get(attr, [])
        if not rows:
            continue
        bars = "".join(_bar_row(r, baseline) for r in rows)
        blocks.append(f'<div class="attr-block"><h2 class="attr-title">{label}</h2>{bars}</div>')

    # two attribute-blocks per page for breathing room
    pages = []
    for i in range(0, len(blocks), 2):
        pages.append(f'<section class="trend-page">{"".join(blocks[i:i+2])}</section>')
    return "".join(pages) or (
        '<section class="trend-page"><div class="empty-note">No rising attributes yet '
        '— trends appear from the second weekly run.</div></section>')


# ---------------------------------------------------------------------------
# CSS — Style Island brand palette (warm sand / clay / terracotta)
# ---------------------------------------------------------------------------

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300&family=Inter:wght@300;400;500&display=swap');
@page { size: A4 landscape; margin: 0; }
* { box-sizing: border-box; }
:root {
  --bg:#FAF6F1; --ink:#2A2320; --ink-soft:#4A4039; --muted:#7A6A5D;
  --accent:#c97b6e; --accent-deep:#9c5e62; --sand:#c19d86; --hairline:#E7DCD1;
  --tile:#EFE6DB;
  --serif:'Cormorant Garamond',Georgia,serif; --sans:'Inter',-apple-system,sans-serif;
}
html,body { margin:0; font-family:var(--sans); font-weight:300; color:var(--ink);
  background:var(--bg); -webkit-print-color-adjust:exact; print-color-adjust:exact; }

/* Cover */
.cover { width:297mm; height:210mm; padding:22mm 26mm; display:grid;
  grid-template-columns:1.3fr 1fr; gap:22mm; page-break-after:always; }
.cover-left { display:flex; flex-direction:column; }
.cover-eyebrow { font-size:9pt; font-weight:500; letter-spacing:.4em; text-transform:uppercase;
  color:var(--accent); margin-bottom:auto; }
.cover-title { font-family:var(--serif); font-weight:300; font-size:58pt; line-height:1.0;
  margin:0 0 7mm; }
.cover-title .it { font-style:italic; color:var(--accent); }
.cover-subtitle { font-family:var(--serif); font-style:italic; font-size:13.5pt;
  color:var(--muted); line-height:1.5; max-width:135mm; margin-bottom:12mm; }
.cover-rule { border:none; border-top:.5pt solid var(--accent); width:28mm; margin:0; }
.cover-footer { margin-top:auto; padding-top:12mm; font-size:8pt; font-weight:400;
  letter-spacing:.3em; text-transform:uppercase; color:var(--accent); }
.cover-summary { display:flex; flex-direction:column; justify-content:center; }
.cover-summary-heading { font-size:8.5pt; font-weight:500; letter-spacing:.4em;
  text-transform:uppercase; color:var(--accent); margin-bottom:8mm; }
.cover-summary-row { display:flex; justify-content:space-between; align-items:baseline;
  border-bottom:.3pt solid var(--hairline); padding:5mm 0; }
.cover-summary-row .cat-name { font-size:9.5pt; letter-spacing:.2em; text-transform:uppercase; }
.cover-summary-row .cat-count { font-family:var(--serif); font-style:italic; font-size:26pt;
  color:var(--accent); }

/* Divider */
.divider-page { width:297mm; height:210mm; display:flex; flex-direction:column;
  align-items:center; justify-content:center; page-break-after:always; }
.divider-eyebrow { font-size:9pt; font-weight:500; letter-spacing:.45em; text-transform:uppercase;
  color:var(--accent); margin-bottom:9mm; }
.divider-name { font-family:var(--serif); font-weight:300; font-size:78pt; letter-spacing:.06em;
  margin:0; text-align:center; }

/* New-this-week grid — fixed card dimensions (deterministic in paged media, no
   height:100%/1fr/flex tricks that overflow when rendered to PDF). */
.grid-page { width:297mm; height:210mm; padding:16mm 22mm; page-break-after:always; }
.grid { display:grid; grid-template-columns:repeat(3,1fr); column-gap:10mm; row-gap:7mm; }
.card { display:flex; flex-direction:column; overflow:hidden; }
/* object-position:center favours the garment/torso over the model's head — we read
   the clothing, not the person. */
.card-img { height:54mm; overflow:hidden; background:var(--tile); border-radius:1mm; }
.card-img img { width:100%; height:100%; object-fit:cover; object-position:center;
  display:block; }
.card-img.placeholder { background:var(--tile); }
.card-store { font-size:7.5pt; font-weight:500; letter-spacing:.25em; text-transform:uppercase;
  color:var(--accent); margin-top:3mm; }
.card-title { font-family:var(--serif); font-size:12pt; line-height:1.15; color:var(--ink);
  margin-top:1.5mm; height:12mm; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2;
  -webkit-box-orient:vertical; }
.card-price { font-size:9.5pt; color:var(--ink); margin-top:1mm; }
.card-attrs { font-size:7.5pt; color:var(--muted); margin-top:1.5mm; line-height:1.35;
  height:8mm; overflow:hidden; }

/* Rising / snapshot bars */
.trend-page { width:297mm; height:210mm; padding:20mm 26mm; page-break-after:always;
  display:flex; flex-direction:column; justify-content:center; gap:14mm; }
.attr-block { }
.attr-title { font-family:var(--serif); font-weight:400; font-size:22pt; color:var(--ink);
  margin:0 0 6mm; }
.bar-row { display:grid; grid-template-columns:55mm 1fr 34mm; align-items:center; gap:6mm;
  padding:2.2mm 0; border-bottom:.3pt solid var(--hairline); }
.bar-label { font-size:10pt; color:var(--ink-soft); text-transform:capitalize; }
.bar-track { height:5mm; background:var(--tile); border-radius:3mm; overflow:hidden; }
.bar-fill { height:100%; background:linear-gradient(90deg,var(--sand),var(--accent)); }
.metric { font-size:9.5pt; color:var(--ink); text-align:right; }
.delta { color:var(--accent-deep); font-weight:500; }
.empty-note { font-family:var(--serif); font-style:italic; font-size:16pt; color:var(--muted);
  text-align:center; margin-top:80mm; }
"""


def build_html(data: dict) -> str:
    run = html.escape(str(data.get("run_date", "")))
    baseline = data.get("is_baseline")
    new_count = data.get("new_count", 0)
    trend_title = "Current Snapshot" if baseline else "Rising Attributes"
    trend_sub = ("Where the live catalog sits today" if baseline
                 else "Gaining share versus last week")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Style Island Trend Report {run}</title><style>{CSS}</style></head><body>
{_cover(data)}
{_section_divider("New This Week", f"{new_count} newly dropped garments")}
{_new_this_week_pages(data)}
{_section_divider(trend_title, trend_sub)}
{_trend_pages(data)}
</body></html>"""


def main():
    parser = argparse.ArgumentParser(description="Render the weekly trend report PDF.")
    parser.add_argument("--input", type=Path,
                        help="trends_<date>.json (default: most recent in .tmp/).")
    args = parser.parse_args()

    in_file = args.input
    if not in_file:
        files = sorted(TMP.glob("trends_*.json"), reverse=True)
        if not files:
            print("ERROR: no trends_*.json in .tmp/ — run analyze_trends.py first.")
            sys.exit(1)
        in_file = files[0]

    print(f"Reading: {in_file}")
    data = json.loads(in_file.read_text())
    run = data.get("run_date", "report")

    html_doc = build_html(data)
    html_path = TMP / f"trend_report_{run}.html"
    pdf_path = TMP / f"trend_report_{run}.pdf"
    html_path.write_text(html_doc, encoding="utf-8")

    print("Rendering PDF via Chromium ...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html_doc, wait_until="networkidle")
        page.pdf(path=str(pdf_path), format="A4", landscape=True,
                 print_background=True,
                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        browser.close()

    print(f"Saved → {pdf_path}")
    print(f"  HTML preview → {html_path}")


if __name__ == "__main__":
    main()
