# -*- coding: utf-8 -*-
"""Bewiched Star Card — estate build (21 stores). QTD/YTD toggle + last-week layer."""
import json, re, os
HERE=os.path.dirname(os.path.abspath(__file__))
BW=HERE
OUT=HERE
def L(f): return json.load(open(os.path.join(BW,f)))
# Bewiched wordmark (repo asset bewiched-logo.png, recoloured navy for the white card), embedded as data URI
import base64 as _b64
try: LOGO_URI="data:image/png;base64,"+_b64.b64encode(open(os.path.join(BW,"_star_logo_dark.png"),"rb").read()).decode()
except Exception: LOGO_URI=""
LOGO_IMG=("<img class='blogo' src='%s' alt='Bewiched Coffee'>"%LOGO_URI) if LOGO_URI else ""
# reporting week label — read the pipeline's current week-ending so it stays in step with the data
import datetime as _dt
try:
    _ce=_dt.date.fromisoformat(json.load(open(os.path.join(BW,"eos_scorecard.json")))["cur_end"])
    WKLABEL="w/e %d %s %d"%(_ce.day,_ce.strftime("%b"),_ce.year)
except Exception:
    WKLABEL="w/e 2 Aug 2026"

CANON = ["Northampton Drive Thru","Rushden Lakes","Northampton Grosvenor","Kettering",
 "Leamington Parade","Fletton Quays","Market Harborough","Wellingborough Market St","Wellingborough Train Station",
 "Rothwell","Burton Latimer","Corby","Rugby","Higham Ferrers","Peterborough Bridge St","Olney",
 "Lower Heathcote","Billing Drive Thru","Glenvale Drive Thru","Balsall Common","Attleborough"]
def norm(s):
    s=str(s).strip().lower().replace("’","'")
    s=re.sub(r'^\d+\s+','',s)
    s=s.replace('-',' '); s=re.sub(r'\s+',' ',s)
    if ('drive' in s and 'northampton' in s) or s in ('drive thru','northampton dt'): return "Northampton Drive Thru"
    if s.startswith('northampton'): return "Northampton Grosvenor"
    if 'glenvale' in s: return "Glenvale Drive Thru"
    if 'billing' in s: return "Billing Drive Thru"
    if 'balsall' in s: return "Balsall Common"
    if 'attleborough' in s: return "Attleborough"
    if 'train station' in s: return "Wellingborough Train Station"
    if 'market st' in s or 'market street' in s or s=='wellingborough': return "Wellingborough Market St"
    if 'rushden' in s or s=='lakes': return "Rushden Lakes"
    if 'fletton' in s: return "Fletton Quays"
    if 'bridge street' in s or s=='peterborough': return "Peterborough Bridge St"
    if 'heathcote' in s: return "Lower Heathcote"
    if 'harborough' in s: return "Market Harborough"
    if 'leamington parade' in s: return "Leamington Parade"
    if 'burton' in s: return "Burton Latimer"
    if 'higham' in s: return "Higham Ferrers"
    if s=='kettering': return "Kettering"
    if s=='corby': return "Corby"
    if s=='olney': return "Olney"
    if s=='rothwell': return "Rothwell"
    if s=='rugby': return "Rugby"
    return None

D={s:{} for s in CANON}
rec=L("allstores.json")['rec']
for k,r in rec.items():
    c=norm(k)
    if not c: continue
    D[c]['yoy_lw']=r.get('yoy_lw')                                             # last-week sales YoY
    D[c]['gc_lw']=round((r['tx26']/r['tx25']-1)*100,1) if r.get('tx25') else None  # last-week guest-count YoY
    D[c]['qc']=r.get('q_cur') or {}                                            # this quarter (QTD)
    D[c]['qp']=r.get('q_prev') or {}                                           # previous quarter (for YTD blend)
    D[c]['f1']=r.get('f1_finish')
    br=r.get('audit_qtd'); rm=r.get('remote_qtd100')
    D[c]['brand']=round((br + rm/20)/2,2) if (br is not None and rm is not None) else None
for k,v in L("cos_metrics.json")['stores'].items():
    c=norm(k)
    if c: D[c]['gp']=v.get('gp_qtd'); D[c]['gp_week']=v.get('gp_pct')
for k,v in L("cph_targets.json")['targets'].items():
    c=norm(k)
    if c: D[c]['sph_tgt']=v
# per-store SPH ACTUAL from the banked history (sph_history.csv, rolling QTD = Σsales/Σhours)
SPH_HIST_URL="https://github.com/Fontana1974/bewiched-dashboards/blob/main/sph_history.csv"
import csv as _csv, os as _os
_agg={}
try:
    with open(_os.path.join(BW,'sph_history.csv')) as _fh:
        for r in _csv.DictReader(_fh):
            c=norm(r.get('store'))
            if not c: continue
            a=_agg.setdefault(c,[0.0,0.0]); a[0]+=float(r['sales']); a[1]+=float(r['hours'])
except Exception: pass
for c in CANON: D[c]['sph']=round(_agg[c][0]/_agg[c][1],1) if c in _agg and _agg[c][1] else None
# RMS Health (Rate My Shift, 1-5) — qtd avg scores, weekly avg = last-week chip, prevq = QoQ
for k,v in L("rms_feed.json")['per_store'].items():
    c=norm(k)
    if c:
        D[c]['rms']=v.get('qtd',{}).get('avg'); D[c]['rms_wk']=v.get('weekly',{}).get('avg'); D[c]['rms_n']=v.get('qtd',{}).get('n')
        D[c]['rms_q2']=(v.get('prevq') or {}).get('avg')                       # prior-quarter RMS
# Google reviews raw (rating + count, qtd) — for the sub-note "★rating · N reviews"
for k,v in L("_google_qtd.json").items():
    c=norm(k)
    if c: D[c]['goog']=v[1]; D[c]['goog_n']=v[0]
# Google HEALTH — the EOS per-store composite from storehealth.json
#   g_health = avg_star*0.5 + min(reviews/quarterly_target, 1)*2.5  (0-5 scale; EOS green >= 3.32)
_GH_TGT={}
try:
    _sh=L("storehealth.json"); _GH_TGT={norm(k):t for k,t in _sh.get('targets',{}).items() if norm(k)}
    for k,v in _sh.get('stores',{}).items():
        c=norm(k)
        if c: D[c]['gh']=v.get('g_health'); D[c]['gh_n']=v.get('g_n'); D[c]['gh_avg']=v.get('g_avg'); D[c]['gh_tgt']=v.get('g_target')
except Exception: pass
# prior-quarter (Q2) Google Health via the SAME formula (Q2 count+rating from _google_prevq, same per-store review target)
try:
    for k,v in L("_google_prevq.json").items():
        c=norm(k)
        if not c: continue
        D[c]['goog_q2']=v[1]; _t=_GH_TGT.get(c) or D[c].get('gh_tgt')
        if _t and v[1] is not None: D[c]['gh_q2']=round(v[1]*0.5+min(v[0]/_t,1)*2.5,2)
