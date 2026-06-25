#!/usr/bin/env python3
# Recompute star_rating.json (Grow composite — Glenvale + Leamington Parade) from live sources.
# Each pillar 0-5 by linear interpolation between anchors floor=0 / target=3 / stretch=5 (clamped).
# Pillar inputs are the Monday-refreshed JSONs (allstores.json, f1_detail.json, storehealth.json);
# the 3 slow-moving compliance/remote sub-metrics come from star_inputs.json (operator-maintained from the
# remote-assessment tab, HRP coaching checklist, Process Street open/close). Keep last on miss.
# Graceful fallbacks: if a store's QTD Google-health feed is stale, fall back to its LIVE Google rating
# (rec.cust) as the Google signal (flagged all-time). If a store's slow Ops sub-metrics are missing,
# Operations is the brand audit alone (flagged) and the compliance panel is omitted for that store.
import json
from statistics import mean
ALL=json.load(open("allstores.json"))["rec"]
FD=json.load(open("f1_detail.json"))
SHS=json.load(open("storehealth.json"))["stores"]
SI=json.load(open("star_inputs.json"))
STORES=[k for k in SI.keys() if not k.startswith("_")]

def up(v,f,t,s):
    if v<=f: return 0.0
    if v<=t: return 3*(v-f)/(t-f)
    if v<=s: return 3+2*(v-t)/(s-t)
    return 5.0
def dn(v,f,t,s):
    if v>=f: return 0.0
    if v>=t: return 3*(f-v)/(f-t)
    if v>=s: return 3+2*(t-v)/(t-s)
    return 5.0
r1=lambda x:round(x,1)

METHOD=("Grow composite star rating. Each pillar scored 0-5 vs target by linear interpolation between anchors "
 "floor=0 / target=3 / stretch=5 stars (clamped). Anchors — Sales YoY (4-wk): floor -8 / target +8 / stretch +20. "
 "CUSTOMER = 50/50 of Google-health (1.66/3.32/5.0) and F1 race score (320/190/130, lower better). "
 "PEOPLE = 50/50 of RMS-health (1.66/3.32/5.0) and RTW% (0/80/100). "
 "OPERATIONS = equal blend of brand audit /5 (4.0/4.5/5.0), remote audit /100 (50/85/100) and COMPLIANCE "
 "(50/50 coaching-% and open/close-%, 50/85/100); where remote/compliance are not yet pulled for a store, "
 "Operations falls back to the brand audit alone (flagged). Composite = average of the four pillars. All QTD (Q2 2026). "
 "Google-health falls back to the store's live all-time rating when its QTD review feed is stale (flagged).")

out={"_method":METHOD,"_window":"quarter-to-date · Q2 2026 (rebuilt weekly)","stores":{}}
log=[]
for G in STORES:
    A=ALL.get(G,{}); F=FD.get(G,{}); SH=SHS.get(G,{}); si=SI[G]
    sales_yoy=A.get("yoy_4w"); brand_audit=A.get("audit_qtd")
    f1_score=(F.get("race_qtd") or {}).get("score")
    rms=SH.get("r_avg"); rtw=A.get("sent",{}).get("rtw_rate")
    # Google health (QTD) or live-rating fallback
    google_h=SH.get("g_health"); g_basis="QTD feed"
    if google_h is None:
        cu=A.get("cust",{}) or {}
        if cu.get("rating") is not None:
            tgt=SH.get("g_target",15) or 15
            google_h=cu["rating"]*0.5 + min((cu.get("reviews",0) or 0)/tgt,1)*2.5
            g_basis=f"live rating {cu['rating']}★/{cu.get('reviews',0)} (all-time — QTD feed stale)"
    # slow Ops sub-metrics
    remote=si.get("remote_audit")
    cs=si.get("coaching_cs_pct"); ba=si.get("coaching_barista_pct")
    coaching=mean([x for x in (cs,ba) if x is not None]) if (cs is not None or ba is not None) else None
    openclose=si.get("openclose_pct")
    # pillars
    sales=up(sales_yoy,-8,8,20)
    customer=0.5*up(google_h,1.66,3.32,5.0)+0.5*dn(f1_score,320,190,130)
    people=0.5*up(rms,1.66,3.32,5.0)+0.5*up(rtw,0,80,100)
    ops_full = (remote is not None and coaching is not None and openclose is not None)
    if ops_full:
        compliance_star=0.5*up(coaching,50,85,100)+0.5*up(openclose,50,85,100)
        operations=(up(brand_audit,4.0,4.5,5.0)+up(remote,50,85,100)+compliance_star)/3
        ops_qtd=f"audit {round(brand_audit,2)} + remote {round(remote)} + compliance {round((coaching+openclose)/2)}%"
        ops_tgt="equal blend: audit·remote·compliance"
    else:
        operations=up(brand_audit,4.0,4.5,5.0)
        ops_qtd=f"audit {round(brand_audit,2)} · remote & compliance pending"
        ops_tgt="brand audit only (remote/compliance not yet pulled)"
    composite=(sales+operations+customer+people)/4
    cu_qtd=f"Google health {round(google_h,2)} ({g_basis.split('(')[0].strip() if '(' in g_basis else g_basis}) + F1 {round(f1_score)}"
    entry={"composite":r1(composite),"pillars":[
        {"name":"Sales","star":r1(sales),"qtd":f"{'+' if sales_yoy>=0 else ''}{round(sales_yoy,1)}% YoY","target":"target +8%"},
        {"name":"Operations","star":r1(operations),"qtd":ops_qtd,"target":ops_tgt},
        {"name":"Customer","star":r1(customer),"qtd":cu_qtd,"target":"Google health + F1 race (50/50)"},
        {"name":"People","star":r1(people),"qtd":f"{round(rms,2)} RMS + {round(rtw)}% RTW","target":"RMS health + RTW% (50/50)"},
    ]}
    if ops_full:
        entry["ops"]={"brand_audit":round(brand_audit,2),"remote_audit":round(remote),"remote_n":si.get("remote_n"),
            "compliance_pct":round((coaching+openclose)/2),"coaching_cs_pct":cs,"coaching_barista_pct":ba,
            "open_pct":si.get("open_pct"),"close_pct":si.get("close_pct"),"openclose_pct":openclose,
            "openclose_detail":si.get("openclose_detail",""),"rtw_pct":round(rtw),"rtw_detail":si.get("rtw_detail","")}
    out["stores"][G]=entry
    log.append((G,entry["composite"],{p["name"]:p["star"] for p in entry["pillars"]},"FULL-ops" if ops_full else "audit-only-ops",g_basis))
json.dump(out,open("star_rating.json","w"),indent=1,ensure_ascii=False)
for L in log: print(L[0],"→ composite",L[1],L[2],"|",L[3],"| Google:",L[4])
