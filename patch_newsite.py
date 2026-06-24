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
try: STAR=json.load(open('star_rating.json'))          # TEST: Grow composite star rating, gated to stores in this file (Glenvale only for now)
except FileNotFoundError: STAR={}
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
    return f"""  <!-- PILLARS START -->
  <div class="kpws">
    <a class="kpw {s_k}"><div class="kl">📈 Sales</div><div class="kv">{s_v}</div><div class="kt">{s_t}</div></a>
    <a class="kpw {o_k}"><div class="kl">🏁 Operations</div><div class="kv">{o_v}</div><div class="kt">F1 race score · last wk · target ≤190 (lower=better)</div></a>
    <a class="kpw {c_k}"><div class="kl">⭐ Customer</div><div class="kv">{c_v}</div><div class="kt">{c_t}</div></a>
    <a class="kpw {p_k}"><div class="kl">👥 People</div><div class="kv">{p_v}</div><div class="kt">{p_t}</div></a>
  </div>
  <div class="note" style="margin:2px 0 8px;background:#fff8ec;border:1px solid #f0e0bf;color:#7a5e1e;border-radius:10px;padding:8px 12px;font-size:12px"><b>At a glance</b> — <b style="color:#1c6b3d">green</b> on/above target · <b style="color:#9a2f22">red</b> below · <b style="color:#8a7a6d">grey</b> = no data/feed. Sales &amp; Operations are last week; Customer &amp; People are quarter-to-date.</div>
  <!-- PILLARS END -->
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

# DRIVERS' (per-store) leaderboard — rebuilt each week from champ['drivers']=[ [store,coach,pts], ... ]
# (the engine used to leave this tbody static, so it drifted out of sync with the constructors block)
DRV_DISP={'Olney':'Olney','Attleborough':'Attleborough','Billing Drive Thru':'Billing Drive Thru','Glenvale Drive Thru':'Glenvale Drive Thru','Northampton Drive-Thru':'Northampton Drive Thru'}
def drivers_tbody(store):
    drv=sorted(champ.get('drivers',[]), key=lambda x:-x[2])
    if not drv: return None
    own=DRV_DISP.get(store); rows=['<tbody>']
    for i,(st,co,pts) in enumerate(drv,1):
        if st==own:
            tr='<tr style="background:#fff7e9;font-weight:700">'
            nm=f'{st} <span style="font-size:10px;font-weight:700;color:#b8860b">◄ you</span>'
        else:
            tr=f'<tr style="background:{"#faf7f2" if i%2==0 else "transparent"};">'; nm=st
        rows.append(tr+'\n     <td style="text-align:center;color:#8a7a6d">'+str(i)+'</td>\n     <td>'+nm
                    +'</td>\n     <td><span class="tag t-ok" style="font-size:10.5px">'+co
                    +'</span></td>\n     <td style="text-align:right;font-weight:700">'+str(pts)+'</td>\n   </tr>')
    rows.append('</tbody>'); return ''.join(rows)

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
    # all-time record cards (record revenue week + record revenue hour)
    def _reccard(title, obj, sub):
        if not obj: return f'<div class="card" style="border-left:4px solid #b8860b"><div class="lbl">🏆 {title}</div><div class="val">—</div><div class="meta">no record yet</div></div>'
        return (f'<div class="card" style="border-left:4px solid #b8860b"><div class="lbl">🏆 {title}</div>'
                f'<div class="val">{gbp(obj["gbp"])}</div><div class="meta">all-time best · {(sub+" "+obj["label"]).strip()}</div></div>')
    recs=('<div class="cards" style="grid-template-columns:repeat(2,1fr)">'
          + _reccard("Record revenue week", d.get("rec_week"), "week of")
          + _reccard("Record revenue hour", d.get("rec_hour"), "")
          + '</div>')
    # drive-thru widget (drive-thru stores only)
    dt=d.get("drivethru"); dt_section=""
    if dt and dt.get("cars"):
        rec_line=(f'<div class="meta" style="margin-top:3px">🏆 Record week: <b>{dt["rec_cars"]:,} cars</b> · w/c {dt["rec_label"]}</div>'
                  if dt.get("rec_cars") else "")
        dt_section=(f'  <div class="section-title">🚗 Drive-thru — last week</div>\n'
                    f'  <div class="cards" style="grid-template-columns:repeat(2,1fr)">'
                    f'<div class="card"><div class="lbl">🚗 Cars last week</div><div class="val">{dt["cars"]:,}</div>'
                    f'<div class="meta">drive-thru orders through the lane till</div>{rec_line}</div>'
                    f'<div class="card"><div class="lbl">🚗 Drive-thru mix</div><div class="val">{dt["mix"]:g}%</div>'
                    f'<div class="meta">share of the store\'s transactions taken at the drive-thru</div></div>'
                    f'</div>\n')
    return (f'<!-- STORESALES START -->\n<!-- ===== TAB: Sales (store-scoped) ===== -->\n'
            f'<section class="tab-panel" id="tab-storesales">\n'
            f'  <div class="section-title">📊 Sales by day &amp; daypart — {store}</div>\n'
            f'  <div class="note">This store only · {win}, shown as <b>averages for a typical day</b> (not 4-week totals). Day-of-week = 4-week total ÷ 4 weeks; daypart = 4-week total ÷ 28 days. Dayparts: <b>Morning 5am–11am</b>, <b>Lunch 11am–2pm</b>, <b>Afternoon 2pm–5pm</b>, <b>Evening 5pm+</b>. (The Food &amp; bakery traction panel below stays as 4-week totals.)</div>\n'
            f'  <div class="section-title">🏆 All-time records</div>\n  {recs}\n'
            f'{dt_section}'
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

# ===== TEST: Grow composite star rating (gated to stores in star_rating.json — Glenvale only for now) =====
def _stars(score, size):
    # fractional gold stars: grey row behind, gold row clipped to (score/5) width
    pct=max(0,min(100, round(score/5*100,2)))
    return (f'<span style="position:relative;display:inline-block;font-size:{size}px;line-height:1;white-space:nowrap;letter-spacing:1px">'
            f'<span style="color:#ddd5cb">★★★★★</span>'
            f'<span style="position:absolute;top:0;left:0;overflow:hidden;width:{pct}%;color:#e8b923">★★★★★</span></span>')

def star_card(store):
    st=(STAR.get("stores") or {}).get(store) if STAR else None
    if not st: return ""
    comp=st["composite"]
    rows=""
    for p in st["pillars"]:
        rows+=(f'<div style="display:flex;align-items:center;gap:8px;font-size:12px;color:#3f2d22">'
               f'<span style="width:74px;font-weight:700">{p["name"]}</span>{_stars(p["star"],14)}'
               f'<span style="font-weight:800;width:26px">{p["star"]:g}</span>'
               f'<span class="mini">· {p["qtd"]} <span style="opacity:.7">({p["target"]})</span></span></div>')
    return (f'<!-- STARRATING START -->\n'
            f'<div class="card" style="border:1.5px solid #e8b923;background:linear-gradient(180deg,#fffdf5,#fff);margin:16px 0 6px;padding:16px 18px">'
            f'<div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">'
            f'<div><div class="lbl" style="color:#8a6d1e">⭐ {store} Grow score · quarter-to-date</div>'
            f'<div style="display:flex;align-items:center;gap:12px;margin-top:6px">{_stars(comp,34)}'
            f'<div style="font-size:30px;font-weight:800;color:#5b3a29">{comp:g} <span style="font-size:15px;color:#9a8a7c">/ 5</span></div></div></div>'
            f'<div style="flex:1;min-width:300px;display:flex;flex-direction:column;gap:5px">{rows}</div></div>'
            f'<div class="mini" style="margin-top:10px">Composite of the four pillars on a quarter-to-date basis. Each pillar scored 0–5 vs its target (target = 3★, stretch = 5★, miss pulls toward 0); the four are averaged. A Starbucks-Grow-style snapshot — TEST on Glenvale only.</div>'
            f'</div>\n<!-- STARRATING END -->')

def inject_star(h, store):
    # remove any prior star card (so removing a store from star_rating.json removes the widget), then insert above the pillars
    h=re.sub(r'\s*<!-- STARRATING START -->.*?<!-- STARRATING END -->', '', h, flags=re.S)
    sc=star_card(store)
    if not sc: return h
    if 'class="kpws"' in h: return h.replace('<div class="kpws">', sc+'\n  <div class="kpws">', 1)
    return re.sub(r'(</header>)', lambda m: m.group(1)+"\n  "+sc, h, count=1)

def compliance_panel(store):
    st=(STAR.get("stores") or {}).get(store) if STAR else None
    c=st and st.get("ops")
    if not c: return ""
    return (f'<!-- COMPLIANCE START -->\n'
            f'<div class="section-title" style="margin-top:4px">🛡️ Operations &amp; compliance — quarter to date</div>\n'
            f'<div class="cards" style="grid-template-columns:repeat(4,1fr)">'
            f'<div class="card"><div class="lbl">Brand audit</div><div class="val">{c.get("brand_audit"):g}<span style="font-size:15px;color:var(--muted)">/5</span></div>'
            f'<div class="meta">QTD · feeds Operations</div></div>'
            f'<div class="card"><div class="lbl">Remote audit</div><div class="val">{c.get("remote_audit"):g}<span style="font-size:15px;color:var(--muted)">/100</span></div>'
            f'<div class="meta">avg of {c.get("remote_n")} QTD · feeds Operations</div></div>'
            f'<div class="card"><div class="lbl">Compliance</div><div class="val">{c.get("compliance_pct"):g}%</div>'
            f'<div class="meta">coaching {c.get("coaching_cs_pct"):g}% + open/close {c.get("openclose_pct"):g}% (50/50) · feeds Operations</div></div>'
            f'<div class="card"><div class="lbl">Return-to-work (RTW)</div><div class="val">{c.get("rtw_pct"):g}%</div>'
            f'<div class="meta">{esc(c.get("rtw_detail",""))} · feeds People</div></div>'
            f'</div>\n'
            f'<div class="note" style="margin-top:8px">The <b>Operations</b> star is now an equal-thirds blend of <b>brand audit</b>, <b>remote audit</b> and <b>compliance</b> (coaching {c.get("coaching_cs_pct"):g}% + open/close {c.get("openclose_pct"):g}%, from the Process Street → HRP feed: {esc(c.get("openclose_detail",""))}). The <b>F1 race score below now feeds the Customer star</b> (50/50 with Google health), not Operations. RTW feeds People.</div>\n'
            f'<!-- COMPLIANCE END -->')

def inject_compliance(h, store):
    h=re.sub(r'\s*<!-- COMPLIANCE START -->.*?<!-- COMPLIANCE END -->', '', h, flags=re.S)
    cp=compliance_panel(store)
    if not cp: return h
    # insert at the very top of the Op's Excellence tab (id="tab-f1")
    return re.sub(r'(<section class="tab-panel"[^>]*id="tab-f1">)', lambda m: m.group(1)+"\n  "+cp, h, count=1)

# ---- Simply Lunch food order forecast (chilled food-to-go) -------------------
# Gated to stores with a simply_lunch_<key>.json file (Glenvale only for now).
# Reads the file build_simply_lunch.py writes from the BigQuery day-of-week pull and
# renders the recommended Mon/Wed/Sat delivery orders on the Mix & opportunity tab.
# Idempotent + self-removing (markers), like the star/compliance cards — survives Monday.
try: SLUNCH=json.load(open('simply_lunch_glenvale.json'))
except (FileNotFoundError, ValueError): SLUNCH=None
SL_STORES={'Glenvale Drive Thru'}

def simply_lunch_card(store):
    if store not in SL_STORES or not SLUNCH: return ""
    d=SLUNCH; items=d.get('items',[])
    if not items: return ""
    cov={'mon':'covers Mon–Tue','wed':'covers Wed–Fri','sat':'covers Sat–Sun'}
    def th(label,sub):
        return (f'<th style="padding:6px 9px;text-align:right;font-weight:700">{label}'
                f'<br><span style="font-weight:600;color:var(--muted);font-size:10.5px">{sub}</span></th>')
    rows=[]; cur=None
    for it in items:
        if it['category']!=cur:
            cur=it['category']
            rows.append(f'<tr><td colspan="6" style="padding:7px 9px 3px;background:var(--cream);'
                        f'font-weight:700;color:var(--brown);font-size:12px">{esc(cur)}</td></tr>')
        sparse=it.get('sparse'); nm=esc(it['item'])+(' <span style="color:var(--amber)">†</span>' if sparse else '')
        muted=';color:var(--muted)' if sparse else ''
        rows.append(
            f'<tr style="border-bottom:1px solid var(--line){muted}">'
            f'<td style="padding:6px 9px">{nm}</td>'
            f'<td style="padding:6px 9px;text-align:right;color:var(--muted)">{it["weekly_mean"]:g}</td>'
            f'<td style="padding:6px 9px;text-align:right;font-weight:700">{it["mon"]}</td>'
            f'<td style="padding:6px 9px;text-align:right;font-weight:700">{it["wed"]}</td>'
            f'<td style="padding:6px 9px;text-align:right;font-weight:700">{it["sat"]}</td>'
            f'<td style="padding:6px 9px;text-align:right;font-weight:800;color:var(--brown)">{it["weekly_order"]}</td></tr>')
    tot=lambda k: sum(i[k] for i in items)
    rows.append(
        f'<tr style="border-top:2px solid var(--line);font-weight:800;color:var(--brown)">'
        f'<td style="padding:7px 9px">Weekly total (all lines)</td>'
        f'<td style="padding:7px 9px;text-align:right">{tot("weekly_mean"):g}</td>'
        f'<td style="padding:7px 9px;text-align:right">{tot("mon")}</td>'
        f'<td style="padding:7px 9px;text-align:right">{tot("wed")}</td>'
        f'<td style="padding:7px 9px;text-align:right">{tot("sat")}</td>'
        f'<td style="padding:7px 9px;text-align:right">{tot("weekly_order")}</td></tr>')
    return (
        '<!-- SIMPLYLUNCH START -->\n'
        '<div class="section-title" style="margin-top:26px">🥪 Simply Lunch food order forecast — chilled food-to-go</div>\n'
        f'<div class="mini" style="margin-bottom:10px">Recommended order quantities for the three weekly <b>Simply Lunch</b> deliveries, '
        f'built from this store\'s average daily demand by day of week over the last <b>{d["window_weeks"]} complete weeks</b> (to {esc(d["cur_end"])}). '
        f'Deliveries land <b>Mon</b>, <b>Wed</b> and <b>Sat</b>; each order covers demand until the next delivery, plus a <b>{d["buffer_pct"]}% buffer</b>, rounded up.</div>\n'
        '<table style="width:100%;border-collapse:collapse;font-size:13px">\n'
        '<thead><tr style="text-align:left;color:var(--brown);border-bottom:2px solid var(--line)">'
        '<th style="padding:6px 9px;font-weight:700">Item</th>'
        '<th style="padding:6px 9px;text-align:right;font-weight:700">Avg sold/wk</th>'
        + th('Mon order',cov['mon']) + th('Wed order',cov['wed']) + th('Sat order',cov['sat'])
        + '<th style="padding:6px 9px;text-align:right;font-weight:700">Weekly total</th>'
        '</tr></thead>\n<tbody>\n' + "\n".join(rows) + '\n</tbody></table>\n'
        f'<div class="note" style="margin-top:12px"><b>Method.</b> For each item we take the average units sold on each day of the week '
        f'(last {d["window_weeks"]} complete weeks) and add up the days a delivery must cover: '
        f'<b>Mon</b> covers Mon–Tue (2 days), <b>Wed</b> covers Wed–Fri (3 days), <b>Sat</b> covers Sat–Sun (2 days). '
        f'Longest run is {d["max_coverage_days"]} days — within the {d["shelf_life_days"]}-day shelf life. '
        f'We then add a <b>{d["buffer_pct"]}% buffer</b> and round up. The buffer is a balance: too small and you risk lunchtime stockouts, '
        f'too large and you waste stock given the {d["shelf_life_days"]}-day life. '
        f'<span style="color:var(--amber)">†</span> = demand too sparse to forecast reliably (under {d["sparse_threshold_weekly"]}/week) — treat these as a guide and adjust by eye.</div>\n'
        '<!-- SIMPLYLUNCH END -->')

def inject_simply_lunch(h, store):
    h=re.sub(r'\s*<!-- SIMPLYLUNCH START -->.*?<!-- SIMPLYLUNCH END -->', '', h, flags=re.S)
    card=simply_lunch_card(store)
    if not card: return h
    # insert at the END of the Mix & opportunity tab (id="tab-mix"), before its </section>
    i=h.find('id="tab-mix"')
    if i<0: return h
    j=h.find('</section>', i)
    if j<0: return h
    return h[:j]+"  "+card+"\n  "+h[j:]

# --- Store FOCUS box -----------------------------------------------------------
# Regenerate the top "Focus areas" box every run from the page's OWN authoritative,
# already-refreshed figures (actbox sales / vs-forecast / CPH stat / Latest Race / wastage),
# with the trading-week label taken from the actbox. Deriving from the page (not from the
# source maps, which can lag a week) guarantees the box can never contradict the page and
# always lands on the current trading week. Fallback week label is auto-derived from today.
import datetime as _dtm_fw, re as _re_fw
def _focus_week_fallback():
    t=_dtm_fw.date.today(); ce=t-_dtm_fw.timedelta(days=((t.weekday()+1)%7)); m=ce-_dtm_fw.timedelta(days=6)
    return "week of "+str(m.day)+" "+m.strftime("%b")

def build_focus_box(h, store, coach):
    def f(pat, grp=1, default=None):
        m=_re_fw.search(pat, h); return m.group(grp) if m else default
    wk      = f(r'Last week actual sales · [Ww]/c (\d{1,2} \w{3})')          # "15 Jun"
    focus_w = ("week of "+wk) if wk else _focus_week_fallback()
    sales   = f(r'Last week actual sales · [Ww]/c \d{1,2} \w{3}</div><div class="ab-val">(£[\d,]+)')
    vsf     = f(r'<span>vs forecast</span><b[^>]*>([^<]+)</b><small>fcst £[\d,]+</small>')
    fcst    = f(r'<span>vs forecast</span><b[^>]*>[^<]+</b><small>fcst (£[\d,]+)</small>')
    cph     = f(r'<span>CPH</span><b[^>]*>(£[\d.]+)</b><small>target £\d+ · (?:met|missed)</small>')
    cpht    = f(r'<span>CPH</span><b[^>]*>£[\d.]+</b><small>target (£\d+) · (?:met|missed)</small>')
    cph_st  = f(r'<span>CPH</span><b[^>]*>£[\d.]+</b><small>target £\d+ · (met|missed)</small>')
    race    = f(r'Latest Race result</div><div class="val"[^>]*>(P\d+)')
    waste   = f(r'color:var\(--\w+\)">([\d.]+)%</div><div style="font-size:10px;color:#9a8a7c;margin-top:2px">last week')
    bullets=[]; red=False
    if sales:
        extra = (f" vs {fcst} forecast ({vsf})" if (vsf and fcst) else "")
        bullets.append(f"<b>Sales:</b> {sales} last week{extra}.")
        if vsf and vsf.strip().startswith(MINUS): red=True
    if cph and cpht:
        if cph_st=="missed":
            bullets.append(f"<b>Labour:</b> ran <b>{cph} CPH</b> vs {cpht} target — tighten the rota to sales."); red=True
        else:
            bullets.append(f"<b>Labour:</b> ran <b>{cph} CPH</b> vs {cpht} target — labour in line with sales.")
    if race:
        try: pn=int(race[1:])
        except: pn=0
        tail=" — reset the weekend routine." if pn>=15 else " — holding a strong grid slot."
        if pn>=15: red=True
        bullets.append(f"<b>Op's Excellence:</b> latest Race finish <b>{race}</b> (Coach {coach}){tail}")
    if waste:
        try: wv=float(waste)
        except: wv=0.0
        wt=" — over the 3% target, tighten pars." if wv>3 else " — within the 3% target."
        if wv>3: red=True
        bullets.append(f"<b>Wastage:</b> {waste}% last week{wt}")
    if not bullets:
        bullets.append("<b>Focus:</b> review last week's sales, labour, Op's Excellence and wastage.")
    cls="focusmod red" if red else "focusmod"
    lis="".join("\n      <li>%s</li>"%b for b in bullets)
    return ('<div class="%s">\n    <h2>\U0001F3AF Focus areas — %s</h2>\n    <ul>%s\n    </ul>\n  </div>'
            % (cls, focus_w, lis))

def patch(fn,store,coach,mature):
    h=open(fn,encoding='utf-8').read(); log=[]
    def sub(pat,repl,n_expected,label,flags=0):
        nonlocal h
        h2,nn=re.subn(pat,repl,h,count=n_expected,flags=flags)
        if nn: h=h2; log.append(f"  ✓ {label} ({nn})")
        else: log.append(f"  ✗ {label} — NOT FOUND")
        return nn
    r=R[store]; LW=r['lw26']
    # 1) PILLAR CSS (inject once) + pillar block (RE-RENDER every run via PILLARS markers,
    #    mirroring how the star-rating card re-renders). Strip any prior block — marker form
    #    or legacy unmarked kpws+note — then re-inject with current values so the pillars
    #    never go stale.
    if 'class="kpws"' not in h:
        sub(r'</style>', PILLAR_CSS+"\n</style>",1,"pillar CSS")
    # strip prior pillar block: new marker form first, then legacy unmarked form
    h=re.sub(r'\s*<!-- PILLARS START -->.*?<!-- PILLARS END -->', '', h, flags=re.S)
    h=re.sub(r'\s*<div class="kpws">.*?At a glance.*?</div>', '', h, flags=re.S)
    sub(r'(</header>)', r'\1\n'+pillars(store).replace('\\','\\\\'),1,"pillar block (re-render)")
    # 1b) TEST Grow star rating + compliance panel (gated to stores in star_rating.json — Glenvale only). Idempotent + self-removing.
    h=inject_star(h,store)
    h=inject_compliance(h,store)
    h=inject_simply_lunch(h,store)   # Simply Lunch food order forecast on the Mix tab (Glenvale)
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
    # 6b) drivers' (per-store) leaderboard tbody — rebuild from champ['drivers'] (was previously left static)
    dtb=drivers_tbody(store)
    if dtb:
        di=h.find('Drivers'); tb=h.find('<tbody>',di) if di>=0 else -1; te=h.find('</tbody>',tb) if tb>=0 else -1
        if di>=0 and tb>=0 and te>=0:
            h=h[:tb]+dtb+h[te+8:]; log.append("  ✓ drivers leaderboard rebuilt")
        else: log.append("  ✗ drivers leaderboard — tbody markers not found")
    else:
        log.append("  • drivers leaderboard held (no champ['drivers'] supplied)")
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
    # FOCUS BOX (top of page) — rebuild LAST, from the page's now-current figures.
    _newbox=build_focus_box(h,store,coach)
    h2,_nn=re.subn(r'<div class="focusmod[^"]*">\s*<h2>\U0001F3AF Focus areas[\s\S]*?</ul>\s*</div>', lambda m:_newbox, h, count=1)
    if _nn: h=h2; log.append('  ✓ focus box (re-render)')
    else: log.append('  ✗ focus box — NOT FOUND')
    open(fn,'w',encoding='utf-8').write(h)
    print(f"\n=== {fn} ({store}) ==="); print("\n".join(log))

if __name__=='__main__':
    for fn,store,coach,mature in STORES:
        try:
            patch(fn,store,coach,mature)
        except Exception as e:
            import traceback; print(f"\n!!! {fn} FAILED: {e}"); traceback.print_exc()
    print("\nDONE")