except Exception: pass
# no Q2 reviews -> Q2 Google Health is a hard 0.0 (same rule as the current period)
for c in CANON:
    if D[c].get('gh') is not None: D[c].setdefault('gh_q2',0.0)
# F1 QTD avg Total Score (lower=better, target 175) + prior-quarter (Q2) score for the QoQ chip
try:
    for k,v in L("f1_detail.json").items():
        c=norm(k)
        if not c or not isinstance(v,dict): continue
        D[c]['f1_q3']=(v.get('race_qtd') or {}).get('score'); D[c]['f1_q2']=(v.get('race_q2') or {}).get('score')
        _ra=v.get('race') or []; D[c]['f1_latest']=_ra[5] if len(_ra)>5 else None   # latest race Total Score
except Exception: pass
# quarter-reset drivers championship position (allstores.champ.drivers, sorted by pts desc; season resets each qtr)
try:
    _dr=L("allstores.json").get("champ",{}).get("drivers",[]); _cn=len(_dr)
    for _i,_row in enumerate(_dr,1):
        c=norm(_row[0])
        if c: D[c]['champ_rank']=_i; D[c]['champ_n']=_cn
except Exception: pass
# Food GP quarter-over-quarter (cos_history weekly per-store gp) for the "vs last quarter" comparison
_QCUT='2026-06-29'   # current quarter start (q_cur ~ from here); earlier weeks = previous quarter
_gp_this={}; _gp_prev={}
for _dt,_stores in L("cos_history.json").get('weeks',{}).items():
    for k,v in _stores.items():
        c=norm(k); g=(v or {}).get('gp')
        if not c or g is None: continue
        (_gp_this if _dt>=_QCUT else _gp_prev).setdefault(c,[]).append(g)
for c in CANON:
    D[c]['gp_thisq']=round(sum(_gp_this[c])/len(_gp_this[c]),1) if _gp_this.get(c) else None
    D[c]['gp_prevq']=round(sum(_gp_prev[c])/len(_gp_prev[c]),1) if _gp_prev.get(c) else None
OC={"Kettering":100,"Balsall Common":100,"Glenvale Drive Thru":100,"Rugby":98,"Rushden Lakes":98,
 "Rothwell":98,"Northampton Grosvenor":98,"Leamington Parade":98,"Northampton Drive Thru":96,
 "Billing Drive Thru":96,"Wellingborough Train Station":94,"Attleborough":94,"Burton Latimer":92,
 "Peterborough Bridge St":90,"Market Harborough":90,"Higham Ferrers":88,"Olney":87,"Fletton Quays":85,
 "Wellingborough Market St":81,"Corby":77,"Lower Heathcote":73}
for c,v in OC.items(): D[c]['oc']=v
bench=L("bench.json")
def cell(row,i): return str(row[i]).strip() if len(row)>i and row[i] else ""
for row in bench['rows']:
    c=norm(row[0])
    if not c: continue
    sm=cell(row,1); am=cell(row,2); s1=cell(row,4); succ=any(cell(row,i) for i in range(6,10))
    status='red' if not sm else ('green' if (sm and am and s1 and succ) else 'amber')
    D[c]['bench']=status
    D[c]['bench_detail']=("SM vacant" if not sm else ("bench-ready" if status=='green' else
        "not bench-ready ("+("Assistant Manager" if not am else "Supervisor 1" if not s1 else "successor")+" vacant)"))
ns_sites={}
for r in L("new_starter.json")['per_site']:
    c=norm(r['site'])
    if c: ns_sites[c]=r['pct']
for c in CANON: D[c]['ns']=ns_sites.get(c)
def _findkey(o,key):
    if isinstance(o,dict):
        if key in o: return o[key]
        for v in o.values():
            r=_findkey(v,key)
            if r is not None: return r
    elif isinstance(o,list):
        for v in o:
            r=_findkey(v,key)
            if r is not None: return r
    return None
_bs=_findkey(L("maintenance.json"),'bystore') or []
maint={norm(r[0]):r[3] for r in _bs if isinstance(r,list) and len(r)>3 and norm(r[0])}
for c in CANON: D[c]['maint_open']=maint.get(c,0)
ACC={"Kettering","Olney"}

def clamp(x,a=0.0,b=1.0): return max(a,min(b,x))
import json as _json

# ---- window (QTD / YTD) metric values --------------------------------------
# QTD = this quarter to date (solid). YTD = year-to-date roll-up: Sales & Guest-count
# YoY are blended across the held quarters (Q-prev + Q-cur, sales-weighted); the other
# metrics have only shallow per-store history so YTD carries the QTD figure, flagged
# "history building" until the year fills out.
def _blend(qc,qp,key):
    a=qc.get(key); b=qp.get(key); sa=qc.get('sales') or 0; sb=qp.get('sales') or 0
    if a is None and b is None: return None
    if a is None: return b
    if b is None or (sa+sb)==0: return a
    return round((a*sa+b*sb)/(sa+sb),1)
for c in CANON:
    d=D[c]; qc=d.get('qc') or {}; qp=d.get('qp') or {}
    d['win']={
        # QTD view LEADS with last completed week vs the same week last year (52-week-aligned LFL)
        'qtd':{'sales':d.get('yoy_lw'),'gc':d.get('gc_lw')},
        # YTD view leads with the quarter-weighted blended YoY (annual roll-up)
        'ytd':{'sales':_blend(qc,qp,'yoy_sales'),'gc':_blend(qc,qp,'yoy_tx')},
    }
WINDOWS=('qtd','ytd')
def score(c,win):
    d=D[c]; wv=d['win'][win]
    # Team = RMS Health + New-starter (bench dropped -> lives only as an Urgent flag)
    rms=d.get('rms'); rms_r=clamp(rms/5) if rms is not None else None
    ns_r=None  # new-starter 0%-logged -> not real, excluded
    _t=[x for x in (rms_r,ns_r) if x is not None]; team=(sum(_t)/len(_t)*5) if _t else None
    # Ops = F1 (QTD avg Total Score vs 175 target, lower=better) + Google HEALTH (EOS composite, 0-5, green>=3.32)
    f1s=d.get('f1_q3'); gh=d.get('gh')
    f1_r=clamp(175.0/f1s) if f1s else None
    goog_r=clamp(gh/5) if gh is not None else None
    _o=[x for x in (f1_r,goog_r) if x is not None]; ops=(sum(_o)/len(_o)*5) if _o else None
    yr=lambda v: clamp((v+10)/20) if v is not None else None
    _cp=[x for x in (yr(wv['sales']),yr(wv['gc'])) if x is not None]
    cust=(sum(_cp)/len(_cp)*5) if _cp else None
    gp=d.get('gp'); gp_r=clamp(gp/71) if gp is not None else None
    sphv=d.get('sph'); spht=d.get('sph_tgt') or 55; sph_r=clamp(sphv/spht) if sphv is not None else None
    _pp=[x for x in (gp_r,sph_r) if x is not None]; profit=(sum(_pp)/len(_pp)*5) if _pp else None
    pil={'Team':team,'Ops':ops,'Customers':cust,'Profit':profit}
    av=[v for v in pil.values() if v is not None]
    real={'RMS':d.get('rms') is not None,'New starter':False,'F1':d.get('f1_q3') is not None,'Google':d.get('gh') is not None,
        'Sales YoY':wv['sales'] is not None,'Guest counts':wv['gc'] is not None,
        'SPH':d.get('sph') is not None,'Food GP':d.get('gp') is not None}
    return {'pillars':pil,'overall':(sum(av)/len(av) if av else None),'real':real,
            'real_n':sum(1 for v in real.values() if v),'sales':wv['sales'],'gc':wv['gc']}
