#!/usr/bin/env python3
# Bewiched EOS Weekly Scorecard generator (v1 DRAFT).
# Reads scorecard_data.json -> writes Company_Scorecard.html, matching the dashboards stack design.
import json, datetime as dt

D = json.load(open('scorecard_data.json'))
GEN = dt.datetime.now().strftime('%d %b %Y, %H:%M')
weeks = D['weeks']
def wlab(iso):
    d = dt.date.fromisoformat(iso); return f"{d.day}/{d.month}"
WL = [wlab(w) for w in weeks]

def fmt(v, f):
    if v is None: return "—"
    if f == "gbp":  return "£"+format(int(round(v)), ",d")
    if f == "gbp2": return "£%.2f" % v
    if f == "pct":  return ("+%.1f%%"%v) if (f=="pct" and False) else ("%.2f%%"%v if abs(v)<10 else "%.1f%%"%v)
    if f == "int":  return format(int(round(v)), ",d")
    if f == "star": return "%.2f★" % v
    if f == "score":return "%.2f" % v
    return str(v)

def fmt_pct(v):  # signed for LFL
    return ("+" if v>=0 else "")+("%.1f%%"%v)

def cls(v, goal, amber, dr):
    if v is None: return "t-na"
    if dr == "high":
        return "t-ok" if v>=goal else ("t-amber" if v>=amber else "t-red")
    else:
        return "t-ok" if v<=goal else ("t-amber" if v<=amber else "t-red")

def cellval(m, v):
    if v is None: return "—"
    if m['id']=='lfl': return fmt_pct(v)
    return fmt(v, m['fmt'])

# sparkline (uses .spk style from stack)
def spark(vals):
    xs=[x for x in vals if x is not None]
    if len(xs)<2: return ""
    lo,hi=min(xs),max(xs); rng=(hi-lo) or 1
    bars=""
    for x in vals:
        if x is None:
            bars+='<span class="spk" style="height:2px;opacity:.25"></span>'
        else:
            h=4+round(16*(x-lo)/rng)
            bars+=f'<span class="spk" style="height:{h}px"></span>'
    return f'<span class="spkwrap">{bars}</span>'

def trend_arrow(vals, dr):
    xs=[x for x in vals if x is not None]
    if len(xs)<2: return '<span class="mini">—</span>'
    a,b=xs[-2],xs[-1]; up=b>a
    good = up if dr=="high" else (not up)
    arrow = "▲" if up else ("▼" if b<a else "▬")
    col = "var(--green)" if good else ("var(--red)" if b!=a else "var(--muted)")
    return f'<span style="color:{col};font-weight:800">{arrow}</span>'

# ---- group by section ----
SECT_ORDER=["Sales & Growth","Cost & Efficiency","Customer & People"]
SECT_ICON={"Sales & Growth":"📈","Cost & Efficiency":"💷","Customer & People":"⭐"}
rows_html=""
green=amber=red=0; live_green=0; live_total=0
for sect in SECT_ORDER:
    rows_html += f'<tr class="secrow"><td colspan="{4+len(weeks)+1}">{SECT_ICON[sect]} {sect}</td></tr>'
    for m in [x for x in D['measurables'] if x['section']==sect]:
        live = m['cadence']=='live'
        # build weekly value list
        if live:
            vals = D['series'][m['series']]
        else:
            vals = [None]*(len(weeks)-1) + [m.get('latest')]
        # cells
        cells=""
        for i,v in enumerate(vals):
            c = cls(v, m['goal'], m['amber'], m['dir'])
            last = (i==len(vals)-1)
            style = ' style="border-left:2px solid #b9a890"' if last else ''
            cells += f'<td class="{c}"{style}>{cellval(m,v)}</td>'
        # status from latest non-null
        latest = next((v for v in reversed(vals) if v is not None), None)
        st = cls(latest, m['goal'], m['amber'], m['dir'])
        if st=="t-ok": green+=1
        elif st=="t-amber": amber+=1
        elif st=="t-red": red+=1
        if live:
            live_total+=1
            if st=="t-ok": live_green+=1
        # cadence badge
        if live: badge='<span class="cad live">live wkly</span>'
        elif m['cadence']=='weekly-manual': badge='<span class="cad wman">wkly · manual</span>'
        else: badge='<span class="cad mon">monthly</span>'
        tr = spark(vals)+" "+trend_arrow(vals,m['dir']) if live else trend_arrow(vals,m['dir'])
        rows_html += (
            f'<tr><td class="meas"><span class="mname">{m["name"]}</span> {badge}'
            f'<div class="msrc">{m["source"]}</div></td>'
            f'<td class="own">{m["owner"]}</td>'
            f'<td class="goal">{m["goal_text"]}</td>'
            f'{cells}<td class="tr">{tr}</td></tr>'
        )

