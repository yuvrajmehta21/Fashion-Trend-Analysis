# Fashion Trend Analysis — Handoff

_Last updated: 2026-08-04. This is the single source of truth for picking the project up
cold. Read top-to-bottom once, then use the file-by-file reference as needed. Standing
operational facts live in `CLAUDE.md`, not here._

> **Start at §14 (2026-08-04 audit).** The droplet ran 10 weekly crons between 2026-06-04
> and 08-03 and reported all 10 as successes. It was not. §14 is what actually happened,
> what was fixed, and what is still unproven. Sections 1–13 describe the design and remain
> accurate; §2's "DONE & working" list predates the audit and should be read through it.

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
- **Latest commit:** `012fb60` (stop the pipeline reporting failures as success) — see §12/§14
- **Local path:** `/Users/yuvrajmehta/Desktop/Automations/Fashion Trend Analysis`
- **Owner email (reports):** yuvrajmehta05@gmail.com (sent from yuvrajmehta2107@gmail.com)
- Deployment coordinates, the schedule, tuning knobs and standing warnings live in
  **`CLAUDE.md`** (auto-loaded every session) — not repeated here. See §13 for the *why*.

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
- **Cross-source corroboration** (search ⨯ catalog ⨯ social) — ⚠️ **produced 0 results in
  its first 10 weeks; the gate was unreachable.** Fixed 2026-08-04, unproven live. See §14.
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
- **DEPLOYED & SCHEDULED** (2026-06-04): weekly cron on the droplet with email delivery.
  See `CLAUDE.md` for coordinates, §13 for the rationale. ⚠️ **Delivery silently failed for
  8 of its first 10 weeks** — see §14.
- **10 weekly runs banked, 9 honest** (the 10th was fabricated and has been purged; one
  more, 2026-07-06, is a partial). Catalog holds 2,549 items. Social has 10 snapshots.

### 🚧 IN PROGRESS / BLOCKED
- **Awaiting executives' list** of brands/accounts/influencers they most want monitored
  (owner asked them; will paste handles later).

### 🔜 NOT STARTED (future)
- **Bank a 2nd social run** so emerging/velocity actually populates (run 1 is a baseline
  snapshot by definition) — arrives with the first scheduled cron run.
- Nice-to-haves in §8: branded exec PDF, better fabric tagging, enabling more competitors.

---

## 3. Architecture & weekly data flow

