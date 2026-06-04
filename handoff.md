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
- **Latest commit:** `5dcf004` (pin transformers<5 / pandas<3) — see §12
- **Local path:** `/Users/yuvrajmehta/Desktop/Code/Fashion Trend Analysis`
- **Deployed on:** DigitalOcean droplet `139.59.34.167`, weekly cron Mon 06:00 IST — see §13
- **Owner email (reports):** yuvrajmehta05@gmail.com (sent from yuvrajmehta2107@gmail.com)

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
- **Full social layer LIVE** (2026-06-04): social images tagged with FashionCLIP, new
  `update_social.py` banks engagement-weighted memory, `analyze_trends.py` does
  emerging-trend detection + social cross-source, `build_pdf.py` has a Social section.
- **First REAL retail baseline run done** (2026-06-04): full catalogs scraped + tagged →
  **2,299 items across 6 brands** (Reistor 660, Salt Attire 459, Summer House 418, Verb
  412, Azurina 233, Label by Mohita 117; **Saaki skipped — robots.txt disallows
  /products.json**). `data/catalog.json` now holds this baseline. A complete **21-page
  retail+social PDF** was generated and verified page-by-page (`.tmp/trend_report_2026-06-04.pdf`).
- **DEPLOYED & SCHEDULED** (2026-06-04): running on DigitalOcean droplet `139.59.34.167`,
  **weekly cron Mon 06:00 IST**, with **email delivery** to yuvrajmehta05@gmail.com
  (`send_email.py`, Gmail SMTP_SSL). Smoke-tested + baseline run on the droplet. See §13.

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
3. ✅ **DONE (2026-06-04): FashionCLIP on social images.** `tag_garments.py --social`
   added (input adapter for the IG schema; all attrs from the image since there's no
   store metadata). First run tagged 195 posts, 47 needs_review (~24%, expected for
   noisier social photos).
4. ✅ **DONE (2026-06-04): emerging-trend detection.** New `update_social.py` banks an
   **engagement-weighted** snapshot to `data/social_history.json` (likes+comments,
   weighted by source so trend-leaders count most). `analyze_trends.py` computes
   **engagement-share velocity vs the previous social run** + a "from a low base" flag.
   ⚠️ Needs **2 social runs** to show emergence — run 1 (banked) is a baseline snapshot.
5. ✅ **DONE (2026-06-04): folded social into cross-source + added the PDF section.**
   Cross-source now counts agreeing signals (search ⨯ catalog ⨯ social); a keyword is
   corroborated when search agrees with catalog **or** social momentum. New "Social
   Snapshot / Emerging on Social" PDF section (engagement bars + a top-posts image grid);
   layout verified by rendering to PNG (fixed a 6-row overflow → capped to 5 rows/attr).
6. ✅ **DONE (2026-06-04): social phase wired into `run_tracker.sh`** behind `SOCIAL=1`
   (off by default — Apify costs ~$0.66/run). `SOCIAL=1 bash run_tracker.sh` runs it all.

### Still to do on social
- **Bank a 2nd social run** (next week, or a back-dated test) so the emerging/velocity
  view actually populates — right now it correctly shows a baseline snapshot.

### Then (productionising) — ✅ ALL DONE 2026-06-04 (see §13)
7. ✅ **Real baseline run** — local full run banked **2,299 items / 6 brands**; the droplet
   ran its own full baseline too. No simulation.
8. ✅ **Scheduled weekly on the DigitalOcean droplet** (`139.59.34.167`): cron
   `30 0 * * 1` (UTC) = **Mon 06:00 IST**, with `flock` + log. Loop was proven end-to-end
   first, per the owner's instruction.
9. ✅ **Email delivery LIVE** — `tools/send_email.py` (Gmail SMTP_SSL:465, gated on
   `REPORT_SHARING_ENABLED=true`), sending to **yuvrajmehta05@gmail.com**. Verified
   (baseline report delivered). See §13 for the full deploy.

### Optional / nice-to-have
- Branded PDF version of `Instagram_Monitoring_Sources.md` for execs (offered, not done).
- Improve FashionCLIP fabric tagging (over-predicts "georgette").
- Enable more benched competitors once multi-source loop is proven.

---

## 9. Awaiting from the owner
- **Executives' list of Instagram handles + brands to monitor** — the ONLY substantive
  open item. Paste the handles; they go into `config/instagram_sources.yaml` (set
  `enabled: true`, pick `weight`), then verify each resolves on the next run. The influencer
  + competitor + trend-account rows there are drafts, currently disabled, waiting on this.
- (Optional) whether to render the exec doc (`Instagram_Monitoring_Sources.md`) as a
  branded PDF.
- (Optional) the owner plans to **disable the other droplet automation** (Bestseller agent,
  cron `30 2 1,15 * *`) once this is confirmed stable — not required for this to run.

---

## 10. Honest limitations (set expectations)
- **One real week banked (2026-06-04 baseline).** Velocity signals (rising, sell-through,
  emerging, cross-source) need a 2nd run — they populate from the **first scheduled cron
  run (Mon 2026-06-08)**. Snapshot signals are useful now; value compounds weekly.
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
- **`.env` holds API tokens** (`APIFY_TOKEN`; legacy `HIKERAPI_KEY`) — gitignored. Never
  echo, commit, or put a value in any tracked file (including this handoff).
