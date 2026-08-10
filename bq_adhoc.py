#!/usr/bin/env python3
"""Diagnosis: why pull_accidents drops the 5 Aug row. Imports run_weekly's real normalize() +
_accident_date() and tests each Accident Forms row. Prints dates + store label + normalize result
ONLY (store names are not PII; no person/incident/injury/address text)."""
import os, json, datetime
import run_weekly as R   # real normalize(), _accident_date(), sheet(), SID, CUR_END

sh_vals = R._sheets_api()
HRP = R.SID["hrp"]
def read(unformatted):
    opt = "UNFORMATTED_VALUE" if unformatted else "FORMATTED_VALUE"
    return sh_vals.get(spreadsheetId=HRP, range="'Accident Forms'!A1:K400",
                       valueRenderOption=opt).execute().get("values", [])

uf = read(True); ff = read(False)
cur_end = R.CUR_END
cutoff = cur_end - datetime.timedelta(days=180)
print("===ACC_STORE_DIAG===")
print("rows %d cur_end %s cutoff %s" % (len(uf), cur_end, cutoff))
def gu(r,j): return r[j] if len(r)>j and r[j] not in (None,"") else ""
for i in range(1, max(len(uf),len(ff))):
    ru = uf[i] if i<len(uf) else []
    rf = ff[i] if i<len(ff) else []
    d = R._accident_date(gu(ru,0) if gu(ru,0)!="" else None)
    win = "-" if not d else ("IN" if cutoff<=d<=cur_end else ("FUT" if d>cur_end else "OLD"))
    raw_store = str(gu(rf,5) or gu(ru,5))
    norm = R.normalize(raw_store)
    keep = bool(d and win=="IN" and norm)
    print("r%-2d date=%-11s win=%-3s store_raw=%-26s normalized=%-24s KEEP=%s"
          % (i+1, (d.isoformat() if d else "NULL"), win, raw_store[:26], str(norm)[:24], keep))
print("===END===")