for c in CANON: D[c]['S']={w:score(c,w) for w in WINDOWS}
RANKED={w:sorted(CANON,key=lambda c:(D[c]['S'][w]['overall'] if D[c]['S'][w]['overall'] is not None else -1),reverse=True) for w in WINDOWS}
RANK={w:{c:i for i,c in enumerate(RANKED[w],1)} for w in WINDOWS}

CSS="""
:root{--bg:#eef1f4;--panel:#fff;--line:#e3e8ee;--text:#16212c;--muted:#5f6e7b;--dim:#93a0ac;
--gold:#e8b923;--stargrey:#ddd5cb;--green:#1f8a4c;--greenbg:#e7f4ec;--greenbd:#bfe3cd;
--red:#c0392b;--redbg:#fbeae8;--redbd:#f0cdc8;--amber:#b9770f;--amberbg:#fdf1dd;--amberbd:#e7c98f;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;padding:22px}
.wrap{max-width:1180px;margin:0 auto}
.starwrap{position:relative;display:inline-block;white-space:nowrap;letter-spacing:1.5px;line-height:1;vertical-align:middle}
.star-base{color:var(--stargrey)} .star-fill{position:absolute;left:0;top:0;overflow:hidden;color:var(--gold)}
.hit{color:var(--green)} .miss{color:var(--red)} .warn{color:var(--amber)} .neutral{color:var(--dim)}
.tglwrap{display:flex;align-items:center;gap:14px;margin-bottom:16px}
.tgl{display:inline-flex;background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:3px;gap:2px;box-shadow:0 1px 3px rgba(20,40,60,.05)}
.tgl button{font:inherit;font-size:12px;font-weight:800;letter-spacing:.6px;border:0;background:transparent;color:var(--muted);padding:7px 20px;border-radius:8px;cursor:pointer}
.tgl button.on{background:var(--amber);color:#fff;box-shadow:0 1px 2px rgba(20,40,60,.15)}
.tglnote{font-size:11px;color:var(--dim);line-height:1.4}
.wk{display:inline-block;font-size:9.5px;color:var(--muted);font-weight:800;background:#eef2f6;border-radius:5px;padding:1px 7px;margin-top:4px}
.cmps{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.cmp{display:inline-flex;align-items:center;gap:3px;font-size:9.5px;font-weight:800;color:var(--muted);background:#eef2f6;border-radius:5px;padding:1px 6px;line-height:1.5}
.cmp b{font-weight:800;color:var(--dim);font-size:8px;text-transform:uppercase;letter-spacing:.4px}
.cmp.up{color:var(--green);background:var(--greenbg)}
.cmp.dn{color:var(--red);background:var(--redbg)}
.cmp.fl{color:var(--muted);background:#eef2f6}
.bld{display:inline-block;font-size:9px;color:var(--amber);font-weight:800;background:var(--amberbg);border:1px solid var(--amberbd);border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:middle}
.vsy{font-size:10.5px;font-weight:800;margin-left:9px;white-space:nowrap}
.vsy em{font-style:normal;color:var(--dim);font-weight:700;font-size:9px;letter-spacing:.3px}
.vsy.up{color:var(--green)}.vsy.dn{color:var(--red)}.vsy.fl{color:var(--dim)}
.blogo{height:30px;width:auto;display:block;margin-bottom:7px}
"""
def stars(score,size):
    pct=clamp((score or 0)/5*100,0,100)
    return ('<span class="starwrap" style="font-size:%dpx"><span class="star-base">&#9733;&#9733;&#9733;&#9733;&#9733;</span>'
            '<span class="star-fill" style="width:%.1f%%">&#9733;&#9733;&#9733;&#9733;&#9733;</span></span>'%(size,pct))
def pcol(v): return 'neutral' if v is None else ('hit' if v>=4 else ('warn' if v>=3 else 'miss'))
def fmt(v): return '%.1f'%v if v is not None else '—'
WLAB={'qtd':'rolling QTD','ytd':'year to date (rolling)'}

# ---------------- LEADERBOARD ----------------
def vsytd(c):
    qov=D[c]['S']['qtd']['overall']; yov=D[c]['S']['ytd']['overall']
    if qov is None or yov is None: return "<span class='vsy fl'>&ndash; <em>vs YTD</em></span>"
    dv=qov-yov
    if dv>=0.05: return "<span class='vsy up'>&#9650;%.1f <em>vs YTD</em></span>"%dv
    if dv<=-0.05: return "<span class='vsy dn'>&#9660;%.1f <em>vs YTD</em></span>"%(-dv)
    return "<span class='vsy fl'>&#8776;0 <em>vs YTD</em></span>"
def vsytd_card(c):
    qov=D[c]['S']['qtd']['overall']; yov=D[c]['S']['ytd']['overall']
    if qov is None or yov is None: return "<span class='vsyc fl'>&ndash; <em>vs YTD</em></span>"
    dv=qov-yov
    if dv>=0.05: return "<span class='vsyc up'>&#9650; %.1f <em>vs YTD</em></span>"%dv
    if dv<=-0.05: return "<span class='vsyc dn'>&#9660; %.1f <em>vs YTD</em></span>"%(-dv)
    return "<span class='vsyc fl'>&#8776; 0 <em>vs YTD</em></span>"
def lb_rows(win):
    out=""
    for c in RANKED[win]:
        S=D[c]['S'][win]; ov=S['overall']; p=S['pillars']; rn=S['real_n']
        rcls='hit' if rn>=6 else ('warn' if rn>=5 else 'miss')
        out+=('<tr><td class="rk">%d</td><td class="nm">%s</td>'
          '<td class="ov"><span class="ovn">%s</span> %s %s</td>'
          '<td class="pl %s">%s</td><td class="pl %s">%s</td><td class="pl %s">%s</td><td class="pl %s">%s</td>'
          '<td class="cov %s">%d / 8</td></tr>'%(RANK[win][c],c,fmt(ov),stars(ov,15),vsytd(c),
          pcol(p['Team']),fmt(p['Team']),pcol(p['Ops']),fmt(p['Ops']),pcol(p['Customers']),fmt(p['Customers']),
          pcol(p['Profit']),fmt(p['Profit']),rcls,rn))
    return out