- **`run_tracker.sh` must quote `"$PY"`** — the project path has spaces ("Fashion Trend
  Analysis"), so an unquoted `$PY` splits and every phase fails with "No such file or
  directory". Fixed 2026-06-04; keep it quoted.
- **`tagged_social_*.json` collides with `update_catalog.py`'s `tagged_*` glob** — it has
  `posts`, not `products`, so update_catalog silently recorded 0 items. Fixed by excluding
  `social` from the glob. Watch this if you add more `tagged_*`-named outputs.
- **Baseline-run semantics (no prior week):** there's no real velocity yet, so the report
  shows a *snapshot* not "rising", and **cross-source is omitted** (its catalog "delta"
  would just be the current share — misleading as growth). It returns from run 2. Also:
  baseline bar rows use the `share` key (rising rows use `current_share`) — `build_pdf`
  reads both.
- **Don't let "New This Week" render the whole catalog on a baseline** — every item is
  "new", so the grid is capped (`NEW_MAX_CARDS`) to a sample; the full set still feeds the
  attribute analysis. (An uncapped baseline tried to embed 2,299 images → ~383 pages.)
- **PIN `transformers<5` and `pandas<3` in `requirements.txt`.** A fresh install (droplet,
  Python 3.12) pulled transformers 5.x, whose `CLIPModel.get_text_features()` returns a
  ModelOutput object, not a tensor → `feats.norm()` crashes → tagging silently produces
  nothing. Verified ranges: transformers 4.57 / pandas 2.3.
- **Gmail SMTP: use `SMTP_SSL` on port 465, not STARTTLS on 587** (587 fails "Server not
  connected"), and **strip spaces from the App Password** (Google shows it spaced). Copied
  from the Bestseller agent's working `send_email.py`.
- **Don't change the droplet's system timezone** — it's shared with the Bestseller cron, so
  a TZ change would shift *its* schedule. The droplet runs UTC; the weekly cron uses
  `30 0 * * 1` (UTC) to hit 06:00 IST. Append to crontab, never replace it.

---

## 12. Commit history (orientation)
- `8cd5776` Build #1: competitor catalog tracker (scrape→tag→catalog→trends→PDF)
- `932e7fc` Fix PDF layout + scope to competitors only (drop Style Island)
- `68e29ac` Multi-source: more brands, sell-through, Google Trends, cross-source
- `55a6f9b` Add Instagram trend layer (HikerAPI): source list + scraper scaffold
- `ea1d906` Migrate Instagram scraper HikerAPI → Apify (live-verified)
- `bc5e276` Add social trend layer (tag IG, emerging detection, PDF section)
- `78522a3` Fix baseline-run bugs from the first full retail run
- `3f8699e` Add email delivery + droplet deployment guide
- `5dcf004` Pin transformers<5 / pandas<3 (5.x broke FashionCLIP)

---

## 13. Deployment (LIVE — 2026-06-04)

**Where it runs:** existing DigitalOcean droplet **`139.59.34.167`** (Ubuntu 24.04, 2 GB
RAM + 2 GB swap, 1 vCPU). SSH as `root` from the owner's Mac (key auth, port 22). The repo
lives at `/root/Fashion-Trend-Analysis`; secrets in `/root/Fashion-Trend-Analysis/.env`
(`chmod 600`, scp'd up — never via git). FashionCLIP needs ~1.5–2 GB at peak, hence the
RAM bump + swap (the 1 GB default OOMs).

**Schedule:** cron, **Mon 06:00 IST** (`30 0 * * 1` UTC):
```
30 0 * * 1 cd /root/Fashion-Trend-Analysis && mkdir -p .tmp && /usr/bin/flock -n /tmp/fashion-tracker.lock env SOCIAL=1 bash run_tracker.sh >> .tmp/cron.log 2>&1
```
The droplet also runs the **Bestseller agent** (`30 2 1,15 * *`) — left untouched; we
appended, never replaced. `SOCIAL=1` includes the Apify Instagram pull (~$0.53/run).

**Email:** delivered to **yuvrajmehta05@gmail.com**, sent from **yuvrajmehta2107@gmail.com**
(Gmail App Password in `.env`), gated on `REPORT_SHARING_ENABLED=true`.

**Operate (from the owner's Mac):**
- Code change: `git push` locally → `ssh root@139.59.34.167 'cd Fashion-Trend-Analysis && git pull'`.
- Rotate a secret: re-`scp .env` up.
- Watch a run: `ssh root@139.59.34.167 'tail -f Fashion-Trend-Analysis/.tmp/cron.log'`.
- Pause: edit crontab and comment the Style Island line (leave Bestseller's intact).
- Full setup steps + droplet-sizing rationale live in **`DEPLOY.md`**.

**Cost:** droplet (already owned) + Apify ~$2.86/mo (inside the free $5) ≈ negligible new spend.
