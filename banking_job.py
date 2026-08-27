#!/usr/bin/env python3
"""
Bewiched Weekly Banking -> Bookkeeper email.

Data entry: stores submit the "Weekly Banking" Google Form (Store / Day / Amount)
twice a week. Responses land in the "Weekly Banking" spreadsheet on the tab
"Form Responses 1" (Timestamp | Store | Day | Amount (£)). This job reads that tab
as the service account, compiles each equity store's Monday + Friday amount for the
CURRENT week (latest submission wins), flags any store still missing a figure, and
emails the recipient.

Run modes:
  python banking_job.py            # DRY RUN — prints the email, sends nothing
  python banking_job.py --send     # sends via Gmail SMTP (needs GMAIL_APP_PASSWORD)

Recipient:  env BANKING_TO (defaults to matt@bewiched.co.uk so a first/test send is
            SAFE — point it at Joanne only once Matt approves).
Auth read:  env GCP_SA_JSON (the service-account JSON, same GitHub secret the
            dashboards pipeline already uses); or GOOGLE_APPLICATION_CREDENTIALS file.
Auth send:  env GMAIL_APP_PASSWORD (16-char Gmail App Password) as SMTP_USER/MAIL_FROM.
"""
import os, sys, json, re, datetime as dt, smtplib
from email.mime.text import MIMEText

SHEET_ID  = "1f_bWorTvRTN_LaijRXzD385c_8Y97g_lZNcOF_s1QhE"
RESP_TAB  = "Form Responses 1"
TO        = os.environ.get("BANKING_TO", "matt@bewiched.co.uk")   # default = safe/test
MAIL_FROM = os.environ.get("MAIL_FROM", "matt@bewiched.co.uk")
SMTP_USER = os.environ.get("SMTP_USER", "matt@bewiched.co.uk")    # Gmail login (App-Pwd owner)

EQUITY = [
    "Billing Drive Thru","Burton Latimer","Corby","Higham Ferrers","Kettering",
    "Leamington Parade","Lower Heathcote","Market Harborough","Northampton",
    "Northampton Drive-Thru","Olney","Peterborough Bridge Street",
    "Peterborough Fletton Quays","Rothwell","Rugby","Rushden Lakes",
    "Wellingborough","Wellingborough Train Station",
]

def monday_of(d): return d - dt.timedelta(days=d.weekday())
def parse_amount(s):
    # Robust to messy Form entries: "£1140 .38" (stray space), "913.30 (note...)",
    # thousands separators. Strip currency/commas/ALL spaces, take the leading number.
    if s is None: return None
    s = str(s).replace("£","").replace(",","").replace(" ","")
    m = re.match(r"-?\d+\.?\d*", s)
    return float(m.group()) if (m and m.group() not in ("", "-", ".")) else None
def parse_ts(s):
    # Google Form timestamps are US M/D/YYYY (e.g. 7/31/2026, 8/3/2026) — try month-first
    # BEFORE day-first so ambiguous dates like 8/3 read as 3 Aug, not 8 Mar.
    for fmt in ("%m/%d/%Y %H:%M:%S","%m/%d/%Y %H:%M","%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S","%d/%m/%Y %H:%M"):
        try: return dt.datetime.strptime(str(s).strip(), fmt)
        except ValueError: continue
    return None

def _credentials():
    from google.oauth2 import service_account
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    if os.environ.get("GCP_SA_JSON"):                       # same secret as the pipeline
        info = json.loads(os.environ["GCP_SA_JSON"])
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    return service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"], scopes=scopes)

def read_responses():
    # Retry the Sheets read on transient outages (HTTP 5xx / timeouts): the Google Sheets API
    # intermittently returns 503 "service currently unavailable", which used to kill the whole
    # send (e.g. the Tue 25 Aug 2026 run). 3 attempts, ~25s backoff; 4xx (real errors) fail fast.
    import time, socket, ssl
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    svc = build("sheets", "v4", credentials=_credentials(), cache_discovery=False)
    rng = f"'{RESP_TAB}'!A2:D100000"
    req = svc.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=rng)
    last = None
    for attempt in range(3):
        try:
            vals = req.execute().get("values", [])
            return [tuple((r + ["","","",""])[:4]) for r in vals]
        except HttpError as e:
            code = getattr(getattr(e, "resp", None), "status", None)
            if code is not None and int(code) < 500:
                raise                                   # 4xx = genuine error, do not retry
            last = e
        except (TimeoutError, socket.timeout, ssl.SSLError, ConnectionError, OSError) as e:
            last = e
        if attempt < 2:
            print("[retry] Sheets read failed (%s) - attempt %d/3, waiting 25s" % (type(last).__name__, attempt + 1))
            time.sleep(25)
    raise last

