#!/usr/bin/env python3
# Headless refresh + pillar injection for the 5 store dashboards.
# Data sources (all headless): allstores.json / f1_detail.json / storehealth.json (area pipeline, BigQuery+F1, w/c 8 Jun)
# + Master Populator "hours used" (passed in HOURS map, gviz).  No Chrome needed.
import json, re, sys

def relocate_coaching(h):
    """Ensure the 'Documented coaching' block lives ONLY on the Op's Excellence (tab-f1)
    tab, not Sentiment. Sickness/RTW stay on Sentiment. Idempotent / self-healing."""
    sidx=h.find('id="tab-sentiment"'); cidx=h.find('Documented coaching')
    if cidx<0 or (0<=cidx<sidx): return h          # missing, or already pre-sentiment (on f1)
    m=re.search(r'(\s*<div class="section-title"[^>]*>\U0001F4CB Documented coaching[\s\S]*?)(\n\s*<footer style="margin-top:18px">Customer:)', h)
    if not m: return h
    block=m.group(1); h=h[:m.start(1)]+h[m.end(1):]
    h2,n=re.subn(r'(\n\s*</section>)(\s*(?:<!--[^>]*-->\s*)?<section class="tab-panel" id="tab-sentiment">)',
                 lambda mm: "\n"+block.rstrip()+"\n"+mm.group(1)+mm.group(2), h, count=1)
    return h2 if n else h

A=json.load(open('allstores.json')); R=A['rec']; champ=A['champ']; CATS=A['cats']
FD=json.load(open('f1_detail.json')); STH=json.load(open('storehealth.json'))['stores']
try: SENT=json.load(open('newsite_sentiment.json'))   # review snippets / RMS trend+comments / sickness cross-ref (gviz, headless)
except FileNotFoundError: SENT={}
try: NS=json.load(open('newsite_sales.json'))          # per-store Sales tab: DOW + daypart + Food&Bakery traction (BigQuery, headless)
except FileNotFoundError: NS={}
T_RMS=50*13/21.0  # per-store quarterly RMS submission target (area method / store)
import html as _html
def esc(t): return _html.escape((t or "").strip())[:200]
def stars(n):
    try: n=int(round(float(n)))
    except: n=0
    return "★"*max(0,min(5,n))

NEWWK="w/c 8 Jun"; OLDWK="w/c 1 Jun"; NEWWK_C="W/C 8 Jun"; OLDWK_C="W/C 1 Jun"
NEWDATE="2026-06-08"; NEWWK_DDMM="08/06"

# Master Populator "hours used" for the just-completed week (w/c 8 Jun), from the 15-Jun-dated rows. None = not yet posted.
HOURS={'Olney':None,'Attleborough':161.0,'Billing Drive Thru':273.0,'Glenvale Drive Thru':277.0,'Northampton Drive-Thru':350.0}
# CPH targets (Store Targets sheet) and the just-completed week's committed forecast £ (Master Populator "Forecasts last week", 15-Jun row)
CPH_T={'Olney':49,'Attleborough':49,'Billing Drive Thru':56,'Glenvale Drive Thru':63,'Northampton Drive-Thru':70}
FCST={'Olney':5800,'Attleborough':6300,'Billing Drive Thru':12000,'Glenvale Drive Thru':18250,'Northampton Drive-Thru':26000}
MINUS="−"  # unicode minus, matches the dashboards' existing style
def pct1(v): return ("+" if v>=0 else MINUS)+f"{abs(v):.1f}%"

STORES=[
 ('Olney_Forecast.html','Olney','Jon',False),
 ('Attleborough_Forecast.html','Attleborough','Ian',False),
 ('Billing_DriveThru_Forecast.html','Billing Drive Thru','Rich',False),
 ('Northampton_DriveThru_Forecast.html','Northampton-DriveThru','Rich',True),  # key fixed below
 ('Glenvale_Forecast.html','Glenvale Drive Thru','Ian',True),
]
# fix NDT key
STORES=[(f,('Northampton-DriveThru' and 'Northampton Drive-Thru') if k=='Northampton-DriveThru' else k,c,m) for (f,k,c,m) in STORES]

