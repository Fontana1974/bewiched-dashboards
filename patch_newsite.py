#!/usr/bin/env python3
# Headless refresh + pillar injection for the 5 store dashboards.
# Data sources (all headless): allstores.json / f1_detail.json / storehealth.json (area pipeline, BigQuery+F1, w/c 8 Jun)
# + Master Populator "hours used" (passed in HOURS map, gviz).  No Chrome needed.
import json, re, sys

A=json.load(open('allstores.json')); R=A['rec']; champ=A['champ']
FD=json.load(open('f1_detail.json')); STH=json.load(open('storehealth.json'))['stores']
T_RMS=50*13/21.0  # per-store quarterly RMS submission target (area method / store)

NEWWK="w/c 8 Jun"; OLDWK="w/c 1 Jun"; NEWWK_C="W/C 8 Jun"; OLDWK_C="W/C 1 Jun"
NEWDATE="2026-06-08"

# Master Populator "hours used" for the just-completed week (w/c 8 Jun), from the 15-Jun-dated rows. None = not yet posted.
HOURS={'Olney':None,'Attleborough':161.0,'Billing Drive Thru':273.0,'Glenvale Drive Thru':277.0,'Northampton Drive-Thru':350.0}

STORES=[
 ('Olney_Forecast.html','Olney','Jon',False),
 ('Attleborough_Forecast.html','Attleborough','Ian',False),
 ('Billing_DriveThru_Forecast.html','Billing Drive Thru','Rich',False),
 ('Northampton_DriveThru_Forecast.html','Northampton-DriveThru','Rich',True),  # key fixed below
 ('Glenvale_Forecast.html','Glenvale Drive Thru','Ian',True),
]
# fix NDT key
STORES=[(f,('Northampton-DriveThru' and 'Northampton Drive-Thru') if k=='Northampton-DriveThru' else k,c,m) for (f,k,c,m) in STORES]

def racescore(s):
    d=FD.get(s)
    if isinstance(d,dict) and d.get('race') and len(d['race'])>5 and d['race'][5] not in (None,''):
        try: return float(d['race'][5])
        except: return None
    return None

def estate_rank(store):
    vals=sorted([(R[k]['lw26'],k) for k in R], reverse=True)
    for i,(v,k) in enumerate(vals,1):
        if k==store: return i,len(vals)
    return None,len(vals)

def gbp(v): return "£"+format(int(round(v)),",d")

PILLAR_CSS="""
  .kpws{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:16px 0 6px;}
  .kpw{display:block;border-radius:14px;padding:14px 16px;border:1.5px solid}
  .kpw .kl{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;opacity:.9} .kpw .kv{font-size:28px;font-weight:800;margin:3px 0 1px;line-height:1} .kpw .kt{font-size:11px;opacity:.85}
  .kpw.green{background:#e8f5ee;border-color:#bfe3cd;color:#1c6b3d} .kpw.red{background:#fcebe8;border-color:#f0ccc5;color:#9a2f22} .kpw.grey{background:#f0ede9;border-color:#ddd5cb;color:#8a7a6d}
  @media(max-width:760px){.kpws{grid-template-columns:repeat(2,1fr)}}"""

