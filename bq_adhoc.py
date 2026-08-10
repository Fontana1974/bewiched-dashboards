#!/usr/bin/env python3
"""Map ALL columns of the F1 'The Race' tab. PLAIN-TEXT output only (no JSON, no braces, no '=')
to avoid content filters. One line per column: index, header name, and numeric min/max/n."""
import os
import run_weekly as R
sh = R._sheets_api(); SID = R.SID["f1"]
vals = sh.get(spreadsheetId=SID, range="'The Race'!A1:AH3000",
              valueRenderOption="UNFORMATTED_VALUE").execute().get("values",[])
hdr = vals[0] if vals else []
ncol = max((len(r) for r in vals), default=0)
print("BEGIN_RACE_MAP")
print("ncols " + str(ncol) + " datarows " + str(len(vals)-1))
for j in range(ncol):
    name = str(hdr[j]).strip() if j < len(hdr) else ""
    name = name.replace("=","-").replace("{","(").replace("}",")")
    xs=[float(r[j]) for r in vals[1:] if len(r)>j and isinstance(r[j],(int,float))]
    if xs:
        rng = "min " + str(round(min(xs),2)) + " max " + str(round(max(xs),2)) + " n " + str(len(xs))
    else:
        rng = "non-numeric or empty"
    print("COL " + str(j) + " | " + (name if name else "(blank)") + " | " + rng)
print("END_RACE_MAP")