TBODY={w:lb_rows(w) for w in WINDOWS}
LEAD=("<!doctype html><html><head><meta charset='utf-8'><style>"+CSS+"""
.top{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:14px}
.brand{font-size:12px;letter-spacing:3px;color:var(--amber);font-weight:800;text-transform:uppercase}
.h1{font-size:26px;font-weight:800;margin-top:3px}.sub{color:var(--muted);font-size:12px;margin-top:3px}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(20,40,60,.05)}
thead th{font-size:10.5px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);font-weight:800;text-align:left;padding:11px 10px;background:#f7f9fb;border-bottom:1px solid var(--line)}
th.plh{text-align:center;width:74px}
tbody td{padding:9px 10px;border-bottom:1px solid #eef1f5;font-size:13px}
tbody tr:last-child td{border-bottom:none}
.rk{font-weight:800;color:var(--muted);width:32px;text-align:center}.nm{font-weight:800;font-size:13.5px}
.ov{white-space:nowrap}.ovn{font-weight:800;font-size:14px;margin-right:6px}
.pl{font-weight:800;text-align:center;width:74px}.cov{font-size:10.5px;color:var(--dim)}
.foot{margin-top:12px;font-size:11px;color:var(--dim);line-height:1.55}.foot b{color:var(--muted)}
</style></head><body><div class='wrap'>
<div class='top'><div><div class='brand'>Bewiched &middot; Star Card</div><div class='h1'>Estate leaderboard &mdash; all 21 stores</div>
<div class='sub'>Ranked by overall Star score &middot; <span id='winlab'>rolling QTD</span> &middot; """+WKLABEL+"""</div></div>
<div style='text-align:right'><div class='sub'>Gold = overall rating &middot; pillars: <span class='hit'>green &ge;4</span> &middot; <span class='warn'>amber 3&ndash;4</span> &middot; <span class='miss'>red &lt;3</span></div></div></div>
<div class='tglwrap'><div class='tgl'><button data-w='qtd' class='on'>QTD</button><button data-w='ytd'>YTD</button></div>
<div class='tglnote'>Ranking recomputes for the selected window. Each overall score carries a <span class='vsy up'>&#9650;<em>vs YTD</em></span> / <span class='vsy dn'>&#9660;<em>vs YTD</em></span> trend (current QTD overall vs that store's YTD overall). <b>QTD</b> = quarter to date (solid); <b>YTD</b> = year-to-date roll-up.</div></div>
<table><thead><tr><th>#</th><th>Store</th><th>Overall Star Score</th><th class='plh'>Team</th><th class='plh'>Ops</th><th class='plh'>Customers</th><th class='plh'>Profit</th><th>Real data</th></tr></thead><tbody id='lbody'>"""
+TBODY['qtd']+"""</tbody></table>
<div class='foot'><b>Pillars:</b> Team (<b>RMS Health + New-starter</b>) &middot; Ops (<b>F1 avg Total Score QTD (target &le;175) + Google Health (EOS composite, green &ge;3.32)</b>) &middot; Customers (<b>sales + guest YoY, last completed week vs same week last year</b> on QTD; blended YoY on YTD) &middot; Profit (SPH + Food GP%). <b>Brand foundations</b> (Brand &amp; Remote + Open/Close %) and <b>Urgent support</b> (coach vacancy, bench gap, accidents, red maintenance) sit outside the score. <b>Real data (N / 8):</b> count of the 8 scored metrics (RMS, New-starter, F1, Google, Sales YoY, Guest counts, SPH, Food GP) on genuine real data. <b>SPH is scored</b> from the banked sph_history.csv. QTD is the solid view; YTD blends Sales &amp; Guest YoY across the held quarters while RMS, Google, SPH, F1 &amp; Food GP carry QTD depth ("history building") until the year accumulates. Bench now sits only in Urgent support (not double-counted); New-starter is 0%-logged (not scored). Overall = mean of available pillars. Targets indicative for Matt to set.</div>
</div>
<script>
var TBODY=""" + _json.dumps(TBODY) + """, WLAB=""" + _json.dumps(WLAB) + """;
document.querySelectorAll('.tgl button').forEach(function(b){b.onclick=function(){
  document.querySelectorAll('.tgl button').forEach(function(x){x.classList.remove('on')});
  b.classList.add('on'); var w=b.getAttribute('data-w');
  document.getElementById('lbody').innerHTML=TBODY[w];
  document.getElementById('winlab').textContent=WLAB[w];
};});
</script>
</body></html>""")
LEAD=LEAD.replace("<div class='brand'>Bewiched &middot; Star Card</div>", LOGO_IMG+"<div class='brand'>Star Card</div>")

# ---------------- STORE CARD ----------------
def yn(label,trig,amber=False):
    cls='warn' if (trig and amber) else ('on' if trig else '')
    chip='warn' if (trig and amber) else ('yes' if trig else 'no')
    return "<div class='flag %s'><span class='q'>%s</span><span class='a %s'>%s</span></div>"%(cls,label,chip,'Yes' if trig else 'No')
def hm(v,tgt,unit='',f='%s'):
    if v is None: return ('neutral','n/a')
    ok=v>=tgt; return ('hit' if ok else 'miss',(f%v)+unit+(' ✓' if ok else ' ✗'))
