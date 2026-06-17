# -*- coding: utf-8 -*-
# Engagement-Coach company-wide dashboard generator.
# Reads the SAME freshly-downloaded feeds as gen_area.py / gen_company.py
# (allstores.json, smt_visits.json, actuals.json, planner_overrides.json, f1_detail.json)
# plus the shared TEMPLATE_COACH.html. Tab one = this coach's movements (smt_visits[COACH]);
# tabs 2-7 = whole-company rollup across all 21 stores. Writes <COACH>_Engagement_Dashboard.html
# to the current directory (same place gen_company.py writes Company_Dashboard.html).
COACH = "Kel"   # gen_claire.py is identical with COACH="Claire"

import json, datetime as _dt
from collections import defaultdict
from statistics import mean, median

A=json.load(open('allstores.json')); REC=A['rec']; champ=A['champ']; CATS=A['cats']
WX_TMPL=open('wx_nudge_tmpl.html',encoding='utf-8').read()
WX_TOP='<div id="wxnudge_top" style="display:none;margin:0 0 16px;padding:9px 14px;border-radius:11px;font-size:13px;line-height:1.5"></div>'
WX_FOOD='<div id="wxfood" style="display:none;margin:2px 0 14px;padding:11px 15px;border-radius:12px;font-size:13.5px;line-height:1.55"></div>'
import re as _rep
def cleanprod(n):
    n=(n or '').strip(); n=_rep.sub(r'^(?:[23]\*?|\*)\s+','',n); n=_rep.sub(r'\s+TA$','',n); return n.strip()
def clean_outliers(lst):
    ag={}
    for o in lst:
        nm=cleanprod(o[0])
        if nm in ag: ag[nm][2]+=o[2]; ag[nm][3]+=o[3]; ag[nm][4]+=o[4]
        else: ag[nm]=[nm,o[1],o[2],o[3],o[4]]
    out=[]
    for a in ag.values():
        w,s=a[2],a[3]; a[1]=round(100*w/(w+s),1) if (w+s)>0 else 0; out.append(a)
    return sorted(out,key=lambda x:-x[4])
ANALOG_TBL=json.load(open('analog_table.json'))['ANALOG']
def wx_nudge(locs,recent):
    locs=[[round(x[0],4),round(x[1],4)] for x in locs if x]
    return WX_TMPL.replace("__LOCS__",json.dumps(locs)).replace("__ANALOG__",json.dumps(ANALOG_TBL)).replace("__RECENT__",json.dumps(recent))
def wx_recent(amix):
    return {"cold":amix['Cold drinks']['mix'],"hot":amix['Hot drinks']['mix'],"milk":amix['Milkshakes']['mix'],"coldfood":25.9,"temp":19.7}
ACT=json.load(open('actuals.json'))
try: OVR=json.load(open('planner_overrides.json'))
except FileNotFoundError: OVR={}
try: FD=json.load(open('f1_detail.json'))
except FileNotFoundError: FD={}
SMT_ALL=json.load(open('smt_visits.json'))
if COACH not in SMT_ALL:
    raise SystemExit("smt_visits.json has no key %r (keys: %s)"%(COACH,list(SMT_ALL.keys())))
SMT=SMT_ALL[COACH]
GEN_STAMP=_dt.datetime.now().strftime('%d %b %Y, %H:%M')

SHORT={"Burton Latimer":"Burton","Corby":"Corby","Higham Ferrers":"Higham","Kettering":"Kettering","Olney":"Olney",
"Peterborough Bridge Street":"P'boro Bridge St","Peterborough Fletton Quays":"P'boro Fletton","Rothwell":"Rothwell","Rushden Lakes":"Rushden Lakes",
"Attleborough":"Attleborough","Billing Drive Thru":"Billing DT","Glenvale Drive Thru":"Glenvale DT","HOE Balsall Common":"Balsall Common",
"Leamington Parade":"Leam Parade","Lower Heathcote":"Lower Heathcote","Market Harborough":"Mkt Harborough","Northampton":"Northampton",
"Northampton Drive-Thru":"Northampton DT","Rugby":"Rugby","Wellingborough":"Wellingborough","Wellingborough Train Station":"W'boro Train Stn",
"Leam Retail":"Leam Retail"}
def sh(n): return SHORT.get(n,n)
GBP=lambda v:"£"+format(int(round(v)),",d")
def cls(v,g,a,rev=False):
    if v is None: return "t-na"
    if rev: return "t-ok" if v<=g else ("t-amber" if v<=a else "t-red")
    return "t-ok" if v>=g else ("t-amber" if v>=a else "t-red")
def tag(t,k): return '<span class="tag %s">%s</span>'%(k,t)
def pctxt(v): return "n/a" if v is None else (("+" if v>=0 else "")+"%s%%"%v)
def _f1score(s):
    d=FD.get(s)
    if isinstance(d,dict) and d.get('race') and len(d['race'])>5 and d['race'][5] not in (None,''):
        try: return float(d['race'][5])
        except: return None
    return None
COACHCHIP={"Jon":"t-ok","Rich":"t-amber","Ian":"t-amber"}
PLANNERS_HTML=('<a class="plannerbtn" href="https://docs.google.com/spreadsheets/d/1PSjBGiR40171h769esQCtn3ldcpCB5XJyfqRTo7Yccs/edit" target="_blank" rel="noopener">Jon&#39;s Planner</a>'
 '<a class="plannerbtn" href="https://docs.google.com/spreadsheets/d/1_qdK6fzqPg1NcA2KKMy2TnaZ8nQJtVE-fglz2On3oBw/edit" target="_blank" rel="noopener">Ian&#39;s Planner</a>'
 '<a class="plannerbtn" href="https://docs.google.com/spreadsheets/d/11XuXn9zQr-JB4x2fQ0ORV96Sf-U7xWPQPvg2YlCl_dQ/edit" target="_blank" rel="noopener">Rich&#39;s Planner</a>')

