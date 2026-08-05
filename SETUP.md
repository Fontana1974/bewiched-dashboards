# Customer-contact routing — cloud (GitHub Actions) version

Runs the daily website-contact routing in the cloud on a fixed 08:00 UTC cron, so it
fires whether or not your Mac is on. Same logic as the desktop Cowork task: read Wix →
dedupe against the sheet → classify with Claude → auto-reply or forward → log to the
sheet. Dedupe is by Wix id over a rolling 10-day window, so a missed day self-heals.

## Files
```
route_contacts.py                              # the whole task
.github/workflows/customer-contact-routing.yml # the daily cron
```
Drop both into the **Fontana1974/bewiched-dashboards** repo (same repo as the dashboards),
keeping the `.github/workflows/` path.

## Secrets to add (repo → Settings → Secrets and variables → Actions → New secret)

| Secret | What it is / where to get it |
|---|---|
| `WIX_API_KEY` | Wix dashboard → Settings → **API Keys** → create a key with **Wix Data (read)** permission on the site. Paste the key value. |
| `WIX_SITE_ID` | `62053263-e9d4-4ba1-a80a-0c04596e5b77` (already known). |
| `WIX_ACCOUNT_ID` | Shown next to the API key when you create it (the account the site sits under). |
| `GOOGLE_SA_JSON` | A Google Cloud **service-account** JSON key, pasted whole. You may reuse the service account the dashboards already use for BigQuery — just enable the Sheets API for it and **share the Contacts Log sheet with the service-account email (Editor)**. |
| `SMTP_USER` | `contact@bewiched.co.uk` |
| `SMTP_PASS` | A Google **App Password** for the contact@ mailbox (Google Account → Security → 2-Step Verification → App passwords). Not the normal password. |
| `ANTHROPIC_API_KEY` | From console.anthropic.com → API keys. |

All outbound mail sends *from* `contact@` (both the customer auto-reply and the internal
forwards), so no send-as aliases are needed — a single app password on that mailbox covers
everything.

## Before go-live
1. **Confirm Jon's email.** The script uses `jon.bewiched@gmail.com` (inferred from the
   other coaches' pattern). If that's wrong, fix `RECIPIENTS["Jon"]` in `route_contacts.py`.
2. **Test safely.** In the workflow file, uncomment `DRY_RUN: "1"`, then run it manually
   (Actions tab → this workflow → *Run workflow*). It classifies and prints what it *would*
   send/log without sending or writing anything. Check the log output looks right, then
   re-comment `DRY_RUN`.
3. **Retire the desktop task** only once you've seen a clean live run — disable
   `daily-customer-contact-routing` in Cowork so you don't double-process. (Dedupe means
   even if both ran, nothing would be logged twice, but one source of truth is cleaner.)

## Notes / trade-offs vs the desktop task
- **Cron is UTC.** 08:00 UTC = 9am UK in summer, 8am in winter. Row timestamps are still
  stamped in true UK time (Europe/London) either way. If you want a hard 9am year-round,
  say so and I'll add a small "skip unless it's ~9am UK" guard.
- **Failure alerts** email matt@ (same as now); GitHub also emails you if the run itself
  errors out.
- **Classification** uses `claude-sonnet-5` by default (override with a `MODEL` env/secret).
  Cost is a few pennies a day at current volumes.
