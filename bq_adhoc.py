#!/usr/bin/env python3
"""READ-ONLY inspection of the Weekly SMT Visit Diary sheet: title, all tab names (in order),
the Master roll-up formula, the latest weekly tab + its structure. No writes. Plain text."""
import os, json, re, datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build as gbuild
SMT_ID="1IGL3sLWSI7k1vuXEMFBWplgk3uS4tTUU1-MtGYDk-bQ"
MONTHS=["January","February","March","April","May","June","July","August","September","October","November","December"]
def parse_tab_date(title, today):
    m=re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)", title.strip())
    if not m: return None
    day=int(m.group(1)); mon=m.group(2).lower()[:3]
    mi=next((i+1 for i,nm in enumerate(MONTHS) if nm.lower().startswith(mon)),None)
    if not mi: return None
    best=None
    for yr in (today.year-1,today.year,today.year+1):
        try: d=datetime.date(yr,mi,day)
        except ValueError: continue
        if best is None or abs((d-today).days)<abs((best-today).days): best=d
    return best if (best and abs((best-today).days)<=260) else None
sa=json.loads(os.environ["GCP_SA_JSON"])
creds=service_account.Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
ss=gbuild("sheets","v4",credentials=creds,cache_discovery=False).spreadsheets()
today=datetime.date.today()
meta=ss.get(spreadsheetId=SMT_ID, fields="properties.title,sheets.properties(sheetId,title,index)").execute()
print("BEGIN_SMT")
print("TITLE:", meta["properties"]["title"])
props=[s["properties"] for s in meta["sheets"]]
print("NTABS:", len(props))
for p in props:
    print("TAB idx%-3d | %s" % (p["index"], p["title"]))
# weekly tabs
weekly={}
for p in props:
    if p["title"].strip().lower()=="master": continue
    d=parse_tab_date(p["title"], today)
    if d: weekly[p["title"]]={"date":d,"gid":p["sheetId"]}
print("WEEKLY_RECOGNISED:", len(weekly))
if weekly:
    latest=max(weekly, key=lambda t:weekly[t]["date"])
    print("LATEST_TAB:", latest, "| monday:", weekly[latest]["date"].isoformat(), "| weekday:", weekly[latest]["date"].strftime("%A"))
    # last 6 weekly tabs by date
    order=sorted(weekly, key=lambda t:weekly[t]["date"])
    print("LAST8_BY_DATE:", " || ".join("%s(%s)"%(t,weekly[t]["date"].isoformat()) for t in order[-8:]))
    # latest tab header + structure
    hdr=ss.values().get(spreadsheetId=SMT_ID, range="'%s'!1:1"%latest).execute().get("values",[[]])
    hdr=hdr[0] if hdr else []
    print("HEADER:", " | ".join(str(h) for h in hdr))
    colA=ss.values().get(spreadsheetId=SMT_ID, range="'%s'!A2:A"%latest).execute().get("values",[])
    n=0
    for r in colA:
        if r and str(r[0]).strip(): n+=1
        else: break
    print("STORE_ROWS:", n)
# Master formula
mf=ss.values().get(spreadsheetId=SMT_ID, range="Master!A2", valueRenderOption="FORMULA").execute().get("values",[[""]])
mf=mf[0][0] if (mf and mf[0]) else ""
print("MASTER_A2_LEN:", len(mf))
print("MASTER_A2_HEAD:", mf[:600])
# Master header row
mh=ss.values().get(spreadsheetId=SMT_ID, range="Master!1:1").execute().get("values",[[]])
print("MASTER_HEADER:", " | ".join(str(h) for h in (mh[0] if mh else [])))
print("END_SMT")