SHORT={"Burton Latimer":"Burton","Higham Ferrers":"Higham","Olney":"Olney","Peterborough Bridge Street":"P'boro Bridge St","Peterborough Fletton Quays":"P'boro Fletton","Rushden Lakes":"Rushden Lakes","Attleborough":"Attleborough","Billing Drive Thru":"Billing DT","Glenvale Drive Thru":"Glenvale DT","HOE Balsall Common":"Balsall Common","Leamington Parade":"Leam Parade","Lower Heathcote":"Lower Heathcote","Market Harborough":"Mkt Harborough","Northampton":"Northampton","Northampton Drive-Thru":"Northampton DT","Wellingborough":"Wellingborough","Wellingborough Train Station":"W'boro Train Stn","Corby":"Corby","Kettering":"Kettering","Rothwell":"Rothwell","Rugby":"Rugby"}
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

# ===== NEW per-store "Sales" tab (DOW + daypart + Food&Bakery traction) =====
_DPICON={"Morning":"🌅","Lunch":"🥪","Afternoon":"☕","Evening":"🌙"}
def _chip(pct):
    if pct is None: return ""
    up=pct>=0; bg="#eef3ee" if up else "#fbeae8"; col="var(--green)" if up else "var(--red)"; sign="+" if up else MINUS
    return f'<span style="display:inline-block;font-size:11px;padding:1px 7px;border-radius:5px;background:{bg};color:{col};font-weight:600">{sign}{abs(pct)}%</span>'

