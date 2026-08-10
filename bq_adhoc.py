#!/usr/bin/env python3
"""Map ALL columns of the F1 'The Race' tab — HEADER NAMES ONLY (audit criteria; no data rows,
no PII). Also report, per numeric column, whether values look like 0-1 fractions or 0-100 scores
using column-wise min/max over audited rows (aggregates only, no row content printed)."""
import os, json
import run_weekly as R
sh = R._sheets_api(); SID = R.SID["f1"]
vals = sh.get(spreadsheetId=SID, range="'The Race'!A1:AH3000",
              valueRenderOption="UNFORMATTED_VALUE").execute().get("values",[])
hdr = vals[0] if vals else []
print("===RACE_HEADER===")
print(json.dumps(["%d:%s" % (i, str(n).strip()) for i,n in enumerate(hdr)], ensure_ascii=False))
# column-wise numeric range over data rows (aggregate only)
import statistics
ncol = max((len(r) for r in vals), default=0)
rng = {}
for j in range(ncol):
    xs=[]
    for r in vals[1:]:
        if len(r)>j and isinstance(r[j],(int,float)):
            xs.append(float(r[j]))
    if xs:
        rng[j] = [round(min(xs),3), round(max(xs),3), len(xs)]
print("===COL_RANGES===")
print(json.dumps(rng, ensure_ascii=False))
print("===END===")
