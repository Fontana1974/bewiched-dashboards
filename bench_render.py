# Shared bench renderer used by gen_kel.py, gen_company.py and gen_area.py.
# Builds the Leaflet/OSM star map + a per-store MANAGEMENT-TEAM names table from the HRP
# 'HRP & Bench' roster (bench.json). One code path; callers pass a store filter.
# HRP & Bench columns B-J: Store Manager, Assistant Manager, Culture Coach (D, new), Supervisor 1,
# Supervisor 2, Bench Manager (G), Pipeline 1/2/3 (H-J). Full names.
import json

_STAR="14,2 17.5,10.5 26.5,11 20,17 22,26 14,21.5 6,26 8,17 1.5,11 10.5,10.5"
_BMAP={"Drive Thru Northampton":"Northampton Drive-Thru","Train Station":"Wellingborough Train Station",
       "Wellingborough Market St":"Wellingborough","Fletton Quays":"Peterborough Fletton Quays",
       "Peterborough":"Peterborough Bridge Street","Balsall Common":"HOE Balsall Common"}
_SCOL={"bench":"#1f8a4c","thin":"#b8860b","gap":"#c0392b"}
_STAG={"bench":"t-ok","thin":"t-amber","gap":"t-red"}
# Position labels for the management-team table (cells[0..8] = HRP & Bench cols B..J).
_POS=["Store Manager","Assistant Manager","Culture Coach","Supervisor 1","Supervisor 2",
      "Bench Manager","Pipeline 1","Pipeline 2","Pipeline 3"]
# Potential new openings (not in allstores.json) — estate growth context. Fit-outs/moves excluded by design.
NEW_OPENINGS=[("Daventry (new site)",52.2650,-1.1480),("Grantham Designer Village",52.9116,-0.6416),
              ("Hinckley",52.5408,-1.3703),("Warwick",52.2812,-1.5846),("Bromsgrove",52.3351,-2.0580),
              ("Derby Drive-Thru",52.9225,-1.4746),("Hemel Hempstead",51.7526,-0.4692)]