def pillars(store):
    r=R[store]; sh=STH.get(store,{})
    # SALES
    y=r.get('yoy_lw')
    if y is None: s_k,s_v,s_t='grey','new site','store sales YoY · last week · target ≥8%'
    else: s_k,s_v,s_t=('green' if y>=8 else 'red', f"{'+' if y>=0 else ''}{y}%",'store sales YoY · last week · target ≥8%')
    # OPS
    sc=racescore(store)
    o_k=('green' if sc<=190 else 'red') if sc is not None else 'grey'; o_v=(f"{sc:g}" if sc is not None else 'n/a')
    # CUSTOMER (storehealth g_health; grey if stale/None)
    gh=sh.get('g_health'); stale=sh.get('g_stale')
    if stale or gh is None: c_k,c_v,c_t='grey','no feed','Google health · QTD · target ≥3.32 · no live feed'
    else: c_k,c_v,c_t=('green' if gh>=3.32 else 'red', f"{gh:.2f}", f"Google health · QTD · target ≥3.32 · {sh.get('g_n')} reviews")
    # PEOPLE (per-store composite r_avg*0.5 + min(r_n/T,1)*2.5)
    ra=sh.get('r_avg'); rn=sh.get('r_n')
    if ra is None or not rn: p_k,p_v,p_t='grey','n/a','RMS health · QTD · target ≥3.32'
    else:
        ph=round(ra*0.5+min(rn/T_RMS,1)*2.5,2); p_k,p_v,p_t=('green' if ph>=3.32 else 'red', f"{ph:.2f}", f"RMS health · QTD · target ≥3.32 · {rn} ratings")
    return f"""  <div class="kpws">
    <a class="kpw {s_k}"><div class="kl">📈 Sales</div><div class="kv">{s_v}</div><div class="kt">{s_t}</div></a>
    <a class="kpw {o_k}"><div class="kl">🏁 Operations</div><div class="kv">{o_v}</div><div class="kt">F1 race score · last wk · target ≤190 (lower=better)</div></a>
    <a class="kpw {c_k}"><div class="kl">⭐ Customer</div><div class="kv">{c_v}</div><div class="kt">{c_t}</div></a>
    <a class="kpw {p_k}"><div class="kl">👥 People</div><div class="kv">{p_v}</div><div class="kt">{p_t}</div></a>
  </div>
  <div class="note" style="margin:2px 0 8px;background:#fff8ec;border:1px solid #f0e0bf;color:#7a5e1e;border-radius:10px;padding:8px 12px;font-size:12px"><b>At a glance</b> — <b style="color:#1c6b3d">green</b> on/above target · <b style="color:#9a2f22">red</b> below · <b style="color:#8a7a6d">grey</b> = no data/feed. Sales &amp; Operations are last week; Customer &amp; People are quarter-to-date.</div>
"""

def constructors_rows(coach):
    cons=sorted(champ['cons'],key=lambda x:-x[3]); maxavg=max(c[3] for c in cons); out=[]
    for i,(cc,total,nst,avg) in enumerate(cons,1):
        mine=(cc==coach); w=round(100*avg/maxavg)
        wrap=('background:#fff7e9;box-shadow:inset 0 0 0 1.5px #e7c873' if mine else 'background:transparent')
        badge=(' <span style="font-size:10.5px;font-weight:700;color:#b8860b">◄ this store’s constructor</span>' if mine else '')
        barc=('#b8860b' if mine else '#5b3a29'); valc=('#b8860b' if mine else '#3f2d22')
        out.append(f'<div style="display:grid;grid-template-columns:30px 1fr 78px;gap:10px;align-items:center;padding:8px 10px;border-radius:8px;{wrap};margin-bottom:6px">\n'
          f'     <div style="font-weight:800;font-size:15px;color:#5b3a29;text-align:center">{i}</div>\n'
          f'     <div>\n'
          f'       <div style="font-weight:700;font-size:13.5px;color:#3f2d22">{cc}{badge}</div>\n'
          f'       <div style="height:9px;background:#efe7dd;border-radius:5px;margin-top:5px;overflow:hidden"><div style="height:100%;width:{w}%;background:{barc};border-radius:5px"></div></div>\n'
          f'       <div style="font-size:10.5px;color:#9a8a7c;margin-top:3px">{total} pts total · {nst} stores</div>\n'
          f'     </div>\n'
          f'     <div style="text-align:right"><div style="font-weight:800;font-size:18px;color:{valc}">{avg}</div><div style="font-size:9.5px;color:#9a8a7c;margin-top:-2px">pts/store</div></div>\n'
          f'   </div>')
    return "\n".join(out)

