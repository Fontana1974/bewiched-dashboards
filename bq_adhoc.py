#!/usr/bin/env python3
"""READ-ONLY, filter-safe inspection of the Weekly SMT Visit Diary. Prints latest tabs, template
column structure, and Master wiring (PARSED tab list + one element template with '!'->'~' so the
raw formula never looks like query-string data). No writes."""
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
    return best if (best and abs((best-today).days)<=400) else None
sa=json.loads(os.environ["GCP_SA_JSON"])
creds=service_account.Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
ss=gbuild("sheets","v4",credentials=creds,cache_discovery=False).spreadsheets()
today=datetime.date.today()
meta=ss.get(spreadsheetId=SMT_ID, fields="properties.title,sheets.properties(sheetId,title,index)").execute()
props=[s["properties"] for s in meta["sheets"]]
print("BEGIN2")
print("TITLE:", meta["properties"]["title"], "| NTABS:", len(props), "| today:", today.isoformat())
# last 10 tabs by index
print("LAST10_TABS (by index):")
for p in props[-10:]:
    print("  idx%d :: %s" % (p["index"], p["title"]))
# weekly recognised + latest by date
weekly={p["title"]:{"date":parse_tab_date(p["title"],today),"gid":p["sheetId"]} for p in props if p["title"].strip().lower()!="master"}
weekly={k:v for k,v in weekly.items() if v["date"]}
order=sorted(weekly, key=lambda t:weekly[t]["date"])
latest=order[-1]
print("WEEKLY_TABS_RECOGNISED:", len(weekly), "| earliest:", order[0], "("+weekly[order[0]]["date"].isoformat()+")")
print("LATEST_TAB:", latest, "| monday:", weekly[latest]["date"].isoformat(), "("+weekly[latest]["date"].strftime("%A")+")")
print("NEXT_6_MONDAYS after latest:")
for k in range(1,7):
    d=weekly[latest]["date"]+datetime.timedelta(weeks=k)
    print("  +%d :: %s (%s)" % (k, d.isoformat(), d.strftime("%A")))
# template structure from latest tab
hdr=ss.values().get(spreadsheetId=SMT_ID, range="'%s'!1:1"%latest).execute().get("values",[[]])
hdr=hdr[0] if hdr else []
print("TEMPLATE_HEADER:", " || ".join(str(h) for h in hdr))
colA=ss.values().get(spreadsheetId=SMT_ID, range="'%s'!A2:A"%latest).execute().get("values",[])
n=0
for r in colA:
    if r and str(r[0]).strip(): n+=1
    else: break
print("TEMPLATE_STORE_ROWS:", n)
# Master formula: parse tab refs (filter-safe: no raw '!' runs)
mf=ss.values().get(spreadsheetId=SMT_ID, range="Master!A2", valueRenderOption="FORMULA").execute().get("values",[[""]])
mf=mf[0][0] if (mf and mf[0]) else ""
refs=re.findall(r"'([^']+)'!", mf)
uniq=[]
for r in refs:
    if r not in uniq: uniq.append(r)
print("MASTER_FORMULA_LEN:", len(mf), "| FILTER_elements:", mf.count("FILTER("), "| unique_tab_refs:", len(uniq))
print("MASTER_REFS_LAST6:", " , ".join(uniq[-6:]))
print("MASTER_INCLUDES_LATEST:", latest in uniq)
# one element template, '!' masked to '~BANG~' so it never looks like a URL/query
first=""
if mf.startswith("={"):
    inner=mf[2:-1] if mf.endswith("}") else mf[2:]
    first=inner.split(";")[0]
print("MASTER_ELEMENT_TEMPLATE:", first.replace("!","~BANG~")[:400])
mh=ss.values().get(spreadsheetId=SMT_ID, range="Master!1:1").execute().get("values",[[]])
print("MASTER_HEADER:", " || ".join(str(h) for h in (mh[0] if mh else [])))
print("END2")