def build_bench(REC, SHORT=None, include_keys=None):
    """Return (BENCH_NAV, BENCH_PANEL).
    REC: allstores rec dict. SHORT: short-name map for labels.
    include_keys: iterable of REC keys to include (current-store stars+table); None = full estate.
    Potential openings are always shown (blue). Markers/colours/legend identical across dashboards.
    Bench status keys on cols G-J (Bench Manager + Pipeline 1/2/3); leadership on B-F."""
    SHORT=SHORT or {}
    sh=lambda n:SHORT.get(n,n)
    tag=lambda t,k:'<span class="tag %s">%s</span>'%(k,t)
    esc=lambda x:(str(x).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;") if x else "")
    try: BENCH=json.load(open('bench.json'))
    except Exception: BENCH=None
    if not (BENCH and BENCH.get('rows')): return "",""
    inc=set(include_keys) if include_keys is not None else None
    pts=[]; tbl=[]; ng=na=nr=0; unplotted=[]
    for row in BENCH['rows']:
        nm=(row[0] or "").strip()
        cells=([(c or "").strip() for c in row[1:10]]+[""]*9)[:9]   # B..J, padded to 9
        key=_BMAP.get(nm,nm)
        if inc is not None and key not in inc: continue
        sm=cells[0]                                    # Store Manager (B)
        leaders=[c for c in cells[0:5] if c]           # SM, AM, Culture Coach, Sup1, Sup2 (B-F)
        bench=[c for c in cells[5:9] if c]             # Bench Manager + Pipeline 1/2/3 (G-J)
        if bench: st,sl="bench","Bench ready"; ng+=1
        elif not sm: st,sl="gap","Gap (no SM)"; nr+=1
        else: st,sl="thin","Thin"; na+=1
        rec=REC.get(key); coords=rec.get('coords') if rec else None
        lab=sh(key) if rec else nm
        if coords: pts.append((coords,st,_SCOL[st],lab,nm,sl,bench))
        else: unplotted.append(nm)
        tbl.append((nm,cells,sl,st))
    if not tbl: return "",""
    # ---- real map: Leaflet 1.9.4 + OpenStreetMap tiles; one star divIcon per store, coloured by bench status ----
    def _benchpop(nm,sl,bench):
        return "<b>%s</b><br>%s%s"%(nm,sl,("<br>Bench: "+", ".join(bench)) if bench else "")
    mpts=[{"lat":c[0],"lng":c[1],"color":col,"stroke":"#fff","label":lab,"pop":_benchpop(nm,sl,bench)}
          for (c,st,col,lab,nm,sl,bench) in pts]
    mpts+=[{"lat":la,"lng":lo,"color":"#88aaff","stroke":"#2244aa","label":nm,
            "pop":"<b>%s</b><br>Potential new opening"%nm} for (nm,la,lo) in NEW_OPENINGS]
    svg=('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>'
         '<div id="benchmap" style="height:460px;width:100%%;max-width:820px;border:1px solid var(--line);border-radius:12px;overflow:hidden;z-index:0"></div>'
         '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
         '<script>(function(){var PTS=%s,STAR=%s,map=null;'
         'function star(c,s){return L.divIcon({className:"",iconSize:[28,28],iconAnchor:[14,14],popupAnchor:[0,-13],'
         'html:\'<svg width="28" height="28" viewBox="0 0 28 28"><polygon points="\'+STAR+\'" fill="\'+c+\'" stroke="\'+s+\'" stroke-width="1.6" stroke-linejoin="round"/></svg>\'});}'
         'function init(){if(map)return;map=L.map("benchmap",{scrollWheelZoom:false});'
         'L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:"&copy; OpenStreetMap contributors"}).addTo(map);'
         'var b=[];PTS.forEach(function(p){var m=L.marker([p.lat,p.lng],{icon:star(p.color,p.stroke)}).addTo(map);'
         'm.bindTooltip(p.label,{direction:"top",offset:[0,-13]});'
         'm.bindPopup(p.pop);b.push([p.lat,p.lng]);});'
         'if(b.length)map.fitBounds(b,{padding:[34,34]});setTimeout(function(){map.invalidateSize();},60);}'
         'var btn=document.querySelector(\'[data-tab="bench"]\');'
         'if(btn)btn.addEventListener("click",function(){setTimeout(function(){init();if(map)map.invalidateSize();},80);});'
         'var bp=document.getElementById("tab-bench");if(bp&&bp.classList.contains("active"))init();'
         '})();</script>')%(json.dumps(mpts),json.dumps(_STAR))
    _sw=lambda col,stk="#fff":'<svg width="13" height="13" viewBox="0 0 28 28" style="vertical-align:-2px"><polygon points="%s" fill="%s" stroke="%s" stroke-width="2" stroke-linejoin="round"/></svg>'%(_STAR,col,stk)
    legend=('<div style="margin-top:10px;font-size:11.5px;color:#6b5a47;display:flex;gap:18px;flex-wrap:wrap">'
            '<span style="display:inline-flex;align-items:center;gap:6px">%s Bench ready (named successor)</span>'
            '<span style="display:inline-flex;align-items:center;gap:6px">%s Thin (team, no named bench)</span>'
            '<span style="display:inline-flex;align-items:center;gap:6px">%s Gap (manager vacancy)</span>'
            '<span style="display:inline-flex;align-items:center;gap:6px">%s Potential opening</span></div>'
            %(_sw('#1f8a4c'),_sw('#b8860b'),_sw('#c0392b'),_sw('#88aaff','#2244aa')))
    # ---- management-team names table (every position per store; — where vacant) ----
    mt_head="<th style=\"text-align:left\">Store</th>"+"".join("<th>%s</th>"%p for p in _POS)+"<th>Status</th>"
    mt_rows="".join(
        '<tr><td style="text-align:left;font-weight:600">%s</td>%s<td>%s</td></tr>'
        %(esc(nm),
          "".join('<td style="text-align:left">%s</td>'%(esc(c) if c else "&mdash;") for c in cells),
          tag(sl,_STAG[st]))
        for (nm,cells,sl,st) in tbl)
    mt_table='<table class="scorecard" style="min-width:1080px"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'%(mt_head,mt_rows)
    upd=BENCH.get('_updated','')
    upnote=(" %s has no mapped location so it is listed but not plotted."%(", ".join(unplotted))) if unplotted else ""
    BENCH_NAV='<button class="tab-btn" data-tab="bench"><span>🪑</span>Bench</button>'
    BENCH_PANEL=('<section class="tab-panel" id="tab-bench">'
      '<div class="cards" style="grid-template-columns:repeat(3,1fr)">'
      '<div class="card"><div class="lbl">Bench-ready stores</div><div class="val" style="color:#1f8a4c">%d</div><div class="meta">named Bench Manager / pipeline</div></div>'
      '<div class="card"><div class="lbl">Thin bench</div><div class="val" style="color:#b8860b">%d</div><div class="meta">leadership team, no named successor</div></div>'
      '<div class="card"><div class="lbl">Capability gap</div><div class="val" style="color:#c0392b">%d</div><div class="meta">Store Manager vacancy</div></div></div>'
      '<div class="note" style="margin-top:12px"><b>Bench</b> = succession cover from the HRP ‘HRP &amp; Bench’ roster. <b style="color:#1c6b3d">Green</b> = a named Bench Manager or pipeline successor is in place; <b style="color:#7a5b12">amber</b> = a full leadership line but no named successor; <b style="color:#9a2f22">red</b> = a Store Manager vacancy. Refreshed Monday.</div>'
      '<div class="section-title">Where the bench is &mdash; and the gaps</div>'
      '<div class="panel">%s%s</div>'
      '<div class="section-title" style="margin-top:18px">Store management teams</div>'
      '<div class="panel"><div style="overflow-x:auto">%s</div>'
      '<div class="mini" style="margin-top:8px">Every leadership position per store from the HRP ‘HRP &amp; Bench’ tab (full names; &mdash; where vacant). Status keys on Bench Manager + Pipeline 1-3. <b>Culture Coach</b> is a new column and is currently unassigned across the estate.%s Pulled %s.</div></div>'
      '</section>')%(ng,na,nr,svg,legend,mt_table,upnote,upd)
    return BENCH_NAV, BENCH_PANEL
