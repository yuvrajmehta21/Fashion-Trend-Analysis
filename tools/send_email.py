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

Also runs as the pipeline's ALERT channel: `--alert "<what broke>"` mails a short plain-text
failure notice instead of a report.

Fail-soft, but NOT silent: SMTP errors never abort the run, but the tool now retries and
exits non-zero so the orchestrator can say so. Eight consecutive weekly reports (2026-06-04
to 07-20) were lost to a transient "[Errno 101] Network is unreachable" that was logged,
swallowed, and reported as success — the owner got 2 of 10 reports and had no idea.
"""

from __future__ import annotations

import argparse
import json
import smtplib
import ssl
import sys
import time
from datetime import date
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).parent.parent
TMP = ROOT / ".tmp"
ENV = ROOT / ".env"
TODAY = str(date.today())

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465   # SSL. (STARTTLS on 587 drops as "Server not connected" with Gmail —
                  # matches the Best Sellers agent's working send_email.py.)

SEND_RETRIES = 3
SEND_BACKOFF = 30   # seconds: 30, 60 — the droplet's failures were transient network drops


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


def deliver(msg: EmailMessage, sender: str, app_pw: str, recipients: list[str]) -> bool:
    """Send with retries. Returns True on success. Never raises — the caller decides
    what a failure means for the run, but it must not go unreported."""
    for attempt in range(1, SEND_RETRIES + 1):
        try:
            ctx = ssl.create_default_context()
            # Fresh SMTP_SSL handshake (300s — large attachments upload slowly).
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=300) as s:
                s.login(sender, app_pw)
                s.send_message(msg)
            print(f"\nSent → {', '.join(recipients)}.")
            return True
        except smtplib.SMTPAuthenticationError as e:
            # Credentials won't fix themselves on a retry.
            print(f"\n! SMTP auth failed — check EMAIL_FROM_APP_PASSWORD "
                  f"(App Password, 2FA on): {e}")
            return False
        except Exception as e:
            if attempt < SEND_RETRIES:
                wait = SEND_BACKOFF * attempt
                print(f"\n! send attempt {attempt}/{SEND_RETRIES} failed ({e}) — "
                      f"retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"\n! Email send FAILED after {SEND_RETRIES} attempts: {e}")
    return False


def send_alert(env: dict, text: str, run_date: str) -> int:
    """Mail a plain-text pipeline-failure notice. Same gate and credentials as reports."""
    recipients = [e.strip() for e in (env.get("REPORT_EMAILS") or "").split(",") if e.strip()]
    sender = (env.get("EMAIL_FROM_ADDRESS") or "").strip()
    app_pw = (env.get("EMAIL_FROM_APP_PASSWORD") or "").replace(" ", "")
    if (env.get("REPORT_SHARING_ENABLED", "").lower() != "true"):
        print(f"[alert, not sent — REPORT_SHARING_ENABLED is not 'true']\n{text}")
        return 0
    if not (sender and app_pw and recipients):
        print(f"[alert, not sent — missing email credentials in .env]\n{text}")
        return 1

    msg = EmailMessage()
    msg["Subject"] = f"[ACTION NEEDED] Style Island trend run {run_date} had failures"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(
        f"The weekly trend run on {run_date} did not complete cleanly.\n\n"
        f"{text}\n\n"
        "Nothing was silently substituted: phases that could not produce real data were\n"
        "skipped rather than back-filled with stale input.\n\n"
        "Log: .tmp/tracker_" + run_date + ".log on the droplet.\n"
    )
    return 0 if deliver(msg, sender, app_pw, recipients) else 1


def main():
    ap = argparse.ArgumentParser(description="Email the latest weekly trend PDF.")
    ap.add_argument("--alert", metavar="TEXT",
                    help="Send a plain-text pipeline-failure alert instead of a report.")
    ap.add_argument("--input", type=Path, help="PDF to send (default: latest in .tmp/).")
    ap.add_argument("--run-date", default=None, help="Date for the summary/subject.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview recipients + summary; never send, ignore the gate.")
    args = ap.parse_args()

    env = load_env()

    if args.alert:
        return send_alert(env, args.alert, args.run_date or TODAY)

    recipients = [e.strip() for e in (env.get("REPORT_EMAILS") or "").split(",") if e.strip()]
    pdf = args.input or latest_pdf()
    if not pdf or not pdf.exists():
        print("No trend_report_*.pdf in .tmp/ — run build_pdf.py first. (skipping)")
        return 1
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
        return 0

    sender = (env.get("EMAIL_FROM_ADDRESS") or "").strip()
    # App passwords are shown by Google with spaces; SMTP accepts either, strip defensively.
    app_pw = (env.get("EMAIL_FROM_APP_PASSWORD") or "").replace(" ", "")
    if not (sender and app_pw and recipients):
        print("\nMissing EMAIL_FROM_ADDRESS / EMAIL_FROM_APP_PASSWORD / REPORT_EMAILS "
              "in .env — cannot send.")
        return 1

    msg = EmailMessage()
    msg["Subject"] = f"Style Island Trend Report — {run_date}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf",
                       filename=pdf.name)

    if deliver(msg, sender, app_pw, recipients):
        print(f"  ({pdf.stat().st_size // 1024} KB attached)")
        return 0
    print("  The report is still on disk at " + str(pdf))
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