def sales_tab_section(store):
    d=(NS.get("stores") or {}).get(store); win=NS.get("_window",""); hrs=NS.get("hours",{})
    if not d:
        return ('<!-- STORESALES START -->\n<section class="tab-panel" id="tab-storesales">\n'
                f'  <div class="section-title">📊 Sales by day &amp; daypart — {store}</div>\n'
                '  <p class="note">Store sales data not available this run.</p>\n</section>\n<!-- STORESALES END -->')
    has=d.get("has_ly")
    # day of week
    dow=d.get("dow",[]); maxc=max([c for _,c,_ in dow] or [1]) or 1; dowrows=""
    for lab,cur,ly in dow:
        pct=round(100*(cur-ly)/ly) if ly>0 else None; bw=round(100*cur/maxc); chip=_chip(pct) if has else ""
        dowrows+=(f'<div style="display:flex;align-items:center;gap:10px;margin:4px 0">'
                  f'<div style="width:58px;font-size:12px;color:var(--muted)">avg {lab}</div>'
                  f'<div style="flex:1;height:14px;background:var(--cream);border-radius:7px;overflow:hidden"><div style="height:100%;width:{bw}%;background:var(--brown);border-radius:7px"></div></div>'
                  f'<div style="width:64px;text-align:right;font-size:12.5px"><b>{gbp(cur)}</b></div>'
                  f'<div style="width:56px;text-align:right">{chip}</div></div>')
    dow_title="Average day-of-week sales · YoY" if has else "Average day-of-week sales"
    dow_note=('<div class="mini" style="margin-top:6px">Average per weekday — the 4-week total ÷ 4 weeks (a typical Monday, Tuesday, …).</div>' if has
              else '<div class="mini" style="margin-top:6px">Average per weekday (4-week total ÷ 4). Brand-new site — this year only (no prior-year comparison yet).</div>')
    # daypart cards
    dpcards=""
    for lab,cur,ly in d.get("daypart",[]):
        pct=round(100*(cur-ly)/ly) if ly>0 else None
        meta=(hrs.get(lab,"")+" · avg/day · "+_chip(pct)) if has else (hrs.get(lab,"")+" · avg/day · <span class='mini'>new site</span>")
        dpcards+=(f'<div class="card"><div class="lbl">{_DPICON.get(lab,"")} {lab}</div>'
                  f'<div class="val">{gbp(cur)}</div><div class="meta">{meta}</div></div>')
    # food & bakery traction
    fcards=""; food=d.get("food",{})
    for lab in ["Morning","Lunch","Afternoon","Evening"]:
        fd=food.get(lab,{}); rows=""; cap=""
        if has:
            for nm,cur,pct,gb in fd.get("gain",[]):
                rows+=(f'<div style="display:flex;justify-content:space-between;gap:8px;padding:5px 0;border-bottom:1px solid var(--line)">'
                       f'<span style="font-size:12.5px;color:#3f2d22">{nm}</span>'
                       f'<span style="white-space:nowrap;font-size:12px"><b>{gbp(cur)}</b> {_chip(pct)}</span></div>')
            if fd.get("new"):
                cap="<div style='font-size:11.5px;color:#1d4e7a;margin-top:7px'>🆕 New this year: "+", ".join(f"{p} ({gbp(c)})" for p,c in fd["new"])+"</div>"
        else:
            for p,c in fd.get("sell",[]):
                rows+=(f'<div style="display:flex;justify-content:space-between;gap:8px;padding:5px 0;border-bottom:1px solid var(--line)">'
                       f'<span style="font-size:12.5px;color:#3f2d22">{p}</span>'
                       f'<span style="white-space:nowrap;font-size:12px"><b>{gbp(c)}</b></span></div>')
            if rows: cap="<div style='font-size:11.5px;color:#8a7a6d;margin-top:7px'>Top sellers — new site, no prior-year comparison yet.</div>"
        if not rows: rows='<div class="mini" style="padding:5px 0">Limited data this daypart.</div>'
        fcards+=(f'<div class="panel" style="padding:13px 15px"><div style="font-size:13px;font-weight:700;color:var(--brown);margin-bottom:6px">{_DPICON.get(lab,"")} {lab} <span class="mini" style="font-weight:400">· {hrs.get(lab,"")}</span></div>{rows}{cap}</div>')
    food_lead=("Food &amp; bakery items growing fastest vs the same 4 weeks last year (ranked by £ added over the 4 weeks — these are 4-week totals, not averages). Names cleaned of till codes."
               if has else "Top food &amp; bakery sellers by daypart (4-week totals) — this brand-new site has no prior-year comparison yet.")
    return (f'<!-- STORESALES START -->\n<!-- ===== TAB: Sales (store-scoped) ===== -->\n'
            f'<section class="tab-panel" id="tab-storesales">\n'
            f'  <div class="section-title">📊 Sales by day &amp; daypart — {store}</div>\n'
            f'  <div class="note">This store only · {win}, shown as <b>averages for a typical day</b> (not 4-week totals). Day-of-week = 4-week total ÷ 4 weeks; daypart = 4-week total ÷ 28 days. Dayparts: <b>Morning 5am–11am</b>, <b>Lunch 11am–2pm</b>, <b>Afternoon 2pm–5pm</b>, <b>Evening 5pm+</b>. (The Food &amp; bakery traction panel below stays as 4-week totals.)</div>\n'
            f'  <div class="section-title">{dow_title}</div>\n  <div>{dowrows}</div>{dow_note}\n'
            f'  <div class="section-title">Average sales by daypart — a typical day</div>\n  <div class="cards">{dpcards}</div>\n'
            f'  <div class="section-title">🥪 Food &amp; bakery gaining traction by daypart</div>\n'
            f'  <div class="note" style="margin-bottom:4px">{food_lead}</div>\n'
            f'  <div class="cards">{fcards}</div>\n</section>\n<!-- STORESALES END -->')