stores=sorted(REC.keys())
R={s:REC[s] for s in stores}
atv_med=median([R[s]['atv'] for s in stores])
area_last=sum(R[s]['lw26'] for s in stores); area_4wk=sum(R[s]['s4'] for s in stores)
comp=[s for s in stores if R[s]['lw25']>0]
ylw=round(100*(sum(R[s]['lw26'] for s in comp)/sum(R[s]['lw25'] for s in comp)-1),1) if comp else 0
comp4=[s for s in stores if R[s]['s4_25']>0]
y4=round(100*(sum(R[s]['s4'] for s in comp4)/sum(R[s]['s4_25'] for s in comp4)-1),1) if comp4 else 0
awr=sum(R[s]['wr'] for s in stores); awpct=round(100*awr/area_4wk,1); awr_lw=sum(R[s].get('wr_lw',0) for s in stores); area_lw_sales=sum(R[s].get('lw_sales',0) for s in stores); awpct_lw=round(100*awr_lw/area_lw_sales,1) if area_lw_sales else 0; awr_wk=round(awr/4)
avg_fin=round(mean([R[s]['f1'][0] for s in stores]),1)
cons=sorted(champ['cons'],key=lambda x:-x[3])
audit_vals=[R[s]['audit_qtd'] for s in stores if R[s].get('audit_qtd') is not None]; audit_mean=round(mean(audit_vals),2) if audit_vals else None; audit_k=cls(audit_mean,4.5,4.0)

# ---- movements (tab one) from smt_visits[COACH] ----
def hc(p):
    a=round(p/100*0.85+0.06,2); fg="#fff" if p>=45 else "#5b3a29"
    return '<td class="dc" style="background:rgba(31,138,76,%s);color:%s">%s</td>'%(a,fg,(p if p>0 else ""))
korder=sorted(SMT.items(), key=lambda kv:-kv[1][0])
mov=""
for s,a in korder:
    tot=a[0]; nw=a[1]; byday=a[2:9]
    bc="#1f8a4c" if tot>=40 else ("#b8860b" if tot>=20 else "#c0392b")
    ntag=' <span class="newtag">%s wks</span>'%nw if nw<30 else ''
    mov+=('<tr><td class="ms">%s%s</td>'%(sh(s),ntag)+"".join(hc(p) for p in byday)+
          '<td class="cov"><div class="pbar"><i style="width:%s%%;background:%s"></i></div><span>%s%%</span></td></tr>'%(min(tot,100),bc,tot))
n_sites=len(SMT); kavg=round(sum(v[0] for v in SMT.values())/n_sites)
ktop=korder[0]; k2=korder[1]; k3=korder[2]; klow=korder[-1]
mov_note=("%s is most present at <b>%s (%s%%)</b>, <b>%s (%s%%)</b> and <b>%s (%s%%)</b>; "
          "lightest at <b>%s (%s%%)</b>. Across all %s sites she averages <b>~%s%%</b> weekly coverage — "
          "weighted toward her engagement-focus stores. Each cell = %% of that store's logged weeks %s was on site that weekday; "
          "the bar = %% of weeks she visited at all (green &ge;40%% · amber &ge;20%% · red below).")%(
          COACH,sh(ktop[0]),ktop[1][0],sh(k2[0]),k2[1][0],sh(k3[0]),k3[1][0],sh(klow[0]),klow[1][0],n_sites,kavg,COACH)
COACH_CARDS=('<div class="cards" style="grid-template-columns:repeat(5,1fr)">'
 '<div class="card"><div class="lbl">Sites on %s&#39;s patch</div><div class="val">%s</div><div class="meta">21 stores + Leam Retail</div></div>'
 '<div class="card"><div class="lbl">Avg weekly coverage</div><div class="val">%s%%</div><div class="meta">share of weeks on site · all sites</div></div>'
 '<div class="card"><div class="lbl">Most present</div><div class="val">%s%%</div><div class="meta">%s · top site</div></div>'
 '<div class="card"><div class="lbl">Diary span</div><div class="val">60 wks</div><div class="meta">Weekly SMT Visit Diary</div></div>'
 '<div class="card"><div class="lbl">Stores audit avg — QTD</div><div class="val"><span class="tag %s" style="font-size:20px;padding:2px 9px">%s</span><small style="font-size:13px;color:#9a8a7c"> /5</small></div><div class="meta">%s stores · Brand Audit QTD</div></div>'
 '</div>')%(COACH,n_sites,kavg,ktop[1][0],sh(ktop[0]),audit_k,(("%.2f"%audit_mean) if audit_mean is not None else "n/a"),len(audit_vals))

# ---- sales ----
def yoycell(v): return '<td><span class="tag t-na">n/a</span></td>' if v is None else '<td><span class="tag %s">%s%s%%</span></td>'%("t-ok" if v>=0 else "t-red",("+" if v>=0 else ""),round(v,1))
lw_rows=""; A0=[0,0,0,0]; sl=0; st_=0
for s in sorted(stores,key=lambda x:-R[x]['lw26']):
    r=R[s]; lw=r['lw26']; lw25=r['lw25']; t26=r['tx26']; t25=r['tx25']; sl+=lw; st_+=t26
    sy=None if lw25==0 else 100*(lw/lw25-1); avs=lw/t26 if t26 else 0
    avs25=(lw25/t25) if t25 else None; ay=None if avs25 is None else 100*(avs/avs25-1); gy=None if t25==0 else 100*(t26/t25-1)
    if lw25>0: A0[0]+=lw;A0[1]+=lw25;A0[2]+=t26;A0[3]+=t25
    lw_rows+='<tr><td>%s</td><td style="font-weight:700">%s</td>%s<td>£%.2f</td>%s<td>%s</td>%s</tr>'%(s,GBP(lw),yoycell(sy),avs,yoycell(ay),format(t26,",d"),yoycell(gy))
