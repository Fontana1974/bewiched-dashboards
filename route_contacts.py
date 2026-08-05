#!/usr/bin/env python3
"""
Bewiched daily customer-contact routing — cloud (GitHub Actions) version.

Mirrors the Cowork desktop task `daily-customer-contact-routing` but runs headless
with no MCP connectors: raw Wix REST + Google Sheets API + SMTP + Anthropic API.

Flow each run:
  1. Read last 10 days of website submissions from Wix CMS (salesLead022).
  2. Read already-logged Wix ids from the Contacts Log sheet (dedupe).
  3. For each NEW item, ask Claude to classify -> route + summary.
  4. Auto-reply to app-availability queries (from contact@), else forward to the
     right internal person. Log every new item to the sheet (columns A-K).

Fail-safe: any hard failure emails matt@bewiched.co.uk and exits non-zero.
Because dedupe is by Wix id over a rolling 10-day window, a failed/skipped run is
safe — the next successful run catches up automatically.

Required env (set as GitHub Actions secrets):
  WIX_API_KEY, WIX_SITE_ID, WIX_ACCOUNT_ID
  GOOGLE_SA_JSON        (service-account JSON, as a string; sheet shared with its email)
  SMTP_USER, SMTP_PASS  (contact@bewiched.co.uk + Google app password)
  ANTHROPIC_API_KEY
Optional env:
  MODEL (default claude-sonnet-5), DRY_RUN ("1" = classify+log to stdout, send nothing),
  ALERT_TO (default matt@bewiched.co.uk)
"""

import os
import sys
import json
import ssl
import smtplib
import datetime as dt
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo

import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest

# ---------------------------------------------------------------- config -----
SHEET_ID = "17j3a6jBdYv82xfuROHl6nra3BuAzmMj1rJ9mEBO0aPs"
SHEET_TAB = "Contacts Log"
WIX_COLLECTION = "salesLead022"
WINDOW_DAYS = 10
UK = ZoneInfo("Europe/London")
CONTACT_FROM = "contact@bewiched.co.uk"
CONTACT_FROM_NAME = "Bewiched Coffee"
ALERT_TO = os.environ.get("ALERT_TO", "matt@bewiched.co.uk")
MODEL = os.environ.get("MODEL", "claude-sonnet-5")
DRY_RUN = os.environ.get("DRY_RUN") == "1"

# Internal recipients. NOTE: Jon's address is inferred from the naming pattern of
# the other coaches (rich./claire./kel. .bewiched@gmail.com) — CONFIRM before go-live.
RECIPIENTS = {
    "Rich":   "rich.bewiched@gmail.com",
    "Jon":    "jon.bewiched@gmail.com",       # <-- CONFIRM
    "Ian":    "Ian.Hawkswood@heartofengland-coop.co.uk",
    "Claire": "claire.bewiched@gmail.com",
    "Kel":    "Kel.bewiched@gmail.com",
    "Matt":   "matt@bewiched.co.uk",
}

# Routing rules handed to Claude verbatim. Keep in sync with the desktop SKILL.
ROUTING_RULES = """
You are routing a single Bewiched Coffee website "Customer Contact" submission.

CLASSIFY into exactly one action:
- APP AVAILABILITY query (can't find/download the Bewiched app, app missing from
  Play Store/App Store, "is there still an app", worried about losing points because
  the app is gone) -> action "auto_reply". Do NOT forward, UNLESS they ALSO report a
  specific points discrepancy needing correction -> then action "forward" to CLAIRE and
  set also_note "app+points".
- Barista course booking/refund/enquiry -> forward RICH, category "Course".
- HR & recruitment: employment references/letters, background/DBS checks,
  recruitment/job enquiries -> forward KEL, category "HR/Reference" or "Recruitment".
- Other company-wide: brand/marketing, offers/merch/vouchers/gift/sponsorship,
  PR/press, university research, loyalty-points corrections, general -> forward CLAIRE.
- Property/new-site/landlord/agent, acquisition/investment, green-coffee/wholesale
  supplier/sourcing approaches -> forward MATT.
- Store-specific service issue/complaint/lost property/feedback naming a store ->
  forward that store's Area Coach, category "Store - {name}".
- Anything else -> forward MATT (catch-all); explain why in the summary.

Store -> Area Coach:
  RICH: Train Station, Northampton Drive Thru, Northampton Grosvenor, Market Street
        (Wellingborough Market St), Rugby, Market Harborough, Lower Heathcote/Warwick,
        Leamington Parade, Billing.
  JON:  Higham, Kettering, Fletton, Peterborough, Rothwell, Burton, Corby, Olney, Lakes.
  IAN:  Balsall Common, Glenvale Drive Thru, Attleborough, Nuneaton (=Attleborough),
        Leamington Retail.
  "Nuneaton"->IAN, "Billing"->RICH, unknown store->MATT (say why).

Return STRICT JSON only, no prose, with keys:
  action           : "auto_reply" | "forward"
  route_to         : one of "Rich","Jon","Ian","Claire","Kel","Matt","Auto"
  category         : short label for the log (e.g. "Recruitment", "Store - Olney",
                     "App/Tech", "Sponsorship/Marketing", "Other - Police/CCTV")
  forward_topic    : 3-6 word topic for the email subject (forward only, else "")
  forward_summary  : 1-3 tight sentences describing what the customer wants (forward only)
  forward_action   : one short sentence telling the recipient what to do (forward only)
  log_message      : one-line summary for the sheet
  reply_detail     : "" for forwards; for auto_reply a short note of the app message sent
  also_note        : "" normally; "app+points" for the app+points-correction edge case

Be careful with edge cases: an app grumble embedded inside a store complaint is still a
store complaint (route to the Area Coach, mention the app point in the summary). Flag an
obviously mistyped email address in forward_summary if you spot one.
""".strip()

