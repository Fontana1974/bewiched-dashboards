import json,sys
from collections import defaultdict
from statistics import mean,median
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
import datetime as _dtm; GEN_STAMP=_dtm.datetime.now().strftime('%d %b %Y, %H:%M')
PLANNERS={"Jon":"https://docs.google.com/spreadsheets/d/1PSjBGiR40171h769esQCtn3ldcpCB5XJyfqRTo7Yccs/edit","Rich":"https://docs.google.com/spreadsheets/d/11XuXn9zQr-JB4x2fQ0ORV96Sf-U7xWPQPvg2YlCl_dQ/edit","Ian":"https://docs.google.com/spreadsheets/d/1_qdK6fzqPg1NcA2KKMy2TnaZ8nQJtVE-fglz2On3oBw/edit"}
try: FD=json.load(open('f1_detail.json'))
except FileNotFoundError: FD={}
try: STH=json.load(open('storehealth.json'))
except FileNotFoundError: STH={'targets':{},'stores':{}}
STT=STH.get('targets',{}); STS=STH.get('stores',{})
def _f1score(s):
    d=FD.get(s)
    if isinstance(d,dict) and d.get('race') and len(d['race'])>5 and d['race'][5] not in (None,''):
        try: return float(d['race'][5])
        except: return None
    return None
def _avf_rows(stores,R):
    body=""; sfc=sa=ssc=su=0
    for s in sorted(stores,key=lambda x:-R[x]['lw26']):
        a=ACT.get(s)
        if not isinstance(a,list): continue
        fc=a[1] or 0; sched=a[2] or 0; used=a[3] or 0; act=R[s]['lw26']; tcph=R[s].get('cph',55)
        if isinstance(OVR.get(s),dict) and OVR[s].get('used_lastwk') is not None: used=OVR[s]['used_lastwk']
        sfc+=fc; sa+=act; ssc+=sched; su+=used
        sv=round(100*(act/fc-1)) if fc else None
        hv=round(used-sched,1) if (used or sched) else None
        ac=round(act/used,2) if used else None
        svk='t-ok' if (sv is not None and sv>=0) else 't-red'
        cpk='t-ok' if (ac is not None and ac>=tcph) else 't-red'
        hvk='t-ok' if (hv is not None and hv<=0) else 't-amber'
        svt=(("+" if sv>=0 else "")+str(sv)+"%") if sv is not None else "n/a"
        hvt=(("+" if hv>=0 else "")+("%g"%hv)) if hv is not None else "n/a"
        body+=(f'<tr><td style="font-weight:700">{s}</td><td>£{fc:,.0f}</td><td style="font-weight:700">£{act:,.0f}</td>'
               f'<td>{tag(svt,svk)}</td><td>{"%g"%sched}</td><td>{"%g"%used}</td><td>{tag(hvt,hvk)}</td>'
               f'<td>£{tcph}</td><td>{tag(("£%.2f"%ac) if ac is not None else "n/a",cpk)}</td></tr>')
    tsv=round(100*(sa/sfc-1)) if sfc else 0; tac=round(sa/su,2) if su else 0; thv=round(su-ssc,1)
    body+=(f'<tr style="font-weight:700;background:#EFE6DC"><td>TOTAL</td><td>£{sfc:,.0f}</td><td>£{sa:,.0f}</td>'
           f'<td>{("+" if tsv>=0 else "")+str(tsv)}%</td><td>{"%g"%ssc}</td><td>{"%g"%su}</td><td>{("+" if thv>=0 else "")+("%g"%thv)}</td><td></td><td>£{tac:.2f}</td></tr>')
    return body
SHORT={"Burton Latimer":"Burton","Corby":"Corby","Higham Ferrers":"Higham","Kettering":"Kettering","Olney":"Olney",
"Peterborough Bridge Street":"P'boro Bridge St","Peterborough Fletton Quays":"P'boro Fletton","Rothwell":"Rothwell","Rushden Lakes":"Rushden Lakes",
"Attleborough":"Attleborough","Billing Drive Thru":"Billing DT","Glenvale Drive Thru":"Glenvale DT","HOE Balsall Common":"Balsall Common",
"Leamington Parade":"Leam Parade","Lower Heathcote":"Lower Heathcote","Market Harborough":"Mkt Harborough","Northampton":"Northampton",
"Northampton Drive-Thru":"Northampton DT","Rugby":"Rugby","Wellingborough":"Wellingborough","Wellingborough Train Station":"W'boro Train Stn"}
PAL=["#2d6fb3","#c08a2d","#7a4ea8","#1f8a4c","#0e8a8a","#d2691e","#b8860b","#c0392b","#5b3a29","#3f8e7c","#8a5a44"]
GBP=lambda v:"£"+format(int(round(v)),",d")
def cls(v,g,a,rev=False):
    if v is None: return "t-na"
    if rev: return "t-ok" if v<=g else ("t-amber" if v<=a else "t-red")
    return "t-ok" if v>=g else ("t-amber" if v>=a else "t-red")
def tag(t,k): return f'<span class="tag {k}">{t}</span>'
def pctxt(v): return "n/a" if v is None else (("+" if v>=0 else "")+f"{v}%")

# F1 drivers name map (champ uses informal names)
DRVMAP={"Burton":"Burton Latimer","Fletton":"Peterborough Fletton Quays","Lakes":"Rushden Lakes","Corby":"Corby","Rothwell":"Rothwell",
"Peterborough":"Peterborough Bridge Street","Kettering":"Kettering","Higham":"Higham Ferrers","Olney":"Olney",
"Leamington Parade":"Leamington Parade","Northampton Grosvenor":"Northampton","Train Station":"Wellingborough Train Station",
"Market Harborough":"Market Harborough","Glenvale Drive Thru":"Glenvale Drive Thru","Market Street":"Wellingborough",
"Lower Heathcote, Warwick":"Lower Heathcote","Northampton Drive Thru":"Northampton Drive-Thru","Rugby":"Rugby",
"Balsall Common":"HOE Balsall Common","Attleborough":"Attleborough","Billing Drive Thru":"Billing Drive Thru"}

