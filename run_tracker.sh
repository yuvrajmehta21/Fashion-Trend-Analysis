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

run_phase() {
    local label="$1"; shift
    echo ""
    echo "[${label}] $*"
    if "$@"; then
        return 0
    else
        echo "  ! ${label} failed (continuing)"
        return 1
    fi
}

{
    echo "=== Catalog Tracker — $(date) ==="

    echo ""
    echo "════════════════════════════════════"
    echo "  1 — SCRAPE competitor catalogs"
    echo "════════════════════════════════════"
    run_phase "1" $PY tools/scrape_catalog.py $LIMIT_ARG

    echo ""
    echo "════════════════════════════════════"
    echo "  2 — TAG garments (FashionCLIP)"
    echo "════════════════════════════════════"
    run_phase "2" $PY tools/tag_garments.py

    echo ""
    echo "════════════════════════════════════"
    echo "  3 — UPDATE persistent catalog"
    echo "════════════════════════════════════"
    run_phase "3" $PY tools/update_catalog.py

    echo ""
    echo "════════════════════════════════════"
    echo "  4 — SEARCH INTEREST (Google Trends)"
    echo "════════════════════════════════════"
    # Fail-soft: a Google Trends hiccup must not block the report. analyze_trends
    # simply omits the search/cross-source sections if this produced nothing.
    run_phase "4" $PY tools/google_trends.py

    # Optional SOCIAL layer (Instagram via Apify). Opt in with SOCIAL=1 — it spends
    # Apify credit (~$0.66/run at the current source list), so it's off by default and
    # kept out of plain catalog-only test runs. Each step is fail-soft.
    if [[ -n "${SOCIAL:-}" ]]; then
        echo ""
        echo "════════════════════════════════════"
        echo "  S1 — SCRAPE Instagram (Apify)"
        echo "════════════════════════════════════"
        run_phase "S1" $PY tools/scrape_instagram.py

        echo ""
        echo "════════════════════════════════════"
        echo "  S2 — TAG social images (FashionCLIP)"
        echo "════════════════════════════════════"
        run_phase "S2" $PY tools/tag_garments.py --social

        echo ""
        echo "════════════════════════════════════"
        echo "  S3 — UPDATE social engagement memory"
        echo "════════════════════════════════════"
        run_phase "S3" $PY tools/update_social.py
    fi

    echo ""
    echo "════════════════════════════════════"
    echo "  5 — ANALYZE trends (pandas)"
    echo "════════════════════════════════════"
    run_phase "5" $PY tools/analyze_trends.py

    echo ""
    echo "════════════════════════════════════"
    echo "  6 — BUILD weekly PDF report"
    echo "════════════════════════════════════"
    run_phase "6" $PY tools/build_pdf.py

    echo ""
    echo "=== Done — $(date) ==="
    echo "Report → .tmp/trend_report_${DATE}.pdf"
} 2>&1 | tee -a "$LOG_FILE"
