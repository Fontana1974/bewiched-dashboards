#!/usr/bin/env python3
# Recompute star_rating.json (Grow composite — Glenvale + Leamington Parade) from live sources.
# Pillars aligned to the four tabs: Sales · Commercial · Operations · People & Customer.
#   Sales            = Sales YoY (4-wk) + ATV vs £6.80
#   Commercial       = Profit after tax vs target + CPH vs the store's OWN target (CPH target now READ
#                      from the Store-Targets Google Sheet via cph_targets.json — Glenvale £63, Leamington £58)
#   Operations       = F1 DRIVERS' CHAMPIONSHIP position + brand audit /5 + wastage %
#                      (championship-position based: being #1 in the drivers' championship = AT TARGET)
#   People & Customer= RMS health + RTW% + Google health
#
# TARGET-STAR MODEL: each metric scores 0-5 by interpolation floor=0 / target=TARGET_STAR / stretch=5.
#  RESCALE=True  -> target maps to 4.6 (the headline Grow line) so "meeting target on a metric = ON the
#                   4.6★ line" and a #1 championship reads AT TARGET. This is the recommended, consistent model.
#  RESCALE=False -> legacy target maps to 3.0 (the old 0/3/5 anchors); kept here so scores can be compared.
# The 4.6★ headline target is unchanged either way; floor=0 and stretch=5 are unchanged.
import json
from statistics import mean
ALL=json.load(open("allstores.json"))["rec"]
FD=json.load(open("f1_detail.json"))
SHS=json.load(open("storehealth.json"))["stores"]
SI=json.load(open("star_inputs.json"))
CHAMP=json.load(open("allstores.json")).get("champ",{})
def _txq(fn):
    try: return json.load(open(fn)).get("static",{})
    except (FileNotFoundError,ValueError): return {}
TXQ={"Glenvale Drive Thru":_txq("txquality_glenvale.json"),"Leamington Parade":_txq("txquality_leamington.json")}
try: CPHT=json.load(open("cph_targets.json")).get("targets",{})
except (FileNotFoundError,ValueError): CPHT={}
STORES=[k for k in SI.keys() if not k.startswith("_")]
GROW_TARGET=4.6
RESCALE=True
TARGET_STAR=4.6 if RESCALE else 3.0

def up(v,f,t,s,T):
    if v is None: return None
    if v<=f: return 0.0
    if v<=t: return T*(v-f)/(t-f)
    if v<=s: return T+(5-T)*(v-t)/(s-t)
    return 5.0
def dn(v,f,t,s,T):
    if v is None: return None
    if v>=f: return 0.0
    if v>=t: return T*(f-v)/(f-t)
    if v>=s: return T+(5-T)*(t-v)/(t-s)
    return 5.0
r1=lambda x:round(x,1)
def pillar(metrics):
    scored=[m[2] for m in metrics if m[2] is not None]
    return (round(mean(scored),1) if scored else 0.0)

# drivers' championship position per store (1 = top). Used for the F1 Operations sub-score.
DRV=sorted(CHAMP.get("drivers",[]), key=lambda x:-x[2])
N_DRV=len(DRV) or 1
DRV_POS={row[0]: i+1 for i,row in enumerate(DRV)}
def f1_champ_star(store,T):
    pos=DRV_POS.get(store)
    if not pos: return None,None
    # P1 = AT TARGET (= T). Linear down to 0 at last place. (#1 is the best possible, so T is the cap.)
    star=round(T*(N_DRV-pos)/(N_DRV-1),1) if N_DRV>1 else T
    return star,pos

