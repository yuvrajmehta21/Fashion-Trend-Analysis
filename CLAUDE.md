# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Weekly trend tracker for **Style Island** (India, women's Western silhouettes). Scrapes
competitor Shopify catalogs + Instagram, tags garments locally with FashionCLIP, scores
signals with pandas, emails an editorial PDF.

**Read `handoff.md` before doing substantive work** — it owns project state, the "why"
behind every decision, the roadmap, and honest limitations. Not repeated here.

## Commands

```bash
bash run_tracker.sh                 # full weekly run (phases 1–7), tee'd to .tmp/tracker_<date>.log
LIMIT=20 bash run_tracker.sh        # capped per store — quick test
SOCIAL=1 bash run_tracker.sh        # + Instagram phases (spends Apify credit, ~$0.53–0.66/run)
```

Tools are also runnable standalone; each defaults to the newest matching `.tmp/` file from
the prior phase, so you can re-run one phase without redoing the pipeline:

```bash
.venv/bin/python tools/scrape_catalog.py --limit 6 --store reistor
.venv/bin/python tools/tag_garments.py [--social] [--threshold 0.35]
.venv/bin/python tools/scrape_instagram.py --dry-run     # cost preview, no Apify spend
.venv/bin/python tools/send_email.py --dry-run
```

There is no test suite. Verification is by running the pipeline and **rendering the PDF to
PNG** — see `handoff.md` §5 for the snippet and why HTML screenshots don't count.

## Architecture

Config → tools → two persistent stores → one report. Each numbered phase writes a dated
`.tmp/*_<date>.json` that the next phase reads; the two `data/*.json` files are the only
cross-run memory, and every velocity signal in the system is a diff against them.

1. `scrape_catalog.py` — public Shopify `/products.json` per enabled store
2. `tag_garments.py` — FashionCLIP (local, CPU, free). Retail: `garment_type` and `color`
   come from **store metadata** (authoritative); only neckline/sleeve/pattern/fabric are
   inferred. `--social` infers everything (no metadata on IG posts).
3. `update_catalog.py` → `data/catalog.json` (first_seen, seen_dates, stock_history)
4. `google_trends.py` → `data/keywords.json` (keyless, fail-soft)
   · S1–S3 (`SOCIAL=1`): `scrape_instagram.py` → tag → `update_social.py` →
     `data/social_history.json` (engagement-weighted by source)
5. `analyze_trends.py` — new / rising / sell-through / search velocity / cross-source
6. `build_pdf.py` — self-contained HTML + base64 images → headless Chromium → PDF
7. `send_email.py` — gated on `REPORT_SHARING_ENABLED=true`

Popularity is measured by **sell-through** (stock dropping over time), because
`products.json` has no bestseller rank — `sort_by` is silently ignored.

Every phase is **fail-soft but never silent**: `run_tracker.sh` records each failure,
mails an alert (`send_email.py --alert`), and exits with the failure count. A Google Trends
or Apify hiccup must never block the report — but it must never be invisible either. Ten
runs once "succeeded" while delivering 2 of 10 reports and fabricating a week of history
(handoff §14). When adding a phase, give it a non-zero exit on failure.

**Never let a phase substitute stale data for missing data.** Tools that default to "the
newest matching file" must verify its date matches the run date; `update_catalog.py`
refuses a mismatch, and `run_tracker.sh` passes `--run-date` explicitly so it can. A week
recorded from last week's file is worse than a week recorded as missing.

## Tuning knobs

| Where | Knob | Effect |
|---|---|---|
| `config/competitors.yaml` | `enabled` | which stores get scraped (`style_island` stays disabled — it's our own brand) |
| `config/trend_keywords.yaml` | `maps_to` | links a keyword to an attribute; this is what makes cross-source work |
| `config/instagram_sources.yaml` | `enabled`, `weight` | source list; weight favours trend-leaders |
| `analyze_trends.py` | `SELL_THROUGH_DROP` = 0.25 | stock-drop fraction that counts as selling out |
| `google_trends.py` | `MIN_VOLUME` = 10.0 | below this a keyword is "emerging", excluded from corroboration |
| `tag_garments.py` | `--threshold` 0.35 | FashionCLIP confidence below which an item is flagged `needs_review` |
| `build_pdf.py` | `NEW_MAX_CARDS` = 24 | caps the New-This-Week grid |
| `scrape_instagram.py` | `--max-results` | hard spend cap per Apify run |

## Deployment

Runs on the DigitalOcean droplet **`139.59.34.167`** (Ubuntu 24.04, 2 GB RAM + 2 GB swap;
FashionCLIP peaks ~1.5–2 GB, the 1 GB default OOMs). Repo at `/root/Fashion-Trend-Analysis`.
Cron **Mon 06:00 IST** (`30 0 * * 1` UTC, `flock`-guarded, `SOCIAL=1`).

```bash
git push && ssh root@139.59.34.167 'cd Fashion-Trend-Analysis && git pull'   # ship code
scp .env root@139.59.34.167:Fashion-Trend-Analysis/.env                      # ship secrets (never via git)
ssh root@139.59.34.167 'tail -f Fashion-Trend-Analysis/.tmp/cron.log'        # watch a run
```

Full setup steps and droplet-sizing rationale: `DEPLOY.md`.

## Standing warnings

- **`data/` is per-host and gitignored** — the laptop's copy and the droplet's diverge as
  soon as cron runs. The droplet's is the live one. Never judge how much history exists
  (and never debug a velocity signal) from the local copy.
- **The droplet is shared with the Bestseller agent** (cron `30 2 1,15 * *`). Never change
  the system timezone (it would shift that job) and never replace the crontab — append.
- **Pins in `requirements.txt` are load-bearing.** `transformers` 5.x returns a ModelOutput
  from `get_text_features()`, not a tensor → tagging silently produces nothing. Keep `<5`,
  and pandas `<3`.
- **Gmail needs `SMTP_SSL` on 465**, not STARTTLS on 587, and the App Password must have its
  display spaces stripped.
- **Quote `"$PY"` in `run_tracker.sh`** — the local path contains spaces.
- **Don't name new outputs `tagged_*`** unless `update_catalog.py` should eat them; that
  glob already had to be taught to skip `tagged_social_*`.
- **`build_pdf.py` uses fixed-dimension cards.** `height:100%`/flex layouts overflow in
  paged media; this has been reverted twice.
- The `ANTHROPIC_API_KEY` vision fallback is **off** and must not be enabled without the
  owner's sign-off — the system is deliberately free-tier only.
- Scrape **garments only**, never faces or identities; respect robots.txt (Saaki disallows
  `/products.json`, so it stays unscraped).