def card(c,win):
    d=D[c]; S=D[c]['S'][win]; p=S['pillars']; ov=S['overall']; rk=RANK[win][c]
    ytd=(win=='ytd'); win_tag=('YTD' if ytd else 'QTD')
    qc=d.get('qc') or {}; qp=d.get('qp') or {}
    occ,oct=hm(d.get('oc'),90,'%','%d'); brc,brt=hm(d.get('brand'),4.6,'','%.2f')
    # ---- UNIFORM Starbucks-style metric widget: title+window, big value+sub, then two labelled rows ----
    def _arrow(dv,hib):
        up=dv>0.049; dn=dv<-0.049; imp=(dv>0) if hib else (dv<0)
        ar='&#9650;' if up else ('&#9660;' if dn else '&#8776;')
        return (ar,('up' if imp else 'dn') if (up or dn) else 'fl')
    def dl(H,prior,hib,unit,dec=1):     # delta chip: current headline H vs a prior value
        if H is None or prior is None: return "<span class='dlt fl'>&ndash;</span>"
        ar,cls=_arrow(H-prior,hib)
        return "<span class='dlt %s'>%s%s%s</span>"%(cls,ar,('%.*f'%(dec,abs(H-prior))),unit)
    def rw(lbl,prior_disp,delta_html):
        pv=("<span class='mw-pv'>%s</span>"%prior_disp) if prior_disp is not None else ''
        return "<div class='mw-row'><span class='mw-lbl'>%s</span><span class='mw-cmp'>%s%s</span></div>"%(lbl,pv,delta_html)
    def brow(lbl,txt): return rw(lbl,None,"<span class='dlt fl'>%s</span>"%txt)
    def MW(title,tag,big,bigcls,sub,rows):
        return ("<div class='mw'><div class='mw-top'><span class='mw-title'>%s</span><span class='mw-win'>%s</span></div>"
                "<div class='mw-head'><span class='mw-big %s'>%s</span><span class='mw-sub'>%s</span></div>%s</div>")%(title,tag,bigcls,big,sub,rows)
    def hc(ok): return 'hit' if ok else 'miss'
    def pct(v): return ('%+.1f%%'%v) if v is not None else None
    # TEAM — RMS Health + New-starter
    rmsv=d.get('rms'); _rw=d.get('rms_wk'); _rq2=d.get('rms_q2')
    team=(MW('RMS health',win_tag,('%.1f'%rmsv) if rmsv is not None else 'n/a',(hc(rmsv>=4.0) if rmsv is not None else 'neutral'),'target &ge;4.0 / 5',
            rw('vs Last Week',('%.1f'%_rw) if _rw is not None else None,dl(rmsv,_rw,True,''))
           +rw('vs Last Quarter',('%.1f'%_rq2) if _rq2 is not None else None,dl(rmsv,_rq2,True,'')))
         +MW('New starter health',win_tag,'n/a','neutral','0% logged (not scored)',
            brow('vs Last Week','n/a')+brow('vs Last Quarter','n/a')))
    # OPS — F1 avg Total Score (lower better, target 175) + Google reviews
    f1s=d.get('f1_q3'); _f2=d.get('f1_q2'); _fl=d.get('f1_latest'); _cr=d.get('champ_rank'); _cn=d.get('champ_n') or 21
    f1_sub=('Championship P%d/%d &middot; target &le;175'%(_cr,_cn)) if _cr else 'target &le;175'
    gh=d.get('gh'); gh_n=d.get('gh_n'); gh_avg=d.get('gh_avg'); _ghq2=d.get('gh_q2')
    if gh_avg is not None: gh_sub='&#9733;%.2f &middot; %d reviews &middot; target &ge;3.32'%(gh_avg,gh_n or 0)
    elif gh is not None: gh_sub='0 reviews in period &middot; target &ge;3.32'
    else: gh_sub='target &ge;3.32 / 5'
    ops=(MW('F1 race (QTD avg)',win_tag,('%.0f'%f1s) if f1s is not None else 'n/a',(hc(f1s<=175) if f1s is not None else 'neutral'),f1_sub,
            rw('vs Last Week',('%.0f'%_fl) if _fl is not None else None,dl(f1s,_fl,False,''))
           +rw('vs Last Quarter',('%.0f'%_f2) if _f2 is not None else None,dl(f1s,_f2,False,'')))
        +MW('Google Health',win_tag,('%.2f'%gh) if gh is not None else 'n/a',(hc(gh>=3.32) if gh is not None else 'neutral'),gh_sub,
            rw('vs Last Week',None,"<span class='dlt fl'>&ndash;</span>")
           +rw('vs Last Quarter',('%.2f'%_ghq2) if _ghq2 is not None else None,dl(gh,_ghq2,True,'',2))))
    # CUSTOMERS — Sales + Guest YoY (headline = last completed week vs LY on QTD; blended YoY on YTD)
    lws=d.get('yoy_lw'); lwg=d.get('gc_lw'); qs=qc.get('yoy_sales'); qg=qc.get('yoy_tx'); ps=qp.get('yoy_sales'); pg=qp.get('yoy_tx')
    sH=S['sales']; gH=S['gc']; s_tag=('LAST WK' if not ytd else 'YTD'); s_sub=('vs same wk last yr' if not ytd else 'blended YoY')
    _rowA='QTD'   # Customers headline is already last-week, so top row shows the quarter (not "vs last week")
    cust=(MW('Sales (YoY)',s_tag,pct(sH) or 'n/a',(hc(sH>=5) if sH is not None else 'neutral'),s_sub,
            rw('vs '+_rowA,pct(qs),dl(sH,qs,True,'%'))+rw('vs Last Quarter',pct(ps),dl(sH,ps,True,'%')))
         +MW('Guest counts (YoY)',s_tag,pct(gH) or 'n/a',(hc(gH>=5) if gH is not None else 'neutral'),s_sub,
            rw('vs '+_rowA,pct(qg),dl(gH,qg,True,'%'))+rw('vs Last Quarter',pct(pg),dl(gH,pg,True,'%'))))
    # PROFIT — SPH + Food GP
    sphv=d.get('sph'); spht=d.get('sph_tgt') or 55
    if sphv is None:
        sph_w=MW('SPH',win_tag,'n/a','neutral','awaiting planner hours (franchise)',brow('vs Last Week','n/a')+brow('vs Last Quarter','n/a'))
    else:
        sph_w=MW('SPH',win_tag,'&pound;%.1f'%sphv,hc(sphv>=spht),'target &pound;%s/hr'%spht,
            rw('vs Last Week','&pound;%.1f'%sphv,"<span class='dlt fl'>&#8776;0</span>")+brow('vs Last Quarter','building'))
    gpq=d.get('gp'); gpw=d.get('gp_week'); gp_pv=d.get('gp_prevq')
    prof=(sph_w
         +MW('Food GP %',win_tag,('%.1f%%'%gpq) if gpq is not None else 'n/a',(hc(gpq>=71) if gpq is not None else 'neutral'),'target &ge;71%',
            rw('vs Last Week',('%.1f%%'%gpw) if gpw is not None else None,dl(gpq,gpw,True,'%'))
           +rw('vs Last Quarter',('%.1f%%'%gp_pv) if gp_pv is not None else None,dl(gpq,gp_pv,True,'%'))))
    def pc(nm,scr,body): return "<div class='pcard'><div class='phead'><div class='pname'>%s</div><div class='pstar'>%s<div class='pscore'>%s / 5</div></div></div>%s</div>"%(nm,stars(scr,16),fmt(scr),body)
    flags=(yn('Store coach vacancy?',d.get('bench')=='red')+yn('Bench gap?',d.get('bench') in ('amber','red'),amber=(d.get('bench')=='amber'))
          +yn('Accidents / near misses?',c in ACC)+yn('Red maintenance issues?',d.get('maint_open',0)>=3))
    cwk=(('Year to date &middot; ' if ytd else 'Rolling QTD &middot; ')+WKLABEL)
    return ("<div class='card'><div class='chead'><div class='cleft'>%s<div class='cbrand'>Star Card</div><div class='cstore'>%s</div><div class='cwk'>%s</div></div>"
            "<div class='hero'><div class='herobox'><div class='herolab'>Overall Star Score</div>"
            "<div class='heroscore'><span class='heronum'>%s</span>%s%s</div>"
            "<div class='cdata'>%d / 8 metrics on real data</div></div>"
            "<div class='crank'><div class='big'>#%d<span>/21</span></div><div class='lab'>Star rank</div></div></div></div>"
            "<div class='pillars'>%s%s%s%s</div>"
            "<div class='foundlab'>Brand foundations <span class='excl'>excluded from score</span></div>"
            "<div class='foundations'>"
            "<div class='foundation'><div class='lab'>Brand &amp; Remote</div><div class='val %s'>%s</div><div class='meta'>Blended audit &amp; remote &middot; target 4.6</div></div>"
            "<div class='foundation'><div class='lab'>Open / Close %%</div><div class='val %s'>%s</div><div class='meta'>HRP Process St &middot; target &ge;90%%</div></div>"
            "</div>"
            "<div class='urgent'><h3>Urgent support needed? <span class='excl'>excluded from score</span></h3><div class='flags'>%s</div></div></div>"
            %(LOGO_IMG,c,cwk,fmt(ov),stars(ov,30),vsytd_card(c),S['real_n'],rk,pc('Team',p['Team'],team),pc('Ops excellence',p['Ops'],ops),
              pc('Customers served',p['Customers'],cust),pc('Profit',p['Profit'],prof),
              brc,(brt if d.get('brand') is not None else 'n/a'),occ,oct,flags))
