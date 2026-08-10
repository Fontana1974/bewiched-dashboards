#!/usr/bin/env python3
"""One-off inspection: HRP 'Accident Forms' tab date parsing. Runs in GitHub Actions with the
dashboards SA. Prints ONLY date/store/incident/injury + parse result (no name/contact/address)."""
import os, json, re, datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build as gbuild

EPOCH = datetime.date(1899, 12, 30)
def serial_to_date(s):
    try: return EPOCH + datetime.timedelta(days=int(float(s)))
    except Exception: return None
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])}
def parse_any_date(v):
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

print("===ACCIDENT_INSPECT===")
uf = read("'Accident Forms'!A1:K400", True)     # what run_weekly currently reads (unformatted)
ff = read("'Accident Forms'!A1:K400", False)    # formatted (human-readable, what's on screen)
print("rows unformatted=%d formatted=%d" % (len(uf), len(ff)))
n = max(len(uf), len(ff))
out = []
for i in range(1, n):
    ru = uf[i] if i < len(uf) else []
    rf = ff[i] if i < len(ff) else []
    def gu(r,j): return r[j] if len(r)>j and r[j] not in (None,"") else ""
    d_uf = gu(ru,0); d_ff = gu(rf,0)
    store = gu(rf,5) or gu(ru,5)
    inc = (gu(rf,6) or gu(ru,6))[:40]
    inj = (gu(rf,7) or gu(ru,7))[:30]
    p = parse_any_date(d_uf if d_uf!="" else d_ff)
    out.append({"row": i+1, "date_uf_repr": repr(d_uf), "date_uf_type": type(d_uf).__name__,
                "date_ff": str(d_ff), "store": str(store)[:24], "inc": inc, "inj": inj,
                "parsed": p.isoformat() if p else None})
print(json.dumps(out, ensure_ascii=False))
print("===CUR_END_REF===")
today = datetime.date.today()
cur_end = today - datetime.timedelta(days=(today.weekday()+1)%7)
print(json.dumps({"today": today.isoformat(), "cur_end": cur_end.isoformat(),
                  "cutoff_180": (cur_end - datetime.timedelta(days=180)).isoformat()}))
print("===END===")
