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

# ---- OWNERS: one accountable name per metric (EOS-style), keyed by metric NAME — same on both tabs.
# Edit here to reassign. "" / missing => shown as "—" (unassigned).
OWNERS = {
    "YoY Sales Growth": "Rich",
    "YoY Transactional Growth": "Rich",
    "Google Health": "Jon",
    "Rate My Shift Health": "Kel",
    "Brew Crew Kudos Participation": "Kel",
    "Social Media Engagement": "Jon",
    "SPH Labour (incl holiday pay)": "Jon",
    "Bench": "Kel",
    "F1 Score": "Claire",
    "Brand Audit Score": "Claire",
    "Food GP%": "Rich",
    "New Starter Health": "Kel",
    "Net Profit After Tax (projected)": "",   # unassigned — Matt to confirm (likely Matt/MD)
}

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
    if f == "gbp2":       return "£%.2f" % v
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
    src_lab = {"live": "live · BigQuery", "sheet": "live · F1 sheet", "derived": "auto-derived",
               "manual": "manual input", "tbc": "to be defined"}.get(src, src or "")
    detail = m.get("detail") or ""
    note = m.get("note") or ""
    sub = ('<div class="w-detail">%s</div>' % esc(detail)) if detail else ""
    notehtml = ('<div class="w-note">%s</div>' % esc(note)) if note else ""
    return f"""<div class="widget {css}">
      <div class="w-top"><span class="w-name">{esc(m['name'])}</span><span class="w-src {src}">{esc(src_lab)}</span></div>
      <div class="w-owner">Owner: <b>{esc(OWNERS.get(m['name']) or "—")}</b></div>
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

# ---- Quarterly Scorecard grid (metrics as ROWS, quarter weeks as COLUMNS) from weekly_history.csv ----
import csv as _csv
GRID = [
    ("YoY Sales Growth", "yoy_sales_pct", 12, "pct_signed"),
    ("YoY Transactional Growth", "yoy_tx_pct", 5, "pct_signed"),
    ("Google Health", "google_health_pct", 100, "pct0"),
    ("Rate My Shift Health", "rms_pct", 100, "pct0"),
    ("Brew Crew Kudos Participation", "kudos_pct", 50, "pct0"),
    ("Social Media Engagement", None, None, "pct0"),
    ("SPH Labour (incl holiday pay)", "sph", 55, "gbp1"),
    ("Bench", None, 3, "num0"),
    ("F1 Score", "f1_avg", 220, "num1"),
    ("Brand Audit Score", "brand_audit", 4.6, "score2"),
    ("Food GP%", "estate_gp_pct", 71, "pct1"),
    ("Net Profit After Tax (projected)", "npat_proj_pct", 18, "pct1"),
    ("New Starter Health", None, None, "pct0"),
]
# Metrics where a LOWER value is better (green when actual <= plan). All others are higher-is-better.
LOWER_BETTER = {"F1 Score"}
_hp = os.path.join(HERE, "weekly_history.csv")
_hist = []
if os.path.exists(_hp):
    try:
        with open(_hp, newline="") as fh:
            _hist = [r for r in _csv.DictReader(fh)]
    except Exception:
        _hist = []
_hist = sorted(_hist, key=lambda r: r.get("week_ending", ""))
def _wshort(iso):
    try:
        d = dt.date.fromisoformat(iso); return "%d/%-m" % (d.day, d.month)
    except Exception:
        return esc(iso)
def _cell_stat(val, plan, dirn="high"):
    if val in (None, "") or plan is None: return "tbc"
    try: v = float(val)
    except Exception: return "tbc"
    if dirn == "low":
        return "green" if v <= float(plan) else "red"
    return "green" if v >= float(plan) else "red"
def _cell_fmt(val, fm):
    if val in (None, ""): return ""
    try: return fmt_val(float(val), fm)
    except Exception: return esc(val)
_weeks = [r.get("week_ending", "") for r in _hist]
# x-axis / grid columns are numbered by their position in the quarter: Week 1 … Week N.
_ghead = "".join(f'<th title="{esc(w)}">Week {i + 1}</th>' for i, w in enumerate(_weeks))
_gbody = ""
_gg = _gr = 0
for name, col, plan, fm in GRID:
    owner = OWNERS.get(name) or "—"
    dirn = "low" if name in LOWER_BETTER else "high"
    plan_txt = "—" if plan is None else fmt_val(plan, fm)
    cells = ""
    for r in _hist:
        val = r.get(col) if col else None
        st = _cell_stat(val, plan, dirn)
        if st == "green": _gg += 1
        elif st == "red": _gr += 1
        txt = _cell_fmt(val, fm) if st != "tbc" else ""
        cells += f'<td class="c-{st}">{txt}</td>'
    _gbody += (f'<tr><td class="gm"><span class="gmn">{esc(name)}</span>'
               f'<span class="gmo">Owner: <b>{esc(owner)}</b></span></td>'
               f'<td class="gp">{plan_txt}</td>{cells}</tr>')
grid_html = (f'<table class="scgrid"><thead><tr><th class="gm">Measurable</th>'
             f'<th class="gp">Plan</th>{_ghead}</tr></thead><tbody>{_gbody}</tbody></table>')
n_grid_weeks = len(_weeks)
flags = D.get("flags", [])
flags_html = "".join("<li>%s</li>" % esc(f) for f in flags)
WK = esc(D.get("week_label", ""))
QL = esc(D.get("quarter_label", ""))

# ============================ Metric detail tab (selector) ============================
# Static, non-data config. Definitions = one-liner what-it-measures; CALCS = plain-terms formula.
PS = D.get("per_store", {})
YOY = D.get("yoy_detail", {})   # extra ATV + food-attach detail, YoY Sales Growth view only
DEFINITIONS = {
    "YoY Sales Growth": "Like-for-like sales growth versus the same period last year.",
    "YoY Transactional Growth": "Like-for-like transaction (order count) growth versus last year.",
    "Google Health": "Volume and quality of Google reviews, blended into a 0–100 health score.",
    "Rate My Shift Health": "Volume and score of Rate-My-Shift submissions, blended into a 0–100 health score.",
    "Brew Crew Kudos Participation": "Share of employees who gave peer kudos in the period.",
    "Social Media Engagement": "Engagement across Bewiched social channels (metric still to be defined).",
    "SPH Labour (incl holiday pay)": "Sales generated per labour hour, including holiday pay.",
    "Bench": "How many stores have a named, ready successor — management bench strength.",
    "F1 Score": "Average F1 'race' total score across the estate — operational excellence. Lower is better (target ≤220).",
    "Brand Audit Score": "Average brand-audit score out of 5.",
    "Food GP%": "Gross-profit margin from Cost of Sales (food GP proxy).",
    "Net Profit After Tax (projected)": "Projected net-profit margin after tax, flexed off the latest P&L.",
    "New Starter Health": "Onboarding and retention health of new starters (metric still to be defined).",
}
CALCS = {
    "YoY Sales Growth": "Σ this-period sales ÷ Σ same-period-last-year sales − 1, across stores trading in BOTH periods (like-for-like). New and closed sites are excluded.",
    "YoY Transactional Growth": "Same like-for-like basis as sales, but using distinct order counts instead of value.",
    "Google Health": "Average of (reviews ÷ 40) and (rating ÷ 4.6), each capped at 100%, ×100. The QTD volume divisor scales by the number of weeks in the quarter.",
    "Rate My Shift Health": "Average of (submissions ÷ 70) and (average score ÷ 4.6), each capped at 100%, ×100. The QTD volume divisor scales by weeks in the quarter.",
    "Brew Crew Kudos Participation": "Distinct employees who gave kudos (BCKH tab, matched by email to the Employee List) ÷ total employee headcount.",
    "Social Media Engagement": "Not yet defined — awaiting the metric definition and target.",
    "SPH Labour (incl holiday pay)": "Estate sales ÷ labour hours used (from the area planners, Section A), hours-weighted. QTD is hours-weighted across the quarter's weeks in weekly_history.csv.",
    "Bench": "Count of stores with at least one named successor in the HRP 'Bench Manager' / pipeline columns (point-in-time). Green estate-wide when ≥ 3 stores have one.",
    "F1 Score": "Average of each store's race Total Score. Weekly = last completed week's race; QTD = quarter-to-date average. LOWER IS BETTER on this scale — green at or below the target of ≤220, red above.",
    "Brand Audit Score": "Estate average of store brand-audit scores logged in the period, out of 5.",
    "Food GP%": "(Turnover − cost of goods) ÷ turnover from the Cost-of-Sales master (estate proxy; posts roughly one week in arrears).",
    "Net Profit After Tax (projected)": "Baseline 7.9% (May P&L) + GP flex (estate GP% − baseline) − labour flex (labour% − baseline, via live CPH). A projection, not a booked figure.",
    "New Starter Health": "Not yet defined — awaiting the metric definition and target.",
}
# metric name -> (history column, fmt) for the 13-week trend, reusing the GRID mapping
HIST_COL = {name: (col, fm) for name, col, _pl, fm in GRID}

def _hnum(x):
    try: return float(x) if x not in (None, "") else None
    except Exception: return None

def _cellcls(v, plan, dirn):
    if v is None or plan is None: return "tbc"
    return ("green" if v >= plan else "red") if dirn == "high" else ("green" if v <= plan else "red")

def trend_svg(name, plan, dirn):
    col, fm = HIST_COL.get(name, (None, "num1"))
    if not col:
        return ('<div class="md-note">History building — this measure is not banked in the weekly '
                'history yet (fills going forward).</div>')
    return _trend_core(col, fm, plan, dirn)

def _trend_core(col, fm, plan, dirn):
    # x-axis is numbered Week 1 … Week N across the quarter; the week-ending date stays in the tooltip.
    series = [(r.get("week_ending", ""), _hnum(r.get(col))) for r in _hist]
    vals = [v for _, v in series if v is not None]
    if not vals:
        return '<div class="md-note">History building — no values banked for this measure yet.</div>'
    n = len(series)
    W, H, padL, padR, padT, padB = 660, 190, 46, 12, 14, 30
    plotW = W - padL - padR; plotH = H - padT - padB
    ref = ([plan] if plan is not None else [])
    lo = min(vals + ref + [0]); hi = max(vals + ref)
    if hi == lo: hi = lo + 1
    def Y(v): return padT + plotH * (1 - (v - lo) / (hi - lo))
    yB = Y(lo); bw = plotW / n
    parts = ['<svg class="md-svg" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" role="img">' % (W, H)]
    # baseline axis
    parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--line)"/>' % (padL, yB, W - padR, yB))
    for lab, v in [("hi", hi), ("lo", lo)]:
        yy = Y(hi) if lab == "hi" else Y(lo)
        parts.append('<text x="%.1f" y="%.1f" font-size="9" fill="var(--muted)" text-anchor="end">%s</text>'
                     % (padL - 5, yy + 3, esc(fmt_val(v, fm))))
    # bars
    for i, (lab, v) in enumerate(series):
        x = padL + i * bw
        cx = x + bw * 0.5
        if v is None:
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="3" fill="#e2d8cc"><title>Week %d (%s): no data</title></rect>'
                         % (x + bw * 0.2, yB - 3, bw * 0.6, i + 1, esc(lab)))
        else:
            cls = _cellcls(v, plan, dirn)
            fill = {"green": "var(--green)", "red": "var(--red)", "tbc": "var(--gold)"}[cls]
            top = Y(v); ht = max(1.5, yB - top)
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="%s" opacity="0.9">'
                         '<title>Week %d (%s): %s</title></rect>'
                         % (x + bw * 0.16, top, bw * 0.68, ht, fill, i + 1, esc(lab), esc(fmt_val(v, fm))))
        parts.append('<text x="%.1f" y="%.1f" font-size="8.5" fill="var(--muted)" text-anchor="middle">Week %d</text>'
                     % (cx, H - padB + 12, i + 1))
    # plan reference line
    if plan is not None:
        yp = Y(plan)
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--brown)" stroke-width="1.3" '
                     'stroke-dasharray="5 4"/>' % (padL, yp, W - padR, yp))
        parts.append('<text x="%.1f" y="%.1f" font-size="9" font-weight="700" fill="var(--brown)" '
                     'text-anchor="start">plan %s</text>' % (W - padR - 54, yp - 4, esc(fmt_val(plan, fm))))
    parts.append('</svg>')
    return "".join(parts)

def ministat(m, lab):
    st = status(m); css = "tbc" if st in GREY else st
    fm = m.get("fmt", "num1")
    a = "TBC" if st == "tbc" else ("—" if st == "nodata" else fmt_val(m.get("actual"), fm))
    p = fmt_val(m.get("plan"), fm) if m.get("plan") is not None else "—"
    return ('<div class="md-stat %s"><div class="md-stat-lab">%s</div><div class="md-stat-big">%s</div>'
            '<div class="md-stat-plan">plan %s</div><div class="md-stat-flag">%s</div></div>'
            % (css, lab, a, p, STATUS_LAB[st]))

def ps_table(rows_in, basis, psplan, dirn, fmt, informational=False):
    """Render a per-store table (store · value · vs-plan chip · bar). Ranks best-to-worst:
    higher-is-better -> descending; lower-is-better -> ascending. informational=True => no
    green/red vs plan (neutral bars, 'info' chip) for measures without a formal target."""
    present = [r for r in rows_in if r.get("value") is not None]
    missing = [r for r in rows_in if r.get("value") is None]
    present.sort(key=lambda r: r["value"], reverse=(dirn != "low"))
    rows = present + missing
    mx = max((abs(r["value"]) for r in present), default=1) or 1
    body = ""
    for r in rows:
        v = r.get("value")
        if informational or psplan is None:
            cls = "info"; barcol = "var(--gold)"; chiptxt = "info"
        else:
            cls = _cellcls(v, psplan, dirn); barcol = {"green": "var(--green)", "red": "var(--red)", "tbc": "var(--gold)"}[cls]
            chiptxt = "ON" if cls == "green" else ("OFF" if cls == "red" else "—")
        vt = fmt_val(v, fmt) if v is not None else "—"
        chip = '<span class="chip %s">%s</span>' % (cls, chiptxt)
        w = max(2, min(100, abs(v) / mx * 100)) if v is not None else 0
        bar = '<div class="md-bar"><i style="width:%.0f%%;background:%s"></i></div>' % (w, barcol)
        body += ('<tr><td class="s">%s</td><td class="v">%s</td><td class="st">%s</td><td class="bar">%s</td></tr>'
                 % (esc(r.get("store", "—")), vt, chip, bar))
    ref_lbl = "reference" if informational else "store target"
    ref_txt = "informational" if (informational or psplan is None) else fmt_val(psplan, fmt)
    return ('<div class="md-ps-basis">%s · %s <b>%s</b> · %d stores</div>'
            '<table class="md-ps"><thead><tr><th>Store</th><th class="v">Value</th><th class="st">%s</th>'
            '<th class="bar"></th></tr></thead><tbody>%s</tbody></table>'
            % (esc(basis), ref_lbl, ref_txt, len(rows), ("" if informational else "vs plan"), body))

def perstore_html(name, plan, dirn, fmt):
    entry = PS.get(name)
    if not entry or not entry.get("rows"):
        return None
    psplan = entry.get("plan")
    if psplan is None: psplan = plan
    return ps_table(entry["rows"], entry.get("basis", ""), psplan, dirn, fmt)

def company_only(name, qm):
    fm = qm.get("fmt", "num1"); st = status(qm)
    if qm.get("tbc"):
        return '<div class="md-note">Not measured at store level — metric not yet defined.</div>'
    big = "—" if qm.get("actual") is None else fmt_val(qm.get("actual"), fm)
    return ('<div class="md-company"><div class="big">%s</div><div class="md-company-txt">'
            'Company-level measure — not broken out per store. Figure shown is the quarter-to-date company value.'
            '</div></div>' % big)

def yoy_extras_html():
    """Extra sections shown ONLY on the YoY Sales Growth detail view: average spend (ATV) trend +
    per-store, and per-store food-attachment %."""
    if not YOY:
        return ""
    parts = []
    atv_target = YOY.get("atv_target")
    atv_col = YOY.get("atv_trend_col", "estate_atv")
    # ATV estate trend (higher-is-better vs the £6.80 reference)
    parts.append('<div class="md-section-h">Average spend (ATV) — estate trend</div>')
    if atv_col in {c for _n, c, _p, _f in GRID} or any(r.get(atv_col) not in (None, "") for r in _hist):
        parts.append(_trend_core(atv_col, "gbp2", atv_target, "high"))
    else:
        parts.append('<div class="md-note">History building — estate ATV fills going forward.</div>')
    # ATV per store (vs £6.80 target)
    aps = YOY.get("atv_per_store") or []
    parts.append('<div class="md-section-h">Average spend (ATV) — by store</div>')
    if aps:
        parts.append(ps_table(aps, YOY.get("atv_basis", "") + " · target £6.80", atv_target, "high", "gbp2"))
    else:
        parts.append('<div class="md-note">Per-store ATV not available this week.</div>')
    # Food attachment % per store (informational — no formal estate plan)
    fps = YOY.get("food_attach_per_store") or []
    parts.append('<div class="md-section-h">Food attachment % — by store</div>')
    if fps:
        parts.append(ps_table(fps, YOY.get("food_attach_basis", ""), None, "high", "pct1", informational=True))
        if YOY.get("food_attach_note"):
            parts.append('<div class="md-note">%s</div>' % esc(YOY["food_attach_note"]))
    else:
        parts.append('<div class="md-note">Food attachment % not available — the estate-wide BigQuery '
                     'derivation did not return this run (per-store food-attach also exists in the txquality '
                     'views for Glenvale &amp; Leamington Parade).</div>')
    return "".join(parts)

md_options = ""
md_details = ""
for i, (wm, qm) in enumerate(zip(weekly, quarterly)):
    name = wm["name"]; fm = wm.get("fmt", "num1"); dirn = wm.get("dir", "high")
    plan = wm.get("plan")
    owner = OWNERS.get(name) or "—"
    md_options += '<option value="md-%d"%s>%s</option>' % (i, (" selected" if i == 0 else ""), esc(name))
    definition = esc(DEFINITIONS.get(name, ""))
    calc = esc(CALCS.get(name, ""))
    plan_txt = fmt_val(plan, fm) if plan is not None else "not set (TBC)"
    dir_txt = ("Lower is better (green ≤ %s)" % esc(plan_txt)) if dirn == "low" else "Higher is better"
    ps = perstore_html(name, plan, dirn, fm)
    ps_block = ps if ps is not None else company_only(name, qm)
    extras = yoy_extras_html() if name == "YoY Sales Growth" else ""   # ATV + food-attach, YoY view only
    disp = "block" if i == 0 else "none"
    md_details += (
        '<div class="md-detail" id="md-%d" style="display:%s">' % (i, disp)
        + '<div class="md-title">%s<span class="md-owner">Owner: <b>%s</b></span></div>' % (esc(name), esc(owner))
        + '<div class="md-def">%s</div>' % definition
        + '<div class="md-planline">Plan: <b>%s</b> · Owner: <b>%s</b> · %s</div>' % (esc(plan_txt), esc(owner), dir_txt)
        + '<div class="md-section-h">Current status</div>'
        + '<div class="md-stats">%s%s</div>' % (ministat(wm, "This week"), ministat(qm, "Quarter to date"))
        + '<div class="md-section-h">13-week trend</div>'
        + trend_svg(name, plan, dirn)
        + '<div class="md-section-h">Per-store breakdown</div>'
        + ps_block
        + extras
        + '<div class="md-section-h">How it\'s calculated</div>'
        + '<div class="md-calc">%s</div>' % calc
        + '</div>'
    )

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
  .w-owner{{font-size:11px;color:var(--muted);font-weight:600;margin:-4px 0 8px}} .w-owner b{{color:var(--brown);font-weight:800}}
  .w-src{{font-size:9.5px;font-weight:800;text-transform:uppercase;letter-spacing:.4px;padding:2px 7px;border-radius:6px;white-space:nowrap;background:#eee;color:#777}}
  .w-src.live,.w-src.sheet{{background:#e6f4ec;color:#1c6b3d}} .w-src.derived{{background:#eef4fb;color:#2d6fb3}}
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
  .gridwrap{{overflow-x:auto;border:1px solid var(--line);border-radius:14px;background:var(--card);padding:6px;box-shadow:0 1px 2px rgba(80,50,30,.04)}}
  table.scgrid{{border-collapse:collapse;font-size:12px;width:100%;min-width:820px}}
  table.scgrid th,table.scgrid td{{padding:6px 8px;text-align:center;border-bottom:1px solid var(--line);white-space:nowrap}}
  table.scgrid thead th{{font-size:10.5px;text-transform:uppercase;color:var(--muted);font-weight:700;position:sticky;top:0;background:#fff;z-index:1}}
  th.gm,td.gm{{text-align:left;position:sticky;left:0;background:#fff;min-width:220px;border-right:1px solid var(--line);z-index:2}}
  table.scgrid thead th.gm{{z-index:3}}
  td.gm .gmn{{font-weight:800;display:block;line-height:1.2}} td.gm .gmo{{font-size:10.5px;color:var(--muted)}} td.gm .gmo b{{color:var(--brown)}}
  th.gp,td.gp{{font-weight:800;color:var(--brown);border-right:1px solid var(--line);min-width:52px}}
  td.c-green{{background:var(--greenbg);color:var(--green);font-weight:700}}
  td.c-red{{background:var(--redbg);color:var(--red);font-weight:700}}
  td.c-tbc{{background:var(--greybg);color:#b9ad9f}}
  /* metric detail tab */
  .mdbar{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
  .mdsel{{font:inherit;font-size:14px;font-weight:700;color:var(--brown);background:#fff;border:1px solid var(--line);border-radius:9px;padding:8px 12px;cursor:pointer}}
  .md-wrap{{margin-top:14px}}
  .md-detail{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;box-shadow:0 1px 2px rgba(80,50,30,.05)}}
  .md-title{{font-size:19px;font-weight:800;color:var(--ink);display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}}
  .md-title .md-owner{{font-size:12px;font-weight:600;color:var(--muted)}} .md-title .md-owner b{{color:var(--brown);font-weight:800}}
  .md-def{{font-size:13.5px;color:#5b4a3d;margin:7px 0 2px;line-height:1.5}}
  .md-planline{{font-size:12.5px;color:var(--muted);margin:8px 0 2px}} .md-planline b{{color:var(--brown)}}
  .md-section-h{{font-size:11px;text-transform:uppercase;letter-spacing:.7px;color:var(--muted);font-weight:800;margin:18px 0 10px;border-top:1px solid var(--line);padding-top:13px}}
  .md-stats{{display:flex;gap:12px;flex-wrap:wrap}}
  .md-stat{{flex:1;min-width:160px;border:1px solid var(--line);border-radius:12px;padding:12px 14px;border-left:6px solid var(--line);background:#fff}}
  .md-stat.green{{border-left-color:var(--green);box-shadow:0 0 0 1px #cfe6d8}} .md-stat.red{{border-left-color:var(--red);box-shadow:0 0 0 1px #eccfca}} .md-stat.tbc{{border-left-color:#cfc4b5;background:var(--greybg)}}
  .md-stat-lab{{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:800}}
  .md-stat-big{{font-size:28px;font-weight:800;line-height:1.1;margin:2px 0}}
  .md-stat.green .md-stat-big{{color:var(--green)}} .md-stat.red .md-stat-big{{color:var(--red)}} .md-stat.tbc .md-stat-big{{color:#b3a899}}
  .md-stat-plan{{font-size:11.5px;color:#6f5d4e;font-weight:700}}
  .md-stat-flag{{font-size:9.5px;font-weight:800;text-transform:uppercase;letter-spacing:.4px;margin-top:6px;color:var(--muted)}}
  .md-note{{font-size:12.5px;color:var(--muted);font-style:italic;background:var(--greybg);border:1px solid var(--line);border-radius:10px;padding:11px 13px}}
  .md-calc{{font-size:12.5px;color:#5b4a3d;line-height:1.55;background:#fbf7f1;border:1px solid var(--line);border-radius:10px;padding:11px 13px}}
  .md-svg{{width:100%;max-width:680px;height:auto;display:block}}
  .md-ps-basis{{font-size:11.5px;color:var(--muted);margin-bottom:8px}} .md-ps-basis b{{color:var(--brown)}}
  table.md-ps{{width:100%;max-width:680px;border-collapse:collapse;font-size:12px}}
  table.md-ps th,table.md-ps td{{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left}}
  table.md-ps th{{font-size:10px;text-transform:uppercase;color:var(--muted);font-weight:700}}
  table.md-ps td.s{{font-weight:600}}
  table.md-ps td.v,table.md-ps th.v{{text-align:right;font-weight:800;font-variant-numeric:tabular-nums;width:72px}}
  table.md-ps td.st,table.md-ps th.st{{text-align:center;width:56px}}
  table.md-ps td.bar{{width:180px}}
  .md-ps .chip{{display:inline-block;padding:2px 7px;border-radius:6px;font-size:10px;font-weight:800}}
  .md-ps .chip.green{{background:var(--greenbg);color:var(--green)}} .md-ps .chip.red{{background:var(--redbg);color:var(--red)}} .md-ps .chip.tbc{{background:#e7e0d6;color:#9a8c7c}}
  .md-ps .chip.info{{background:#f3ece0;color:#8a6d3b}}
  .md-bar{{height:9px;border-radius:5px;background:var(--greybg);overflow:hidden}} .md-bar > i{{display:block;height:100%}}
  .md-company{{display:flex;gap:16px;align-items:center;background:var(--greybg);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
  .md-company .big{{font-size:30px;font-weight:800;color:var(--brown);line-height:1}}
  .md-company-txt{{font-size:12.5px;color:#5b4a3d;line-height:1.5}}
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
    <button class="tab" data-pane="grid">Quarterly Scorecard <span class="cnt">{n_grid_weeks}-week grid</span></button>
    <button class="tab" data-pane="detail">Metric detail <span class="cnt">any of {len(weekly)}</span></button>
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

  <section class="pane" id="pane-grid">
    <div class="panehead">
      <span class="lbl">Quarter: <b>{QL}</b> · {n_grid_weeks} week{'' if n_grid_weeks==1 else 's'} · one column per week (Week 1…{n_grid_weeks}, hover for the date) · each cell traffic-lit vs plan</span>
    </div>
    <div class="gridwrap">{grid_html}</div>
    <div class="legend"><span><span class="sw" style="background:var(--greenbg);border:1px solid #cfe6d8"></span>on plan</span><span><span class="sw" style="background:var(--redbg);border:1px solid #eccfca"></span>off plan</span><span><span class="sw" style="background:var(--greybg);border:1px solid var(--line)"></span>no data / not defined (Bench is point-in-time; Social Media &amp; New Starter are TBC; SPH &amp; Brand Audit fill going forward). Food GP% row shows the estate blended GP per week. F1 is lower-is-better (green ≤ 220); all other rows are higher-is-better.</span></div>
  </section>

  <section class="pane" id="pane-detail">
    <div class="panehead mdbar">
      <span class="lbl">Choose a measurable:</span>
      <select id="mdsel" class="mdsel">{md_options}</select>
      <span class="lbl">— definition, plan &amp; owner, weekly + QTD status, 13-week trend, and per-store breakdown.</span>
    </div>
    <div class="md-wrap">{md_details}</div>
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
  (function(){{
    var sel = document.getElementById('mdsel');
    if(!sel) return;
    function show(id){{
      document.querySelectorAll('.md-detail').forEach(function(d){{d.style.display='none'}});
      var el = document.getElementById(id);
      if(el) el.style.display='block';
    }}
    sel.addEventListener('change', function(){{ show(sel.value); }});
    show(sel.value);
  }})();
</script>
</body>
</html>"""

open(os.path.join(HERE, "EOS_Scorecard.html"), "w").write(HTML)
print("Wrote EOS_Scorecard.html  (%d bytes)" % len(HTML))
print("Weekly: %dG/%dR/%dgrey | Quarterly: %dG/%dR/%dgrey" % (wg, wr, wt, qg, qr, qt))
print("leftover placeholders: none")