def compile_week(rows, today=None):
    today = today or dt.date.today()
    # WEEKEND BANKING CYCLE: a FRIDAY paired with the FOLLOWING MONDAY's deposit
    # (Friday takings + the Monday deposit of that weekend). Reference = the most recent
    # completed Monday: this week's Monday once it has passed; if today IS Monday the
    # deposit may not be in yet, so use the previous Monday. The Friday is 3 days before
    # that Monday. Run this on a TUESDAY so both figures are in (see banking.yml cron).
    mon = today - dt.timedelta(days=today.weekday())          # this week's Monday
    if today.weekday() == 0:                                  # today IS Monday -> not in yet
        mon -= dt.timedelta(days=7)
    fri = mon - dt.timedelta(days=3)                          # Friday of that weekend
    win_hi = mon + dt.timedelta(days=4)                       # tolerate late Monday entries (Fri..Thu)
    data = {s: {"mon": None, "fri": None, "_t": {"mon": None, "fri": None}} for s in EQUITY}
    for ts, store, day, amt in rows:
        store = str(store).strip()
        if store not in data: continue
        t = parse_ts(ts)
        if t is None: continue
        d = t.date()
        key = "mon" if str(day).lower().startswith("mon") else "fri" if str(day).lower().startswith("fri") else None
        if key is None: continue
        if key == "fri" and not (fri <= d < mon): continue    # Friday figure window [fri, mon)
        if key == "mon" and not (mon <= d < win_hi): continue # Monday figure window [mon, Thu)
        prev = data[store]["_t"][key]
        if prev is None or t >= prev:
            data[store][key] = parse_amount(amt); data[store]["_t"][key] = t
    return fri, mon, data

def build_email(fri, mon, data):
    def money(x): return "—" if x is None else f"£{x:,.2f}"
    sun = fri + dt.timedelta(days=2)                          # Sunday week-ending label (e.g. w/e 02 Aug)
    missing = [s for s,v in data.items() if v["mon"] is None or v["fri"] is None]
    tot_fri = sum(v["fri"] or 0 for v in data.values())
    tot_mon = sum(v["mon"] or 0 for v in data.values())
    subj = f"Bewiched Weekly Banking — w/e {sun:%d %b %Y}"
    lines = [f"{'Store':30} {'Fri '+fri.strftime('%d %b'):>14} {'Mon '+mon.strftime('%d %b'):>14}", "-"*60]
    for s in EQUITY:
        v = data[s]; lines.append(f"{s:30} {money(v['fri']):>14} {money(v['mon']):>14}")
    lines += ["-"*60, f"{'TOTAL':30} {money(tot_fri):>14} {money(tot_mon):>14}"]
    body = ["Hi Joanne,", "",
            f"Please find the weekly banking figures for w/e {sun:%A %d %B %Y} "
            f"(Friday {fri:%d %b} takings + the Monday {mon:%d %b} deposit).",
            "", "\n".join(lines), ""]
    if missing:
        body += ["Awaiting a figure from: " + ", ".join(missing) + ".",
                 "(These stores had not submitted the Form at the time of sending.)", ""]
    body += ["Many thanks,", "Bewiched (automated weekly banking)"]
    return subj, "\n".join(body), missing

def send_email(subj, body):
    pw = os.environ["GMAIL_APP_PASSWORD"]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subj; msg["From"] = MAIL_FROM; msg["To"] = TO
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls(); s.login(SMTP_USER, pw); s.send_message(msg)

def main():
    send = "--send" in sys.argv
    rows = read_responses()
    fri, mon, data = compile_week(rows)
    subj, body, missing = build_email(fri, mon, data)
    print("TO:", TO); print("FROM:", MAIL_FROM); print("SUBJECT:", subj); print(); print(body)
    if send:
        send_email(subj, body); print("\n[sent] email delivered to", TO)
    else:
        print("\n[dry-run] no email sent. Pass --send to deliver.")
    if missing: print("[warn] %d store(s) missing a figure." % len(missing))

if __name__ == "__main__":
    main()