def compute(T):
    out={"target":GROW_TARGET,"stores":{}}
    for G in STORES:
        A=ALL.get(G,{}); F=FD.get(G,{}); SH=SHS.get(G,{}); si=SI[G]; pat=TXQ.get(G,{})
        yoy=A.get("yoy_4w"); atv=A.get("atv"); audit=A.get("audit_qtd"); waste=A.get("waste_pct")
        rms=SH.get("r_avg"); rtw=A.get("sent",{}).get("rtw_rate"); late=A.get("sent",{}).get("late")
        gh=SH.get("g_health"); gbasis="QTD"
        if gh is None:
            cu=A.get("cust",{}) or {}
            if cu.get("rating") is not None:
                tgt=SH.get("g_target",15) or 15
                gh=cu["rating"]*0.5+min((cu.get("reviews",0) or 0)/tgt,1)*2.5
                gbasis=f"live {cu['rating']}★/{cu.get('reviews',0)} all-time (QTD feed stale)"
        pat_pct=pat.get("pat_day_current_pct"); pat_cur=pat.get("pat_day_current")
        pat_tgt_pct=pat.get("pat_pct_target",18)
        cph_a=si.get("cph_actual"); cph_t=CPHT.get(G, si.get("cph_target"))
        f1star,pos=f1_champ_star(G,T)
        sales=[("Sales YoY (4-wk)",f"{'+' if (yoy or 0)>=0 else ''}{round(yoy,1)}%",up(yoy,-8,8,20,T)),
               ("ATV vs £6.80",f"£{atv}",up(atv,5.5,6.8,8.0,T))]
        patstar=up(pat_pct,0,pat_tgt_pct,pat_tgt_pct+6,T) if pat_pct is not None else None
        cphstar=up(cph_a,cph_t*0.85,cph_t,cph_t*1.08,T) if (cph_a is not None and cph_t) else None
        commercial=[("Profit after tax",(f"£{pat_cur}/day · {pat_pct}% vs {pat_tgt_pct}% target" if pat_cur is not None else "n/a"),patstar),
                    (f"CPH vs £{cph_t} target",(f"£{cph_a}" if cph_a is not None else "held — provisional, shown not scored"),cphstar)]
        operations=[(f"F1 drivers' championship — P{pos}/{N_DRV}", (f"P{pos} of {N_DRV}"+(" — #1, at target" if pos==1 else ""), f1star) if pos else ("n/a",None)),
                    ("Brand audit /5",f"{round(audit,2)}",up(audit,4.0,4.5,5.0,T)),
                    ("Wastage %",f"{waste}%",dn(waste,5.0,3.0,1.0,T))]
        # fix operations tuple shape (label,value,star)
        operations=[(f"F1 drivers' championship", (f"P{pos} of {N_DRV}"+(" · #1 = at target" if pos==1 else ""), f1star)),
                    ("Brand audit /5",f"{round(audit,2)}",up(audit,4.0,4.5,5.0,T)),
                    ("Wastage %",f"{waste}%",dn(waste,5.0,3.0,1.0,T))]
        operations=[("F1 drivers' championship", f"P{pos} of {N_DRV}"+(" · #1 = at target" if pos==1 else ""), f1star),
                    ("Brand audit /5",f"{round(audit,2)}",up(audit,4.0,4.5,5.0,T)),
                    ("Wastage %",f"{waste}%",dn(waste,5.0,3.0,1.0,T))]
        peoplecust=[("RMS health /5",f"{round(rms,2)}",up(rms,1.66,3.32,5.0,T)),
                    ("RTW completion",f"{round(rtw)}%",up(rtw,0,80,100,T)),
                    ("Google health",f"{round(gh,2)} ({gbasis})",up(gh,1.66,3.32,5.0,T)),
                    ("Lateness (shown, not scored)",f"{late} late",None)]
        pills=[("Sales",sales),("Commercial",commercial),("Operations",operations),("People & Customer",peoplecust)]
        P=[{"name":n,"star":pillar(ms),"target":GROW_TARGET,"on_target":pillar(ms)>=GROW_TARGET,
            "metrics":[{"label":l,"value":v,"star":(r1(s) if s is not None else None),
                        "on_target":(s is not None and r1(s)>=GROW_TARGET)} for (l,v,s) in ms]} for n,ms in pills]
        comp=round(mean([p["star"] for p in P]),1)
        ops_block=None
        if si.get("remote_audit") is not None:
            cs=si.get("coaching_cs_pct"); oc=si.get("openclose_pct")
            comp_pct=round((cs+oc)/2,1) if (cs is not None and oc is not None) else None
            ops_block={"brand_audit":audit,"remote_audit":si["remote_audit"],"remote_n":si.get("remote_n"),
                       "compliance_pct":comp_pct,"coaching_cs_pct":cs,"coaching_barista_pct":si.get("coaching_barista_pct"),
                       "openclose_pct":oc,"openclose_detail":si.get("openclose_detail",""),
                       "rtw_pct":rtw,"rtw_detail":si.get("rtw_detail","")}
        out["stores"][G]={"composite":comp,"target":GROW_TARGET,"on_target":comp>=GROW_TARGET,
                          "pillars":P,"ops":ops_block,"_cph_target":cph_t,"_f1_pos":pos}
    return out

METHOD=("Grow composite, pillars aligned to the four tabs (Sales · Commercial · Operations · People & Customer). "
 f"Each metric scored 0-5 between floor=0 / target={TARGET_STAR:g} / stretch=5 (clamped). "
 "TARGET maps to 4.6★ (the headline line) so meeting a metric's target reads ON the 4.6 line; a #1 drivers'-championship "
 "position = AT TARGET on F1. Pillar = mean of scored metrics; composite = mean of four pillars. "
 "Sales = Sales YoY(-8/8/20) + ATV vs £6.80(5.5/6.8/8.0). Commercial = Profit-after-tax %(0/18/24) + CPH vs the store's own "
 "target from the Store-Targets sheet(target*0.85/target/target*1.08). Operations = F1 drivers' championship position (P1=at "
 "target, linear to 0 at last) + brand audit /5(4.0/4.5/5.0) + wastage %(5/3/1, lower better). People & Customer = RMS "
 "health(1.66/3.32/5.0) + RTW%(0/80/100) + Google health. GROW TARGET = 4.6★ (below = OFF TARGET).")

ship=compute(TARGET_STAR); ship["_method"]=METHOD; ship["_window"]="quarter-to-date · Q2 2026 (rebuilt weekly)"; ship["_rescaled"]=RESCALE
json.dump(ship,open("star_rating.json","w"),indent=1,ensure_ascii=False)
alt=compute(3.0)  # legacy 0/3/5 basis, for comparison
print(f"=== SHIPPED (RESCALE target->4.6) ===")
for G in STORES:
    d=ship["stores"][G]; print(f"{G}: composite {d['composite']} ({'ON' if d['on_target'] else 'OFF'}) "+str({p['name']:p['star'] for p in d['pillars']})+f"  [F1 P{d['_f1_pos']}, CPH tgt £{d['_cph_target']}]")
print(f"=== COMPARISON (legacy target->3.0) ===")
for G in STORES:
    d=alt["stores"][G]; print(f"{G}: composite {d['composite']} "+str({p['name']:p['star'] for p in d['pillars']}))