asy=100*(A0[0]/A0[1]-1) if A0[1] else 0; aavs=sl/st_; aay=100*((A0[0]/A0[2])/(A0[1]/A0[3])-1) if A0[3] else 0; agy=100*(A0[2]/A0[3]-1) if A0[3] else 0
lw_total='<tr><td>COMPANY (%s stores)</td><td>%s</td>%s<td>£%.2f</td>%s<td>%s</td>%s</tr>'%(len(stores),GBP(sl),yoycell(asy),aavs,yoycell(aay),format(st_,",d"),yoycell(agy))
salestbl=""
for s in sorted(stores,key=lambda x:-R[x]['s4']):
    r=R[s]; salestbl+='<tr><td>%s</td><td>%s</td><td class="%s">%s</td><td>£%.2f</td><td>%s</td><td class="%s">%s</td></tr>'%(s,GBP(r["s4"]),("pos" if (r["yoy_4w"] or 0)>=0 else "neg"),pctxt(r["yoy_4w"]),r["atv"],GBP(r["lw26"]),("pos" if r["vs4w"]>=0 else "neg"),pctxt(r["vs4w"]))
def grcell(v):
    if v is None: return '<td class="gc" style="background:#eee;color:#999">n/a</td>'
    if v>=5: bg,fg="#1f8a4c","#fff"
    elif v>=0: bg,fg="#d6ebde","#1c6b3d"
    elif v>-5: bg,fg="#f7d9d4","#8c2f22"
    else: bg,fg="#c0392b","#fff"
    return '<td class="gc" style="background:%s;color:%s">%s%s%%</td>'%(bg,fg,("+" if v>=0 else ""),v)
DP=["Morning","Lunch","Afternoon","Evening"]
dpg_rows="".join('<tr><td class="ms">%s</td>'%sh(s)+"".join(grcell(R[s]["daypart_growth"][dp]) for dp in DP)+"</tr>" for s in stores)
dowg_rows="".join('<tr><td class="ms">%s</td>'%sh(s)+"".join(grcell(v) for v in R[s]["dow_growth"])+"</tr>" for s in stores)
dpa={dp:[R[s]['daypart_growth'][dp] for s in stores if R[s]['daypart_growth'][dp] is not None] for dp in DP}
best_dp=max(DP,key=lambda dp: mean(dpa[dp]) if dpa[dp] else -99)
dpg_note="%% change vs the same 4 weeks in 2025 (2026 openings show n/a). Strongest daypart growth company-wide is <b>%s</b>."%best_dp
dowg_note="Same YoY basis by weekday — green columns are days to protect, red ones to target with promo or labour."
sales_focus="Chase the red cells in the growth grids; protect the green days with labour."

# ---- wastage (company aggregate) ----
yjs={s:{"latest":"08/06/2026","items":R[s]['yield_items']} for s in stores}
outjs={s:clean_outliers(R[s]['outliers']) for s in stores}
oa=defaultdict(lambda:{'w':0,'s':0,'wr':0.0})
for s in stores:
    for o in outjs[s]:
        oa[o[0]]['w']+=o[2]; oa[o[0]]['s']+=o[3]; oa[o[0]]['wr']+=o[4]
aol=sorted([[n,round(100*v['w']/(v['w']+v['s']),1) if (v['w']+v['s'])>0 else 0,v['w'],v['s'],round(v['wr'])] for n,v in oa.items() if v['w']>0],key=lambda x:-x[4])[:8]
ya=defaultdict(lambda:{'av':[], 'sold':0,'w':0,'wr':0.0})
for s in stores:
    for it in R[s]['yield_items']:
        a=ya[it[0]]; a['av'].append(it[1]); a['sold']+=it[3]
        wr_units=round(it[2]/100*it[3]/(1-it[2]/100)) if it[2]<100 else it[3]
        a['w']+=wr_units; a['wr']+=it[4]
area_items=[]
for n,v in ya.items():
    tot=v['sold']+v['w']
    if tot<=0: continue
    wr=round(100*v['w']/tot,1); area_items.append([n,round(mean(v['av']),1),wr,int(v['sold']),round(v['wr'],1)])
yjs["Company (all %s)"%len(stores)]={"latest":"08/06/2026","items":area_items}; outjs["Company (all %s)"%len(stores)]=aol

# ---- mix ----
area_sales=sum(R[s]['tot'][0] for s in stores); amix={}
swp=[s for s in stores if R[s].get('mix_prev')]
tcl=sum(R[s]['mix'][c]['sales'] for s in swp for c in CATS) or 1
tpl=sum(R[s]['mix_prev'][c]['sales'] for s in swp for c in CATS) or 1
def _mv(cur,pp,valued=False):
    if pp is None: return '<span style="color:#9a8a7c;font-size:11px"> (new this period)</span>'
    if abs(pp)<0.05: return '<span style="color:#9a8a7c;font-size:11px"> (about the same as four weeks ago)</span>'
    prior=round(cur-pp,1); up=pp>0; word="up" if up else "down"
    col=('#1f8a4c' if up else '#c0392b') if valued else '#6b7785'
    return '<span style="color:%s;font-size:11px"> (%s from %s%% four weeks ago)</span>'%(col,word,prior)
for c in CATS:
    cs=sum(R[s]['mix'][c]['sales'] for s in stores); caps=[R[s]['mix'][c]['cap'] for s in stores]; cs_lw=sum(R[s]['mix_lw'][c]['sales'] for s in stores if R[s].get('mix_lw')); caps_lw=[R[s]['mix_lw'][c]['cap'] for s in stores if R[s].get('mix_lw')]
    csl=sum(R[s]['mix'][c]['sales'] for s in swp); psl=sum(R[s]['mix_prev'][c]['sales'] for s in swp)
    mix_pp=round(100*csl/tcl-100*psl/tpl,1) if swp else None
    cap_pp=round(mean([R[s]['mix'][c]['cap'] for s in swp])-mean([R[s]['mix_prev'][c]['cap'] for s in swp]),1) if swp else None
    amix[c]={'mix':round(100*cs/area_sales,1),'cap_avg':round(mean(caps),1),'mix_pp':mix_pp,'cap_pp':cap_pp,'mix_lw':round(100*cs_lw/area_lw_sales,1) if area_lw_sales else 0,'cap_lw':round(mean(caps_lw),1) if caps_lw else 0}
