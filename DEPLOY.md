# Deploying the weekly run on a DigitalOcean droplet

Goal: run `run_tracker.sh` once a week, unattended, and email the PDF to
`yuvrajmehta05@gmail.com`. The laptop is not a server — the droplet runs it on schedule
even while the laptop sleeps.

---

## 0. Droplet size — read this first (it costs more than $4/mo)

The catalog tagging uses **FashionCLIP (PyTorch)**. torch is ~340 MB installed and the
model is ~580 MB loaded **into RAM** at inference. Peak memory during a run is roughly
**1.5–2 GB**. So the cheapest 1 GB droplet **cannot run it as-is** — it will OOM.

| Option | DO size | ~Cost | Notes |
|---|---|---|---|
| **Cheapest viable** | 1 GB RAM + **4 GB swap file** | **~$6/mo** | Works for a *weekly* job — swapping is slow but speed doesn't matter unattended. The tagging and PDF phases peak at different times, so RAM never doubles up. Small OOM risk. |
| **Safe / recommended** | 2 GB RAM (+2 GB swap) | ~$12/mo | Comfortable headroom; runs without thrashing. |
| Generous | 4 GB RAM | ~$24/mo | Fast, no swap needed. Overkill for weekly. |

Disk: venv ~0.8 GB + model ~0.6 GB + image cache ~0.5 GB (plateaus as products repeat).
The standard 25 GB SSD is plenty.

If staying on 1 GB, add swap before anything else:
```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # persist across reboots
```

---

## 1. Provision

- Create an Ubuntu droplet (the size you chose above). **SSH key auth**, not password.
- DigitalOcean's card check sometimes rejects Indian cards → fall back to **Hetzner**
  (€4/mo, 2 GB tiers) or **Vultr** (accepts UPI). Same steps apply.

## 2. Install runtime + clone

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
git clone https://github.com/yuvrajmehta21/Fashion-Trend-Analysis.git
cd Fashion-Trend-Analysis
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install --with-deps chromium   # Chromium for the PDF
```

## 3. Transfer secrets out-of-band (never via git)

From your **laptop**, copy your filled-in `.env` up:
```bash
scp .env root@<DROPLET_IP>:/root/Fashion-Trend-Analysis/.env
```
`.env` must contain: `APIFY_TOKEN`, and for email
`REPORT_EMAILS=yuvrajmehta05@gmail.com`, `EMAIL_FROM_ADDRESS`,
`EMAIL_FROM_APP_PASSWORD` (a Gmail **App Password**), and `REPORT_SHARING_ENABLED=true`.
Then lock it down on the droplet: `chmod 600 .env`.

## 4. Smoke-test once by hand before trusting cron

```bash
SOCIAL=1 bash run_tracker.sh      # full run incl. Instagram + email
tail -n 40 .tmp/tracker_$(date +%F).log
```
Confirm: catalog scraped, FashionCLIP tagged (watch RAM with `htop`), PDF built, and the
email arrived. Fix anything before scheduling.

## 5. Schedule with cron (+ flock so runs never overlap)

`crontab -e`, then add (example: **every Monday 06:00 server time**):
```
0 6 * * 1 cd /root/Fashion-Trend-Analysis && /usr/bin/flock -n .tmp/run.lock env SOCIAL=1 bash run_tracker.sh >> .tmp/cron.log 2>&1
```
- Set the droplet timezone first if you want a specific local time:
  `sudo timedatectl set-timezone Asia/Kolkata`.
- `flock -n` skips a run if the previous one is still going (a swap-heavy run can be long).
- Drop `SOCIAL=1` to run catalog-only (no Apify spend) on some weeks.

## 6. Operate

- **Code change:** push from laptop → `git pull` on the droplet. Next cron tick uses it.
- **Rotate a secret / token:** re-`scp` the `.env`. No restart needed.
- **Pause:** `crontab -r` (removes schedule). Restore by re-adding the line.
- **Watch a run:** `tail -f .tmp/cron.log`.

## Costs to expect
- Droplet: ~$6–12/mo depending on size chosen above.
- Apify (Instagram): ~$2.86/mo at the current source list — inside the $5 free credit.
- Everything else (FashionCLIP, Google Trends, Shopify) is free.