def build(coach):
    stores=sorted([s for s in REC if REC[s]['coach']==coach])
    COL={s:PAL[i%len(PAL)] for i,s in enumerate(stores)}
    R={s:REC[s] for s in stores}
    atv_med=median([R[s]['atv'] for s in stores])
    # area aggregates
    area_last=sum(R[s]['lw26'] for s in stores); area_4wk=sum(R[s]['s4'] for s in stores)
    comp=[s for s in stores if R[s]['lw25']>0]
    ylw=round(100*(sum(R[s]['lw26'] for s in comp)/sum(R[s]['lw25'] for s in comp)-1),1) if comp else 0
    comp4=[s for s in stores if R[s]['s4_25']>0]
    y4=round(100*(sum(R[s]['s4'] for s in comp4)/sum(R[s]['s4_25'] for s in comp4)-1),1) if comp4 else 0
    awr=sum(R[s]['wr'] for s in stores); awpct=round(100*awr/area_4wk,1); awr_lw=sum(R[s].get('wr_lw',0) for s in stores); area_lw_sales=sum(R[s].get('lw_sales',0) for s in stores); awpct_lw=round(100*awr_lw/area_lw_sales,1) if area_lw_sales else 0; awr_wk=round(awr/4)
    avgcov=round(mean([R[s]['visdow']['total'] for s in stores]))
    audit_vals=[R[s]['audit_qtd'] for s in stores if R[s].get('audit_qtd') is not None]; audit_mean=round(mean(audit_vals),2) if audit_vals else None
    avg_fin=round(mean([R[s]['f1'][0] for s in stores]),1)
    # constructor standing
    cons=sorted(champ['cons'],key=lambda x:-x[3]); jr=[i+1 for i,c in enumerate(cons) if c[0]==coach][0]
    cdict={c[0]:c[3] for c in cons}
    con_pos=f"P{jr} of {len(cons)}"
    con_meta=f"{coach} {cdict[coach]} avg pts/store · "+" · ".join(f"{c[0]} {c[3]}" for c in cons if c[0]!=coach)
    # ---- scorecard ----
    ov=""
    for s in stores:
        r=R[s]; v4=r['vs4w']; ylw_s=r['yoy_lw']; y4_s=r['yoy_4w']; fin=r['f1_finish']; cov=r['visdow']['total']; av=r['avail']; wp=r['waste_pct']; wpl=r.get('waste_pct_lw', wp); gy=round(100*(r['tx26']/r['tx25']-1),1) if r['tx25'] else None; aud=r.get('audit_qtd'); aud_cell=tag(("%.2f"%aud) if aud is not None else "n/a",cls(aud,4.5,4.0))
        new = r['lw25']==0
        ov+=("<tr>"+f'<td style="font-weight:700"><span class="dotc" style="background:{COL[s]}"></span>{s}</td>'
          f'<td style="font-weight:700">{GBP(r["lw26"])}</td>'
          f'<td>{tag("new*" if new else pctxt(ylw_s),"t-amber" if new else cls(ylw_s,0,-5))}</td>'
          f'<td>{tag("new*" if new else pctxt(gy),"t-amber" if new else cls(gy,0,-5))}</td>'
          f'<td>{aud_cell}</td>'
          f'<td>{tag(f"{wpl}%",cls(wpl,3,4,rev=True))}</td><td>{tag((str(av)+"%") if av is not None else "n/a",cls(av,95,85))}</td>'
          f'<td>{tag("P"+str(fin),cls(fin,6,15,rev=True))}</td><td>{tag(f"{cov}%",cls(cov,70,40))}</td></tr>')
    # ---- movements ----
    DOWL=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    def hc(p):
        a=round(p/100*0.85+0.06,2); fg="#fff" if p>=45 else "#5b3a29"; return f'<td class="dc" style="background:rgba(31,138,76,{a});color:{fg}">{p if p>0 else ""}</td>'
    mov=""
    for s in sorted(stores,key=lambda x:-R[x]['visdow']['total']):
        vd=R[s]['visdow']; tot=vd['total']; bc="#1f8a4c" if tot>=70 else ("#b8860b" if tot>=40 else "#c0392b")
        nw=vd.get('weeks',60); ntag=f' <span class="newtag">{nw} wks</span>' if nw<30 else ''
        mov+=(f'<tr><td class="ms">{SHORT[s]}{ntag}</td>'+"".join(hc(p) for p in vd['byday'])+
              f'<td class="cov"><div class="pbar"><i style="width:{tot}%;background:{bc}"></i></div><span>{tot}%</span></td></tr>')
    covd=sorted(stores,key=lambda x:-R[x]['visdow']['total'])
    mov_note=f"{coach} is on site most at <b>{SHORT[covd[0]]} ({R[covd[0]]['visdow']['total']}%)</b> and <b>{SHORT[covd[1]]} ({R[covd[1]]['visdow']['total']}%)</b>; thinnest at <b>{SHORT[covd[-1]]} ({R[covd[-1]]['visdow']['total']}%)</b>. Average patch coverage <b>{avgcov}%</b>."
    # ---- sales: lw table + growth heatmaps + table ----
    def yoycell(v): return '<td><span class="tag t-na">n/a</span></td>' if v is None else f'<td><span class="tag {"t-ok" if v>=0 else "t-red"}">{("+" if v>=0 else "")}{round(v,1)}%</span></td>'
    lw_rows=""; A0=[0,0,0,0]; sl=0; st_=0
    for s in sorted(stores,key=lambda x:-R[x]['lw26']):
        r=R[s]; lw=r['lw26']; lw25=r['lw25']; t26=r['tx26']; t25=r['tx25']; sl+=lw; st_+=t26
        sy=None if lw25==0 else 100*(lw/lw25-1); avs=lw/t26 if t26 else 0
        avs25=(lw25/t25) if t25 else None; ay=None if avs25 is None else 100*(avs/avs25-1); gy=None if t25==0 else 100*(t26/t25-1)
        if lw25>0: A0[0]+=lw;A0[1]+=lw25;A0[2]+=t26;A0[3]+=t25
        lw_rows+=(f'<tr><td>{s}</td><td style="font-weight:700">{GBP(lw)}</td>{yoycell(sy)}<td>£{avs:.2f}</td>{yoycell(ay)}<td>{t26:,}</td>{yoycell(gy)}</tr>')
    asy=100*(A0[0]/A0[1]-1) if A0[1] else 0; aavs=sl/st_; aay=100*((A0[0]/A0[2])/(A0[1]/A0[3])-1) if A0[3] else 0; agy=100*(A0[2]/A0[3]-1) if A0[3] else 0
    lw_total=f'<tr><td>AREA ({len(stores)} stores)</td><td>{GBP(sl)}</td>{yoycell(asy)}<td>£{aavs:.2f}</td>{yoycell(aay)}<td>{st_:,}</td>{yoycell(agy)}</tr>'
    salestbl=""
    for s in sorted(stores,key=lambda x:-R[x]['s4']):
        r=R[s]; salestbl+=(f'<tr><td>{s}</td><td>{GBP(r["s4"])}</td><td class="{"pos" if (r["yoy_4w"] or 0)>=0 else "neg"}">{pctxt(r["yoy_4w"])}</td><td>£{r["atv"]:.2f}</td><td>{GBP(r["lw26"])}</td><td class="{"pos" if r["vs4w"]>=0 else "neg"}">{pctxt(r["vs4w"])}</td></tr>')
    def grcell(v):
        if v is None: return '<td class="gc" style="background:#eee;color:#999">n/a</td>'
        if v>=5: bg,fg="#1f8a4c","#fff"
        elif v>=0: bg,fg="#d6ebde","#1c6b3d"
        elif v>-5: bg,fg="#f7d9d4","#8c2f22"
        else: bg,fg="#c0392b","#fff"
        return f'<td class="gc" style="background:{bg};color:{fg}">{("+" if v>=0 else "")}{v}%</td>'
    DP=["Morning","Lunch","Afternoon","Evening"]
    dpg_rows="".join(f'<tr><td class="ms">{SHORT[s]}</td>'+"".join(grcell(R[s]["daypart_growth"][dp]) for dp in DP)+"</tr>" for s in stores)
    dowg_rows="".join(f'<tr><td class="ms">{SHORT[s]}</td>'+"".join(grcell(v) for v in R[s]["dow_growth"])+"</tr>" for s in stores)
    # area daypart bests
    dpa={dp:[R[s]['daypart_growth'][dp] for s in stores if R[s]['daypart_growth'][dp] is not None] for dp in DP}
    best_dp=max(DP,key=lambda dp: mean(dpa[dp]) if dpa[dp] else -99)
    dpg_note=f"% change vs the same 4 weeks in 2025 (2026 openings show n/a). Strongest daypart growth is <b>{best_dp}</b>. Use it to target the daypart that's slipping."
    dowg_note="Same YoY basis by weekday — a green column is a day to protect, a red one is where to add a promo or labour."
    sales_focus="Chase the red cells in the growth grids; protect the green days with labour."
    # ---- wastage yjs/outjs + Area ----
    yjs={s:{"latest":"08/06/2026","items":R[s]['yield_items']} for s in stores}
    outjs={s:clean_outliers(R[s]['outliers']) for s in stores}
    # Area aggregate
    ai=defaultdict(lambda:{'av':[], 'sold':0,'w':0,'wr':0.0})
    for s in stores:
        for it in R[s]['yield_items']:
            a=ai[it[0]]; a['av'].append(it[1]); a['sold']+=it[3]; a['w']+=it[2]/100*(it[3]/(1-it[2]/100)) if it[2]<100 else 0
    # simpler: aggregate outliers across stores by name for Area outliers
    oa=defaultdict(lambda:{'w':0,'s':0,'wr':0.0})
    for s in stores:
        for o in outjs[s]:
            oa[o[0]]['w']+=o[2]; oa[o[0]]['s']+=o[3]; oa[o[0]]['wr']+=o[4]
    aol=sorted([[n,round(100*v['w']/(v['w']+v['s']),1) if (v['w']+v['s'])>0 else 0,v['w'],v['s'],round(v['wr'])] for n,v in oa.items() if v['w']>0],key=lambda x:-x[4])[:8]
    # area yield items: aggregate by product
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
    yjs[f"Area (all {len(stores)})"]={"latest":"08/06/2026","items":area_items}; outjs[f"Area (all {len(stores)})"]=aol
    # ---- mix ----
    area_sales=sum(R[s]['tot'][0] for s in stores)
    amix={}
    swp=[s for s in stores if R[s].get('mix_prev')]
    tcl=sum(R[s]['mix'][c]['sales'] for s in swp for c in CATS) or 1
    tpl=sum(R[s]['mix_prev'][c]['sales'] for s in swp for c in CATS) or 1
    def _mv(cur,pp,valued=False):
        if pp is None: return '<span style="color:#9a8a7c;font-size:11px"> (new this period)</span>'
        if abs(pp)<0.05: return '<span style="color:#9a8a7c;font-size:11px"> (about the same as four weeks ago)</span>'
        prior=round(cur-pp,1); up=pp>0; word="up" if up else "down"
        col=('#1f8a4c' if up else '#c0392b') if valued else '#6b7785'
        return f'<span style="color:{col};font-size:11px"> ({word} from {prior}% four weeks ago)</span>'
    for c in CATS:
        cs=sum(R[s]['mix'][c]['sales'] for s in stores); caps=[R[s]['mix'][c]['cap'] for s in stores]; cs_lw=sum(R[s]['mix_lw'][c]['sales'] for s in stores if R[s].get('mix_lw')); caps_lw=[R[s]['mix_lw'][c]['cap'] for s in stores if R[s].get('mix_lw')]
        csl=sum(R[s]['mix'][c]['sales'] for s in swp); psl=sum(R[s]['mix_prev'][c]['sales'] for s in swp)
        mix_pp=round(100*csl/tcl-100*psl/tpl,1) if swp else None
        cap_pp=round(mean([R[s]['mix'][c]['cap'] for s in swp])-mean([R[s]['mix_prev'][c]['cap'] for s in swp]),1) if swp else None
        amix[c]={'mix':round(100*cs/area_sales,1),'cap_avg':round(mean(caps),1),'mix_pp':mix_pp,'cap_pp':cap_pp,'mix_lw':round(100*cs_lw/area_lw_sales,1) if area_lw_sales else 0,'cap_lw':round(mean(caps_lw),1) if caps_lw else 0}
    mar=""
    for c in CATS:
        caps=[(s,R[s]['mix'][c]['cap']) for s in stores]; best=max(caps,key=lambda x:x[1]); worst=min(caps,key=lambda x:x[1])
        mar+=(f'<tr><td>{c}</td><td><b>{amix[c]["mix"]}%</b> <span style="color:#9a8a7c;font-size:10px">4-wk run rate</span>{_mv(amix[c]["mix"],amix[c]["mix_pp"])}<br><span style="color:#6b5a47;font-size:11px">last week {amix[c]["mix_lw"]}%</span></td><td><b>{amix[c]["cap_avg"]}%</b> <span style="color:#9a8a7c;font-size:10px">4-wk run rate</span>{_mv(amix[c]["cap_avg"],amix[c]["cap_pp"],True)}<br><span style="color:#6b5a47;font-size:11px">last week {amix[c]["cap_lw"]}%</span></td><td style="text-align:left;color:#1f8a4c">{SHORT[best[0]]} {best[1]}%</td><td style="text-align:left;color:#c0392b">{SHORT[worst[0]]} {worst[1]}%</td></tr>')
    caphdr="".join(f'<th>{c.split(" ")[0]}</th>' for c in CATS)
    capmat=""
    for s in stores:
        cells=""
        for c in CATS:
            cap=R[s]['mix'][c]['cap']; av=amix[c]['cap_avg']; k="t-ok" if cap>=av*1.05 else ("t-red" if cap<=av*0.85 else "t-amber"); cells+=f'<td>{tag(f"{cap}%",k)}</td>'
        capmat+=f'<tr><td class="ms">{SHORT[s]}</td>{cells}</tr>'
    mix_ds=json.dumps([amix[c]['mix'] for c in CATS]); mix_lbls=json.dumps(CATS)
    foodcap=amix['Food']['cap_avg']
    mix_note=f"Hot drinks anchor the mix; <b>Food capture sits at ~{foodcap}%</b> across the area — the clearest add-on prize. The small note after each figure shows the change vs four weeks ago (like-for-like): capture changes are coloured green (up) / red (down); mix-share changes are neutral grey."
    mix_focus="Food attach is the area-wide prize — prompt a food add-on at the till where the Food column shows red."
    # ---- F1 ----
    f1tbl=""
    for s in sorted(stores,key=lambda x:R[x]['f1'][0]):
        fin,ch,last6=R[s]['f1']
        spk="".join(f'<span class="spk" style="height:{max(2,round((26-int(p))/26*18))}px" title="P{p}"></span>' for p in last6)
        _sc=_f1score(s)
        f1tbl+=f'<tr><td>{s}</td><td>{tag("P"+str(fin),cls(fin,6,15,rev=True))}</td><td>{ch}</td><td>{tag(("%g"%_sc) if _sc is not None else "n/a",cls(_sc,210,285,rev=True))}</td><td style="text-align:left"><span class="spkwrap">{spk}</span></td></tr>'
    f1_fin_ds=json.dumps([R[s]['f1'][0] for s in sorted(stores,key=lambda x:R[x]['f1'][0])])
    f1_fin_lbls=json.dumps([SHORT[s] for s in sorted(stores,key=lambda x:R[x]['f1'][0])])
    f1_champ_avg=round(mean([R[s]['f1'][1] for s in stores]),1)
    bestf=sorted(stores,key=lambda x:R[x]['f1'][0]); worstf=bestf[::-1]
    f1_top=f"{SHORT[bestf[0]]} P{R[bestf[0]]['f1'][0]}"; f1_top_meta=f"{SHORT[bestf[1]]} P{R[bestf[1]]['f1'][0]} next" if len(bestf)>1 else ""
    con_note=f"{coach}'s {len(stores)}-store team averages {cdict[coach]} pts/store (rank {jr} of {len(cons)}). Every weekend finish lifts the constructor average — the bottom-third stores are where the championship is won."
    f1_note=f"Best of the grid: <b>{SHORT[bestf[0]]} (P{R[bestf[0]]['f1'][0]})</b>; needs a reset: <b>{SHORT[worstf[0]]} (P{R[worstf[0]]['f1'][0]})</b>. The sparkline shows recent form — taller = better finish."
    f1_focus=f"Reset the weekend routine at {SHORT[worstf[0]]}" + (f" &amp; {SHORT[worstf[1]]}" if len(worstf)>1 and R[worstf[1]]['f1'][0]>15 else "")+"; lift qualifying to fix the handicapped grid start."
    # constructors bars + drivers
    maxavg=max(c[3] for c in cons); con_html=""
    for i,c in enumerate(cons):
        cc,total,nst,avg=c; w=round(100*avg/maxavg); hl='style="background:#fbf4e9;border:1.5px solid #e7b35a"' if cc==coach else ''
        badge=f' <span style="color:#b8860b;font-weight:700;font-size:11px">◄ {coach}</span>' if cc==coach else ''
        con_html+=(f'<div class="crow" {hl}><div class="crank">{i+1}</div><div class="cbody"><div class="cname">{cc}{badge}</div><div class="cbar"><i style="width:{w}%"></i></div><div class="csub">{total} pts total · {nst} stores</div></div><div class="cval">{avg}<small>pts/store</small></div></div>')
    COACHCHIP={"Jon":"t-ok","Rich":"t-amber","Ian":"t-amber"}; drv=champ['drivers']; drv_rows=""
    for i,(stn,cc,pts) in enumerate(drv):
        mine = stn in stores or DRVMAP.get(stn) in stores
        hl=' style="background:#fbf4e9"' if mine else ''; you=f' <span style="color:#b8860b;font-weight:700">◄ {coach}</span>' if mine else ''
        drv_rows+=f'<tr{hl}><td style="text-align:center">{i+1}</td><td style="text-align:left;font-weight:{700 if mine else 400}">{stn}{you}</td><td>{tag(cc,COACHCHIP.get(cc,"t-na"))}</td><td style="font-weight:700">{pts}</td></tr>'
    # ---- sentiment ----
    sent={s:R[s]['sent'] for s in stores}
    rmsv=[sent[s]['rms'] for s in stores if sent[s]['rms']]; area_rms=round(mean(rmsv),2) if rmsv else 0
    area_sick=sum(sent[s]['sick'] for s in stores); area_late=sum(sent[s]['late'] for s in stores); area_rtw=sum(sent[s]['rtw'] for s in stores)
    area_sickfs=sum(sent[s].get('sickfs',sent[s]['sick']) for s in stores); area_out45=sum(sent[s].get('out45',0) for s in stores); area_sick45=sum(sent[s].get('sick45',0) for s in stores)
    _cand=sorted(stores,key=lambda z:(-sent[z].get('out45',0),-sent[z].get('sickfs',0),z))[0]; _wn=sent[_cand].get('out45',0)
    _rb=('#fbeae8','#eccfca','#8c2f22') if area_out45>0 else ('#e6f4ec','#cfe6d8','#1c6b3d')
    _rsub=(f" &mdash; of {area_sick45} sick-for-shift in window · worst {SHORT.get(_cand,_cand)} ({_wn})" if area_out45>0 else " &mdash; all caught up")
    rtw_chip=f'<li style="list-style:none;margin:2px 0 9px -18px;padding:9px 13px;border-radius:10px;font-weight:700;background:{_rb[0]};border:1px solid {_rb[1]};color:{_rb[2]}">🩹 RTWs to do &mdash; last 45 days: {area_out45}{_rsub}</li>'
    rtw_comp=round(100*area_rtw/area_sickfs) if area_sickfs else 0; rtw_k="t-ok" if rtw_comp>=80 else ("t-amber" if rtw_comp>=50 else "t-red")
    reps=[sent[s]['rep_pct'] for s in stores if sent[s]['rep_pct'] is not None]; area_rep=round(mean(reps)) if reps else 0
    rms_rows=""
    for s in sorted(stores,key=lambda x:-(sent[x]['rms'] or 0)):
        v=sent[s]['rms']
        if v is None: continue
        w=round(100*v/5); k="t-ok" if v>=4.5 else ("t-amber" if v>=4.0 else "t-red"); bc="#1f8a4c" if v>=4.5 else ("#b8860b" if v>=4.0 else "#c0392b")
        rms_rows+=f'<tr><td class="ms">{SHORT[s]}</td><td style="width:55%"><div class="pbar" style="width:100%"><i style="width:{w}%;background:{bc}"></i></div></td><td>{tag(f"{v:.2f}",k)}</td><td class="mini">{sent[s]["rms_n"]} ratings</td></tr>'
    hr_rows=""
    for s in sorted(stores,key=lambda x:-sent[x]['sick']):
        x=sent[s]; rep=x['rep_pct']; rr=x['rtw_rate']
        repk="t-na" if rep is None else ("t-ok" if rep>=90 else ("t-amber" if rep>=70 else "t-red"))
        rrk="t-na" if rr is None else ("t-ok" if rr>=80 else ("t-amber" if rr>=50 else "t-red"))
        hr_rows+=f'<tr><td>{s}</td><td>{x.get("sickfs",x["sick"])}</td><td>{x["late"]}</td><td>{tag((str(rep)+"%") if rep is not None else "n/a",repk)}</td><td>{x["rtw"]}</td><td>{tag((str(rr)+"%") if rr is not None else "n/a",rrk)}</td></tr>'
    lowrms=sorted([s for s in stores if sent[s]['rms']],key=lambda x:sent[x]['rms'])
    rms_note=f"RMS is the team's own shift rating. Softest at <b>{SHORT[lowrms[0]]} ({sent[lowrms[0]]['rms']})</b>" + (f" and <b>{SHORT[lowrms[1]]} ({sent[lowrms[1]]['rms']})</b>" if len(lowrms)>1 else "")+f"; strongest <b>{SHORT[lowrms[-1]]} ({sent[lowrms[-1]]['rms']})</b>."
    sickd=sorted(stores,key=lambda x:-sent[x]['sick'])
    rtw_note=f"<b>Return-to-work is the gap.</b> Only {area_rtw} RTW interviews logged against {area_sickfs} sick-for-shift absences ({rtw_comp}%) — policy is an RTW chat after every absence. <b>{SHORT[sickd[0]]} ({sent[sickd[0]]['sick']})</b> carries the most sickness."
    # focus bullets
    syoy = f"area ran <b>{GBP(area_last)}</b> last week ({pctxt(ylw)} YoY)" if comp else f"area ran <b>{GBP(area_last)}</b> last week"
    topsales=sorted(comp4,key=lambda x:-(R[x]['yoy_4w'] or -99));
    sales_b=f"<b>Sales:</b> {syoy}; 4-week {pctxt(y4)} YoY."+(f" <b>{SHORT[topsales[0]]} {pctxt(R[topsales[0]]['yoy_4w'])}</b> leads." if topsales else "")
    wpd=sorted(stores,key=lambda x:-R[x]['waste_pct'])
    waste_b=f"<b>Wastage:</b> area {awpct}% retail; worst <b>{SHORT[wpd[0]]} ({R[wpd[0]]['waste_pct']}%)</b>."
    f1_b=f"<b>Op's Excellence:</b> best <b>{SHORT[bestf[0]]} P{R[bestf[0]]['f1'][0]}</b>; reset <b>{SHORT[worstf[0]]} P{R[worstf[0]]['f1'][0]}</b>."
    pres_b=f"<b>Presence &amp; team:</b> {coach} averages <b>{avgcov}%</b> coverage; RTW completion just <b>{rtw_comp}%</b> across {area_sickfs} sick-for-shift (lateness excluded)."
    focus_li=rtw_chip+"".join(f"<li>{b}</li>" for b in [sales_b,f1_b,waste_b,pres_b])

    # ---- customer (Google reviews) ----
    cu={s:R[s].get('cust',{'rating':None,'reviews':0}) for s in stores}
    rated=[s for s in stores if cu[s]['rating'] is not None]
    area_rating=round(mean([cu[s]['rating'] for s in rated]),2) if rated else 0
    area_reviews=sum(cu[s]['reviews'] for s in stores)
    def ratcol(v): return "#1f8a4c" if v>=4.7 else ("#b8860b" if v>=4.5 else "#c0392b")
    def ratk(v): return "t-ok" if v>=4.7 else ("t-amber" if v>=4.5 else "t-red")
    cust_rows=""
    for s in sorted(rated,key=lambda x:-cu[x]['rating']):
        v=cu[s]['rating']; w=round(100*v/5)
        cust_rows+=f'<tr><td class="ms">{SHORT[s]}</td><td style="width:55%"><div class="pbar" style="width:100%"><i style="width:{w}%;background:{ratcol(v)}"></i></div></td><td>{tag(f"{v:.1f}★",ratk(v))}</td><td class="mini">{cu[s]["reviews"]:,} reviews</td></tr>'
    rsort=sorted(rated,key=lambda x:cu[x]['rating'])
    cust_note=f"Live Google rating per store ({area_reviews:,} reviews across the area). Strongest <b>{SHORT[rsort[-1]]} ({cu[rsort[-1]]['rating']}★)</b>; lowest <b>{SHORT[rsort[0]]} ({cu[rsort[0]]['rating']}★, {cu[rsort[0]]['reviews']:,} reviews)</b> — high-volume sites naturally sit a touch lower."

    # ---- forecast & hours tab ----
    import datetime as _dt
    _t=_dt.date.today(); _mon=_t-_dt.timedelta(days=_t.weekday()); lw_label="W/C "+str((_mon-_dt.timedelta(days=7)).day)+" "+(_mon-_dt.timedelta(days=7)).strftime("%b")
    def _wl(d): return "W/C "+str(d.day)+" "+d.strftime("%b")
    wk_this=_wl(_mon); wk_n1=_wl(_mon+_dt.timedelta(days=7)); wk_n2=_wl(_mon+_dt.timedelta(days=14))
    def _fc(s,i):
        ly=R[s].get('ly',[0,0,0,0])[i]; y=R[s].get('yoy_4w')
        return round(ly*(1+y/100)) if (ly>0 and y is not None) else R[s]['lw26']
    sumly=[0,0,0]; sumf=[0,0,0]; sumh=[0,0,0]; sumlw=0; fcst_rows=""
    for s in sorted(stores,key=lambda x:-R[x]['lw26']):
        cph=R[s].get('cph',55); lw=R[s]['lw26']; sumlw+=lw
        cells=f'<td style="text-align:left">{SHORT[s]}</td><td>£{cph}</td><td>{GBP(lw)}</td>'
        for wi in range(3):
            ly=R[s].get('ly',[0,0,0,0])[wi+1]; f=_fc(s,wi+1); h=round(f/cph) if cph else 0
            if isinstance(OVR.get(s),dict): f=OVR[s]['fc'][wi]; h=OVR[s]['hrs'][wi]
            sumly[wi]+=ly; sumf[wi]+=f; sumh[wi]+=h
            cells+=f'<td class="mini">{GBP(ly) if ly>0 else "&mdash;"}</td><td style="font-weight:600">{GBP(f)}</td><td>{h}</td>'
        fcst_rows+=f'<tr>{cells}</tr>'
    tot=f'<tr style="font-weight:700;background:#EFE6DC"><td style="text-align:left">AREA TOTAL</td><td></td><td>{GBP(sumlw)}</td>'
    for wi in range(3): tot+=f'<td>{GBP(sumly[wi])}</td><td>{GBP(sumf[wi])}</td><td>{sumh[wi]}</td>'
    fcst_rows+=tot+'</tr>'
    fcst_blended=round(sumf[0]/sumh[0],1) if sumh[0] else 0
    TARGETS="https://docs.google.com/spreadsheets/d/18iUyF6Usm5QnUAARPgNsAkqWp00fKPv1WA3waBKJFZU/edit"

    # ---- F1 Qualifying / Race detail tables (area-scoped: this coach's stores; Rank/Finish = company-wide championship position) ----
    def _hosp(x):
        try: v=float(x)
        except: return tag("n/a","t-na")
        p=round(v*100); k="t-ok" if v>=1 else ("t-amber" if v>=0.5 else "t-red"); return tag(f"{p}%",k)
    def _qsec(x):
        try: v=float(x)
        except: return tag("n/a","t-na")
        k="t-ok" if v<=180 else ("t-amber" if v<=300 else "t-red"); return tag(f"{int(round(v))}s",k)
    def _rk(x):
        try: v=int(float(x))
        except: return tag(str(x),"t-na")
        k="t-ok" if v<=6 else ("t-amber" if v<=15 else "t-red"); return tag(str(v),k)
    def _scrag(x):
        try: v=float(x)
        except: return tag(str(x),"t-na")
        return tag(("%g"%v),cls(v,210,285,rev=True))
    _qd=[(s,FD[s]['quali']) for s in stores if isinstance(FD.get(s),dict) and 'quali' in FD[s] and len(FD[s]['quali'])>=8]
    _qd.sort(key=lambda x:int(float(x[1][6])))
    quali_rows="".join(f'<tr><td>{SHORT.get(s,s)}</td><td>{_rk(q[6])}</td><td>{_qsec(q[0])}</td><td>{_hosp(q[1])}</td><td>{_hosp(q[2])}</td><td>{_hosp(q[3])}</td><td>{_hosp(q[4])}</td><td>{q[5]}</td><td class="mini">{q[7]}</td></tr>' for s,q in _qd)
    _rd=[(s,FD[s]['race']) for s in stores if isinstance(FD.get(s),dict) and 'race' in FD[s] and len(FD[s]['race'])>=9]
    _rd.sort(key=lambda x:int(float(x[1][7])))
    race_rows="".join(f'<tr><td>{SHORT.get(s,s)}</td><td>{_rk(r[7])}</td><td style="font-weight:700">{r[6]}</td><td>{_qsec(r[0])}</td><td>{_hosp(r[1])}</td><td>{_hosp(r[2])}</td><td>{_hosp(r[3])}</td><td>{_hosp(r[4])}</td><td>{_scrag(r[5])}</td><td class="mini">{r[8]}</td></tr>' for s,r in _rd)
    if not quali_rows: quali_rows='<tr><td colspan="9" class="mini" style="text-align:center;padding:10px">No qualifying audits yet for this area.</td></tr>'
    if not race_rows: race_rows='<tr><td colspan="10" class="mini" style="text-align:center;padding:10px">No race audits yet for this area.</td></tr>'

    # ---- four pillar widgets (area-scoped; same targets/look as the company dashboard) ----
    Np=len(stores)
    # SALES: area last-week YoY vs 8% (last-week basis, like company)
    kpw_sales_k='green' if ylw>=8 else 'red'; kpw_sales_v=pctxt(ylw)
    # OPERATIONS: area last-week avg F1 race score vs 190 (lower=better; latest race, like company)
    _scs=[_f1score(s) for s in stores]; _scs=[x for x in _scs if x is not None]
    ops_lw=round(sum(_scs)/len(_scs)) if _scs else None
    kpw_ops_k=('green' if ops_lw<=190 else 'red') if ops_lw is not None else 'grey'
    kpw_ops_v=(str(ops_lw) if ops_lw is not None else "n/a")
    # CUSTOMER: QTD Google health (last-week per-area review volume too sparse). Company composite shape over the
    #   area's stores: star term = (sum live-feed avg star / area store count)*0.5; volume term = (sum live-feed QTD
    #   reviews, each capped at its quarterly target / sum of the area's per-store quarterly review targets)*2.5.
    #   GREY "no feed" if the area has no live Google feed this week (sparse-data guard, like the per-store column).
    _live=[s for s in stores if s in STS and not STS[s].get('g_stale') and STS[s].get('g_avg') is not None and STS[s].get('g_n') is not None]
    _gtgt=sum(STT.get(s,0) for s in stores)
    if _live and _gtgt>0:
        _star=(sum(STS[s]['g_avg'] for s in _live)/Np)*0.5
        _vol=(sum(min(STS[s]['g_n'],STT.get(s,0)) for s in _live)/_gtgt)*2.5
        cust_h=round(_star+_vol,2)
        kpw_cust_k='green' if cust_h>=3.32 else 'red'; kpw_cust_v=("%.2f"%cust_h)
    else:
        kpw_cust_k='grey'; kpw_cust_v="no feed"
    kpw_cust_n=(f"{len(_live)}/{Np} live feeds" if _live else f"0/{Np} feeds")
    # PEOPLE: QTD RMS health (last-week per-area submission volume too sparse). Company composite shape over the
    #   area's stores: rating term = (mean per-store QTD avg shift rating / area store count)*0.5; volume term =
    #   (sum area QTD submissions / scaled target)*2.5, where the target = company weekly target 50, spread evenly
    #   across 21 stores over a 13-week quarter (= 50*13*area_store_count/21). GREY if no RMS data in the area.
    _rated=[s for s in stores if s in STS and STS[s].get('r_n') and STS[s].get('r_avg') is not None]
    if _rated:
        _ar=mean(STS[s]['r_avg'] for s in _rated); _subs=sum(STS[s]['r_n'] for s in _rated)
        _rtgt=50*13*Np/21.0
        ppl_h=round((_ar/Np)*0.5 + (_subs/_rtgt)*2.5,2)
        kpw_people_k='green' if ppl_h>=3.32 else 'red'; kpw_people_v=("%.2f"%ppl_h); kpw_people_n=f"{_subs} ratings"
    else:
        kpw_people_k='grey'; kpw_people_v="n/a"; kpw_people_n="0 ratings"

    repl={
     "{{KPW_SALES_K}}":kpw_sales_k,"{{KPW_SALES_V}}":kpw_sales_v,"{{KPW_OPS_K}}":kpw_ops_k,"{{KPW_OPS_V}}":kpw_ops_v,
     "{{KPW_CUST_K}}":kpw_cust_k,"{{KPW_CUST_V}}":kpw_cust_v,"{{KPW_CUST_N}}":kpw_cust_n,
     "{{KPW_PEOPLE_K}}":kpw_people_k,"{{KPW_PEOPLE_V}}":kpw_people_v,"{{KPW_PEOPLE_N}}":kpw_people_n,
     "{{WX_NUDGE}}":wx_nudge([R[s]['coords'] for s in stores if R[s].get('coords')],wx_recent(amix)),
     "{{WX_NUDGE_TOP}}":WX_TOP,"{{WX_FOOD}}":WX_FOOD,
     "{{GEN_STAMP}}":GEN_STAMP,"{{LW_LABEL}}":lw_label,"{{AVF_WK}}":ACT.get('_week_label','last week'),"{{AVF_ROWS}}":_avf_rows(stores,R),"{{PLANNER_LINK}}":PLANNERS.get(coach,'#'),
     "{{COACH}}":coach,"{{NSTORES}}":str(len(stores)),"{{PILL}}":" · ".join(SHORT[s] for s in sorted(stores,key=lambda x:-R[x]['s4'])),
     "{{FOCUS_LI}}":focus_li,"{{OVROWS}}":ov,"{{AREA_LAST}}":GBP(area_last),"{{AREA_YOY_LW}}":pctxt(ylw),"{{LWCHIP}}":"up" if ylw>=0 else "dn",
     "{{AREA_4WK}}":GBP(area_4wk),"{{AREA_YOY_4W}}":pctxt(y4),"{{W4CHIP}}":"up" if y4>=0 else "dn",
     "{{AREA_WASTE_PCT}}":str(awpct),"{{AREA_WASTE_RETAIL}}":GBP(awr),"{{WASTE_PCT_LW}}":str(awpct_lw),"{{WASTE_RETAIL_LW}}":GBP(awr_lw),"{{WASTE_RETAIL_WK}}":GBP(awr_wk),"{{CON_POS}}":con_pos,"{{CON_META}}":con_meta,"{{AREA_GC}}":format(st_,",d"),"{{AREA_GC_YOY}}":pctxt(round(agy,1)),"{{GCCHIP}}":"up" if agy>=0 else "dn","{{AUDIT_QTD}}":("%.2f"%audit_mean) if audit_mean is not None else "n/a","{{AUDIT_K}}":cls(audit_mean,4.5,4.0),"{{AUDIT_META}}":str(len(audit_vals))+" stores audited · QTD",
     "{{ATV_MED}}":f"{atv_med:.2f}","{{MOVROWS}}":mov,"{{MOV_NOTE}}":mov_note,
     "{{LW_TABLE}}":lw_rows,"{{LW_TOTAL}}":lw_total,"{{SALESTBL}}":salestbl,"{{DPG_ROWS}}":dpg_rows,"{{DOWG_ROWS}}":dowg_rows,
     "{{DPG_NOTE}}":dpg_note,"{{DOWG_NOTE}}":dowg_note,"{{SALES_FOCUS}}":sales_focus,
     "{{YJS}}":json.dumps(yjs),"{{OUTJS}}":json.dumps(outjs),
     "{{MIX_AREA_ROWS}}":mar,"{{CAPHDR}}":caphdr,"{{CAPMAT}}":capmat,"{{MIX_DS}}":mix_ds,"{{MIX_LBLS}}":mix_lbls,"{{MIX_NOTE}}":mix_note,"{{MIX_FOCUS}}":mix_focus,
     "{{F1TBL}}":f1tbl,"{{F1_FIN_DS}}":f1_fin_ds,"{{F1_FIN_LBLS}}":f1_fin_lbls,"{{F1_CHAMP_AVG}}":str(f1_champ_avg),"{{AVG_FIN2}}":str(avg_fin),
     "{{F1_TOP}}":f1_top,"{{F1_TOP_META}}":f1_top_meta,"{{CON_HTML}}":con_html,"{{CON_NOTE}}":con_note,"{{DRV_ROWS}}":drv_rows,"{{F1_NOTE}}":f1_note,"{{F1_FOCUS}}":f1_focus,"{{QUALI_DETAIL_ROWS}}":quali_rows,"{{RACE_DETAIL_ROWS}}":race_rows,
     "{{RMS_ROWS}}":rms_rows,"{{HR_ROWS}}":hr_rows,"{{AREA_RMS}}":str(area_rms),"{{AREA_SICK}}":str(area_sick),"{{AREA_SICKFS}}":str(area_sickfs),"{{AREA_LATE}}":str(area_late),
     "{{RTW_COMP}}":str(rtw_comp),"{{RTW_COMP_K}}":rtw_k,"{{AREA_REP}}":str(area_rep),"{{AREA_RTW}}":str(area_rtw),"{{RMS_NOTE}}":rms_note,"{{RTW_NOTE}}":rtw_note,"{{AREA_RATING}}":str(area_rating),"{{AREA_REVIEWS}}":f"{area_reviews:,}","{{CUST_ROWS}}":cust_rows,"{{CUST_NOTE}}":cust_note,"{{WK_THIS}}":wk_this,"{{WK_N1}}":wk_n1,"{{WK_N2}}":wk_n2,"{{FCST_ROWS}}":fcst_rows,"{{FCST_AREA_THIS}}":GBP(sumf[0]),"{{FCST_HRS_THIS}}":str(sumh[0]),"{{FCST_BLENDED}}":str(fcst_blended),"{{TARGETS_LINK}}":TARGETS,
    }
    html=open('TEMPLATE_AREA.html').read()
    for k,v in repl.items(): html=html.replace(k,v)
    return html

import re,os
_OUT=os.environ.get('OUTDIR','.')
for coach,fn in [("Jon","Jon_Area_Dashboard.html"),("Ian","Ian_Area_Dashboard.html"),("Rich","Rich_Area_Dashboard.html")]:
    h=build(coach)
    left=re.findall(r'{{[A-Z_0-9]+}}',h)
    open(os.path.join(_OUT,fn),'w').write(h)
    print(coach,"-> ",fn," leftover placeholders:",sorted(set(left)) or "none")
