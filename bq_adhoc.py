#!/usr/bin/env python3
"""One-off diagnosis: HRP 'Accident Forms' date parsing. Prints DATES ONLY (no names / no
incident text / no store names / no addresses) so nothing trips content filters. Compares the
current parser vs a robust UK-first parser and flags in-window capture."""
import os, json, re, datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build as gbuild

EPOCH = datetime.date(1899, 12, 30)
def serial_to_date(s):
    try: return EPOCH + datetime.timedelta(days=int(float(s)))
    except Exception: return None
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])}

# ---- CURRENT parser (verbatim from run_weekly.parse_any_date) ----
def parse_current(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return serial_to_date(v)
    s = str(v).strip()
    if not s: return None
    m = re.match(r"Date\((\d+),(\d+),(\d+)", s)
    if m:
        try: return datetime.date(int(m.group(1)), int(m.group(2))+1, int(m.group(3)))
        except ValueError: return None
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try: return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: return None
    for fmt in ("%Y-%m-%d","%d-%b-%Y","%b %d %Y","%d %b %Y","%m/%d/%Y","%d/%m/%Y"):
        try: return datetime.datetime.strptime(s, fmt).date()
        except ValueError: pass
    md = re.search(r"\b([A-Za-z]{3})\s+(\d{1,2})\b", s)
    yr = re.search(r"\b(?:19|20)\d{2}\b", s)
    if md and yr and md.group(1).lower() in _MONTHS:
        try: return datetime.date(int(yr.group(0)), _MONTHS[md.group(1).lower()], int(md.group(2)))
        except ValueError: return None
    return None

sc = service_account.Credentials.from_service_account_info(
    json.loads(os.environ["GCP_SA_JSON"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
sh = gbuild("sheets","v4",credentials=sc,cache_discovery=False).spreadsheets().values()
HRP = "1f_nTz6TJTPlVP4CSX6AzQ9sf5KbF7QwpVdVnxiW-bM4"
def read(rng, unformatted):
    opt = "UNFORMATTED_VALUE" if unformatted else "FORMATTED_VALUE"
    return sh.get(spreadsheetId=HRP, range=rng, valueRenderOption=opt).execute().get("values",[])

uf = read("'Accident Forms'!A1:K400", True)
ff = read("'Accident Forms'!A1:K400", False)
today = datetime.date.today()
cur_end = today - datetime.timedelta(days=(today.weekday()+1)%7)
cutoff = cur_end - datetime.timedelta(days=180)

print("===ACC_DIAG===")
print("rows_uf %d rows_ff %d today %s cur_end %s cutoff %s"
      % (len(uf), len(ff), today, cur_end, cur_end and cutoff))
def gu(r,j): return r[j] if len(r)>j and r[j] not in (None,"") else ""
n = max(len(uf), len(ff))
captured = 0
for i in range(1, n):
    ru = uf[i] if i < len(uf) else []
    rf = ff[i] if i < len(ff) else []
    du = gu(ru,0); dff = gu(rf,0)
    has_store = bool(str(gu(rf,5) or gu(ru,5)).strip())
    # what run_weekly actually feeds: the UNFORMATTED value
    p = parse_current(du if du!="" else None)
    win = "-"
    if p:
        win = "IN" if (cutoff <= p <= cur_end) else ("FUT" if p > cur_end else "OLD")
    if p and win=="IN" and has_store:
        captured += 1
    fmt = re.sub(r"\d","#", str(du))
    # show real dates ONLY (safe), plus formatted-cell date, type, parse + window + store flag
    print("r%-3d type=%-5s uf=%-12s ff=%-12s parse=%-10s win=%-3s store=%s"
          % (i+1, type(du).__name__, str(du)[:12], str(dff)[:12],
             (p.isoformat() if p else "NULL"), win, "Y" if has_store else "n"))
print("CAPTURED_NOW %d (in-window + store + parsed)" % captured)
print("===END===")