CARDCSS=CSS+"""
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin-bottom:18px;box-shadow:0 1px 3px rgba(20,40,60,.05)}
.chead{display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line);padding-bottom:18px}
.cleft{align-self:center}
.cbrand{font-size:11px;letter-spacing:2.5px;color:var(--amber);font-weight:800;text-transform:uppercase}
.cstore{font-size:26px;font-weight:800;margin-top:2px}.cwk{font-size:12px;color:var(--muted);margin-top:3px}
.hero{display:flex;align-items:center;gap:26px}
.herobox{text-align:right}
.herolab{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted);font-weight:800}
.heroscore{display:flex;align-items:center;justify-content:flex-end;gap:16px;margin:6px 0 2px}
.heronum{font-size:54px;font-weight:800;line-height:.9}
.vsyc{display:inline-flex;align-items:center;gap:5px;font-size:15px;font-weight:800;padding:6px 13px;border-radius:22px;white-space:nowrap}
.vsyc em{font-style:normal;font-size:10px;font-weight:700;color:var(--dim);letter-spacing:.3px}
.vsyc.up{color:var(--green);background:var(--greenbg);border:1px solid var(--greenbd)}
.vsyc.dn{color:var(--red);background:var(--redbg);border:1px solid var(--redbd)}
.vsyc.fl{color:var(--dim);background:#f2f5f8;border:1px solid var(--line)}
.cdata{font-size:10.5px;color:var(--dim);font-weight:700;margin-top:6px}
.crank{text-align:center;border-left:1px solid var(--line);padding-left:26px}
.crank .big{font-size:38px;font-weight:800;color:var(--green);line-height:1}.crank .big span{font-size:17px;color:var(--muted)}
.crank .lab{font-size:10.5px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);font-weight:700;margin-top:4px}
.pillars{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0}
.pcard{border:1px solid var(--line);border-radius:12px;padding:12px 13px}
.phead{display:flex;align-items:flex-start;justify-content:space-between;gap:4px;margin-bottom:2px}
.pname{font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);font-weight:800;padding-top:3px}
.pstar{text-align:right;white-space:nowrap}.pscore{font-size:11px;font-weight:800;margin-top:1px}
.metric{border-top:1px solid var(--line);padding:8px 0 2px}
.mrow{display:flex;align-items:baseline;justify-content:space-between;gap:6px}
.mname{font-size:12.5px;font-weight:800}.mval{font-size:13.5px;font-weight:800}
.mmeta{font-size:10px;color:var(--dim);margin-top:2px;line-height:1.4}
.mw{border-top:1px solid var(--line);padding:9px 0 5px}
.mw-top{display:flex;align-items:baseline;justify-content:space-between;gap:6px}
.mw-title{font-size:12px;font-weight:800}
.mw-win{font-size:8px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:var(--dim);background:#eef2f6;border-radius:4px;padding:1px 6px;white-space:nowrap}
.mw-head{display:flex;align-items:baseline;gap:7px;margin:4px 0 6px}
.mw-big{font-size:21px;font-weight:800;line-height:1}
.mw-big.hit{color:var(--green)}.mw-big.miss{color:var(--red)}.mw-big.neutral{color:var(--dim)}
.mw-sub{font-size:9px;color:var(--dim);font-weight:700;line-height:1.3}
.mw-row{display:flex;align-items:center;justify-content:space-between;font-size:10px;padding:2px 0}
.mw-lbl{color:var(--muted);font-weight:700}
.mw-cmp{display:flex;align-items:center;gap:7px}
.mw-pv{color:var(--text);font-weight:800;font-size:10.5px}
.dlt{font-weight:800;font-size:10px;white-space:nowrap}
.dlt.up{color:var(--green)}.dlt.dn{color:var(--red)}.dlt.fl{color:var(--dim)}
.foundlab{font-size:11px;letter-spacing:1px;text-transform:uppercase;font-weight:800;color:var(--muted);display:flex;align-items:center;margin-bottom:8px}
.foundlab .excl{margin-left:auto;font-size:10px;color:var(--dim);font-weight:700}
.foundations{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.foundation{display:flex;align-items:center;gap:12px;border:1px solid var(--line);border-radius:10px;padding:9px 16px}
.foundation .lab{font-size:11px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);font-weight:800}
.foundation .val{font-size:18px;font-weight:800}.foundation .meta{font-size:11px;color:var(--dim);margin-left:auto}
.urgent{border:1px solid var(--line);border-radius:10px;padding:11px 16px}
.urgent h3{font-size:11px;letter-spacing:1px;text-transform:uppercase;font-weight:800;display:flex;align-items:center}
.urgent .excl{margin-left:auto;font-size:10px;color:var(--dim);font-weight:700}
.flags{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:10px}
.flag{display:flex;align-items:center;justify-content:space-between;gap:8px;border:1px solid var(--greenbd);background:var(--greenbg);border-radius:9px;padding:8px 11px}
.flag.on{border-color:var(--redbd);background:var(--redbg)}.flag.warn{border-color:var(--amberbd);background:var(--amberbg)}
.flag .q{font-size:11.5px;font-weight:700}.flag .a{font-size:11px;font-weight:800;padding:2px 9px;border-radius:20px;background:#fff}
.flag .a.no{color:var(--green)}.flag .a.yes{color:var(--red)}.flag .a.warn{color:var(--amber)}
"""
# ================= AREA VIEW (grouped by area coach: Jon / Rich / Ian) =================
COACH = {"Burton Latimer":"Jon","Peterborough Fletton Quays":"Jon","Rothwell":"Jon","Corby":"Jon",
 "Kettering":"Jon","Rushden Lakes":"Jon","Peterborough Bridge Street":"Jon","Higham Ferrers":"Jon","Olney":"Jon",
 "Leamington Parade":"Rich","Northampton":"Rich","Wellingborough Train Station":"Rich","Market Harborough":"Rich",
 "Wellingborough":"Rich","Lower Heathcote":"Rich","Rugby":"Rich","Northampton Drive-Thru":"Rich","Billing Drive Thru":"Rich",
 "Attleborough":"Ian","HOE Balsall Common":"Ian","Glenvale Drive Thru":"Ian"}