mar=""
for c in CATS:
    caps=[(s,R[s]['mix'][c]['cap']) for s in stores]; best=max(caps,key=lambda x:x[1]); worst=min(caps,key=lambda x:x[1])
    mar+='<tr><td>%s</td><td><b>%s%%</b> <span style="color:#9a8a7c;font-size:10px">4-wk run rate</span>%s<br><span style="color:#6b5a47;font-size:11px">last week %s%%</span></td><td><b>%s%%</b> <span style="color:#9a8a7c;font-size:10px">4-wk run rate</span>%s<br><span style="color:#6b5a47;font-size:11px">last week %s%%</span></td><td style="text-align:left;color:#1f8a4c">%s %s%%</td><td style="text-align:left;color:#c0392b">%s %s%%</td></tr>'%(c,amix[c]["mix"],_mv(amix[c]["mix"],amix[c]["mix_pp"]),amix[c]["mix_lw"],amix[c]["cap_avg"],_mv(amix[c]["cap_avg"],amix[c]["cap_pp"],True),amix[c]["cap_lw"],sh(best[0]),best[1],sh(worst[0]),worst[1])
caphdr="".join('<th>%s</th>'%c.split(" ")[0] for c in CATS)
capmat=""
for s in stores:
    cells=""
    for c in CATS:
        cap=R[s]['mix'][c]['cap']; av=amix[c]['cap_avg']; k="t-ok" if cap>=av*1.05 else ("t-red" if cap<=av*0.85 else "t-amber"); cells+='<td>%s</td>'%tag("%s%%"%cap,k)
    capmat+='<tr><td class="ms">%s</td>%s</tr>'%(sh(s),cells)
mix_ds=json.dumps([amix[c]['mix'] for c in CATS]); mix_lbls=json.dumps(CATS)
foodcap=amix['Food']['cap_avg']
mix_note="Hot drinks anchor the mix; <b>Food capture sits at ~%s%%</b> company-wide — the clearest add-on prize. The small note after each figure shows the change vs four weeks ago (like-for-like): capture changes are coloured green (up) / red (down); mix-share changes are neutral grey."%foodcap
mix_focus="Food attach is the company-wide prize — prompt a food add-on at the till where the Food column shows red."

# ---- F1 ----
f1tbl=""
for s in sorted(stores,key=lambda x:R[x]['f1'][0]):
    fin,ch,last6=R[s]['f1']
    spk="".join('<span class="spk" style="height:%spx" title="P%s"></span>'%(max(2,round((26-int(p))/26*18)),p) for p in last6)
    _sc=_f1score(s)
    f1tbl+='<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td style="text-align:left"><span class="spkwrap">%s</span></td></tr>'%(s,tag("P"+str(fin),cls(fin,6,15,rev=True)),ch,tag(("%g"%_sc) if _sc is not None else "n/a",cls(_sc,210,285,rev=True)),spk)
f1_fin_ds=json.dumps([R[s]['f1'][0] for s in sorted(stores,key=lambda x:R[x]['f1'][0])])
f1_fin_lbls=json.dumps([sh(s) for s in sorted(stores,key=lambda x:R[x]['f1'][0])])
f1_champ_avg=round(mean([R[s]['f1'][1] for s in stores]),1)
bestf=sorted(stores,key=lambda x:R[x]['f1'][0]); worstf=bestf[::-1]
f1_top="%s P%s"%(sh(bestf[0]),R[bestf[0]]['f1'][0]); f1_top_meta="%s P%s next"%(sh(bestf[1]),R[bestf[1]]['f1'][0])
leadc=cons[0]
con_note="Constructors' Championship across all three areas — <b>%s</b> leads on %s pts/store. Every weekend finish lifts a constructor's average; the bottom-third stores are where the title is won."%(leadc[0],leadc[3])
f1_note="Best of the grid: <b>%s (P%s)</b>; needs a reset: <b>%s (P%s)</b>. The sparkline shows recent form — taller = better finish."%(sh(bestf[0]),R[bestf[0]]['f1'][0],sh(worstf[0]),R[worstf[0]]['f1'][0])
f1_focus="Reset the weekend routine at %s &amp; %s; lift qualifying to fix the handicapped grid start."%(sh(worstf[0]),sh(worstf[1]))
maxavg=max(c[3] for c in cons); con_html=""
for i,c in enumerate(cons):
    cc,total,nst,avg=c; w=round(100*avg/maxavg)
    con_html+='<div class="crow"><div class="crank">%s</div><div class="cbody"><div class="cname">%s</div><div class="cbar"><i style="width:%s%%"></i></div><div class="csub">%s pts total · %s stores</div></div><div class="cval">%s<small>pts/store</small></div></div>'%(i+1,cc,w,total,nst,avg)
drv=champ['drivers']; drv_rows=""
for i,(stn,cc,pts) in enumerate(drv):
    drv_rows+='<tr><td style="text-align:center">%s</td><td style="text-align:left">%s</td><td>%s</td><td style="font-weight:700">%s</td></tr>'%(i+1,stn,tag(cc,COACHCHIP.get(cc,"t-na")),pts)

