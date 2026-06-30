#!/usr/bin/env python3
# Bewiched EOS Weekly & Quarterly Scorecard generator.
# Reads eos_scorecard.json -> writes EOS_Scorecard.html, matching the Bewiched dashboards stack.
# Two tabs (Weekly / Quarterly); each metric = an EOS traffic-light widget (plan vs actual).
# STRICTLY BINARY status: GREEN actual>=plan | RED below. No near-target band.
# Greyed tiles: TBC (not yet defined) and AWAITING DATA (defined but no actual yet) — never red.
import json, datetime as dt, os, html

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "eos_scorecard.json")))
GEN = D.get("generated") or dt.datetime.now().strftime("%d %b %Y, %H:%M")

# ---------- formatting ----------
def esc(s): return html.escape(str(s)) if s is not None else ""

def fmt_val(v, f):
    if v is None: return "—"
    try: v = float(v)
    except Exception: return esc(v)
    if f == "pct0":       return "%d%%" % round(v)
    if f == "pct1":       return "%.1f%%" % v
    if f == "pct_signed": return ("+" if v >= 0 else "") + "%.1f%%" % v
    if f == "num0":       return "%d" % round(v)
    if f == "num1":       return "%.1f" % v
    if f == "score2":     return "%.2f" % v
    if f == "gbp0":       return "£%d" % round(v)
    if f == "gbp1":       return "£%.1f" % v
    return ("%g" % v)

def status(m):
    """green | red | nodata | tbc — STRICTLY BINARY (pass/fail only).
    tbc    = metric not yet defined (greyed placeholder, never coloured).
    nodata = metric is defined but has no actual yet (greyed, awaiting — never red).
    green  = actual meets or beats plan ; red = actual below plan."""
    if m.get("tbc"):
        return "tbc"
    if m.get("actual") is None or m.get("plan") is None:
        return "nodata"
    a = float(m["actual"]); p = float(m["plan"])
    if m.get("dir", "high") == "high":
        return "green" if a >= p else "red"
    else:  # lower is better
        return "green" if a <= p else "red"

GREY = ("tbc", "nodata")
STATUS_LAB = {"green": "ON PLAN", "red": "OFF PLAN",
              "nodata": "AWAITING DATA", "tbc": "NOT YET DEFINED"}

def widget(m):
    st = status(m)
    css = "tbc" if st in GREY else st          # both grey states share the greyed tile style
    fmt = m.get("fmt", "num1")
    actual_txt = "TBC" if st == "tbc" else ("—" if st == "nodata" else fmt_val(m.get("actual"), fmt))
    plan_txt   = fmt_val(m.get("plan"), fmt) if m.get("plan") is not None else "—"
    src = (m.get("source") or "").lower()
    src_lab = {"live": "live · BigQuery", "derived": "auto-derived",
               "manual": "manual input", "tbc": "to be defined"}.get(src, src or "")
    detail = m.get("detail") or ""
    note = m.get("note") or ""
    sub = ('<div class="w-detail">%s</div>' % esc(detail)) if detail else ""
    notehtml = ('<div class="w-note">%s</div>' % esc(note)) if note else ""
    return f"""<div class="widget {css}">
      <div class="w-top"><span class="w-name">{esc(m['name'])}</span><span class="w-src {src}">{esc(src_lab)}</span></div>
      <div class="w-nums">
        <div class="w-cell actual"><div class="w-lab">Actual</div><div class="w-big">{actual_txt}</div></div>
        <div class="w-vs">vs</div>
        <div class="w-cell plan"><div class="w-lab">Plan</div><div class="w-big plan">{plan_txt}</div></div>
        <div class="w-flag">{STATUS_LAB[st]}</div>
      </div>
      {sub}{notehtml}
    </div>"""

def tally(metrics):
    g = sum(1 for m in metrics if status(m) == "green")
    r = sum(1 for m in metrics if status(m) == "red")
    t = sum(1 for m in metrics if status(m) in GREY)
    return g, r, t

weekly = D.get("weekly", [])
quarterly = D.get("quarterly", [])
wg, wr, wt = tally(weekly)
qg, qr, qt = tally(quarterly)
weekly_html    = "".join(widget(m) for m in weekly)
quarterly_html = "".join(widget(m) for m in quarterly)
flags = D.get("flags", [])
flags_html = "".join("<li>%s</li>" % esc(f) for f in flags)
WK = esc(D.get("week_label", ""))
QL = esc(D.get("quarter_label", ""))

