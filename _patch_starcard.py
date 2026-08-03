# Patch gen_starcard.py (copied from gen_estate.py): repo paths + single 2-tab star-card.html
P="/tmp/bw/gen_starcard.py"
s=open(P,encoding="utf-8").read()

# 1) repo-relative paths
s=s.replace('BW="/tmp/bw"\nOUT="/sessions/bold-epic-gauss/mnt/Claude"',
            'HERE=os.path.dirname(os.path.abspath(__file__))\nBW=HERE\nOUT=HERE')
assert "HERE=os.path.dirname" in s, "path patch failed"

# 2) drop the standalone leaderboard file write (keep LEAD var, we don't reuse it)
s=s.replace('open(os.path.join(OUT,"Bewiched_Star_Card_Leaderboard.html"),"w",encoding="utf-8").write(LEAD)\n','')

# 3) cut everything from the old standalone card output (def toggle_bar ... prints) and replace with the unified 2-tab builder
cut=s.index("def toggle_bar")

FOOT=("<div class='foot'><b>Pillars:</b> Team (<b>RMS Health + RTW % completed</b>) &middot; Ops "
"(<b>F1 avg Total Score QTD (target &le;175) + Google Health (EOS composite, green &ge;3.32)</b>) &middot; Customers (<b>sales + guest YoY, "
"last completed week vs same week last year</b> on QTD; blended YoY on YTD) &middot; Profit (SPH + Food GP%). "
"<b>Brand foundations</b> (Brand &amp; Remote + Open/Close % + New Starter Health) and <b>Urgent support</b> (coach vacancy, bench gap, "
"accidents, red maintenance) sit outside the score. <b>RTW %</b> = each store's return-to-work completion from the sickness/RTW log (target &ge;90%, indicative). <b>Real data (N / 8):</b> count of the 8 scored metrics "
"(RMS, RTW, F1, Google, Sales YoY, Guest counts, SPH, Food GP) on genuine real data. New Starter Health is now a Brand Foundation (flagged vs &ge;90%, outside the score). The Store Card dropdown also renders a full <b>area</b> card for each coach (Jon / Rich / Ian). Overall = mean of "
"available pillars. Targets indicative for Matt to set.</div>")

UNIFIED = '''# ================= LIVE 2-TAB PAGE: star-card.html =================
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
for _co in AREAS: CARDS[_co+" (area)"]={w:area_card(_co,w) for w in WINDOWS}
_sopts = "".join("<option value=\\"%s\\"%s>%s</option>"%(c,(" selected" if c==_default else ""),c) for c in sorted(CANON))
_aopts = "".join("<option value=\\"%s (area)\\">%s&rsquo;s area (all stores)</option>"%(co,co) for co in AREAS)
_opts = "<optgroup label=\\"Area coaches\\">"+_aopts+"</optgroup><optgroup label=\\"Stores\\">"+_sopts+"</optgroup>"
_lb = ("<div class='top'><div><div class='brand'>Star Card</div><div class='h1'>Estate leaderboard &mdash; all 21 stores</div>"
       "<div class='sub'>Ranked by overall Star score &middot; <span id='winlab'>rolling QTD</span> &middot; "+WKLABEL+"</div></div>"
       "<div style='text-align:right'><div class='sub'>Gold = overall rating &middot; pillars: <span class='hit'>green &ge;4</span> &middot; <span class='warn'>amber 3&ndash;4</span> &middot; <span class='miss'>red &lt;3</span></div></div></div>"
       "<table><thead><tr><th>#</th><th>Store</th><th>Overall Star Score</th><th class='plh'>Team</th><th class='plh'>Ops</th><th class='plh'>Customers</th><th class='plh'>Profit</th><th>Real data</th></tr></thead><tbody id='lbody'>"+TBODY["qtd"]+"</tbody></table>"+__FOOT__)
PAGE = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Bewiched Star Card</title><style>"+CARDCSS+LB_CSS+TAB_CSS+AREA_CSS+"</style></head><body><div class='wrap'>"
        "<div class='appbar'><div class='abrand'>"+_LOGO+"<div><div class='eyebrow'>Store Scorecard</div><div class='h1b'>Star Card</div></div></div>"
        "<div class='tabs'><button data-tab='store' class='on'>Store Card</button><button data-tab='board'>Leaderboard</button><button data-tab='area'>Area</button></div>"
        "<div class='tgl'><button data-w='qtd' class='on'>QTD</button><button data-w='ytd'>YTD</button></div></div>"
        "<div id='pane-store' class='pane'><div class='storesel'><label>Store / Area</label><select id='storesel'>"+_opts+"</select></div><div id='cardhost'></div></div>"
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
'''
UNIFIED=UNIFIED.replace("__FOOT__", repr(FOOT))
s=s[:cut]+UNIFIED
open(P,"w",encoding="utf-8").write(s)
import ast; ast.parse(s)
print("patched + syntax OK; length", len(s))