# ---- sentiment ----
sent={s:R[s]['sent'] for s in stores}
rmsv=[sent[s]['rms'] for s in stores if sent[s]['rms']]; area_rms=round(mean(rmsv),2) if rmsv else 0
area_sick=sum(sent[s]['sick'] for s in stores); area_late=sum(sent[s]['late'] for s in stores); area_rtw=sum(sent[s]['rtw'] for s in stores)
area_sickfs=sum(sent[s].get('sickfs',sent[s]['sick']) for s in stores); area_out45=sum(sent[s].get('out45',0) for s in stores); area_sick45=sum(sent[s].get('sick45',0) for s in stores)
_cand=sorted(stores,key=lambda z:(-sent[z].get('out45',0),-sent[z].get('sickfs',0),z))[0]; _wn=sent[_cand].get('out45',0)
_rb=('#fbeae8','#eccfca','#8c2f22') if area_out45>0 else ('#e6f4ec','#cfe6d8','#1c6b3d')
_rsub=((" &mdash; of %s sick-for-shift in window · worst %s (%s)"%(area_sick45,sh(_cand),_wn)) if area_out45>0 else " &mdash; all caught up")
rtw_chip='<li style="list-style:none;margin:2px 0 9px -18px;padding:9px 13px;border-radius:10px;font-weight:700;background:%s;border:1px solid %s;color:%s">🩹 RTWs to do &mdash; last 45 days: %s%s</li>'%(_rb[0],_rb[1],_rb[2],area_out45,_rsub)
rtw_comp=round(100*area_rtw/area_sickfs) if area_sickfs else 0; rtw_k="t-ok" if rtw_comp>=80 else ("t-amber" if rtw_comp>=50 else "t-red")
reps=[sent[s]['rep_pct'] for s in stores if sent[s]['rep_pct'] is not None]; area_rep=round(mean(reps)) if reps else 0
rms_rows=""
for s in sorted(stores,key=lambda x:-(sent[x]['rms'] or 0)):
    v=sent[s]['rms']
    if v is None: continue
    w=round(100*v/5); k="t-ok" if v>=4.5 else ("t-amber" if v>=4.0 else "t-red"); bc="#1f8a4c" if v>=4.5 else ("#b8860b" if v>=4.0 else "#c0392b")
    rms_rows+='<tr><td class="ms">%s</td><td style="width:55%%"><div class="pbar" style="width:100%%"><i style="width:%s%%;background:%s"></i></div></td><td>%s</td><td class="mini">%s ratings</td></tr>'%(sh(s),w,bc,tag("%.2f"%v,k),sent[s]["rms_n"])
hr_rows=""
for s in sorted(stores,key=lambda x:-sent[x]['sick']):
    x=sent[s]; rep=x['rep_pct']; rr=x['rtw_rate']
    repk="t-na" if rep is None else ("t-ok" if rep>=90 else ("t-amber" if rep>=70 else "t-red"))
    rrk="t-na" if rr is None else ("t-ok" if rr>=80 else ("t-amber" if rr>=50 else "t-red"))
    hr_rows+='<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(s,x.get("sickfs",x["sick"]),x["late"],tag((str(rep)+"%") if rep is not None else "n/a",repk),x["rtw"],tag((str(rr)+"%") if rr is not None else "n/a",rrk))
lowrms=sorted([s for s in stores if sent[s]['rms']],key=lambda x:sent[x]['rms'])
rms_note="RMS is the team's own shift rating. Softest at <b>%s (%s)</b>; strongest <b>%s (%s)</b>."%(sh(lowrms[0]),sent[lowrms[0]]['rms'],sh(lowrms[-1]),sent[lowrms[-1]]['rms'])
sickd=sorted(stores,key=lambda x:-sent[x]['sick'])
rtw_note="<b>Return-to-work is the gap.</b> Only %s RTW interviews logged against %s sick-for-shift absences (%s%%) — policy is an RTW chat after every absence. <b>%s (%s)</b> carries the most sickness."%(area_rtw,area_sickfs,rtw_comp,sh(sickd[0]),sent[sickd[0]]['sick'])
cu={s:R[s].get('cust',{'rating':None,'reviews':0}) for s in stores}
rated=[s for s in stores if cu[s]['rating'] is not None]
area_rating=round(mean([cu[s]['rating'] for s in rated]),2) if rated else 0
area_reviews=sum(cu[s]['reviews'] for s in stores)
def ratcol(v): return "#1f8a4c" if v>=4.7 else ("#b8860b" if v>=4.5 else "#c0392b")
def ratk(v): return "t-ok" if v>=4.7 else ("t-amber" if v>=4.5 else "t-red")
cust_rows=""
for s in sorted(rated,key=lambda x:-cu[x]['rating']):
    v=cu[s]['rating']; w=round(100*v/5)
    cust_rows+='<tr><td class="ms">%s</td><td style="width:55%%"><div class="pbar" style="width:100%%"><i style="width:%s%%;background:%s"></i></div></td><td>%s</td><td class="mini">%s reviews</td></tr>'%(sh(s),w,ratcol(v),tag("%.1f★"%v,ratk(v)),format(cu[s]["reviews"],",d"))
rsort=sorted(rated,key=lambda x:cu[x]['rating'])
cust_note="Live Google rating per store (%s reviews across the company). Strongest <b>%s (%s★)</b>; lowest <b>%s (%s★)</b> — high-volume sites naturally sit a touch lower."%(format(area_reviews,",d"),sh(rsort[-1]),cu[rsort[-1]]['rating'],sh(rsort[0]),cu[rsort[0]]['rating'])
sent_focus="Close the return-to-work gap (currently %s%%): log an RTW chat after every absence, starting with Fletton &amp; Rushden."%rtw_comp

