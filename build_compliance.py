#!/usr/bin/env python3
# Build compliance.json (Operations tab) from a headless HRP pull (compliance_raw.json).
# Three tiers per measure: QTD (quarter to date) · MTD (month to date) · WTD (previous complete week).
#  - Open/close checklists: live from 'Process St - Data' (open+close completions vs calendar days).
#  - Coaching (Customer Service): live from the 'CS and Br %' summary (Monthly=MTD, Quarter=QTD).
#  - Coaching (Barista), Remote audit, RTW: rendered where available, flagged where a feed/period is missing.
# Handles zero-data periods gracefully (renders '—' + a flag, never fabricates).
import json
RAW = json.load(open("compliance_raw.json"))
CUR_END = RAW.get("cur_end", "")
PERIODS = {"qtd": "QTD · Apr–Jun", "mtd": "MTD · Jun", "wtd": "WTD · prev wk"}
STORES = ["Glenvale Drive Thru", "Leamington Parade"]

def rag(p):
    if p is None: return "x"
    return "g" if p >= 95 else ("a" if p >= 85 else "r")

def oc_pct(d):
    if not d or not d.get("days"): return None
    return round(min((d.get("open", 0) + d.get("close", 0)) / (2 * d["days"]), 1) * 100)

def cell(pct):
    return ({"v": f"{pct:g}%", "rag": rag(pct)} if pct is not None else {"v": "—", "rag": "x"})

out = {"_cur_end": CUR_END, "_periods": PERIODS, "stores": {}}
for s in STORES:
    measures = []
    flags = []
    # 1) Open/close (Process Street)
    oc = (RAW.get("openclose") or {}).get(s)
    if oc:
        measures.append({"label": "Open/close checklists", "sub": "Process Street",
                         "qtd": cell(oc_pct(oc.get("qtd"))), "mtd": cell(oc_pct(oc.get("mtd"))), "wtd": cell(oc_pct(oc.get("wtd"))),
                         "status": "live"})
    else:
        measures.append({"label": "Open/close checklists", "sub": "Process Street",
                         "qtd": {"v": "—", "rag": "x"}, "mtd": {"v": "—", "rag": "x"}, "wtd": {"v": "—", "rag": "x"},
                         "status": "pending", "flag": "not yet in the Process Street open/close feed for this store"})
        flags.append("open/close checklists are not yet logged in the Process Street feed for " + s)
    # 2) Coaching — Customer Service (Monthly=MTD, Quarter=QTD; weekly not split in the HRP summary)
    cs = (RAW.get("coaching_cs") or {}).get(s)
    if cs:
        measures.append({"label": "Coaching — Customer Service", "sub": "HRP CS &amp; Br %",
                         "qtd": cell(round(cs.get("qtd"))) if cs.get("qtd") is not None else {"v": "—", "rag": "x"},
                         "mtd": cell(round(cs.get("mtd"))) if cs.get("mtd") is not None else {"v": "—", "rag": "x"},
                         "wtd": {"v": "n/a", "rag": "x"}, "status": "live",
                         "flag": "weekly split not held in the HRP coaching summary (monthly/quarterly only)"})
        flags.append("coaching is monthly/quarterly in HRP — no weekly (WTD) split")
    # 3) Coaching — Barista (per-event log only, no summary tier)
    ba = (RAW.get("coaching_barista") or {}).get(s)
    if not ba:
        measures.append({"label": "Coaching — Barista", "sub": "HRP CS &amp; Br %",
                         "qtd": {"v": "—", "rag": "x"}, "mtd": {"v": "—", "rag": "x"}, "wtd": {"v": "—", "rag": "x"},
                         "status": "pending", "flag": "Barista % is not in the HRP summary block (per-event log only)"})
        flags.append("Barista coaching % is not in the HRP summary block")
    # 4) Remote audit (periodic, QTD only)
    ra = (RAW.get("remote_audit") or {}).get(s)
    if ra:
        measures.append({"label": "Remote audit", "sub": f"avg of {ra.get('n','?')} QTD",
                         "qtd": {"v": f"{ra['score']:g}/100", "rag": rag(ra["score"])},
                         "mtd": {"v": "—", "rag": "x"}, "wtd": {"v": "—", "rag": "x"}, "status": "live",
                         "flag": "remote audit is a periodic assessment (QTD only)"})
    else:
        measures.append({"label": "Remote audit", "sub": "remote-assessment feed",
                         "qtd": {"v": "—", "rag": "x"}, "mtd": {"v": "—", "rag": "x"}, "wtd": {"v": "—", "rag": "x"},
                         "status": "pending", "flag": "remote-assessment feed not wired for this store"})
        flags.append("remote audit not wired for " + s)
    # 5) RTW (QTD)
    rtw = (RAW.get("rtw") or {}).get(s)
    if rtw is not None:
        measures.append({"label": "Return-to-work (RTW)", "sub": "HRP sickness/RTW",
                         "qtd": cell(round(rtw)), "mtd": {"v": "—", "rag": "x"}, "wtd": {"v": "—", "rag": "x"}, "status": "live",
                         "flag": "RTW shown QTD"})
    out["stores"][s] = {"measures": measures, "flags": flags}

json.dump(out, open("compliance.json", "w"), indent=1, ensure_ascii=False)
for s in STORES:
    print(s)
    for m in out["stores"][s]["measures"]:
        print(f"   {m['label']:28s} QTD {m['qtd']['v']:>6}  MTD {m['mtd']['v']:>6}  WTD {m['wtd']['v']:>6}  [{m['status']}]")