HTML = f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="robots" content="noindex, nofollow">
<title>Bewiched — EOS Scorecard</title>
<style>
  :root{{--bg:#f4efe9;--card:#fff;--ink:#2b211b;--muted:#8a7a6d;--line:#e7ddd2;--brown:#5b3a29;--brown2:#3f281c;--cream:#efe6dc;--gold:#e7b35a;
    --green:#1f8a4c;--red:#c0392b;--redbg:#fbeae8;--greenbg:#e6f4ec;--greybg:#f1ece5;}}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}}
  .brandbar{{background:linear-gradient(180deg,var(--brown) 0%,var(--brown2) 100%);color:#f6efe7;}}
  .brandbar .inner{{max-width:1180px;margin:0 auto;padding:14px 22px;display:flex;align-items:center;gap:13px;}}
  .logo .word{{font-size:21px;font-weight:800;line-height:1;}} .logo .word span{{color:var(--gold)}}
  .logo .eyebrow{{font-size:10.5px;letter-spacing:2.4px;text-transform:uppercase;color:#cbb29c;margin-top:3px;}}
  .brandbar .spacer{{flex:1}} .brandbar .ctx{{font-size:11.5px;color:#cbb29c;text-align:right;line-height:1.5}} .brandbar .ctx b{{color:#f6efe7;font-weight:700}}
  .wrap{{max-width:1180px;margin:0 auto;padding:22px 22px 60px;}}
  a.back{{color:var(--brown);font-size:12.5px;text-decoration:none;font-weight:700}} a.back:hover{{text-decoration:underline}}
  header.page h1{{margin:10px 0 4px;font-size:23px;}} header.page .sub{{color:var(--muted);font-size:13.5px;line-height:1.55;max-width:880px}}
  .pill{{display:inline-block;background:var(--cream);color:var(--brown);border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:12px;font-weight:600;margin-left:6px;}}
  /* tabs */
  .tabs{{display:flex;gap:8px;margin:18px 0 4px;border-bottom:2px solid var(--line);}}
  .tab{{appearance:none;border:0;background:transparent;font:inherit;cursor:pointer;padding:10px 18px;font-size:14.5px;font-weight:800;color:var(--muted);border-bottom:3px solid transparent;margin-bottom:-2px;}}
  .tab.active{{color:var(--brown);border-bottom-color:var(--gold);}}
  .tab .cnt{{font-size:11px;font-weight:700;color:#a8978a;margin-left:6px}}
  .pane{{display:none}} .pane.active{{display:block}}
  .panehead{{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin:16px 2px 6px;}}
  .panehead .lbl{{font-size:12.5px;color:var(--muted);font-weight:600}}
  .tallychips span{{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:700;margin-right:10px}}
  .dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
  .dot.green{{background:var(--green)}} .dot.red{{background:var(--red)}} .dot.tbc{{background:#c9bdae}}
  /* widget grid */
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px;margin-top:10px;}}
  .widget{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 15px;border-left:6px solid var(--line);box-shadow:0 1px 2px rgba(80,50,30,.05);position:relative;}}
  .widget.green{{border-left-color:var(--green);box-shadow:0 0 0 1px #cfe6d8, 0 0 14px rgba(31,138,76,.18);}}
  .widget.red{{border-left-color:var(--red);box-shadow:0 0 0 1px #eccfca, 0 0 14px rgba(192,57,43,.16);}}
  .widget.tbc{{border-left-color:#cfc4b5;background:var(--greybg);opacity:.85;}}
  .w-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:10px}}
  .w-name{{font-size:15px;font-weight:800;color:var(--ink);line-height:1.25}}
  .w-src{{font-size:9.5px;font-weight:800;text-transform:uppercase;letter-spacing:.4px;padding:2px 7px;border-radius:6px;white-space:nowrap;background:#eee;color:#777}}
  .w-src.live{{background:#e6f4ec;color:#1c6b3d}} .w-src.derived{{background:#eef4fb;color:#2d6fb3}}
  .w-src.manual{{background:#f3ece0;color:#8a6d3b}} .w-src.tbc{{background:#ece6dd;color:#9a8c7c}}
  .w-nums{{display:flex;align-items:center;gap:12px}}
  .w-cell{{text-align:center}} .w-lab{{font-size:9.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}}
  .w-big{{font-size:30px;font-weight:800;line-height:1.05;margin-top:1px}}
  .widget.green .w-cell.actual .w-big{{color:var(--green)}}
  .widget.red .w-cell.actual .w-big{{color:var(--red)}} .widget.tbc .w-cell.actual .w-big{{color:#b3a899}}
  .w-big.plan{{color:#6f5d4e;font-weight:700;font-size:26px}}
  .w-vs{{font-size:11px;color:var(--muted);font-weight:700;align-self:center;padding-top:12px}}
  .w-flag{{margin-left:auto;align-self:center;font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.4px;padding:5px 9px;border-radius:8px;}}
  .widget.green .w-flag{{background:var(--greenbg);color:var(--green)}}
  .widget.red .w-flag{{background:var(--redbg);color:var(--red)}} .widget.tbc .w-flag{{background:#e7e0d6;color:#9a8c7c}}
  .w-detail{{margin-top:10px;font-size:12px;color:#5b4a3d;line-height:1.45}}
  .w-note{{margin-top:6px;font-size:11px;color:var(--muted);line-height:1.45;font-style:italic}}
  .legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:11.5px;color:var(--muted);margin:18px 4px 2px}} .legend span{{display:inline-flex;align-items:center;gap:5px}} .sw{{width:12px;height:12px;border-radius:3px;display:inline-block}}
  .info{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin-top:18px}}
  .info h2{{margin:0 0 8px;font-size:15px;color:var(--brown)}} .info ul{{margin:6px 0 0;padding-left:18px}} .info li{{font-size:12.5px;line-height:1.5;margin:6px 0}}
  .info.notebox{{background:#fff8ec;border-color:#f0e0bf}} .info.notebox h2{{color:#7a5e1e}}
  footer{{color:var(--muted);font-size:12px;margin-top:26px;line-height:1.6}}
</style>
</head>
<body>
<div class="brandbar"><div class="inner">
  <div class="logo"><div><div class="word">Be<span>wiched</span></div><div class="eyebrow">EOS Scorecard</div></div></div>
  <div class="spacer"></div>
  <div class="ctx">Company level · 21 stores<br>Weekly &amp; Quarterly measurables<br><span style="color:var(--gold);font-weight:700">🔄 Generated {GEN}</span></div>
</div></div>
<div class="wrap">
  <a class="back" href="index.html">← All dashboards</a>
  <header class="page">
    <h1>📋 Bewiched — EOS Scorecard <span class="pill">Weekly + Quarterly</span></h1>
    <div class="sub">EOS-style traffic-light scorecard: each measurable shows <b>actual vs plan</b> side by side and glows
      <b style="color:var(--green)">green</b> when actual meets or beats plan, <b style="color:var(--red)">red</b> when below — a
      strict pass/fail, no in-between. Greyed tiles are not yet defined or awaiting data.</div>
  </header>

  <div class="tabs">
    <button class="tab active" data-pane="weekly">Weekly <span class="cnt">{len(weekly)} measurables</span></button>
    <button class="tab" data-pane="quarterly">Quarterly <span class="cnt">{len(quarterly)} measurables</span></button>
  </div>

  <section class="pane active" id="pane-weekly">
    <div class="panehead">
      <span class="lbl">Week: <b>{WK}</b></span>
      <span class="tallychips"><span><span class="dot green"></span>{wg} on plan</span><span><span class="dot red"></span>{wr} off plan</span><span><span class="dot tbc"></span>{wt} TBC / awaiting</span></span>
    </div>
    <div class="grid">{weekly_html}</div>
  </section>

  <section class="pane" id="pane-quarterly">
    <div class="panehead">
      <span class="lbl">Quarter: <b>{QL}</b></span>
      <span class="tallychips"><span><span class="dot green"></span>{qg} on plan</span><span><span class="dot red"></span>{qr} off plan</span><span><span class="dot tbc"></span>{qt} TBC / awaiting</span></span>
    </div>
    <div class="grid">{quarterly_html}</div>
  </section>

  <div class="legend">
    <span><span class="sw" style="background:var(--greenbg);border:1px solid #cfe6d8"></span>actual ≥ plan (on plan)</span>
    <span><span class="sw" style="background:var(--redbg);border:1px solid #eccfca"></span>below plan (off plan)</span>
    <span><span class="sw" style="background:var(--greybg);border:1px solid var(--line)"></span>not yet defined / awaiting data</span>
  </div>

  <div class="info notebox">
    <h2>Defaults &amp; assumptions — please confirm or adjust</h2>
    <ul>{flags_html}</ul>
  </div>

  <footer>Bewiched Limited · internal use · EOS Scorecard. Live rows from BigQuery POS (bewiched_coffee, europe-west2) + F1 / reviews / RMS feeds; manual rows from the EOS Scorecard Inputs sheet. Generated {GEN}. Sales gross inc VAT.</footer>
</div>
<script>
  document.querySelectorAll('.tab').forEach(function(t){{
    t.addEventListener('click', function(){{
      document.querySelectorAll('.tab').forEach(function(x){{x.classList.remove('active')}});
      document.querySelectorAll('.pane').forEach(function(p){{p.classList.remove('active')}});
      t.classList.add('active');
      document.getElementById('pane-'+t.dataset.pane).classList.add('active');
    }});
  }});
</script>
</body>
</html>"""

open(os.path.join(HERE, "EOS_Scorecard.html"), "w").write(HTML)
print("Wrote EOS_Scorecard.html  (%d bytes)" % len(HTML))
print("Weekly: %dG/%dR/%dgrey | Quarterly: %dG/%dR/%dgrey" % (wg, wr, wt, qg, qr, qt))
print("leftover placeholders: none")