# ---- at a glance ----
lw = D['latest_week_label']
glance_k = "green" if live_green==live_total else ("amber" if live_green>=live_total-1 else "red")
glance_msg = f"{live_green}/{live_total} live weekly measurables ON TRACK"

# notes for assumptions
notes_li = "".join(f'<li><b>{m["name"]}</b> — owner <b>{m["owner"]}</b>; goal <b>{m["goal_text"]}</b>. {m["note"]}</li>' for m in D['measurables'])

whead = "".join(f'<th>{w}</th>' for w in WL)
ncols = 4+len(weeks)+1

HTML = f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="robots" content="noindex, nofollow">
<title>Bewiched — EOS Weekly Scorecard</title>
<style>
  :root{{--bg:#f4efe9;--card:#fff;--ink:#2b211b;--muted:#8a7a6d;--line:#e7ddd2;--brown:#5b3a29;--brown2:#3f281c;--cream:#efe6dc;--gold:#e7b35a;
    --green:#1f8a4c;--red:#c0392b;--amber:#b8860b;--redbg:#fbeae8;--amberbg:#f7f0dd;--greenbg:#e6f4ec;}}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}}
  .brandbar{{background:linear-gradient(180deg,var(--brown) 0%,var(--brown2) 100%);color:#f6efe7;}}
  .brandbar .inner{{max-width:1280px;margin:0 auto;padding:14px 22px;display:flex;align-items:center;gap:13px;}}
  .logo .word{{font-size:21px;font-weight:800;line-height:1;}} .logo .word span{{color:var(--gold)}}
  .logo .eyebrow{{font-size:10.5px;letter-spacing:2.4px;text-transform:uppercase;color:#cbb29c;margin-top:3px;}}
  .brandbar .spacer{{flex:1}} .brandbar .ctx{{font-size:11.5px;color:#cbb29c;text-align:right;line-height:1.5}} .brandbar .ctx b{{color:#f6efe7;font-weight:700}}
  .wrap{{max-width:1280px;margin:0 auto;padding:22px 22px 60px;}}
  header.page h1{{margin:0 0 4px;font-size:23px;}} header.page .sub{{color:var(--muted);font-size:13.5px;line-height:1.55;}}
  .pill{{display:inline-block;background:var(--cream);color:var(--brown);border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:12px;font-weight:600;margin-right:6px;}}
  a.back{{color:var(--brown);font-size:12.5px;text-decoration:none;font-weight:700}} a.back:hover{{text-decoration:underline}}
  .glance{{display:flex;flex-wrap:wrap;align-items:center;gap:14px 22px;border-radius:14px;padding:16px 20px;margin:16px 0 6px;border:1.5px solid;}}
  .glance.green{{background:#e8f5ee;border-color:#bfe3cd;color:#1c6b3d}} .glance.amber{{background:var(--amberbg);border-color:#ece0c0;color:#7a5b12}} .glance.red{{background:#fcebe8;border-color:#f0ccc5;color:#9a2f22}}
  .glance .big{{font-size:26px;font-weight:800;line-height:1}} .glance .lab{{font-size:12.5px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;opacity:.8}}
  .glance .sep{{width:1px;align-self:stretch;background:currentColor;opacity:.2}}
  .glance .tally span{{font-weight:800}}
  .draft{{background:#fff8ec;border:1px solid #f0e0bf;color:#7a5e1e;border-radius:10px;padding:10px 14px;font-size:12.5px;margin:10px 0 0;line-height:1.55}}
  .panel{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px;box-shadow:0 1px 2px rgba(80,50,30,.04);margin-top:14px;overflow-x:auto;}}
  table.sc{{width:100%;border-collapse:collapse;font-size:12.5px;min-width:1120px;}}
  table.sc th,table.sc td{{padding:7px 7px;text-align:center;border-bottom:1px solid var(--line);white-space:nowrap;}}
  table.sc thead th{{font-size:10.5px;text-transform:uppercase;letter-spacing:.3px;color:var(--muted);font-weight:700;position:sticky;top:0;background:#fff;}}
  table.sc th.meas,table.sc td.meas{{text-align:left;white-space:normal;min-width:230px;position:sticky;left:0;background:#fff;z-index:2;border-right:1px solid var(--line);}}
  table.sc thead th.meas{{z-index:3;}}
  td.meas .mname{{font-weight:700;}} td.meas .msrc{{font-size:10.5px;color:var(--muted);margin-top:2px;font-weight:400;white-space:normal;}}
  td.own{{text-align:left;font-size:12px;color:#5b4a3d;white-space:normal;min-width:120px}}
  td.goal{{font-weight:700;color:var(--brown);white-space:nowrap;}}
  td.tr{{min-width:74px}}
  tr.secrow td{{text-align:left;background:#efe6dc;color:var(--brown);font-weight:800;font-size:12px;letter-spacing:.3px;text-transform:uppercase;padding:7px 10px;position:sticky;left:0;}}
  tbody tr:hover td{{background:#faf6f1;}} tbody tr:hover td.meas{{background:#faf6f1;}}
  .t-red{{background:var(--redbg);color:var(--red);font-weight:700}} .t-amber{{background:var(--amberbg);color:var(--amber);font-weight:700}} .t-ok{{background:var(--greenbg);color:var(--green);font-weight:700}} .t-na{{background:#f3efe9;color:#b9ad9f}}
  .cad{{display:inline-block;font-size:9.5px;font-weight:800;padding:1px 6px;border-radius:5px;vertical-align:middle;text-transform:uppercase;letter-spacing:.3px}}
  .cad.live{{background:#e6f4ec;color:#1c6b3d}} .cad.wman{{background:#eef4fb;color:#2d6fb3}} .cad.mon{{background:#f3ece0;color:#8a6d3b}}
  .spkwrap{{display:inline-flex;align-items:flex-end;gap:1px;height:20px;vertical-align:middle}} .spk{{display:inline-block;width:4px;background:#5b3a29;border-radius:1px;opacity:.8}}
  .legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:11.5px;color:var(--muted);margin:12px 4px 2px}} .legend span{{display:inline-flex;align-items:center;gap:5px}} .sw{{width:12px;height:12px;border-radius:3px;display:inline-block}}
  .info{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin-top:18px}}
  .info h2{{margin:0 0 8px;font-size:15px;color:var(--brown)}} .info ul{{margin:6px 0 0;padding-left:18px}} .info li{{font-size:12.5px;line-height:1.5;margin:6px 0}}
  .info.blue{{background:#eef4fb;border-color:#cfe0f2}} .info.blue h2{{color:#1d4e7a}}
  footer{{color:var(--muted);font-size:12px;margin-top:26px;line-height:1.6}}
  @media(max-width:760px){{.glance .sep{{display:none}}}}
</style>
</head>
<body>
<div class="brandbar"><div class="inner">
  <div class="logo"><div><div class="word">Be<span>wiched</span></div><div class="eyebrow">EOS Weekly Scorecard</div></div></div>
  <div class="spacer"></div>
  <div class="ctx">Company level · 21 stores<br>13-week trailing view · most recent: <b>{lw}</b><br><span style="color:var(--gold);font-weight:700">🔄 Generated {GEN}</span></div>
</div></div>
<div class="wrap">
  <a class="back" href="index.html">← All dashboards</a>
  <header class="page" style="margin-top:10px">
    <h1>📋 Bewiched — EOS Weekly Scorecard <span class="pill">v1 DRAFT</span></h1>
    <div class="sub">A tight set of weekly measurables, traffic-lit against goal, with the last 13 weeks of actuals (most recent on the right). Built EOS-style: each row is one number, one owner, one goal. <b>Live weekly</b> rows refresh from BigQuery POS; <b>monthly / manual</b> rows are seeded from the latest snapshot and flagged — confirm those before relying on them.</div>
  </header>

  <div class="glance {glance_k}">
    <div><div class="lab">This week — {lw}</div><div class="big">{glance_msg}</div></div>
    <div class="sep"></div>
    <div class="tally" style="font-size:13px;line-height:1.7">
      Sales <b>£195,115</b> vs £190k goal · LFL <b>+23.4%</b> vs +10% goal<br>
      All measurables (incl. monthly): <span style="color:var(--green)">●</span> {green} on track · <span style="color:var(--amber)">●</span> {amber} watch · <span style="color:var(--red)">●</span> {red} act now
    </div>
  </div>
  <div class="draft"><b>Draft for review.</b> This is a first iteration. The measurable set, goals and owners are smart defaults — owners are role-based <b>placeholders</b> for Matt to confirm/replace, and several goals are placeholders (see Assumptions below). Not yet wired into the weekly runbooks.</div>

  <div class="panel">
    <table class="sc">
      <thead><tr><th class="meas">Measurable</th><th>Owner</th><th>Goal</th>{whead}<th>Trend</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <div class="legend">
    <span><span class="sw" style="background:var(--greenbg);border:1px solid #cfe6d8"></span>on / better than goal</span>
    <span><span class="sw" style="background:var(--amberbg);border:1px solid #ece0c0"></span>watch (near goal)</span>
    <span><span class="sw" style="background:var(--redbg);border:1px solid #eccfca"></span>off goal — act</span>
    <span><span class="sw" style="background:#f3efe9;border:1px solid var(--line)"></span>no weekly data (monthly/manual)</span>
    <span class="mini">Most-recent week is the right-hand column (bordered) = this week's status. Trend = sparkline + last-vs-previous arrow (green = moving the right way).</span>
  </div>

  <div class="info">
    <h2>Assumptions &amp; choices — please confirm or redirect (v1)</h2>
    <p style="font-size:12.5px;color:var(--muted);margin:0 0 4px">Every measurable picked, the goal set and where it came from, and the guessed owner:</p>
    <ul>{notes_li}</ul>
    <p style="font-size:12.5px;line-height:1.5;margin:10px 0 0"><b>Owners are placeholders.</b> Used role-based guesses (Matt/MD, Ops, area coaches Jon·Ian·Rich, engagement Kel, people Claire). EOS says one accountable owner per measurable — tell me the real owner for each and I'll set it.</p>
    <p style="font-size:12.5px;line-height:1.5;margin:8px 0 0"><b>Candidates not yet included:</b> new-store-openings (Billing + Grantham) milestone line, a weekly cash/banking line, and new Google reviews this week. Say the word and I'll add them.</p>
  </div>

  <div class="info blue">
    <h2>How the weekly auto-refresh would work (when wired)</h2>
    <ul>
      <li><b>Live weekly (BigQuery):</b> sales £, LFL %, transactions and ATV from <code>v_sales_details_flat</code>; wastage % from <code>v_sales_vs_wastage</code> — re-pull the trailing 13 complete weeks each Monday and re-colour vs goal. Same pipeline the other dashboards use.</li>
      <li><b>Becomes live once fixed:</b> wages/labour % and CPH need the BigQuery schedule/salary view repopulated (it's currently near-empty); F1 audit score can be pulled weekly from the F1 sheet.</li>
      <li><b>Stays monthly/manual:</b> GP% (from the monthly P&amp;L / Cost of Sales), RMS and RTW (HRP) — refresh on the monthly close and stamp the date.</li>
      <li><b>Generator:</b> this page is built by <code>gen_scorecard.py</code> from <code>scorecard_data.json</code>, so it can be dropped into the existing Monday 9:30am refresh job exactly like the other pages.</li>
    </ul>
  </div>

  <footer>Bewiched Limited · internal use · EOS Weekly Scorecard <b>v1 DRAFT</b>. Live data: BigQuery POS (bewiched_coffee, europe-west2) pulled {GEN}. Monthly/manual rows seeded from the latest dashboard snapshot. Sales gross inc VAT.</footer>
</div>
</body>
</html>"""

open('Company_Scorecard.html','w').write(HTML)
print("Wrote Company_Scorecard.html  (%d bytes)" % len(HTML))
print("At-a-glance: live %d/%d green | all: %d green / %d amber / %d red" % (live_green,live_total,green,amber,red))