Three signal types feed one scoring + report layer:
- **Supply** — competitor Shopify catalogs (what's offered) + rising attributes.
- **Demand (retail)** — sell-through (what's going out of stock = selling).
- **Demand (search)** — Google Trends interest in style keywords.
- **Demand (social)** — Instagram engagement on trend-leader posts (the earliest signal).
  LIVE via Apify since 2026-06-04; opt-in per run because it spends credit.

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

(SOCIAL=1) config/instagram_sources.yaml → scrape_instagram.py → .tmp/instagram_<date>.json
           → [2] tag_garments.py --social → update_social.py → data/social_history.json
           → feeds [5] scoring (emerging + cross-source) and the PDF's Social section.

Orchestrated by run_tracker.sh (phases 1–7, tee's to .tmp/tracker_<date>.log).
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
  OFF (must not enable without sign-off).
- **`update_catalog.py`** — merges tagged items into `data/catalog.json`. New items get
  `first_seen`; returning items update `last_seen`, `seen_dates`, `stock_history`.
  `seen_dates` lets us reconstruct any past run's live set exactly. `--run-date`.
- **`google_trends.py`** — pytrends, no key. Pulls ~90d India interest per keyword,
  current interest (0–100) + 14-day velocity, persists to `data/keywords.json`. **Fail-soft**
  (retries + backoff; a Google hiccup never breaks the run). A minimum-volume floor keeps
  low-volume terms out of corroboration (they'd produce noisy %), shown as "emerging".
- **`analyze_trends.py`** — pandas. Computes: new-this-week, rising attributes (share
  delta), **sell-through** (items still listed whose stock dropped past the threshold
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
- **`run_tracker.sh`** — the whole pipeline, phases 1–7 plus the opt-in social phases.
  macOS PATH handling, prefers `.venv`, tee's a log. Invocations: `CLAUDE.md § Commands`.
- **`CLAUDE.md`** — standing ops facts (deploy coordinates, schedule, knobs, warnings).
  Auto-loaded every session; keep it lean and don't restate it here.
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
⚠️ **`data/` is per-host.** It's gitignored, so the laptop's copy and the droplet's diverge
the moment cron runs. The droplet's is the real one; the laptop's is whatever you last ran
locally. Never reason about "how many weeks we have" from the local copy — check the droplet.

- **`data/catalog.json`** (local copy) — **2,299 items, one run: the 2026-06-04 baseline.**
  The earlier 2-week *simulation* was deleted so the first real run started clean.
- **`data/keywords.json`** (local) — real Google Trends history, runs 2026-06-02 + 06-04.
- **`data/social_history.json`** (local) — one baseline social snapshot; velocity needs a 2nd.
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
cd "/Users/yuvrajmehta/Desktop/Automations/Fashion Trend Analysis"
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

> The ones that are permanent code-touching invariants (dependency pins, SMTP, the shared
> droplet, the `tagged_*` glob, PDF card layout) live in **`CLAUDE.md` § Standing warnings**.
> What follows is the narrative — how we learned them and what they cost.

- **Verify pricing/free-tier claims before telling the owner** (HikerAPI "free 100" was
  wrong; cost us trust).
- **Verify PDFs by rendering to PNG** (pymupdf), not HTML screenshots — paged-media
  overflow is invisible in an HTML element screenshot. This burned us twice.
- **Don't ship unverified code as "done"** — the owner pushed back on this; build, then
  verify live, then claim it works.
- **`.env` holds API tokens** (`APIFY_TOKEN`; legacy `HIKERAPI_KEY`) — gitignored. Never
  echo, commit, or put a value in any tracked file (including this handoff).
- **The dependency pins came from a real outage:** a clean install on the droplet (Python
  3.12) pulled transformers 5.x and tagging silently produced *nothing* — no error, just
  zero tags. Verified-good ranges are transformers 4.57 / pandas 2.3.
- **The `tagged_social_*` glob collision** silently recorded 0 catalog items for a run —
  same failure mode: no error, empty output. Both cost a full debug cycle because the
  pipeline is fail-soft and happily reported success.
- **Baseline-run semantics (no prior week):** there's no real velocity yet, so the report
  shows a *snapshot* not "rising", and **cross-source is omitted** (its catalog "delta"
  would just be the current share — misleading as growth). It returns from run 2. Also:
  baseline bar rows use the `share` key (rising rows use `current_share`) — `build_pdf`
  reads both.
- **Don't let "New This Week" render the whole catalog on a baseline** — every item is
  "new", so the grid is capped (`NEW_MAX_CARDS`) to a sample; the full set still feeds the
  attribute analysis. (An uncapped baseline tried to embed 2,299 images → ~383 pages.)
- **The Gmail SMTP fix was borrowed, not derived** — port 587/STARTTLS failed opaquely
  ("Server not connected") until we copied the Bestseller agent's working `send_email.py`
  wholesale. Check that project first when a shared concern misbehaves.

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
- `012fb60` Stop the pipeline reporting failures as success (the §14 audit fixes)

---

## 13. Deployment — why it looks like this (LIVE since 2026-06-04)

> Coordinates, cron line and operating commands: **`CLAUDE.md`**. Setup steps: **`DEPLOY.md`**.
> This section is only the reasoning behind those choices.

- **Reused the existing droplet** rather than a new host: it was already owned and idle
  outside the Bestseller agent's twice-monthly window, so marginal cost is zero. The price
  is a shared machine — hence the "append to crontab, don't touch the TZ" rule.
- **RAM was the binding constraint,** not CPU. FashionCLIP peaks ~1.5–2 GB; the 1 GB
  droplet OOM-killed mid-tagging. Resized to 2 GB + 2 GB swap instead of moving to GPU —
  our volumes tag fine on CPU in a few minutes.
- **Weekly, Monday early morning** so the report is waiting before the owner's week starts,
  and because trend deltas need a week to mean anything (daily would be noise).
- **`flock`-guarded** because a slow run must never overlap the next one and double-spend
  Apify credit.
- **Email rather than a dashboard** — the owner wanted zero new logins. Delivery is gated
  behind `REPORT_SHARING_ENABLED` so a test run on any machine can't mail the owner.
- **Cost:** droplet already owned + Apify ~$2.86/mo (inside the free $5) ≈ negligible.
- **Pause it** by commenting the Style Island crontab line (leave Bestseller's intact).

---

## 14. The 2026-08-04 audit — what 10 "successful" runs were really doing

Two months after deployment nobody had looked at the output. Cron had run 10/10 Mondays
without a miss, every run exited 0, and the project looked healthy. It wasn't. Three
independent failures had been running the whole time, each one logged and swallowed.

**This is the single most important lesson in the project: `fail-soft` without alerting
converts loud failures into silent ones.** Every guard added on 2026-08-04 exists because
of that. The pipeline is still fail-soft — a Google hiccup still must not block the report
— but it can no longer *lie* about it.

### What was actually broken

**1. The owner received 2 of 10 reports.** Every run from 06-04 to 07-20 died at the email
phase with `[Errno 101] Network is unreachable` — a transient droplet network drop, caught
by a bare `except`, logged, exit 0. It started working again on its own for 07-27 and
08-03. Cause of the eight-week outage never established; it predates the retry logic, so
we can't tell in hindsight how many of those would have survived a second attempt.

**2. The 2026-08-03 run recorded a week that never happened.** All 7 stores returned `429`
(root cause below — it was never a rate limit)
in the same minute. The scrape banked 0 products → `tag_garments.py` wrote no file →
`update_catalog.py`'s "newest `tagged_*.json`" default silently picked up **the previous
week's file** and stamped 2,352 items as seen live on 08-03. That poisoned `seen_dates`,
`stock_history` and `last_seen` for every item, flatlined sell-through, and the report
then announced "0 new, 0 selling through" as if it were a market finding. It was one of
only two reports that reached the owner. **Purged 2026-08-04** (backup kept on the droplet
at `data/catalog.json.before-purge-2026-08-03`); the catalog now holds 9 honest runs.
2026-07-06 was separately degraded — 503s cost 4 of 7 stores, banking 760 items instead of
~2,370, which distorts the 07-06 and 07-13 deltas. Left in place, flagged here.

**3. Cross-source corroboration had never fired — and could not.** Zero corroborated
trends in 10 weeks. Not bad luck, arithmetic:

- `google_trends.py` read current interest from `vals[-1]`, the final bucket of a `today
  3-m` **daily** series. That bucket is Google's still-accumulating partial day, so it read
  **0 on 87% of all readings (117/135)** — and dragged down the 14-day mean behind
  `velocity` too.
- `analyze_trends.py` gated `search_rising` on `interest >= 10`, so with interest pinned at
  0 it was permanently `False`.
- `corroborated` was `search_rising AND (catalog OR social)`. A permanently-false term in a
  conjunction makes the whole feature unreachable.

So in weeks where catalog and social independently agreed (`signals: 2`), the verdict was
still "not corroborated". The flagship deliverable — *catch 1–2 trends per season early* —
produced nothing for two months while looking like it was working.

### What changed (commit `012fb60`)

| Fix | Where |
|---|---|
| Refuse an input whose date ≠ run date; refuse a 0-product input | `update_catalog.py` |
| Drop `isPartial` rows; average a 7-day window; bounded trailing-zero strip | `google_trends.py` |
| Gate on the `low_volume` flag, not a re-derived `interest >= 10` | `analyze_trends.py` |
| `corroborated` = **any 2 of 3** sources agree (search is a vote, not a veto) | `analyze_trends.py` |
| **Fetch `products.json` via the `curl` binary** (`requests` is fingerprinted → 429); retry 429/5xx with backoff; exit 2 (total) / 3 (partial) | `scrape_catalog.py` |
| SMTP retries; non-zero exit on failure; new `--alert` mode | `send_email.py` |
| Skip tag/catalog on a dead scrape; skip analyze/PDF/email on an unbanked week; collect failures, mail an alert, propagate exit status | `run_tracker.sh` |

The last one matters as much as the guards: `analyze_trends.py` defaults to the *latest*
run in the catalog, so on a week that wasn't banked it would happily rebuild last week's
figures under today's date — the same lie in a different phase.

### Deliberate judgement calls (revert these if you disagree)

- **`corroborated` = 2-of-3 is a semantic loosening, not a bug fix.** The old rule made
  Google Trends a single point of failure for a feature it structurally cannot support in
  this market (niche English style terms in India are genuinely low-volume — see §10). If
  you want search back as a hard requirement, it's one line in `analyze_trends.py`.
- **A failed retail scrape now costs the whole weekly report,** including the social half
  that may have succeeded. Chosen because a report mixing this week's social with last
  week's retail under one date is worse than no report. Social is still banked to
  `data/social_history.json` and shows up in the next good report.

### Still unproven / open

- **The Trends fix is live-verified, partially.** A 2026-08-04 run got 5 of 15 keywords
  through (the rest 429'd) and they returned real values — `maxi dress` interest 32
  (+4%), `jumpsuit` 20 (+7%), `kaftan` 16 (−10%) — where the old `vals[-1]` code read 0.
  That is the bug fixed against live data. The other 10 keywords remain unconfirmed.
- **Google Trends may be a dead end regardless.** It 429'd two different IPs on the same
  day, only 5/15 keywords got through even on the good attempt, and 87% of its historical
  readings here were unusable. If it stays this unreliable, the honest move is to drop the
  search layer and lean on catalog ⨯ social rather than keep a signal that mostly
  contributes noise. **This is the main open product decision.**
- **The 07-06 partial week** is still in the catalog and skews two weeks of deltas.

### Verification run — 2026-08-04, full pipeline, end to end

Run in a throwaway clone (`/root/fta-verify`) seeded with a **copy** of production
history, so a failed test could not damage real data. Result: **clean**.

- Scrape **2,250 products from 6 stores** over the new curl transport (Saaki skipped by
  robots.txt, as designed). FashionCLIP tagged all 2,250.
- Catalog: **27 new, 2,223 returning → 2,576 items.** Real deltas against 07-27:
  23 items selling through; social emerging `co-ord set +28%`, `white +16%`,
  `textured +11%`.
- **PDF: 18 pages, verified page-by-page as PNG** (cards, images, prices, sold-out
  badges, share bars, low-base flags — no overflow).
- **Report email delivered with a 15.8 MB attachment** — the exact path that failed
  eight times in June/July. The failure alert also delivered.
- Google Trends returned 0/15 (429) → exited 1, **left `keywords.json` untouched** rather
  than banking zeros. Correct behaviour, and the reason the alert fired.

The run was then **promoted into production** (`data/catalog.json`, backup at
`data/catalog.json.before-promote-2026-08-04`), so the catalog holds a recent comparison
point instead of a two-week gap. Revert with the same purge approach used for 08-03.

**One false alarm found and fixed by this run:** Saaki, skipped on purpose by robots.txt,
was counted as a failed store → `DEGRADED` → an alert *every week forever* for correct
behaviour. `scrape_store` now returns a skip reason and only attempted stores count
toward the failure exit codes. Weekly false alarms are how alerting dies, which would
have quietly re-created the original problem.

### 2026-08-10 — first fully clean scheduled run, and the corroboration over-fire

The first cron run with every fix in place completed **clean: no failures, no alert, no
false alarm**. 2,287 products / 6 stores, 67 new, 20 selling through, 186 social posts,
report delivered unaided. **Google Trends returned 15/15 keywords with only 2 zero
readings** — the partial-bucket fix is now conclusively verified in production (87% of
readings were zero before it).

But the report claimed **7 corroborated cross-source trends**, and three of them had
social engagement *falling* 7–10% while being counted as agreement.

**Cause:** `catalog_rising` was `catalog_delta > 0 OR in_sellthrough`. `in_sellthrough`
is a membership test against an attribute's top-6 values, and `dress` is the commonest
`garment_type`, so it is in that list every single week. **10 of the 12 keywords map to
`garment_type: dress`**, so the catalog vote was a constant `True` and the 2-of-3 rule
degenerated into "search OR social rose" — one signal wearing a second signal's hat.

**Fix:** the catalog vote now requires a real share gain. Sell-through keeps its own
report section; in cross-source it is context, not evidence. Re-run against the same real
data: **7 → 1** (`satin dress`, the only term where all three sources genuinely agree —
search +10% at real volume, catalog +0.002, social +0.001).

⚠️ **This rule has now been wrong in both directions**, and both looked like a working
feature from the outside: first it could never fire (search held a veto), then it fired
constantly (a constant standing in for a vote). **Whenever you touch it, print the
per-term votes and read them** — the corroborated *count* tells you nothing about whether
the rule is sound.

⚠️ **Catalog share deltas are tiny** (+0.002 = 0.2pp on a 2,287-item catalog), so a
corroborated trend is a *real* signal, not a *strong* one. The PDF renders it as
"catalog +0%". Don't oversell these to the owner.

### The 429s: root cause found (and two wrong theories on the way)

Worth reading as a method lesson — the first two explanations were plausible, cheap to
believe, and both wrong. Only a controlled A/B settled it.

1. *"Shopify throttles datacenter IPs."* → added in-request retry/backoff. Wrong: the
   laptop got 429s too, and `Retry-After` pinned every attempt at 60s, so four attempts
   bought three minutes.
2. *"It's a rate-limit window longer than the retry budget."* → added a 45-minute
   run-level retry (`SCRAPE_RETRY_WAIT`). Also wrong — and it looked right because a
   `curl` probe minutes after a failed run returned 200. Two variables had changed at
   once (time *and* client) and I credited the wrong one.
3. **Actual cause: Shopify's edge fingerprints the HTTP client.** Same droplet, same IP,
   same URL, seconds apart:

   ```
   curl              -> 200
   python-requests   -> 429   (twice, either side of the curl call)
   ```

   Five header sets were then tried from `requests` — the scraper's own, curl-like
   `Accept: */*`, `Accept-Encoding: identity`, a full browser set, and literally
   `User-Agent: curl/8.5.0` — and **all five got 429**. What is fingerprinted is Python's
   TLS/HTTP stack, which cannot be changed from inside `requests`.

**Fix:** `products.json` is fetched with the `curl` binary (`_get_json_with_retry` in
`scrape_catalog.py`), keeping the same retry/backoff and `Retry-After` handling.
`meta.json` and `robots.txt` stay on `requests` — both kept working right through the
outage, so they are not behind the same protection.

**If catalogs start 429ing again, run the curl-vs-requests A/B FIRST.** It is a transport
question, not a politeness question; no amount of backoff or header tuning moves it. The
run-level retry stays as cheap insurance but was built on theory 2 and is not what makes
the scrape work.