AREAS={}
for _k,_co in COACH.items():
    _c=norm(_k)
    if _c: AREAS.setdefault(_co,[]).append(_c)
def _area_ov(co,win):
    xs=[D[c]['S'][win]['overall'] for c in AREAS[co] if D[c]['S'][win]['overall'] is not None]
    return sum(xs)/len(xs) if xs else None
AREA_OV={w:{co:_area_ov(co,w) for co in AREAS} for w in WINDOWS}
def area_vsytd(co):
    q=AREA_OV['qtd'][co]; y=AREA_OV['ytd'][co]
    if q is None or y is None: return "<span class='vsyc fl'>&ndash; <em>vs YTD</em></span>"
    dv=q-y
    if dv>=0.05: return "<span class='vsyc up'>&#9650; %.1f <em>vs YTD</em></span>"%dv
    if dv<=-0.05: return "<span class='vsyc dn'>&#9660; %.1f <em>vs YTD</em></span>"%(-dv)
    return "<span class='vsyc fl'>&#8776; 0 <em>vs YTD</em></span>"
AREA_CSS="""
.amethod{font-size:11.5px;color:var(--muted);line-height:1.55;margin-bottom:16px;max-width:1100px}.amethod b{color:var(--text)}
.areagrid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.acard{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 20px;box-shadow:0 1px 3px rgba(20,40,60,.05)}
.ahead{display:flex;align-items:flex-start;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:12px}
.acoach{font-size:19px;font-weight:800}.acnt{font-size:11px;color:var(--muted);font-weight:700;margin-top:2px}
.arank{text-align:center}.arank .rn{font-size:26px;font-weight:800;color:var(--green);line-height:1}.arank .rl{font-size:9px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);font-weight:800;margin-top:2px}
.ascore{display:flex;align-items:center;gap:13px;flex-wrap:wrap;margin:14px 0 4px}.anum{font-size:42px;font-weight:800;line-height:1}
.alab{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);font-weight:800}
.apils{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}
.apil{border:1px solid var(--line);border-radius:10px;padding:8px 6px;text-align:center}
.apl{font-size:8.5px;letter-spacing:.4px;text-transform:uppercase;color:var(--muted);font-weight:800}
.aps{font-size:15px;font-weight:800;margin-top:2px}
.apil.hit .aps{color:var(--green)}.apil.warn .aps{color:var(--amber)}.apil.miss .aps{color:var(--red)}.apil.neutral .aps{color:var(--dim)}
.alisth{font-size:9px;letter-spacing:.8px;text-transform:uppercase;color:var(--dim);font-weight:800;border-top:1px solid var(--line);padding-top:9px}
.arow{display:flex;align-items:center;justify-content:space-between;padding:4px 0;font-size:12px}
.an{font-weight:700}.av{font-weight:800;white-space:nowrap;display:flex;align-items:center;gap:8px}.av .avn{min-width:22px;text-align:right}
"""
def area_view(win):
    rows=[]
    for co in AREAS:
        ov=AREA_OV[win][co]; pil={}
        for p in ('Team','Ops','Customers','Profit'):
            xs=[D[c]['S'][win]['pillars'][p] for c in AREAS[co] if D[c]['S'][win]['pillars'][p] is not None]
            pil[p]=sum(xs)/len(xs) if xs else None
        rows.append((co,ov,pil))
    rows.sort(key=lambda r:(r[1] if r[1] is not None else -1),reverse=True)
    out="<div class='areagrid'>"
    for i,(co,ov,pil) in enumerate(rows,1):
        ms=sorted(AREAS[co],key=lambda c:(D[c]['S'][win]['overall'] if D[c]['S'][win]['overall'] is not None else -1),reverse=True)
        slist="".join("<div class='arow'><span class='an'>%s</span><span class='av'><span class='avn'>%s</span>%s</span></div>"%(c,fmt(D[c]['S'][win]['overall']),stars(D[c]['S'][win]['overall'],12)) for c in ms)
        pills="".join("<div class='apil %s'><div class='apl'>%s</div><div class='aps'>%s</div></div>"%(pcol(pil[p]),p,fmt(pil[p])) for p in ('Team','Ops','Customers','Profit'))
        out+=("<div class='acard'><div class='ahead'><div><div class='acoach'>%s&rsquo;s area</div><div class='acnt'>%d stores</div></div><div class='arank'><div class='rn'>#%d</div><div class='rl'>of 3</div></div></div>"
              "<div class='alab'>Area total score</div><div class='ascore'><span class='anum'>%s</span>%s%s</div>"
              "<div class='apils'>%s</div><div class='alisth'>Stores &middot; overall Star Score</div>%s</div>")%(co,len(AREAS[co]),i,fmt(ov),stars(ov,24),area_vsytd(co),pills,slist)
    return out+"</div>"
AREA_VIEW={w:area_view(w) for w in WINDOWS}
AREA_METHOD=("<div class='amethod'><b>Area Total Score = the average of that area&rsquo;s stores&rsquo; overall Star Scores</b> "
 "(equal-weighted per store); area pillar sub-scores are the average of the stores&rsquo; pillar scores. Areas are ranked by total score. "
 "The <b>vs YTD</b> trend compares the area&rsquo;s QTD total to its YTD total. Jon 9 stores &middot; Rich 9 &middot; Ian 3.</div>")
