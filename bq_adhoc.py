#!/usr/bin/env python3
"""ONE-OFF (service account, spreadsheets WRITE): add 6 weekly tabs to the Weekly SMT Visit Diary
by duplicating the '10th Aug' template, clearing coach+Slack cells, setting the Date column, and
APPENDING each new tab (plus the two orphaned tabs 03rd Aug & 10th Aug) to the Master!A2 array
formula in chronological order. Idempotent. No Apps Script, nothing scheduled."""
import os, json, re
from google.oauth2 import service_account
from googleapiclient.discovery import build as gbuild
SMT="1IGL3sLWSI7k1vuXEMFBWplgk3uS4tTUU1-MtGYDk-bQ"
TEMPLATE="10th Aug"
NEW=[("17th Aug","2026-08-17"),("24th Aug","2026-08-24"),("31st Aug","2026-08-31"),
     ("7th Sep","2026-09-07"),("14th Sep","2026-09-14"),("21st Sep","2026-09-21")]
WIRE_ORDER=["03rd Aug","10th Aug"]+[n for n,_ in NEW]   # append these to Master, in this order
creds=service_account.Credentials.from_service_account_info(
    json.loads(os.environ["GCP_SA_JSON"]), scopes=["https://www.googleapis.com/auth/spreadsheets"])
ss=gbuild("sheets","v4",credentials=creds,cache_discovery=False).spreadsheets()
print("BEGIN_SMT_WRITE")

meta=ss.get(spreadsheetId=SMT, fields="sheets.properties(sheetId,title,index)").execute()
props=[s["properties"] for s in meta["sheets"]]
titles=[p["title"] for p in props]
tmpl=next(p for p in props if p["title"]==TEMPLATE)
master=next(p for p in props if p["title"].strip().lower()=="master")
print("template '%s' gid=%s | Master index=%d | tabs=%d" % (TEMPLATE, tmpl["sheetId"], master["index"], len(titles)))

# store row count from template col A
colA=ss.values().get(spreadsheetId=SMT, range="'%s'!A2:A"%TEMPLATE).execute().get("values",[])
n=0
for r in colA:
    if r and str(r[0]).strip(): n+=1
    else: break
last=1+n
print("store rows: %d (rows 2..%d)"%(n,last))

# 1) duplicate for any missing new tab
midx=master["index"]
created=[]
for name,_ in NEW:
    if name in titles:
        print("  exists, skip: %s"%name); continue
    ss.batchUpdate(spreadsheetId=SMT, body={"requests":[{"duplicateSheet":{
        "sourceSheetId":tmpl["sheetId"],"insertSheetIndex":midx,"newSheetName":name}}]}).execute()
    midx+=1; created.append(name); print("  created tab: %s"%name)

# 2) clear coach(B-I)+Slack(J) and set Date(M) for the new tabs
for name,date in NEW:
    ss.values().batchClear(spreadsheetId=SMT, body={"ranges":["'%s'!B2:J%d"%(name,last)]}).execute()
    ss.values().update(spreadsheetId=SMT, range="'%s'!M2:M%d"%(name,last),
        valueInputOption="USER_ENTERED",
        body={"values":[['="%s"'%date] for _ in range(n)]}).execute()
    print("  cleared B2:J%d + Date=%s on %s"%(last,date,name))

# 3) append elements to Master!A2 (Style B), only those not already referenced
cur=ss.values().get(spreadsheetId=SMT, range="Master!A2", valueRenderOption="FORMULA").execute().get("values",[[""]])
cur=cur[0][0] if (cur and cur[0]) else ""
def elem(t): return "FILTER('%s'!A2:M1000, LEN('%s'!A2:A1000))"%(t,t)
refs=set(re.findall(r"'([^']+)'!", cur))
add=[t for t in WIRE_ORDER if t not in refs]
if add:
    body=cur.rstrip()
    assert body.endswith("}"), "Master formula does not end with }"
    body=body[:-1] + ";" + ";".join(elem(t) for t in add) + "}"
    ss.values().update(spreadsheetId=SMT, range="Master!A2",
        valueInputOption="USER_ENTERED", body={"values":[[body]]}).execute()
    print("MASTER: appended %d elements: %s"%(len(add), ", ".join(add)))
else:
    print("MASTER: all target tabs already referenced (no change)")

# 4) verify a test entry on 17th Aug rolls up, then remove it
TESTTAB="17th Aug"; TESTVAL="ROLLUP_TEST_17AUG_DELETEME"
ss.values().update(spreadsheetId=SMT, range="'%s'!J2"%TESTTAB, valueInputOption="RAW",
    body={"values":[[TESTVAL]]}).execute()
mvals=ss.values().get(spreadsheetId=SMT, range="Master!A2:M4000").execute().get("values",[])
found=any(TESTVAL in (str(c) for c in row) for row in mvals)
print("VERIFY: test entry on '%s'!J2 rolled up into Master? %s"%(TESTTAB, found))
ss.values().batchClear(spreadsheetId=SMT, body={"ranges":["'%s'!J2"%TESTTAB]}).execute()
print("VERIFY: test entry removed (tab left clean)")

# final tab list + master ref count
meta2=ss.get(spreadsheetId=SMT, fields="sheets.properties(title,index)").execute()
final=[s["properties"]["title"] for s in meta2["sheets"]]
print("FINAL_TABS(%d): %s"%(len(final), " | ".join(final)))
cur2=ss.values().get(spreadsheetId=SMT, range="Master!A2", valueRenderOption="FORMULA").execute().get("values",[[""]])[0][0]
refs2=[]
for r in re.findall(r"'([^']+)'!", cur2):
    if r not in refs2: refs2.append(r)
print("MASTER_NOW_REFERENCES %d tabs; last 10: %s"%(len(refs2), " , ".join(refs2[-10:])))
print("END_SMT_WRITE")