# ---- focus bullets ----
syoy="company ran <b>%s</b> last week (%s YoY)"%(GBP(area_last),pctxt(ylw)) if comp else "company ran <b>%s</b> last week"%GBP(area_last)
topsales=sorted(comp4,key=lambda x:-(R[x]['yoy_4w'] or -99))
sales_b="<b>Sales:</b> %s; 4-week %s YoY."%(syoy,pctxt(y4))+(" <b>%s %s</b> leads."%(sh(topsales[0]),pctxt(R[topsales[0]]['yoy_4w'])) if topsales else "")
wpd=sorted(stores,key=lambda x:-R[x]['waste_pct'])
waste_b="<b>Wastage:</b> company %s%% retail; worst <b>%s (%s%%)</b>."%(awpct,sh(wpd[0]),R[wpd[0]]['waste_pct'])
f1_b="<b>Op's Excellence:</b> best <b>%s P%s</b>; reset <b>%s P%s</b>."%(sh(bestf[0]),R[bestf[0]]['f1'][0],sh(worstf[0]),R[worstf[0]]['f1'][0])
coach_b="<b>Engagement:</b> %s averages <b>~%s%%</b> weekly site coverage, heaviest at %s (%s%%); RTW completion just <b>%s%%</b> across %s sick-for-shift (lateness excluded)."%(COACH,kavg,sh(ktop[0]),ktop[1][0],rtw_comp,area_sickfs)
focus_li=rtw_chip+"".join("<li>%s</li>"%b for b in [sales_b,f1_b,waste_b,coach_b])

# ---- forecast ----
_t=_dt.date.today(); _mon=_t-_dt.timedelta(days=_t.weekday()); lw_label="W/C "+str((_mon-_dt.timedelta(days=7)).day)+" "+(_mon-_dt.timedelta(days=7)).strftime("%b")
def _wl(d): return "W/C "+str(d.day)+" "+d.strftime("%b")
wk_this=_wl(_mon); wk_n1=_wl(_mon+_dt.timedelta(days=7)); wk_n2=_wl(_mon+_dt.timedelta(days=14))
def _fc(s,i):
    ly=R[s].get('ly',[0,0,0,0])[i]; y=R[s].get('yoy_4w')
    return round(ly*(1+y/100)) if (ly>0 and y is not None) else R[s]['lw26']
sumly=[0,0,0]; sumf=[0,0,0]; sumh=[0,0,0]; sumlw=0; fcst_rows=""
for s in sorted(stores,key=lambda x:-R[x]['lw26']):
    cph=R[s].get('cph',55); lw=R[s]['lw26']; sumlw+=lw
    cells='<td style="text-align:left">%s</td><td>£%s</td><td>%s</td>'%(sh(s),cph,GBP(lw))
    for wi in range(3):
        ly=R[s].get('ly',[0,0,0,0])[wi+1]; f=_fc(s,wi+1); h=round(f/cph) if cph else 0
        if isinstance(OVR.get(s),dict): f=OVR[s]['fc'][wi]; h=OVR[s]['hrs'][wi]
        sumly[wi]+=ly; sumf[wi]+=f; sumh[wi]+=h
        cells+='<td class="mini">%s</td><td style="font-weight:600">%s</td><td>%s</td>'%((GBP(ly) if ly>0 else "&mdash;"),GBP(f),h)
    fcst_rows+='<tr>%s</tr>'%cells
tot='<tr style="font-weight:700;background:#EFE6DC"><td style="text-align:left">COMPANY TOTAL</td><td></td><td>%s</td>'%GBP(sumlw)
for wi in range(3): tot+='<td>%s</td><td>%s</td><td>%s</td>'%(GBP(sumly[wi]),GBP(sumf[wi]),sumh[wi])
fcst_rows+=tot+'</tr>'
fcst_blended=round(sumf[0]/sumh[0],1) if sumh[0] else 0
TARGETS="https://docs.google.com/spreadsheets/d/18iUyF6Usm5QnUAARPgNsAkqWp00fKPv1WA3waBKJFZU/edit"

# ---- actual vs forecast ----
avf=""; sfc=sa=ssc=su=0
for s in sorted(stores,key=lambda x:-R[x]['lw26']):
    a=ACT.get(s)
    if not isinstance(a,list): continue
    fc=a[1] or 0; sched=a[2] or 0; used=a[3] or 0; act=R[s]['lw26']; tcph=R[s].get('cph',55)
    if isinstance(OVR.get(s),dict) and OVR[s].get('used_lastwk') is not None: used=OVR[s]['used_lastwk']
    sfc+=fc; sa+=act; ssc+=sched; su+=used
    sv=round(100*(act/fc-1)) if fc else None; hv=round(used-sched,1) if (used or sched) else None; ac=round(act/used,2) if used else None
    svk='t-ok' if (sv is not None and sv>=0) else 't-red'; cpk='t-ok' if (ac is not None and ac>=tcph) else 't-red'; hvk='t-ok' if (hv is not None and hv<=0) else 't-amber'
    svt=(("+" if sv>=0 else "")+str(sv)+"%") if sv is not None else "n/a"; hvt=(("+" if hv>=0 else "")+("%g"%hv)) if hv is not None else "n/a"
    avf+='<tr><td style="font-weight:700">%s</td><td>£%s</td><td style="font-weight:700">£%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>£%s</td><td>%s</td></tr>'%(s,format(int(fc),",d"),format(int(act),",d"),tag(svt,svk),("%g"%sched),("%g"%used),tag(hvt,hvk),tcph,tag(("£%.2f"%ac) if ac is not None else "n/a",cpk))
tsv=round(100*(sa/sfc-1)) if sfc else 0; tac=round(sa/su,2) if su else 0; thv=round(su-ssc,1)
avf+='<tr style="font-weight:700;background:#EFE6DC"><td>COMPANY TOTAL</td><td>£%s</td><td>£%s</td><td>%s%s%%</td><td>%s</td><td>%s</td><td>%s%s</td><td></td><td>£%.2f</td></tr>'%(format(int(sfc),",d"),format(int(sa),",d"),("+" if tsv>=0 else ""),tsv,("%g"%ssc),("%g"%su),("+" if thv>=0 else ""),("%g"%thv),tac)

