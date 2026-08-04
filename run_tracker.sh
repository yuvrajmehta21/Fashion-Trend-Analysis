#!/bin/bash
set -uo pipefail

# run_tracker.sh — one weekly run of the competitor catalog tracker.
#   scrape → tag (FashionCLIP) → update catalog → analyze trends → build PDF
# Output is tee'd to .tmp/tracker_<date>.log. The PDF lands in .tmp/.
#
# Scheduling is the deployment host's job (a DigitalOcean cron entry on the shared
# droplet, with its own log file). This script just runs unconditionally when called.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p .tmp
DATE=$(date +%Y-%m-%d)
LOG_FILE=".tmp/tracker_${DATE}.log"

# macOS: a minimal cron/launchd PATH lacks Homebrew/pyenv — prepend for local runs.
if [[ "$(uname -s)" == "Darwin" ]]; then
    export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:$HOME/.pyenv/shims:$HOME/.pyenv/bin:$PATH"
fi

# Prefer the project-local virtualenv if present (this is how the droplet runs).
if [[ -x "$SCRIPT_DIR/.venv/bin/python3" ]]; then
    PY="$SCRIPT_DIR/.venv/bin/python3"
else
    PY="python3"
fi

# Optional: cap products/store for a quick run, e.g. LIMIT=20 bash run_tracker.sh
LIMIT_ARG=""
if [[ -n "${LIMIT:-}" ]]; then
    LIMIT_ARG="--limit ${LIMIT}"
fi

# Every phase failure is collected here and mailed as an alert at the end. A run that
# fails silently and exits 0 is worse than one that fails loudly: between 2026-06-04 and
# 07-20 eight weekly reports were lost to a swallowed SMTP error and nobody knew.
FAILURES=()
PHASE_RC=0

run_phase() {
    local label="$1"; shift
    echo ""
    echo "[${label}] $*"
    "$@"
    PHASE_RC=$?
    if [[ $PHASE_RC -ne 0 ]]; then
        echo "  ! ${label} failed (rc=${PHASE_RC})"
        FAILURES+=("${label} (rc=${PHASE_RC})")
    fi
    return $PHASE_RC
}