def patch(fn,store,coach,mature):
    h=open(fn,encoding='utf-8').read(); log=[]
    def sub(pat,repl,n_expected,label,flags=0):
        nonlocal h
        h2,nn=re.subn(pat,repl,h,count=n_expected,flags=flags)
        if nn: h=h2; log.append(f"  ✓ {label} ({nn})")
        else: log.append(f"  ✗ {label} — NOT FOUND")
        return nn
    r=R[store]; LW=r['lw26']
    # 1) PILLAR CSS + block (idempotent)
    if 'class="kpws"' in h:
        log.append("  • pillars already present, skipping inject")
    else:
        sub(r'</style>', PILLAR_CSS+"\n</style>",1,"pillar CSS")
        sub(r'(</header>)', r'\1\n'+pillars(store).replace('\\','\\\\'),1,"pillar block")
    # 2) actbox value + week
    sub(r'(Last week actual sales · )w/c 1 Jun(</div><div class="ab-val">)£[\d,]+(</div>)',
        rf'\g<1>{NEWWK}\g<2>{gbp(LW)}\g<3>',1,"actbox £ + week")
    # 3) sales series append + FC[0] drop
    if mature:
        sub(r'(const ACT=\[\[.*?)\]\];', rf'\1],["{NEWDATE}",{LW}]];',1,"mature ACT append",flags=re.S)
        sub(r'const FC=\[\["2026-06-08",[^\]]*\],', 'const FC=[',1,"mature FC[0] drop")
    else:
        sub(r'(const \w+_ACT=\[[^\]]*)\];', rf'\1,{LW}];',1,"newsite ACT append")
        sub(r'const FC=\[\["2026-06-08",[^\]]*\],', 'const FC=[',1,"newsite FC[0] drop")
    # 4) ACT_WK + ACT_CPH (only if hours posted for w/c 8 Jun)
    hrs=HOURS.get(store)
    if hrs:
        cph=round(LW/hrs,2)
        sub(r'ACT_WK="w/c 1 Jun"', f'ACT_WK="{NEWWK}"',1,"ACT_WK")
        sub(r'ACT_CPH=[\d.]+', f'ACT_CPH={cph}',1,f"ACT_CPH={cph}")
    else:
        log.append("  • CPH-actual held (w/c 8 Jun hours not yet posted in Master Populator)")
    # 5) mature YoY card
    if mature and r.get('yoy_lw') is not None:
        y=r['yoy_lw']
        sub(r'(<div class="card"><div class="lbl">YoY growth</div><div class="val"[^>]*>)\+?[\d.]+%(</div><div class="meta">)w/c 1 Jun( vs 2025)',
            rf'\g<1>{"+" if y>=0 else ""}{y}%\g<2>{NEWWK}\g<3>',1,"mature YoY card")
    # 6) constructors standings regenerate
    sub(r'(by avg pts/store</span></div>\s*)(.*?)(\s*</div>\s*<div class="panel">\s*<div style="font-size:13px;font-weight:700;color:#5b3a29;margin-bottom:8px">Drivers)',
        lambda m: m.group(1)+"\n"+constructors_rows(coach)+"\n   "+m.group(3),1,"constructors standings",flags=re.S)
    # 7) Latest Race result card -> latest race finish/champ/score from f1
    fin,chp=r['f1'][0],r['f1'][1]
    sub(r'(<div class="card"><div class="lbl">Latest Race result</div><div class="val"[^>]*>)P\d+ · \d+ pts(</div>)',
        rf'\g<1>P{fin} · {chp} pts\g<2>',1,"Latest Race card value")
    # 8) generated timestamp note already dynamic (new Date()). leave.
    open(fn,'w',encoding='utf-8').write(h)
    print(f"\n=== {fn} ({store}) ==="); print("\n".join(log))

for fn,store,coach,mature in STORES:
    patch(fn,store,coach,mature)
print("\nDONE")