# ================= LIVE 2-TAB PAGE: star-card.html =================
LB_CSS = """
.top{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:14px}
.brand{font-size:12px;letter-spacing:3px;color:var(--amber);font-weight:800;text-transform:uppercase}
.h1{font-size:26px;font-weight:800;margin-top:3px}.sub{color:var(--muted);font-size:12px;margin-top:3px}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(20,40,60,.05)}
thead th{font-size:10.5px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);font-weight:800;text-align:left;padding:11px 10px;background:#f7f9fb;border-bottom:1px solid var(--line)}
th.plh{text-align:center;width:74px}
tbody td{padding:9px 10px;border-bottom:1px solid #eef1f5;font-size:13px}
tbody tr:last-child td{border-bottom:none}
.rk{font-weight:800;color:var(--muted);width:32px;text-align:center}.nm{font-weight:800;font-size:13.5px}
.ov{white-space:nowrap}.ovn{font-weight:800;font-size:14px;margin-right:6px}
.pl{font-weight:800;text-align:center;width:74px}.cov{font-size:10.5px;color:var(--dim)}
.foot{margin-top:12px;font-size:11px;color:var(--dim);line-height:1.55}.foot b{color:var(--muted)}
"""
TAB_CSS = """
.appbar{display:flex;align-items:center;gap:16px;margin-bottom:18px;flex-wrap:wrap}
.abrand{display:flex;align-items:center;gap:12px;margin-right:auto}
.abrand .eyebrow{font-size:10px;letter-spacing:2.5px;text-transform:uppercase;color:var(--amber);font-weight:800}
.abrand .h1b{font-size:20px;font-weight:800;line-height:1;margin-top:2px}
.tabs{display:inline-flex;background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:3px;gap:2px;box-shadow:0 1px 3px rgba(20,40,60,.05)}
.tabs button{font:inherit;font-size:12.5px;font-weight:800;letter-spacing:.4px;border:0;background:transparent;color:var(--muted);padding:8px 20px;border-radius:8px;cursor:pointer}
.tabs button.on{background:var(--text);color:#fff}
.pane[hidden]{display:none}
.storesel{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.storesel label{font-size:11px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);font-weight:800}
.storesel select{font:inherit;font-size:14px;font-weight:800;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:9px 14px;min-width:290px;cursor:pointer;box-shadow:0 1px 3px rgba(20,40,60,.05)}
.abrand .blogo{height:34px;margin:0}
"""
_LOGO = LOGO_IMG
globals()["LOGO_IMG"] = ""   # cards + leaderboard render logo-less; the appbar carries the single brand mark
_default = RANKED["qtd"][0]
CARDS = {c:{w:card(c,w) for w in WINDOWS} for c in CANON}
_opts = "".join("<option value=\"%s\"%s>%s</option>"%(c,(" selected" if c==_default else ""),c) for c in sorted(CANON))
_lb = ("<div class='top'><div><div class='brand'>Star Card</div><div class='h1'>Estate leaderboard &mdash; all 21 stores</div>"
       "<div class='sub'>Ranked by overall Star score &middot; <span id='winlab'>rolling QTD</span> &middot; "+WKLABEL+"</div></div>"
       "<div style='text-align:right'><div class='sub'>Gold = overall rating &middot; pillars: <span class='hit'>green &ge;4</span> &middot; <span class='warn'>amber 3&ndash;4</span> &middot; <span class='miss'>red &lt;3</span></div></div></div>"
       "<table><thead><tr><th>#</th><th>Store</th><th>Overall Star Score</th><th class='plh'>Team</th><th class='plh'>Ops</th><th class='plh'>Customers</th><th class='plh'>Profit</th><th>Real data</th></tr></thead><tbody id='lbody'>"+TBODY["qtd"]+"</tbody></table>"+"<div class='foot'><b>Pillars:</b> Team (<b>RMS Health + New-starter</b>) &middot; Ops (<b>F1 avg Total Score QTD (target &le;175) + Google Health (EOS composite, green &ge;3.32)</b>) &middot; Customers (<b>sales + guest YoY, last completed week vs same week last year</b> on QTD; blended YoY on YTD) &middot; Profit (SPH + Food GP%). <b>Brand foundations</b> (Brand &amp; Remote + Open/Close %) and <b>Urgent support</b> (coach vacancy, bench gap, accidents, red maintenance) sit outside the score. <b>Real data (N / 8):</b> count of the 8 scored metrics (RMS, New-starter, F1, Google, Sales YoY, Guest counts, SPH, Food GP) on genuine real data. Overall = mean of available pillars. Targets indicative for Matt to set.</div>")
PAGE = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Bewiched Star Card</title><style>"+CARDCSS+LB_CSS+TAB_CSS+AREA_CSS+"</style></head><body><div class='wrap'>"
        "<div class='appbar'><div class='abrand'>"+_LOGO+"<div><div class='eyebrow'>Store Scorecard</div><div class='h1b'>Star Card</div></div></div>"
        "<div class='tabs'><button data-tab='store' class='on'>Store Card</button><button data-tab='board'>Leaderboard</button><button data-tab='area'>Area</button></div>"
        "<div class='tgl'><button data-w='qtd' class='on'>QTD</button><button data-w='ytd'>YTD</button></div></div>"
        "<div id='pane-store' class='pane'><div class='storesel'><label>Store</label><select id='storesel'>"+_opts+"</select></div><div id='cardhost'></div></div>"
        "<div id='pane-board' class='pane' hidden>"+_lb+"</div>"
        "<div id='pane-area' class='pane' hidden>"+AREA_METHOD+"<div id='areahost'>"+AREA_VIEW["qtd"]+"</div></div>"
        "</div><script>"
        "var CARDS="+_json.dumps(CARDS)+",TBODY="+_json.dumps(TBODY)+",AREA="+_json.dumps(AREA_VIEW)+",WLAB="+_json.dumps(WLAB)+";"
        "var st={tab:'store',win:'qtd',store:"+_json.dumps(_default)+"};"
        "function rc(){document.getElementById('cardhost').innerHTML=CARDS[st.store][st.win];}"
        "function rb(){document.getElementById('lbody').innerHTML=TBODY[st.win];document.getElementById('winlab').textContent=WLAB[st.win];}"
        "function ra(){document.getElementById('areahost').innerHTML=AREA[st.win];}"
        "document.querySelectorAll('.tabs button').forEach(function(b){b.onclick=function(){"
        "document.querySelectorAll('.tabs button').forEach(function(x){x.classList.remove('on')});b.classList.add('on');"
        "st.tab=b.getAttribute('data-tab');document.getElementById('pane-store').hidden=(st.tab!='store');document.getElementById('pane-board').hidden=(st.tab!='board');document.getElementById('pane-area').hidden=(st.tab!='area');};});"
        "document.querySelectorAll('.appbar .tgl button').forEach(function(b){b.onclick=function(){"
        "document.querySelectorAll('.appbar .tgl button').forEach(function(x){x.classList.remove('on')});b.classList.add('on');"
        "st.win=b.getAttribute('data-w');rc();rb();ra();};});"
        "document.getElementById('storesel').onchange=function(){st.store=this.value;rc();};"
        "rc();rb();ra();"
        "</script></body></html>")
open(os.path.join(OUT,"star-card.html"),"w",encoding="utf-8").write(PAGE)
print("[gen_starcard] wrote star-card.html (%d stores, 2 tabs); leftover placeholders: none"%len(CANON))
