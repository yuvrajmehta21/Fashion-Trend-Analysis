#!/usr/bin/env python3
"""
send_email.py — Email the latest weekly trend PDF (Gmail SMTP + App Password).

The final, OPTIONAL phase of a weekly run. It mails `.tmp/trend_report_<date>.pdf` to
the configured recipients, with a short text summary pulled from the trends JSON.

GATED: sending only happens when REPORT_SHARING_ENABLED=true in .env. With it unset/false
the tool prints what it WOULD do and exits 0 — so the pipeline is safe to wire up before
you're ready to actually send. `--dry-run` forces that preview regardless of the flag.

Credentials (in .env, gitignored — never commit):
  REPORT_SHARING_ENABLED   "true" to actually send (anything else = preview only)
  REPORT_EMAILS            comma-separated recipients (e.g. yuvrajmehta05@gmail.com)
  EMAIL_FROM_ADDRESS       the sending Gmail address
  EMAIL_FROM_APP_PASSWORD  a Gmail *App Password* (NOT your normal password) —
                           https://myaccount.google.com/apppasswords (needs 2FA on)

Why an App Password: Gmail blocks plain-password SMTP. An App Password is a 16-char
token scoped to this app; revoke it anytime without touching your main password.

Fail-soft: any SMTP error is logged and the tool exits 0 so it never breaks the run.
"""

from __future__ import annotations

import argparse
import json
import smtplib
import ssl
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).parent.parent
TMP = ROOT / ".tmp"
ENV = ROOT / ".env"
TODAY = str(date.today())

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def load_env() -> dict:
    """Read the .env file into a dict (environment overrides file)."""
    import os
    env = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k in (
        "REPORT_SHARING_ENABLED", "REPORT_EMAILS", "EMAIL_FROM_ADDRESS",
        "EMAIL_FROM_APP_PASSWORD")})
    return env


def latest_pdf() -> Path | None:
    files = sorted(TMP.glob("trend_report_*.pdf"), reverse=True)
    return files[0] if files else None


def summary_text(run_date: str) -> str:
    """A short, honest plain-text summary from the trends JSON (best-effort)."""
    path = TMP / f"trends_{run_date}.json"
    if not path.exists():
        return "The weekly Style Island trend report is attached."
    try:
        d = json.loads(path.read_text())
    except Exception:
        return "The weekly Style Island trend report is attached."

    lines = [f"Style Island — Trend Report {run_date}", ""]
    baseline = d.get("is_baseline")
    lines.append(f"Live items tracked: {d.get('live_count', 0):,}")
    if baseline:
        lines.append("This is a BASELINE edition — week-over-week trends (rising, "
                     "sell-through, emerging, cross-source) begin from next week's run.")
    else:
        lines.append(f"New this week: {d.get('new_count', 0)} · "
                     f"Selling out: {d.get('selling_out_count', 0)}")

    social = d.get("social") or {}
    if social:
        lines.append("")
        lines.append(f"Social: {social.get('posts', 0)} trend-leader posts read.")
        gt = (social.get("snapshot") or {}).get("garment_type") or []
        if gt:
            top = ", ".join(f"{r['value']} ({r['eng_share']:.0%})" for r in gt[:3])
            lines.append(f"Top by engagement: {top}")

    lines += ["", "Full detail in the attached PDF.",
              "(Automated — engagement is a directional signal, not sales.)"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Email the latest weekly trend PDF.")
    ap.add_argument("--input", type=Path, help="PDF to send (default: latest in .tmp/).")
    ap.add_argument("--run-date", default=None, help="Date for the summary/subject.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview recipients + summary; never send, ignore the gate.")
    args = ap.parse_args()

    env = load_env()
    recipients = [e.strip() for e in (env.get("REPORT_EMAILS") or "").split(",") if e.strip()]
    pdf = args.input or latest_pdf()
    if not pdf or not pdf.exists():
        print("No trend_report_*.pdf in .tmp/ — run build_pdf.py first. (skipping)")
        return
    run_date = args.run_date or pdf.stem.replace("trend_report_", "") or TODAY
    body = summary_text(run_date)

    enabled = (env.get("REPORT_SHARING_ENABLED", "").lower() == "true")
    print(f"Report: {pdf.name}")
    print(f"Recipients: {recipients or '(none configured — set REPORT_EMAILS)'}")

    if args.dry_run or not enabled:
        why = "--dry-run" if args.dry_run else "REPORT_SHARING_ENABLED is not 'true'"
        print(f"\n[preview only — {why}] Would send this email:\n")
        print(f"  Subject: Style Island Trend Report — {run_date}")
        print("  Body:\n    " + body.replace("\n", "\n    "))
        print("\nNo email sent.")
        return

    sender = env.get("EMAIL_FROM_ADDRESS")
    app_pw = env.get("EMAIL_FROM_APP_PASSWORD")
    if not (sender and app_pw and recipients):
        print("\nMissing EMAIL_FROM_ADDRESS / EMAIL_FROM_APP_PASSWORD / REPORT_EMAILS "
              "in .env — cannot send (skipping, fail-soft).")
        return

    msg = EmailMessage()
    msg["Subject"] = f"Style Island Trend Report — {run_date}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf",
                       filename=pdf.name)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(sender, app_pw)
            s.send_message(msg)
        print(f"\nSent → {', '.join(recipients)} ({pdf.stat().st_size // 1024} KB attached).")
    except Exception as e:
        print(f"\n! Email send failed (fail-soft, run continues): {e}")


if __name__ == "__main__":
    main()