AUTO_REPLY_SUBJECT = "Re: your message about the Bewiched app"
AUTO_REPLY_BODY = (
    "Hi {first},\n\n"
    "Thanks for getting in touch about the Bewiched app.\n\n"
    "We're rebuilding it at the moment — the new app goes into testing this month "
    "and we're aiming to launch in early autumn. Please don't worry: your loyalty points "
    "are safe and nothing will be lost. In the meantime, just give your registered email "
    "to the team at the till and they'll add your points as usual.\n\n"
    "We'll let you know as soon as the new app is live.\n\n"
    "Thanks for your patience,\nThe Bewiched Team"
)
AUTO_REPLY_DETAIL_DEFAULT = (
    "Sent app-rebuild message: new app in testing this month, launching early autumn; "
    "points safe; give email at till meanwhile"
)


# ------------------------------------------------------------- utilities -----
def fail_alert(step, err):
    """Email Matt that the run failed, then exit non-zero. Never raise past here."""
    body = (
        f"Morning Matt,\n\n"
        f"Today's customer-contact routing (cloud) failed at: {step}.\n"
        f"Error: {err}\n\n"
        f"No submissions were processed or logged this run. Likely fix depends on the "
        f"step (Wix key, Google service account, SMTP app password or Anthropic key).\n"
        f"Nothing is lost — the task reads a rolling {WINDOW_DAYS}-day window and dedupes "
        f"by Wix id, so the next successful run catches up automatically.\n\n"
        f"Bewiched routing bot"
    )
    try:
        _smtp_send(
            to=[ALERT_TO],
            subject="[Customer contacts] ⚠️ Cloud task failed — action needed",
            body=body,
            from_name="Bewiched routing bot",
        )
    except Exception as e:  # SMTP itself is down — nothing more we can do
        print(f"FAILED and could not send alert: {step}: {err} / alert error: {e}",
              file=sys.stderr)
    print(f"FAIL @ {step}: {err}", file=sys.stderr)
    sys.exit(1)


def _smtp_send(to, subject, body, from_name=CONTACT_FROM_NAME):
    if DRY_RUN:
        print(f"[DRY_RUN] would email {to} | {subject}\n{body}\n---")
        return
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, CONTACT_FROM))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.send_message(msg)


# ------------------------------------------------------------------ Wix -----
def wix_recent():
    headers = {
        "Authorization": os.environ["WIX_API_KEY"],
        "wix-site-id": os.environ["WIX_SITE_ID"],
        "wix-account-id": os.environ["WIX_ACCOUNT_ID"],
        "Content-Type": "application/json",
    }
    body = {
        "dataCollectionId": WIX_COLLECTION,
        "query": {"sort": [{"fieldName": "_createdDate", "order": "DESC"}],
                  "paging": {"limit": 100}},
    }
    r = requests.post("https://www.wixapis.com/wix-data/v2/items/query",
                      headers=headers, json=body, timeout=30)
    r.raise_for_status()
    raw = r.json().get("dataItems") or r.json().get("items") or []
    items = [x.get("data", x) for x in raw]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=WINDOW_DAYS)
    out = []
    for it in items:
        cd = it.get("_createdDate")
        cd = cd.get("$date") if isinstance(cd, dict) else cd
        if not cd:
            continue
        ts = dt.datetime.fromisoformat(cd.replace("Z", "+00:00"))
        if ts >= cutoff:
            out.append(it)
    return out


# --------------------------------------------------------- Google Sheets -----
def google_token():
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    creds.refresh(GoogleAuthRequest())
    return creds.token


def sheets_processed_ids(token):
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
           f"/values/{requests.utils.quote(SHEET_TAB)}!I2:I2000")
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    vals = r.json().get("values", [])
    return {row[0].strip() for row in vals if row and row[0].strip()}


def sheets_append(token, rows):
    if DRY_RUN:
        print(f"[DRY_RUN] would append {len(rows)} rows:")
        for row in rows:
            print("   ", row)
        return
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
           f"/values/{requests.utils.quote(SHEET_TAB)}!A1:append"
           f"?valueInputOption=RAW")
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                      json={"values": rows}, timeout=30)
    r.raise_for_status()