# ---- role (Kel unchanged) ----
ROLE="Engagement Coach"
SPEED_WIDGETS=""

# ---- BENCH tab (Kel only): geographical bench-vs-gap map from HRP 'Bench and HRP' ----
BENCH_NAV=""; BENCH_PANEL=""
try: BENCH=json.load(open('bench.json'))
except Exception: BENCH=None
if BENCH and BENCH.get('rows'):
    BMAP={"Drive Thru Northampton":"Northampton Drive-Thru","Train Station":"Wellingborough Train Station",
          "Wellingborough Market St":"Wellingborough","Fletton Quays":"Peterborough Fletton Quays",
          "Peterborough":"Peterborough Bridge Street","Balsall Common":"HOE Balsall Common"}
    SCOL={"bench":"#1f8a4c","thin":"#b8860b","gap":"#c0392b"}
    STAG={"bench":"t-ok","thin":"t-amber","gap":"t-red"}
    pts=[]; tbl=[]; ng=na=nr=0
    for row in BENCH['rows']:
        nm=(row[0] or "").strip(); cells=[(c or "").strip() for c in row[1:10]]
        sm=cells[0]; leaders=[c for c in cells[0:5] if c]; bench=[c for c in cells[5:9] if c]
        if bench: st,sl="bench","Bench ready"; ng+=1
        elif not sm: st,sl="gap","Gap (no SM)"; nr+=1
        else: st,sl="thin","Thin"; na+=1
        key=BMAP.get(nm,nm); rec=REC.get(key); coords=rec.get('coords') if rec else None
        lab=sh(key) if rec else nm
        if coords: pts.append((coords,st,SCOL[st],lab))
        tbl.append((nm,len(leaders),(", ".join(bench) if bench else "—"),sl,st))
    # inline SVG map (dependency-free; north up; lat/long projection over plotted stores)
    lats=[c[0] for c,_,_,_ in pts]; lons=[c[1] for c,_,_,_ in pts]
    la0,la1=min(lats),max(lats); lo0,lo1=min(lons),max(lons)
    W,H,m=720,470,48
    Xp=lambda lon:m+(lon-lo0)/((lo1-lo0) or 1)*(W-2*m)
    Yp=lambda lat:m+(la1-lat)/((la1-la0) or 1)*(H-2*m)
    marks=""
    for i,(c,st,col,lab) in enumerate(sorted(pts,key=lambda z:-z[0][0])):
        x=Xp(c[1]); y=Yp(c[0]); dy=-11 if i%2==0 else 18
        marks+=('<circle cx="%.1f" cy="%.1f" r="7" fill="%s" stroke="#fff" stroke-width="1.5"><title>%s — %s</title></circle>'
                '<text x="%.1f" y="%.1f" font-size="9.5" text-anchor="middle" fill="#2b211b" paint-order="stroke" stroke="#fff" stroke-width="2.5">%s</text>'
                %(x,y,col,lab,st,x,y+dy,lab))
    svg=('<svg viewBox="0 0 %d %d" width="100%%" style="max-width:760px;height:auto;background:#f3efe9;border:1px solid var(--line);border-radius:12px" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Estate bench map">'
         '<text x="%d" y="28" font-size="13" font-weight="700" fill="#5b3a29">Estate bench map · North up · one marker per store</text>%s</svg>'%(W,H,m,marks))
    legend=('<div style="margin-top:10px;font-size:11.5px;color:#6b5a47;display:flex;gap:18px;flex-wrap:wrap">'
            '<span style="display:inline-flex;align-items:center;gap:6px"><span style="width:12px;height:12px;border-radius:3px;background:#1f8a4c;display:inline-block"></span>Bench ready (named successor)</span>'
            '<span style="display:inline-flex;align-items:center;gap:6px"><span style="width:12px;height:12px;border-radius:3px;background:#b8860b;display:inline-block"></span>Thin (team, no named bench)</span>'
            '<span style="display:inline-flex;align-items:center;gap:6px"><span style="width:12px;height:12px;border-radius:3px;background:#c0392b;display:inline-block"></span>Gap (manager vacancy)</span></div>')
    rows="".join('<tr><td style="text-align:left">%s</td><td>%s</td><td style="text-align:left">%s</td><td>%s</td></tr>'%(n,ld,bn,tag(sl,STAG[st])) for (n,ld,bn,sl,st) in tbl)
    upd=BENCH.get('_updated','')
    BENCH_NAV='<button class="tab-btn" data-tab="bench"><span>🪑</span>Bench</button>'
    BENCH_PANEL=('<section class="tab-panel" id="tab-bench">'
      '<div class="cards" style="grid-template-columns:repeat(3,1fr)">'
      '<div class="card"><div class="lbl">Bench-ready stores</div><div class="val" style="color:#1f8a4c">%d</div><div class="meta">named Bench Manager / pipeline</div></div>'
      '<div class="card"><div class="lbl">Thin bench</div><div class="val" style="color:#b8860b">%d</div><div class="meta">leadership team, no named successor</div></div>'
      '<div class="card"><div class="lbl">Capability gap</div><div class="val" style="color:#c0392b">%d</div><div class="meta">Store Manager vacancy</div></div></div>'
      '<div class="note" style="margin-top:12px"><b>Bench</b> = succession cover from the HRP ‘Bench and HRP’ roster. <b style="color:#1c6b3d">Green</b> = a named Bench Manager (promotion-ready) is in place; <b style="color:#7a5b12">amber</b> = a full leadership line but no named successor; <b style="color:#9a2f22">red</b> = a Store Manager vacancy. Refreshed Monday.</div>'
      '<div class="section-title">Where the bench is &mdash; and the gaps</div>'
      '<div class="panel">%s%s</div>'
      '<div class="section-title" style="margin-top:18px">Per-store bench &amp; succession</div>'
      '<div class="panel"><div style="overflow-x:auto"><table class="scorecard"><thead><tr><th>Store</th><th>Leadership team</th><th>Bench / successor</th><th>Status</th></tr></thead><tbody>%s</tbody></table></div>'
      '<div class="mini" style="margin-top:8px">Leadership team = filled Store Manager + Assistant Managers + Supervisors. “Leamington Retail” has no mapped location so it is listed but not plotted. Source: HRP ‘Bench and HRP’ tab, pulled %s.</div></div>'
      '</section>')%(ng,na,nr,svg,legend,rows,upd)

