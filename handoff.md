# Fashion Trend Analysis — Handoff

_Last updated: 2026-06-04. This is the single source of truth for picking the project up
cold. Read top-to-bottom once, then use the file-by-file reference as needed._

---

## 1. What this project is

A **private, multi-source fashion trend-analysis system for Style Island** — an
India-based, Gurugram-HQ'd, contemporary **women's Western-silhouette** brand (dresses,
co-ords, jumpsuits, linen/print/embroidery, ₹3–12.5k). Run **solo** by the owner.

**Goal (in priority order):**
1. **Catch 1–2 real garment trends per season *early*** — before they're obvious. This is
   THE most valued outcome (stated explicitly by the owner).
2. Tell the owner what's new, rising, and selling across competitors, with evidence, to
   plan collections from data instead of guesswork.

Built on the **WAT framework** (Workflows = markdown SOPs, Agents = the AI orchestrating,
Tools = deterministic Python). Separate project from the owner's "Best Sellers Scraping
Agent" (borrowed its *shape* — polite scraping, dated JSON in `.tmp/`, the editorial PDF
builder — but shares no code).

- **Repo:** https://github.com/yuvrajmehta21/Fashion-Trend-Analysis (PUBLIC, branch `main`)
- **Latest commit:** `5a0b71c` (Instagram monitoring sources doc)
- **Local path:** `/Users/yuvrajmehta/Desktop/Code/Fashion Trend Analysis`
- **Owner email:** yuvrajmehta05@gmail.com

> ⚠️ Repo is PUBLIC. Never commit secrets. `.env`, `data/`, `.tmp/`, `.venv/` are
> gitignored. Verified safe so far.

---

## 2. Status at a glance

### ✅ DONE & working (tested, pushed)
- **Retail catalog pipeline** end-to-end: scrape → tag → catalog → search interest →
  analyze → PDF. Verified via 2-week simulations; PDF renders cleanly (all sections).
- **7 competitor brands enabled** (14 total configured, tiered).
- **FashionCLIP** garment tagging, **local & free** (no API key).
- **Sell-through** popularity signal (stock tracked over time).
- **Google Trends** search-interest signal (free, fail-soft).
- **Cross-source corroboration** (search ⨯ catalog).
- **Editorial PDF report** in Style Island's brand palette, 6 sections.
- **Style Island brand profile** + **competitor research** docs.
- **Instagram layer Phase 1**: source list + scraper *scaffold* + executive doc.
- **Instagram scraper LIVE on Apify** (2026-06-04): `scrape_instagram.py` rewritten off
  HikerAPI onto **Apify** (`apify/instagram-scraper`); first real pull banked **195 posts
  + images** across 8 brands + 5 hashtags for **$0.53** of the free $5/mo credit. Same
  output schema as before, so downstream tagging/scoring is unchanged. See §7.

### 🚧 IN PROGRESS / BLOCKED
- **Awaiting executives' list** of brands/accounts/influencers they most want monitored
  (owner asked them; will paste handles later).

### 🔜 NOT STARTED (future)
- Run FashionCLIP on social images + **emerging-trend detection** (the actual early-catch
  logic) + social in cross-source + a social PDF section.
- A real (non-simulated) baseline run.
- Scheduling on the DigitalOcean droplet + email delivery.

---

## 3. Architecture & weekly data flow