def inject_sales_tab(h, store):
    # 1) rename existing front tab button label (idempotent)
    h=h.replace('data-tab="sales" role="tab"><span class="dot">📈</span>Sales &amp; Hours</button>',
                'data-tab="sales" role="tab"><span class="dot">📈</span>Forecast / Review</button>')
    # 2) ensure the new Sales nav button exists right after the Forecast/Review button
    if 'data-tab="storesales"' not in h:
        h=h.replace('data-tab="sales" role="tab"><span class="dot">📈</span>Forecast / Review</button>',
                    'data-tab="sales" role="tab"><span class="dot">📈</span>Forecast / Review</button>\n    <button class="tab-btn" data-tab="storesales" role="tab"><span class="dot">📊</span>Sales</button>',1)
    # 3) tab-status dot map (idempotent)
    if 'storesales:' not in h:
        h=h.replace('sentiment:"green"}','sentiment:"green",storesales:"green"}',1)
    # 4) (re)build the section: replace prior injection else insert before the Wastage tab
    sec=sales_tab_section(store)
    h2,n=re.subn(r'<!-- STORESALES START -->.*?<!-- STORESALES END -->', lambda m: sec, h, flags=re.S)
    if n: return h2
    m=re.search(r'(\n\s*(?:<!--[^>]*-->\s*)?<section class="tab-panel" id="tab-waste">)', h)
    if m: return h[:m.start()]+"\n  "+sec+"\n"+h[m.start():]
    return h

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
    # 5b) derived headline stats -> w/c 8 Jun (data-driven, reproducible)
    fcst=FCST.get(store); cpht=CPH_T.get(store)
    # vs-forecast (actbox) — sales-based, applies to all incl. new sites
    if fcst:
        vsf=round(100*(LW/fcst-1),1); vcls='pos' if vsf>=0 else 'neg'
        sub(r'<span>vs forecast</span><b class="(?:neg|pos)">[^<]*</b><small>fcst £[\d,]+</small>',
            f'<span>vs forecast</span><b class="{vcls}">{pct1(vsf)}</b><small>fcst {gbp(fcst)}</small>',1,"actbox vs-forecast")
        # forecast note(s): "£X vs £Y forecast (Z%)"
        sub(r'£[\d,]+ vs £[\d,]+ forecast \([^)]*\)',
            f'{gbp(LW)} vs {gbp(fcst)} forecast ({pct1(vsf)})',3,"forecast note sales")
    # CPH-actual (only where w/c 8 Jun hours posted)
    if hrs:
        cph=round(LW/hrs,1); diff=round(cph-cpht,1); met=cph>=cpht
        cw='met' if met else 'missed'; cvar='green' if met else 'red'; cab='pos' if met else 'neg'
        dsign='+' if diff>=0 else MINUS
        sub(r'<span>CPH</span><b class="(?:neg|pos)">£[\d.]+</b><small>target £\d+ · (?:missed|met)</small>',
            f'<span>CPH</span><b class="{cab}">£{cph}</b><small>target £{cpht} · {cw}</small>',1,"actbox CPH stat")
        sub(r'last wk actual <b style="color:var\(--(?:red|green)\);?">£[\d.]+</b> · [^(]*\(w/c \d Jun\)',
            f'last wk actual <b style="color:var(--{cvar})">£{cph}</b> · {dsign}£{abs(diff)}/hr (w/c 8 Jun)',1,"KPI CPH card")
        sub(r'ran £[\d.]+ CPH', f'ran £{cph} CPH',2,"forecast-note CPH (mature)")
    # actbox YoY stat (mature only; new sites read "new site — no prior yr" and are skipped by the pattern)
    if mature and r.get('yoy_lw') is not None:
        y=r['yoy_lw']; ly=r['lw25']; ycls='pos' if y>=0 else 'neg'
        sub(r'(<span>YoY[^<]*</span><b class=")(?:pos|neg|mut)(">)[^<]*(</b><small>)vs £[\d.]+k last yr(</small>)',
            rf'\g<1>{ycls}\g<2>{"+" if y>=0 else MINUS}{abs(y)}%\g<3>vs £{ly/1000:.1f}k last yr\g<4>',1,"actbox YoY stat")
    # 5c) WASTAGE + MIX + SENTIMENT — fully headless (allstores.json + newsite_sentiment.json), no Chrome/Maps
    sj=SENT.get(store,{}); gj=sj.get('google',{}); rj=sj.get('rms',{}); kj=sj.get('sickness',{})
    sent=r.get('sent',{})
    def arr(name, tf, label):
        nonlocal h
        i=h.find('const '+name+'=')
        if i<0: log.append(f"  ✗ {label} array — NOT FOUND"); return
        j=h.find('[', i); depth=0; k=j
        while k<len(h):
            if h[k]=='[': depth+=1
            elif h[k]==']':
                depth-=1
                if depth==0: break
            k+=1
        try: cur=json.loads(h[j:k+1])
        except Exception as e: log.append(f"  ✗ {label} array — parse fail {e}"); return
        h=h[:j]+json.dumps(tf(cur),ensure_ascii=False)+h[k+1:]
        log.append(f"  ✓ {label} array")
    # --- WASTAGE ---
    wp_lw=r['waste_pct_lw']; wp4=r['waste_pct']; wr_lw=int(round(r['wr_lw'])); wr4=int(round(r['wr']/4))
    wcol=lambda v:'green' if v<=3 else ('amber' if v<=4 else 'red')
    sub(r'color:var\(--\w+\)">[\d.]+%(</div><div style="font-size:10px;color:#9a8a7c;margin-top:2px">last week)',
        f'color:var(--{wcol(wp_lw)})">{wp_lw}%\\1',1,"wastage% last-wk card")
    sub(r'color:var\(--\w+\)">[\d.]+%(</div><div style="font-size:10px;color:#9a8a7c;margin-top:2px">4-week run rate)',
        f'color:var(--{wcol(wp4)})">{wp4}%\\1',1,"wastage% 4wk card")
    sub(r'(line-height:1">)£[\d,]+(</div><div style="font-size:10px;color:#9a8a7c;margin-top:2px">last week)',
        rf'\g<1>£{wr_lw:,}\g<2>',1,"waste£ last-wk card")
    sub(r'(line-height:1">)£[\d,]+(</div><div style="font-size:10px;color:#9a8a7c;margin-top:2px">4-week weekly avg)',
        rf'\g<1>£{wr4:,}\g<2>',1,"waste£ 4wk card")
    arr('WK', lambda cur: cur+[[NEWWK_DDMM, wp_lw]], "wastage WK trend (+latest wk)")
    def items_tf(_):
        ol=sorted(r.get('outliers',[]), key=lambda x:-x[4])[:10]
        return [[o[0], int(round(o[4])), int(o[2]), int(o[3])] for o in ol]
    arr('ITEMS', items_tf, "wastage outlier ITEMS")
    # --- MIX ---
    def rows_tf(cur):
        mix=r.get('mix') or {}; mlwd=r.get('mix_lw') or {}; mprev=r.get('mix_prev') or {}
        out=[]
        for row in cur:
            lbl=row[0]; tilt=row[2] if len(row)>2 else 0
            cat=next((c for c in CATS if c==lbl or c.split()[0]==lbl.split()[0] or lbl.startswith(c.split()[0])), None)
            mc=mix.get(cat) if cat else None
            if not mc: out.append(row); continue
            m4=mc.get('mix'); c4=mc.get('cap')
            lwc=mlwd.get(cat) or {}; mlw=lwc.get('mix', row[6] if len(row)>6 else m4); clw=lwc.get('cap', row[7] if len(row)>7 else c4)
            pc=mprev.get(cat) if isinstance(mprev,dict) else None
            mpp=round(m4-pc['mix'],1) if pc else None; cpp=round(c4-pc['cap'],1) if pc else None
            out.append([lbl, m4, tilt, c4, mpp, cpp, mlw, clw])
        return out
    arr('ROWS', rows_tf, "mix/capture ROWS")
    def peer_tf(cur):
        out=[]
        for row in cur:
            lbl=row[0]
            cat=next((c for c in CATS if c==lbl or c.split()[0]==lbl.split()[0] or lbl.startswith(c.split()[0])), None)
            caps=[(R[s]['mix'][cat]['cap'], s) for s in R if cat and cat in (R[s].get('mix') or {})] if cat else []
            mc=(r.get('mix') or {}).get(cat)
            if not caps or not mc: out.append(row); continue
            caps.sort(reverse=True)
            rank=next((i+1 for i,(v,s) in enumerate(caps) if s==store), len(caps))
            avg=round(sum(v for v,_ in caps)/len(caps),1)
            best=caps[0]; bestnm=SHORT.get(best[1],best[1])
            out.append([lbl, mc['cap'], rank, len(caps), avg, f"{bestnm} {best[0]}%"])
        return out
    arr('PEER', peer_tf, "mix PEER (estate rank)")
    # --- SENTIMENT cards ---
    grate=gj.get('rating'); gcount=gj.get('count'); rms=sent.get('rms'); rmsn=sent.get('rms_n')
    if grate is not None:
        gcol='green' if grate>=4.5 else 'amber'
        sub(r'(lbl">Customer \(Google\)</div><div class="val" style="color:var\(--)\w+(\)">)[\d.]+★(</div><div class="meta">)[\d,]+( reviews)',
            rf'\g<1>{gcol}\g<2>{grate}★\g<3>{gcount:,}\g<4>',1,"Customer card")
        sub(r'(<div class="scorebig" style="color:var\(--)\w+(\)">)[\d.]+(<span style="font-size:20px">★)',
            rf'\g<1>{gcol}\g<2>{grate}\g<3>',1,"Google scorebig")
        sub(r'(Google · )[\d,]+( reviews)', rf'\g<1>{gcount:,}\g<2>',1,"Google scoresub count")
    if rms is not None:
        rmscol='green' if rms>=4.5 else ('amber' if rms>=4.0 else 'red')
        sub(r'(lbl">Team \(RMS · /5\)</div><div class="val" style="color:var\(--)\w+(\)">)[\d.]+(</div><div class="meta">)\d+( shift ratings)',
            rf'\g<1>{rmscol}\g<2>{rms}\g<3>{rmsn}\g<4>',1,"Team RMS card")
        sub(r'(<div class="scorebig" style="color:var\(--)\w+(\)">)[\d.]+(<span style="font-size:20px">/5)',
            rf'\g<1>{rmscol}\g<2>{rms}\g<3>',1,"RMS scorebig")
        sub(r'(RMS [^·]*· )\d+( ratings)', rf'\g<1>{rmsn}\g<2>',1,"RMS scoresub count")
    # RMS monthly trend chart
    if rj.get('trend'): arr('tT', lambda _:[[m,v] for m,v in rj['trend']], "RMS trend tT")
    # --- SICKNESS cards + chart + cross-ref ---
    sickfs=sent.get('sickfs'); rtw=sent.get('rtw'); late=sent.get('late'); rep_pct=sent.get('rep_pct')
    if sickfs is not None:
        reported=round((rep_pct or 0)*sickfs/100)
        sub(r'(lbl">Sick absences</div><div class="val">)\d+(</div>)', rf'\g<1>{sickfs}\g<2>',1,"Sick-absences card")
        sub(r'(lbl">Lateness</div><div class="val">)\d+(</div>)', rf'\g<1>{late}\g<2>',1,"Lateness card")
        sub(r'(lbl">Reported correctly</div><div class="val"[^>]*>)\d+ / \d+(</div>)', rf'\g<1>{reported} / {sickfs}\g<2>',1,"Reported card")
        rtwcol='green' if rtw>=sickfs*0.8 else ('amber' if rtw>=sickfs*0.5 else 'red')
        sub(r'(lbl">Return-to-work \(RTW\) completed</div><div class="val" style="color:var\(--)\w+(\)">)\d+ / \d+(</div>)',
            rf'\g<1>{rtwcol}\g<2>{rtw} / {sickfs}\g<3>',1,"RTW card")
        sub(r'(data:\[)\d+, ?\d+(\],backgroundColor:\["#b8860b")', rf'\g<1>{sickfs},{rtw}\g<2>',1,"absChart data")
    if kj.get('rows') is not None:
        rh="".join(f'<tr><td>{esc(n)}</td><td>{d}</td><td>{rep}</td><td>{"✓" if rb else "✗"}</td></tr>' for n,d,rep,rb in kj['rows'])
        sub(r'(<th>Team member</th><th>Sick date</th><th>Reported</th><th>RTW</th></tr></thead>\s*<tbody>)[\s\S]*?(</tbody>)',
            lambda m:m.group(1)+rh+m.group(2),1,"sickness cross-ref table")
    if kj.get('out45') is not None:
        sub(r'RTWs to do — last 45 days: \d+', f'RTWs to do — last 45 days: {kj["out45"]}',1,"RTW chip (top)")
    # --- review snippets + RMS comments (Reviews sheet text; flag empties) ---
    def quotes(items, who_first):
        out=[]
        for a,b,c in items:
            # google snippets are [star,date,text]; rms comments are [date,star,text]
            st,dt,txt=(a,b,c) if isinstance(a,(int,float)) else (b,a,c)
            if not (txt or '').strip(): continue
            out.append(f'<div class="quote">{esc(txt)}<span class="who">{dt} · <span class="stars">{stars(st)}</span></span></div>')
        if not out:
            out=['<div class="quote" style="color:#9a8a7c">No review text in the Reviews sheet for this store yet (rating &amp; count only).<span class="who"></span></div>']
        return "\n          "+"\n          ".join(out)+"\n        "
    if gj.get('snippets') is not None:
        sub(r'(scoresub">Google ·[\s\S]*?<div style="margin-top:\d+px">)[\s\S]*?(</div>\s*</div>\s*<div class="panel">)',
            lambda m:m.group(1)+quotes(gj['snippets'],True)+m.group(2),1,"customer review snippets")
        # new-site star-distribution chart (custDist) if present
        if gj.get('dist'): sub(r'(custDist[\s\S]{0,300}?data:\[)\d+(?:, ?\d+){4}(\])', rf'\g<1>{",".join(str(x) for x in gj["dist"])}\g<2>',1,"custDist distribution")
    if rj.get('comments') is not None:
        sub(r'(<canvas id="teamTrend"></canvas></div>\s*<div style="margin-top:8px">)[\s\S]*?(</div>\s*<div class="note)',
            lambda m:m.group(1)+quotes(rj['comments'],False)+m.group(2),1,"RMS comment quotes")
    # 6) constructors standings regenerate
    sub(r'(by avg pts/store</span></div>\s*)(.*?)(\s*</div>\s*<div class="panel">\s*<div style="font-size:13px;font-weight:700;color:#5b3a29;margin-bottom:8px">Drivers)',
        lambda m: m.group(1)+"\n"+constructors_rows(coach)+"\n   "+m.group(3),1,"constructors standings",flags=re.S)
    # 7) Latest Race result card -> latest race finish/champ/score from f1
    fin,chp=r['f1'][0],r['f1'][1]
    sub(r'(<div class="card"><div class="lbl">Latest Race result</div><div class="val"[^>]*>)P\d+ · \d+ pts(</div>)',
        rf'\g<1>P{fin} · {chp} pts\g<2>',1,"Latest Race card value")
    # 8) generated timestamp note already dynamic (new Date()). leave.
    # SAFETY: sentiment section must have balanced <div> nesting, else sickness/RTW leaks onto every tab.
    def _sent_depth(s):
        i=s.find('id="tab-sentiment"'); j=s.find('</section>',i)
        seg=s[i:j] if i>=0 else ""
        return len(re.findall(r'<div\b',seg))-len(re.findall(r'</div>',seg))
    if _sent_depth(h)<0:
        h=re.sub(r'(</div>)\s*</div>\s*(<div class="note[^"]*" style="margin-top:6px">)', r'\1\n        \2', h, count=1)
    if _sent_depth(h)!=0:
        log.append(f"  !! SENTIMENT DIV IMBALANCE {_sent_depth(h)} — sickness/RTW may leak; not auto-fixed")
    h=relocate_coaching(h)  # keep coaching on Op's Excellence only (sickness/RTW stay on Sentiment)
    before=('data-tab="storesales"' in h)
    h=inject_sales_tab(h,store)   # rename front tab -> "Forecast / Review" + (re)build store-scoped "Sales" tab
    log.append("  ✓ Sales tab "+("rebuilt" if before else "added")+" + front tab renamed to Forecast / Review")
    open(fn,'w',encoding='utf-8').write(h)
    print(f"\n=== {fn} ({store}) ==="); print("\n".join(log))

if __name__=='__main__':
    for fn,store,coach,mature in STORES:
        try:
            patch(fn,store,coach,mature)
        except Exception as e:
            import traceback; print(f"\n!!! {fn} FAILED: {e}"); traceback.print_exc()
    print("\nDONE")