# ---- fill template ----
repl={
 "{{BENCH_NAV}}":BENCH_NAV,"{{BENCH_PANEL}}":BENCH_PANEL,
 "{{WX_NUDGE}}":wx_nudge([R[s]['coords'] for s in stores if R[s].get('coords')],wx_recent(amix)),
 "{{WX_NUDGE_TOP}}":WX_TOP,"{{WX_FOOD}}":WX_FOOD,
 "{{COACH}}":COACH,"{{COACH_CARDS}}":COACH_CARDS,"{{MOVROWS}}":mov,"{{MOV_NOTE}}":mov_note,"{{PLANNER_LINKS}}":PLANNERS_HTML,
 "{{GEN_STAMP}}":GEN_STAMP,"{{FOOT_VIEW}}":"engagement","{{ROLE}}":ROLE,"{{SPEED_WIDGETS}}":SPEED_WIDGETS,"{{LW_LABEL}}":lw_label,"{{NSTORES}}":str(len(stores)),"{{PILL}}":COACH+" · "+ROLE+" · all "+str(len(stores))+" stores","{{FOCUS_LI}}":focus_li,
 "{{AREA_LAST}}":GBP(area_last),"{{AREA_YOY_LW}}":pctxt(ylw),"{{LWCHIP}}":"up" if ylw>=0 else "dn",
 "{{AREA_4WK}}":GBP(area_4wk),"{{AREA_YOY_4W}}":pctxt(y4),"{{W4CHIP}}":"up" if y4>=0 else "dn",
 "{{AREA_WASTE_PCT}}":str(awpct),"{{AREA_WASTE_RETAIL}}":GBP(awr),"{{WASTE_PCT_LW}}":str(awpct_lw),"{{WASTE_RETAIL_LW}}":GBP(awr_lw),"{{WASTE_RETAIL_WK}}":GBP(awr_wk),"{{ATV_MED}}":"%.2f"%atv_med,
 "{{LW_TABLE}}":lw_rows,"{{LW_TOTAL}}":lw_total,"{{SALESTBL}}":salestbl,"{{DPG_ROWS}}":dpg_rows,"{{DOWG_ROWS}}":dowg_rows,
 "{{DPG_NOTE}}":dpg_note,"{{DOWG_NOTE}}":dowg_note,"{{SALES_FOCUS}}":sales_focus,
 "{{AVF_WK}}":ACT.get('_week_label','last week'),"{{AVF_ROWS}}":avf,
 "{{WK_THIS}}":wk_this,"{{WK_N1}}":wk_n1,"{{WK_N2}}":wk_n2,"{{FCST_ROWS}}":fcst_rows,
 "{{FCST_AREA_THIS}}":GBP(sumf[0]),"{{FCST_HRS_THIS}}":str(sumh[0]),"{{FCST_BLENDED}}":str(fcst_blended),"{{TARGETS_LINK}}":TARGETS,
 "{{YJS}}":json.dumps(yjs),"{{OUTJS}}":json.dumps(outjs),
 "{{MIX_AREA_ROWS}}":mar,"{{CAPHDR}}":caphdr,"{{CAPMAT}}":capmat,"{{MIX_DS}}":mix_ds,"{{MIX_LBLS}}":mix_lbls,"{{MIX_NOTE}}":mix_note,"{{MIX_FOCUS}}":mix_focus,
 "{{F1TBL}}":f1tbl,"{{F1_FIN_DS}}":f1_fin_ds,"{{F1_FIN_LBLS}}":f1_fin_lbls,"{{F1_CHAMP_AVG}}":str(f1_champ_avg),"{{AVG_FIN2}}":str(avg_fin),
 "{{F1_TOP}}":f1_top,"{{F1_TOP_META}}":f1_top_meta,"{{CON_HTML}}":con_html,"{{CON_NOTE}}":con_note,"{{DRV_ROWS}}":drv_rows,"{{F1_NOTE}}":f1_note,"{{F1_FOCUS}}":f1_focus,
 "{{RMS_ROWS}}":rms_rows,"{{HR_ROWS}}":hr_rows,"{{AREA_RMS}}":str(area_rms),"{{AREA_SICK}}":str(area_sick),"{{AREA_SICKFS}}":str(area_sickfs),"{{AREA_LATE}}":str(area_late),
 "{{RTW_COMP}}":str(rtw_comp),"{{RTW_COMP_K}}":rtw_k,"{{AREA_REP}}":str(area_rep),"{{AREA_RTW}}":str(area_rtw),"{{RMS_NOTE}}":rms_note,"{{RTW_NOTE}}":rtw_note,
 "{{AREA_RATING}}":str(area_rating),"{{AREA_REVIEWS}}":format(area_reviews,",d"),"{{CUST_ROWS}}":cust_rows,"{{CUST_NOTE}}":cust_note,"{{SENT_FOCUS}}":sent_focus,
}
html=open('TEMPLATE_COACH.html',encoding='utf-8').read()
for k,v in repl.items(): html=html.replace(k,v)
import re as _re
left=_re.findall(r'{{[A-Z_0-9]+}}',html)
outfn=COACH+"_Engagement_Dashboard.html"
open(outfn,'w',encoding='utf-8').write(html)
print(outfn,"written;","leftover placeholders:",sorted(set(left)) or "none")