# -------------------------------------------------------------- Anthropic ----
def classify(item):
    msg = item.get("paragraphField", "") or ""
    topic = item.get("copyOfLastName", "") or ""
    name = f"{item.get('firstName','')} {item.get('lastName','')}".strip()
    payload = {
        "model": MODEL,
        "max_tokens": 700,
        "system": ROUTING_RULES,
        "messages": [{
            "role": "user",
            "content": (f"Submission topic field: {topic}\n"
                        f"From: {name} <{item.get('email','')}> {item.get('phone','')}\n"
                        f"Message:\n{msg}\n\nReturn the JSON now."),
        }],
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"},
        json=payload, timeout=60)
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):text.rfind("}") + 1]
    return json.loads(text)


# ------------------------------------------------------------------ main -----
def build_forward_body(first, decision, item):
    name = f"{item.get('firstName','')} {item.get('lastName','')}".strip()
    return (
        f"Hi {first},\n\n"
        "This is a website customer contact for you to deal with — please reply to "
        "the customer directly.\n\n"
        f"{decision['forward_summary']}\n\n"
        f"Customer: {name}, {item.get('email','')}, {item.get('phone','')}\n"
        f"Action: {decision['forward_action']}\n\n"
        "When you reply, please CC contact@bewiched.co.uk so your reply is logged in "
        "the tracker."
    )


def main():
    for k in ("WIX_API_KEY", "WIX_SITE_ID", "WIX_ACCOUNT_ID", "GOOGLE_SA_JSON",
              "SMTP_USER", "SMTP_PASS", "ANTHROPIC_API_KEY"):
        if not os.environ.get(k):
            fail_alert("config", f"missing env var {k}")

    try:
        token = google_token()
    except Exception as e:
        fail_alert("google auth", e)
    try:
        processed = sheets_processed_ids(token)
    except Exception as e:
        fail_alert("sheet read (Step 2)", e)
    try:
        items = wix_recent()
    except Exception as e:
        fail_alert("wix read (Step 1)", e)

    new_items = [i for i in items if i.get("_id") not in processed]
    if not new_items:
        try:
            _smtp_send([ALERT_TO], "[Customer contacts] None new today",
                       "No new website submissions today.")
        except Exception:
            pass
        print("Nothing new.")
        return

    # oldest first so the log reads chronologically
    new_items.sort(key=lambda i: (i.get("_createdDate") or {}).get("$date", ""))

    rows, done = [], []
    for item in new_items:
        first_cust = item.get("firstName", "there") or "there"
        try:
            d = classify(item)
        except Exception as e:
            fail_alert(f"classify {item.get('_id')}", e)

        created = (item.get("_createdDate") or {}).get("$date")
        uk = dt.datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(UK)
        date_s, time_s = uk.strftime("%Y-%m-%d"), uk.strftime("%H:%M")
        name = f"{item.get('firstName','')} {item.get('lastName','')}".strip()

        if d["action"] == "auto_reply":
            try:
                _smtp_send([item["email"]], AUTO_REPLY_SUBJECT,
                           AUTO_REPLY_BODY.format(first=first_cust))
            except Exception as e:
                fail_alert(f"auto-reply {item.get('_id')}", e)
            routed_to, reply_status = "Auto (contact@)", "Auto-replied"
            reply_detail = d.get("reply_detail") or AUTO_REPLY_DETAIL_DEFAULT
            # app + points edge case: also forward to Claire
            if d.get("also_note") == "app+points":
                cbody = build_forward_body("Claire", d, item)
                try:
                    _smtp_send([RECIPIENTS["Claire"]],
                               f"Customer contact for you to action – "
                               f"{d['forward_topic']} ({name}, {uk.strftime('%d %b')})",
                               cbody)
                except Exception as e:
                    fail_alert(f"claire fwd {item.get('_id')}", e)
        else:
            route = d["route_to"]
            to = RECIPIENTS.get(route, RECIPIENTS["Matt"])
            body = build_forward_body(route, d, item)
            subject = (f"Customer contact for you to action – {d['forward_topic']} "
                       f"({name}, {uk.strftime('%d %b')})")
            try:
                _smtp_send([to], subject, body)
            except Exception as e:
                fail_alert(f"forward {item.get('_id')}", e)
            routed_to, reply_status, reply_detail = route, f"Forwarded to {route}", ""

        rows.append([date_s, time_s, name, item.get("email", ""),
                     item.get("phone", ""), d["category"], routed_to,
                     d["log_message"], item.get("_id", ""), reply_status, reply_detail])
        done.append(f"{name}: {routed_to}")

    try:
        sheets_append(token, rows)
    except Exception as e:
        fail_alert("sheet append (Step 5)", e)

    print(f"Processed {len(rows)} new item(s):")
    for line in done:
        print("  -", line)


if __name__ == "__main__":
    main()
