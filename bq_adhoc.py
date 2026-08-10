#!/usr/bin/env python3
"""Map ALL columns of the F1 'The Race' tab (header row + a couple of sample audited data rows)
to identify every scoring section. Column headers + numeric scores only (no PII)."""
import os, json
import run_weekly as R
sh = R._sheets_api(); SID = R.SID["f1"]
def read(rng):
    return sh.get(spreadsheetId=SID, range=rng, valueRenderOption="FORMATTED_VALUE").execute().get("values",[])
hdr = read("'The Race'!A1:AH3")
print("===RACE_HEADER===")
# header row 1
h = hdr[0] if hdr else []
out=[]
for i,name in enumerate(h):
    out.append("%d:%s" % (i, str(name).strip()))
print(json.dumps(out, ensure_ascii=False))
print("---sample row 2 (values)---")
if len(hdr)>1: print(json.dumps([str(x).strip()[:16] for x in hdr[1]], ensure_ascii=False))
if len(hdr)>2: print(json.dumps([str(x).strip()[:16] for x in hdr[2]], ensure_ascii=False))
# also unformatted header widths
uf = sh.get(spreadsheetId=SID, range="'The Race'!A1:AH1", valueRenderOption="UNFORMATTED_VALUE").execute().get("values",[])
print("header_len", len(h))
print("===END===")