{
    echo "=== Catalog Tracker — $(date) ==="

    echo ""
    echo "════════════════════════════════════"
    echo "  1 — SCRAPE competitor catalogs"
    echo "════════════════════════════════════"
    run_phase "1" "$PY" tools/scrape_catalog.py $LIMIT_ARG
    # rc=2 means every store returned nothing — an outage, not an empty market. Phases
    # 2–3 would then feed the catalog stale or empty data, so the retail half is skipped
    # entirely. (rc=3 is a partial scrape: degraded, recorded, but still worth banking.)
    RETAIL_OK=1
    if [[ $PHASE_RC -eq 2 ]]; then
        RETAIL_OK=0
        echo "  ! scrape returned 0 products — skipping tag + catalog update so this"
        echo "    week is recorded as MISSING rather than as a week with no movement."
    fi

    if [[ $RETAIL_OK -eq 1 ]]; then
        echo ""
        echo "════════════════════════════════════"
        echo "  2 — TAG garments (FashionCLIP)"
        echo "════════════════════════════════════"
        run_phase "2" "$PY" tools/tag_garments.py

        echo ""
        echo "════════════════════════════════════"
        echo "  3 — UPDATE persistent catalog"
        echo "════════════════════════════════════"
        # --run-date is explicit so update_catalog can refuse a mismatched input file.
        run_phase "3" "$PY" tools/update_catalog.py --run-date "$DATE"
    fi

    echo ""
    echo "════════════════════════════════════"
    echo "  4 — SEARCH INTEREST (Google Trends)"
    echo "════════════════════════════════════"
    # Fail-soft: a Google Trends hiccup must not block the report. analyze_trends
    # simply omits the search/cross-source sections if this produced nothing.
    run_phase "4" "$PY" tools/google_trends.py

    # Optional SOCIAL layer (Instagram via Apify). Opt in with SOCIAL=1 — it spends
    # Apify credit (~$0.66/run at the current source list), so it's off by default and
    # kept out of plain catalog-only test runs. Each step is fail-soft.
    if [[ -n "${SOCIAL:-}" ]]; then
        echo ""
        echo "════════════════════════════════════"
        echo "  S1 — SCRAPE Instagram (Apify)"
        echo "════════════════════════════════════"
        run_phase "S1" "$PY" tools/scrape_instagram.py

        echo ""
        echo "════════════════════════════════════"
        echo "  S2 — TAG social images (FashionCLIP)"
        echo "════════════════════════════════════"
        run_phase "S2" "$PY" tools/tag_garments.py --social

        echo ""
        echo "════════════════════════════════════"
        echo "  S3 — UPDATE social engagement memory"
        echo "════════════════════════════════════"
        run_phase "S3" "$PY" tools/update_social.py
    fi

    # Phases 5–7 only make sense on a week that was actually banked. analyze_trends
    # defaults to the LATEST run in the catalog, so with this week missing it would
    # silently re-analyse last week's retail data and ship it under today's date —
    # the same "stale data wearing a current timestamp" failure the guards exist to
    # stop. Social is already banked in data/social_history.json either way and shows
    # up in the next good report; the alert below explains the gap.
    if [[ $RETAIL_OK -eq 1 ]]; then
        echo ""
        echo "════════════════════════════════════"
        echo "  5 — ANALYZE trends (pandas)"
        echo "════════════════════════════════════"
        run_phase "5" "$PY" tools/analyze_trends.py --run-date "$DATE"

        echo ""
        echo "════════════════════════════════════"
        echo "  6 — BUILD weekly PDF report"
        echo "════════════════════════════════════"
        run_phase "6" "$PY" tools/build_pdf.py

        echo ""
        echo "════════════════════════════════════"
        echo "  7 — EMAIL the report (gated)"
        echo "════════════════════════════════════"
        # Self-gates on REPORT_SHARING_ENABLED=true; otherwise previews and exits 0.
        run_phase "7" "$PY" tools/send_email.py
    else
        echo ""
        echo "Skipping analyze/PDF/email — no retail data was banked for ${DATE}, and a"
        echo "report built now would carry last week's figures under today's date."
    fi

    echo ""
    echo "════════════════════════════════════"
    echo "  8 — ALERT on failures"
    echo "════════════════════════════════════"
    if [[ ${#FAILURES[@]} -eq 0 ]]; then
        echo "All phases clean — no alert needed."
    else
        echo "${#FAILURES[@]} phase(s) failed: ${FAILURES[*]}"
        # Best-effort: if phase 7's SMTP was the thing that broke, this won't get through
        # either — the log is still the backstop. It costs one attempt to find out.
        ALERT_TEXT="Failed phase(s): ${FAILURES[*]}"
        if [[ $RETAIL_OK -eq 0 ]]; then
            ALERT_TEXT="${ALERT_TEXT}
The retail catalog scrape returned nothing, so this week was NOT banked. Sell-through and
rising-attribute figures will span a two-week gap on the next successful run."
        fi
        "$PY" tools/send_email.py --alert "$ALERT_TEXT" --run-date "$DATE" \
            || echo "  ! alert email also failed — see this log."
    fi

    echo ""
    echo "=== Done — $(date) ==="
    echo "Report → .tmp/trend_report_${DATE}.pdf"
    if [[ ${#FAILURES[@]} -ne 0 ]]; then
        echo "=== COMPLETED WITH ${#FAILURES[@]} FAILURE(S) ==="
    fi
    # The braces run in a subshell (they're piped into tee), so FAILURES can't be read
    # after the pipeline — exit from in here and let pipefail carry the status out.
    exit ${#FAILURES[@]}
} 2>&1 | tee -a "$LOG_FILE"

# pipefail (set at the top) propagates the block's non-zero status through tee, so cron
# and any caller see an unhealthy run without having to parse the log.