Three signal types feed one scoring + report layer:
- **Supply** — competitor Shopify catalogs (what's offered) + rising attributes.
- **Demand (retail)** — sell-through (what's going out of stock = selling).
- **Demand (search)** — Google Trends interest in style keywords.
- **Demand (social)** — *planned* — Instagram engagement on trend-leader posts (the
  earliest signal; not yet live, blocked on provider choice).

```
config/competitors.yaml ─┐
                         ├─→ [1] scrape_catalog.py ─→ .tmp/scraped_<date>.json + images
                         │         (Shopify products.json; stock + currency + images)
                         │
                         ├─→ [2] tag_garments.py ──→ .tmp/tagged_<date>.json
                         │         (FashionCLIP local: type/colour/neckline/sleeve/pattern/fabric)
                         │
                         ├─→ [3] update_catalog.py → data/catalog.json  (PERSISTENT memory)
                         │         (first_seen, seen_dates, stock_history)
config/trend_keywords ───┼─→ [4] google_trends.py ─→ data/keywords.json + .tmp/keywords_<date>.json
                         │         (pytrends search interest + velocity; fail-soft)
                         │
                         ├─→ [5] analyze_trends.py → .tmp/trends_<date>.json
                         │         (new + rising + sell-through + search velocity + cross-source)
                         │
                         └─→ [6] build_pdf.py ─────→ .tmp/trend_report_<date>.pdf (+ .html)

(planned)  config/instagram_sources.yaml → scrape_instagram.py → .tmp/instagram_<date>.json
           → feeds [2] tagging + [5] scoring once provider is chosen & verified.

Orchestrated by run_tracker.sh (runs phases 1–6 in order, tee's to .tmp/tracker_<date>.log).
```

---

## 4. File-by-file reference

### Config (`config/`)
- **`competitors.yaml`** — competitor stores. 14 brands, schema: `key, name, base_url,
  platform(shopify), enabled, tier, collections, notes`. **Enabled (7):** reistor, verb,
  azurina, salt_attire, saaki, the_summer_house, label_by_mohita. **Bench (disabled):**
  style_island (our own brand — never analyse), rareism, cord, ampm, kazo, jovi, doodlage,
  chambray_co. All verified Shopify (products.json = 200).
- **`trend_keywords.yaml`** — style keywords for Google Trends; each has optional `maps_to`
  linking it to attributes (for cross-source). `geo: IN`, `timeframe: today 3-m`.
- **`instagram_sources.yaml`** — Instagram accounts + hashtags, weighted to trend-leaders.
  8 intl brands ENABLED; influencers/competitors drafted but DISABLED pending verification.
  ⚠️ Handles are best-guess drafts; scraper validates at runtime.

### Tools (`tools/`)
- **`scrape_catalog.py`** — fetches each enabled store's public Shopify `/products.json`
  (paginated). Captures `product_type`, tags, min price, Color option, images,
  `published_at`, **per-variant `available` → stock_ratio/in_stock** (sell-through input),
  and **currency via `/meta.json`** (reistor=USD, others=INR). Checks robots.txt; polite
  delays. Downloads primary image per product. Flags: `--limit N`, `--store KEY`.
- **`tag_garments.py`** — **FashionCLIP** (`patrickjohncyh/fashion-clip`) local, free.
  garment_type ← store `product_type` (authoritative; image-only mis-types full outfits);
  colour ← declared Color normalised to base colour; **neckline/sleeve/pattern/fabric ←
  FashionCLIP from image**. `needs_review` flag for low-confidence. Vision-API fallback is
  OFF (must not enable without sign-off). `--threshold` (default 0.35).
- **`update_catalog.py`** — merges tagged items into `data/catalog.json`. New items get
  `first_seen`; returning items update `last_seen`, `seen_dates`, `stock_history`.
  `seen_dates` lets us reconstruct any past run's live set exactly. `--run-date`.
- **`google_trends.py`** — pytrends, no key. Pulls ~90d India interest per keyword,
  current interest (0–100) + 14-day velocity, persists to `data/keywords.json`. **Fail-soft**
  (retries + backoff; a Google hiccup never breaks the run). `MIN_VOLUME=10` floor →
  low-volume terms shown as "emerging", excluded from corroboration (avoids noisy %).
- **`analyze_trends.py`** — pandas. Computes: new-this-week, rising attributes (share
  delta), **sell-through** (items still listed whose stock dropped ≥`SELL_THROUGH_DROP`=0.25
  or sold out), search velocity, and **cross-source** (keyword rising w/ real volume AND
  mapped attribute rising/selling-through = corroborated). First run = baseline. `--top`.
- **`build_pdf.py`** — self-contained HTML + base64 images → headless Chromium → PDF, +
  `.html` preview. Style Island warm palette. Sections: Cover → New This Week → Selling Out
  → Rising Attributes → Search Interest → Cross-Source. Search/cross sections omitted if no
  Google data. **Fixed-dimension cards** (6/page) — earlier `height:100%`/flex layout
  overflowed; don't reintroduce it.
- **`scrape_instagram.py`** — **HikerAPI client (BLOCKED — see §7).** Reads `HIKERAPI_KEY`
  from `.env`, validates handles at runtime, defensive field extraction, fail-soft,
  `--dry-run` (cost preview, no calls), `--max-requests` budget. Endpoints/fields written
  against HikerAPI docs, **not yet live-verified** (account has $0 balance). If we switch
  providers, this file gets rewritten/replaced for the new API.

### Orchestration & docs
- **`run_tracker.sh`** — runs phases 1–6. `bash run_tracker.sh` (full) or
  `LIMIT=20 bash run_tracker.sh` (capped). macOS PATH handling, prefers `.venv`, tee's log.
  NOTE: does not yet include the Instagram phase (add once provider chosen + verified).
- **`workflows/catalog_tracker.md`** — the full SOP / design notes + **Self-Improvement
  Log** (read this for the "why" behind decisions).
- **`README.md`**, **`tools/README.md`** — overview + per-tool table.
- **`STYLE_ISLAND_PROFILE.md`** — reusable brand profile (design deck + web research):
  identity, palette (warm sand/terracotta hex codes), price band, customer, competitor
  landscape, sources.
- **`Instagram_Monitoring_Sources.md`** — **executive-facing**, non-technical doc of
  proposed IG sources for the execs to review/extend. Share this with them.
- **`.env.example`** — template (committed). **`.env`** — real secrets (gitignored).

### State
- **`data/catalog.json`** — persistent catalog memory. **Currently RESET/empty** (the
  prior contents were a 2-week *simulation* with injected stock; deleted so the first real
  run is a clean baseline).
- **`data/keywords.json`** — real Google Trends history (from a 2026-06-02 run). Kept.
- **`.tmp/`** — disposable: scrapes, downloaded images, logs, rendered PDFs/PNGs. Holds a
  demo `trend_report_2026-06-02.pdf` from the simulation (for reference only).

---

## 5. Setup, run & verify

### Environment (already set up locally)
- Python **3.9** venv at `.venv/`. macOS, no Homebrew. Python 3.9 system interpreter.
- `pip install -r requirements.txt` → requests, PyYAML, pandas, playwright, Pillow,
  pytrends, torch, transformers.
- `playwright install chromium` (done).
- **FashionCLIP model (~600MB) already downloaded/cached** (first `tag_garments.py` run).
- **`pymupdf`** is installed in the venv for PDF→PNG verification but is NOT in
  requirements.txt (it's a dev/verify tool, not a pipeline dep).

### Run
```bash
cd "/Users/yuvrajmehta/Desktop/Code/Fashion Trend Analysis"
LIMIT=20 bash run_tracker.sh      # quick capped run
bash run_tracker.sh               # full
# individual tools default to the most recent .tmp/ input of the prior step
.venv/bin/python tools/scrape_catalog.py --limit 6
```

### Verify the PDF (IMPORTANT lesson)
**Always render the actual PDF to PNG and look at every section** — HTML element
screenshots hide paged-media overflow bugs (this burned us twice):
```bash
.venv/bin/python - <<'EOF'
import pymupdf, glob, os
for f in glob.glob(".tmp/pdfpage_*.png"): os.remove(f)
doc = pymupdf.open(sorted(glob.glob(".tmp/trend_report_*.pdf"))[-1])
for i,p in enumerate(doc): p.get_pixmap(dpi=105).save(f".tmp/pdfpage_{i+1:02d}.png")
EOF
```
Then Read the `.tmp/pdfpage_*.png` files.

### Testing trends without waiting weeks
Trends need 2+ runs. To test: run week 1 with `--run-date 2026-XX-XX`, then run week 2 with
a later date; to exercise sell-through, inject stock drops into the week-2 `tagged_*.json`
before `update_catalog.py` (see git history / prior simulations for the snippet). **Reset
`data/catalog.json` afterward** so real runs start clean.

---

## 6. Key decisions & constraints (the "why")

- **Budget = free-only first.** Owner won't pay for unproven tooling. This killed HikerAPI
  ($50 min). Drives the whole Instagram provider question.
- **No paid APIs / no API keys in the working system.** FashionCLIP is local; Google Trends
  is keyless; Shopify is public. The only paid thing under consideration is the Instagram
  scraper. `ANTHROPIC_API_KEY` in `.env.example` is an unused, OFF vision fallback.
- **`products.json` has NO bestseller rank** — `sort_by=best-selling` is silently ignored
  (verified). So popularity = **sell-through** (stock going out over time), not rank.
- **Trend-catching is mostly about SOURCES, not code.** Competitors lag (they react to the
  same trends). So Instagram monitoring is weighted to **trend-leaders** (international
  aspirational brands + influencers), with competitors as a confirmation layer. Geography =
  **India + international** (intl leads India by months). Owner chose: trend-leaders first,
  India+intl, "I draft + you add" for the source list.
- **Style Island itself is NOT analysed** (it's our own brand; benched in config).
- **Currency per store** via `/meta.json` (don't hardcode ₹).
- **Engagement ≠ sales.** Social signal is directional; must be corroborated.
- **Honesty over hype.** Owner values candid limitation-talk. The realistic value framing:
  ~7/10 as decision-support/time-saver, ~3/10 as a predictive oracle. "1–2 trends/season
  early" is achievable but probabilistic and improves as data accrues.

---

## 7. RESOLVED: Instagram data provider → Apify (live-verified 2026-06-04)

**Outcome:** Migrated off HikerAPI (which needed a **$50 minimum top-up**, declined) onto
**Apify**, which has a **$5/month free credit, no minimum deposit**. `scrape_instagram.py`
now drives the `apify/instagram-scraper` actor and is **live-verified**.

**Verified facts (checked via the Apify API, not assumed):**
- Owner's account: FREE plan, **$5/mo credit**. Token in `.env` as `APIFY_TOKEN`
  (gitignored). Get/rotate it at https://console.apify.com/settings/integrations.
- Pricing: **$0.0027 per dataset result** on the FREE tier (= the $2.70/1k shown in the
  console). Current source list ≈ **246 results/run ≈ $0.66**, ~**$2.86/mo** — inside the
  free credit. First real run pulled **195 posts + images for $0.53**.

**How the new scraper works:** start an actor run (POST) → poll the run to `SUCCEEDED` →
fetch its default dataset. **Accounts** go in one run (each result carries `ownerUsername`,
mapped back to the configured source; collab/repost items attribute to their real owner).
**Each hashtag is its own run** so every post is attributable to its tag. Fail-soft
throughout; `--dry-run` previews cost with no runs; `--max-results` caps spend per run;
optional `only_posts_newer_than` config key limits to recent posts. **Output schema is
unchanged**, so tagging/scoring slots in untouched. HikerAPI code remains in git history
(commit `55a6f9b`) if the owner ever opts into the $50.

**Why not the alternatives:** RapidAPI scrapers vary too much in quality; the official
Instagram Graph API can't see competitor/influencer posts (kills the trend-leader strategy).

---

## 8. Roadmap / next steps

### Immediate (next session)
1. ✅ **DONE (2026-06-04): Instagram provider resolved → Apify** (§7). Rewritten,
   live-verified, first 195-post dataset banked for $0.53. **Next up is step 3 below** —
   run FashionCLIP on the social images now sitting in `.tmp/images/instagram/`.
2. **Merge executives' source picks** into `instagram_sources.yaml` when the owner sends
   them; verify handles resolve.

### After social scrape is verified pulling real data
3. **Run FashionCLIP on social images** (extend `tag_garments.py` to accept the IG input
   schema — it already tags any image; mainly needs an input adapter).
4. **Emerging-trend detection** — the actual early-catch logic: score attributes by
   **velocity from a low base** (small but accelerating engagement), not absolute volume.
   This is new logic in `analyze_trends.py`.
5. **Fold social into cross-source** corroboration (social + catalog + search agreeing =
   highest confidence) and add a **"Social / Emerging" PDF section**.
6. Add the Instagram phase to `run_tracker.sh`.

### Then (productionising)
7. **Real baseline run** across the 7 brands (no simulation), bank weeks of history.
8. **Schedule weekly** on the shared DigitalOcean droplet (cron + flock + log file). Do NOT
   set up the droplet until the loop is proven end-to-end (owner's instruction).
9. **Email delivery** of the PDF (mirror Best Sellers Agent's `send_email.py` SMTP +
   App-Password pattern, gated by a `REPORT_SHARING_ENABLED` flag).

### Optional / nice-to-have
- Branded PDF version of `Instagram_Monitoring_Sources.md` for execs (offered, not done).
- Improve FashionCLIP fabric tagging (over-predicts "georgette").
- Enable more benched competitors once multi-source loop is proven.

---

## 9. Awaiting from the owner
- **Top-up decision / provider preference** for Instagram (the $50 HikerAPI blocker).
- **Executives' list** of brands + influencers to monitor (handles).
- (Optional) whether to render the exec doc as a branded PDF.

---

## 10. Honest limitations (set expectations)
- No real weeks banked yet — everything shown was simulated; tool value compounds with real
  weekly history.
- Sell-through is a proxy (out-of-stock can mean discontinued, not just sold).
- Google Trends is thin for niche English terms in India (most read "low volume").
- FashionCLIP fabric guess is shaky; social images will be noisier to tag than clean
  product shots (expect ~60–80% usable tags).
- Engagement ≠ sales. Social is a leading-but-noisy signal.

## 11. Gotchas / lessons learned
- **Verify pricing/free-tier claims before telling the owner** (HikerAPI "free 100" was
  wrong; cost us trust).
- **Verify PDFs by rendering to PNG** (pymupdf), not HTML screenshots.
- **`sort_by` is ignored on `products.json`** — no bestseller rank.
- **Don't ship unverified code as "done"** — the owner pushed back on this; build, then
  verify live, then claim it works.
- **`.env` holds the HikerAPI token** (gitignored). Never echo it, never commit it, never
  put the value in any tracked file (including this handoff).

---

## 12. Commit history (orientation)
- `8cd5776` Build #1: competitor catalog tracker (scrape→tag→catalog→trends→PDF)
- `932e7fc` Fix PDF layout + scope to competitors only (drop Style Island)
- `68e29ac` Multi-source: more brands, sell-through, Google Trends, cross-source
- `3d7e736` Fix overlapping rows on the second Search Interest page
- `55a6f9b` Add Instagram trend layer (HikerAPI): source list + scraper scaffold
- `5a0b71c` Add shareable Instagram monitoring sources doc (latest)
