#!/usr/bin/env python3
# Bewiched EOS Weekly & Quarterly Scorecard generator.
# Reads eos_scorecard.json -> writes EOS_Scorecard.html, matching the Bewiched dashboards stack.
# Two tabs (Weekly / Quarterly); each metric = an EOS traffic-light widget (plan vs actual).
# STRICTLY BINARY status: GREEN actual>=plan | RED below. No near-target band.
# Greyed tiles: TBC (not yet defined) and AWAITING DATA (defined but no actual yet) — never red.
import json, datetime as dt, os, html
try:
    import ns_detail
except Exception:
    ns_detail = None

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
    "Brand & Remote Assessment": "Claire",
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
    if f == "num_signed": return ("+%d" % round(v)) if v > 0 else ("%d" % round(v))
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
    # Per-tile caveat 'note' narration intentionally not rendered — dashboard reads clean.
    sub = ('<div class="w-detail">%s</div>' % esc(detail)) if detail else ""
    return f"""<div class="widget {css}">
      <div class="w-top"><span class="w-name">{esc(m['name'])}</span><span class="w-src {src}">{esc(src_lab)}</span></div>
      <div class="w-owner">Owner: <b>{esc(OWNERS.get(m['name']) or "—")}</b></div>
      <div class="w-nums">
        <div class="w-cell actual"><div class="w-lab">Actual</div><div class="w-big">{actual_txt}</div></div>
        <div class="w-vs">vs</div>
        <div class="w-cell plan"><div class="w-lab">Plan</div><div class="w-big plan">{plan_txt}</div></div>
        <div class="w-flag">{STATUS_LAB[st]}</div>
      </div>
      {sub}
    </div>"""

def tally(metrics):
    g = sum(1 for m in metrics if status(m) == "green")
    r = sum(1 for m in metrics if status(m) == "red")
    t = sum(1 for m in metrics if status(m) in GREY)
    return g, r, t

def _relgap(m):
    """Relative shortfall vs plan (comparable across units) — bigger = worse."""
    try:
        a = float(m["actual"]); p = float(m["plan"])
    except Exception:
        return 0.0
    if not p: return 0.0
    return (a - p) / abs(p) if m.get("dir", "high") == "low" else (p - a) / abs(p)

def issues_html(metrics, period):
    """EOS 'home in on' list of the genuinely RED metrics (never grey/TBC/awaiting),
    worst gap first. Driven off the same binary status() so it stays in sync each run."""
    reds = sorted((m for m in metrics if status(m) == "red"), key=_relgap, reverse=True)
    head = '<div class="issues"><div class="iss-h">Issues to home in on (%s)</div>' % esc(period)
    if not reds:
        return head + '<div class="iss-none">No issues — all on plan.</div></div>'
    items = ""
    for m in reds:
        fm = m.get("fmt", "num1"); owner = OWNERS.get(m["name"]) or "—"
        a = fmt_val(m.get("actual"), fm)
        p = fmt_val(m.get("plan"), fm)
        p = ("≤" + p) if m.get("dir", "high") == "low" else p
        items += ('<li><span class="iss-name">%s</span>'
                  '<span class="iss-vs"><b>%s</b> vs plan %s</span>'
                  '<span class="iss-own">%s</span></li>'
                  % (esc(m["name"]), esc(a), esc(p), esc(owner)))
    return head + '<ol class="iss-list">%s</ol></div>' % items

weekly = D.get("weekly", [])
quarterly = D.get("quarterly", [])
wg, wr, wt = tally(weekly)
qg, qr, qt = tally(quarterly)
weekly_html    = "".join(widget(m) for m in weekly)
quarterly_html = "".join(widget(m) for m in quarterly)
weekly_issues_html    = issues_html(weekly, "this week")
quarterly_issues_html = issues_html(quarterly, "QTD")

# ---- Quarterly Scorecard grid (metrics as ROWS, quarter weeks as COLUMNS) from weekly_history.csv ----
import csv as _csv
GRID = [
    ("YoY Sales Growth", "yoy_sales_pct", 12, "pct_signed"),
    ("YoY Transactional Growth", "yoy_tx_pct", 5, "pct_signed"),
    ("Google Health", "google_health_pct", 70, "pct0"),
    ("Rate My Shift Health", "rms_pct", 70, "pct0"),
    ("Brew Crew Kudos Participation", "kudos_pct", 50, "pct0"),
    ("Social Media Engagement", None, None, "pct0"),
    ("SPH Labour (incl holiday pay)", "sph", 55, "gbp1"),
    ("Bench", "bench", 3, "num_signed"),
    ("F1 Score", "f1_avg", 175, "num1"),
    ("Brand & Remote Assessment", "brand_audit", 4.6, "score2"),
    ("Food GP%", "estate_gp_pct", 71, "pct1"),
    ("Net Profit After Tax (projected)", "npat_proj_pct", 18, "pct1"),
    ("New Starter Health", "new_starter_health", 90, "pct0"),
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
# Window the grid + all metric-detail trends to the CURRENT calendar quarter only, so on the first
# run of a new quarter (e.g. Q3 from 1 Jul) prior-quarter rows in weekly_history.csv are kept on file
# for the record but NOT shown/counted. quarter_start comes from run_weekly; fall back to deriving it
# from cur_end so the gen is robust even against an older JSON.
def _qstart_iso():
    qs = D.get("quarter_start")
    if qs: return qs
    try:
        _d = dt.date.fromisoformat(D.get("cur_end", ""))
        return dt.date(_d.year, ((_d.month - 1) // 3) * 3 + 1, 1).isoformat()
    except Exception:
        return ""
_QSTART_ISO = _qstart_iso()
if _QSTART_ISO:
    _hist = [r for r in _hist if r.get("week_ending", "") >= _QSTART_ISO]
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
def _sparkline(col, plan, dirn):
    """Mini SVG trend of a metric across the quarter weeks (from weekly_history). Single week -> a dot;
    coloured by the latest value vs plan (green on/above plan, red below; reversed for lower-is-better)."""
    if not col: return ""
    vals = []
    for r in _hist:
        v = r.get(col)
        try: vals.append(float(v))
        except Exception: vals.append(None)
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if not pts: return ""
    ys = [v for _, v in pts]; lo, hi = min(ys), max(ys)
    W, H, pad = 66, 18, 3; n = max(1, len(vals) - 1)
    X = lambda i: pad + (i / n) * (W - 2 * pad)
    Y = lambda v: pad + (1 - ((v - lo) / (hi - lo) if hi > lo else 0.5)) * (H - 2 * pad)
    last = ys[-1]
    ok = True if plan is None else ((last <= float(plan)) if dirn == "low" else (last >= float(plan)))
    c = "var(--green)" if ok else "var(--red)"
    if len(pts) == 1:
        return ('<svg width="%d" height="%d" style="vertical-align:middle"><circle cx="%.1f" cy="%.1f" r="2.6" fill="%s"/></svg>'
                % (W, H, X(pts[0][0]), Y(pts[0][1]), c))
    poly = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in pts)
    return ('<svg width="%d" height="%d" style="vertical-align:middle">'
            '<polyline points="%s" fill="none" stroke="%s" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
            '<circle cx="%.1f" cy="%.1f" r="2" fill="%s"/></svg>'
            % (W, H, poly, c, X(pts[-1][0]), Y(pts[-1][1]), c))
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
               f'<span class="gmo">{esc(owner)}</span></td>'
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
    "Google Health": "Coverage x volume x rating: how many of 21 stores got a review, total reviews vs a weekly target, and average rating. No-review stores pull it down. Target 70.",
    "Rate My Shift Health": "Volume and score of Rate-My-Shift submissions, blended into a 0–100 health score.",
    "Brew Crew Kudos Participation": "Share of employees who gave peer kudos in the period.",
    "Social Media Engagement": "Engagement across Bewiched social channels (metric still to be defined).",
    "SPH Labour (incl holiday pay)": "Sales generated per labour hour, including holiday pay.",
    "Bench": "Net Store Managers on the bench — the surplus (or shortfall) of ready SM cover. Target is a +3 surplus; the actual goes negative while SM vacancies exist (each open Store Manager = -1).",
    "F1 Score": "Average F1 'race' total score across the estate — operational excellence. Lower is better (target ≤175).",
    "Brand & Remote Assessment": "50/50 blend of brand audit + remote assessment, out of 5.",
    "Food GP%": "Estate gross-profit margin from the Cost-of-Sales sheet (authoritative Gross Profit%, col Q).",
    "Net Profit After Tax (projected)": "Projected net-profit margin after tax, flexed off the latest P&L.",
    "New Starter Health": "Share of first-90-day new starters compliant on every due onboarding step (Youda). Target 90%.",
}
CALCS = {
    "YoY Sales Growth": "Σ this-period sales ÷ Σ same-period-last-year sales − 1, across stores trading in BOTH periods (like-for-like). New and closed sites are excluded.",
    "YoY Transactional Growth": "Same like-for-like basis as sales, but using distinct order counts instead of value.",
    "Google Health": "100 × Coverage × [0.5 × min(total reviews ÷ 50, 1) + 0.5 × min(avg rating ÷ 4.6, 1)], where Coverage = stores with ≥1 review ÷ 21. QTD scales the 50 target by weeks in the quarter. Green ≥ 70.",
    "Rate My Shift Health": "Average of (submissions ÷ 70) and (average score ÷ 4.6), each capped at 100%, ×100. The QTD volume divisor scales by weeks in the quarter. Green ≥ 70.",
    "Brew Crew Kudos Participation": "Distinct employees who gave kudos (BCKH tab, matched by email to the Employee List) ÷ total employee headcount.",
    "Social Media Engagement": "Not yet defined — awaiting the metric definition and target.",
    "SPH Labour (incl holiday pay)": "Estate sales ÷ labour hours used (from the area planners, Section A), hours-weighted. QTD is hours-weighted across the quarter's weeks in weekly_history.csv.",
    "Bench": "MAIN KPI = net SM on the bench. Actual = -(number of Store Manager vacancies) from the HRP 'HRP & Bench' roster (the red 'Gap / no SM' stores); target = +3; miss = target - actual (e.g. -3 vs +3 = 6 off, red). The star map, management-team table and Bench-ready / Thin / Capability-gap cards below are unchanged and byte-identical to the Company Dashboard bench tab (hierarchy-gap rule).",
    "F1 Score": "Average of each store's race Total Score. Weekly = last completed week's race; QTD = quarter-to-date average. LOWER IS BETTER on this scale — green at or below the target of ≤175, red above.",
    "Brand & Remote Assessment": "Each store blends its brand audit (out of 5) 50/50 with its remote assessment (out of 100, normalised to /5). If only one is logged in the period, that one is used. Estate = average of per-store blends. Target 4.6.",
    "Food GP%": "The Cost-of-Sales sheet's own Gross Profit% (col Q), which nets off all cost-of-sales — sales-weighted across stores for the estate figure. Posts roughly one week in arrears.",
    "Net Profit After Tax (projected)": "Baseline 7.9% (May P&L) + GP flex (estate GP% − baseline) − labour flex (labour% − baseline, via live CPH). A projection, not a booked figure.",
    "New Starter Health": "Youda onboarding compliance across the first 90 days: a starter is compliant when every step due on their checklist is done. Estate headline = share of the cohort fully compliant. Target 90%. Detail breaks it down by step, site and starter.",
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
        return '<div class="md-note">No weekly trend for this measure.</div>'
    return _trend_core(col, fm, plan, dirn)

def _trend_core(col, fm, plan, dirn):
    # x-axis is numbered Week 1 … Week N across the quarter; the week-ending date stays in the tooltip.
    series = [(r.get("week_ending", ""), _hnum(r.get(col))) for r in _hist]
    vals = [v for _, v in series if v is not None]
    if not vals:
        return '<div class="md-note">No weekly trend for this measure.</div>'
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

def ps_table(rows_in, basis, psplan, dirn, fmt, informational=False, frows=None):
    """Render a per-store table (store · value · vs-plan chip · bar). Ranks best-to-worst:
    higher-is-better -> descending; lower-is-better -> ascending. informational=True => no
    green/red vs plan (neutral bars, 'info' chip) for measures without a formal target."""
    present = [r for r in rows_in if r.get("value") is not None]
    missing = [r for r in rows_in if r.get("value") is None]
    present.sort(key=lambda r: r["value"], reverse=(dirn != "low"))
    rows = present + missing
    mx = max((abs(r["value"]) for r in present), default=1) or 1
    # Per-store targets: when rows carry their own "target", each store is judged against ITS OWN
    # target (a Target column is shown); a row missing a target falls back to psplan and is flagged
    # 'default'. Metrics without per-row targets keep the single-plan behaviour unchanged.
    per_tgt = (not informational) and any(r.get("target") is not None for r in rows_in)
    any_fb = False
    body = ""
    for r in rows:
        v = r.get("value")
        rtgt = psplan; fb = False
        if per_tgt:
            if r.get("target") is not None:
                rtgt = r["target"]
            else:
                rtgt = psplan; fb = True; any_fb = True
        if informational or rtgt is None:
            cls = "info"; barcol = "var(--gold)"; chiptxt = "info"
        else:
            cls = _cellcls(v, rtgt, dirn); barcol = {"green": "var(--green)", "red": "var(--red)", "tbc": "var(--gold)"}[cls]
            chiptxt = "ON" if cls == "green" else ("OFF" if cls == "red" else "—")
        vt = fmt_val(v, fmt) if v is not None else "—"
        chip = '<span class="chip %s">%s</span>' % (cls, chiptxt)
        w = max(2, min(100, abs(v) / mx * 100)) if v is not None else 0
        bar = '<div class="md-bar"><i style="width:%.0f%%;background:%s"></i></div>' % (w, barcol)
        tgt_cell = ""
        if per_tgt:
            tt = fmt_val(rtgt, fmt) if rtgt is not None else "—"
            if fb: tt += ' <span class="chip tbc">default</span>'
            tgt_cell = '<td class="tg">%s</td>' % tt
        body += ('<tr><td class="s">%s</td><td class="v">%s</td>%s<td class="st">%s</td><td class="bar">%s</td></tr>'
                 % (esc(r.get("store", "—")), vt, tgt_cell, chip, bar))
    ref_lbl = "reference" if informational else "store target"
    if per_tgt:
        ref_txt = "individual per-store targets" + ((" · some default %s" % fmt_val(psplan, fmt)) if any_fb else "")
    else:
        ref_txt = "informational" if (informational or psplan is None) else fmt_val(psplan, fmt)
    tgt_head = '<th class="tg">Target</th>' if per_tgt else ''
    # Franchise (Ian) detail rows: grouped + labelled, EXCLUDED from the equity ranking/count/bar-scaling
    # above; value awaiting where hours aren't recorded. Never part of the company aggregate.
    fbody = ""
    ncols = 4 + (1 if per_tgt else 0)
    for r in (frows or []):
        v = r.get("value")
        vt = fmt_val(v, fmt) if v is not None else "—"
        tcell = ('<td class="tg">%s</td>' % (fmt_val(r.get("target"), fmt) if r.get("target") is not None else "—")) if per_tgt else ""
        fbody += ('<tr class="frow"><td class="s">%s</td><td class="v">%s</td>%s'
                  '<td class="st"><span class="chip tbc">detail</span></td><td class="bar"><div class="md-bar"></div></td></tr>'
                  % (esc(r.get("store", "—")), vt, tcell))
    if fbody:
        fbody = ('<tr class="frhead"><td colspan="%d" style="padding-top:10px;font-weight:600;color:#8a94a3">'
                 'Franchise (Ian) — detail only · not in the company SPH figure · hours used not recorded in planner, so £/hr is awaiting</td></tr>'
                 % ncols) + fbody
    stores_note = "%d stores%s" % (len(rows), (" · +%d franchise (detail)" % len(frows)) if frows else "")
    return ('<div class="md-ps-basis">%s · %s <b>%s</b> · %s</div>'
            '<table class="md-ps"><thead><tr><th>Store</th><th class="v">Value</th>%s<th class="st">%s</th>'
            '<th class="bar"></th></tr></thead><tbody>%s%s</tbody></table>'
            % (esc(basis), ref_lbl, ref_txt, stores_note, tgt_head, ("" if informational else "vs plan"), body, fbody))

def _ps_one(name, basis_key, plan, dirn, fmt):
    """One per-store table for the given basis ('weekly'|'qtd'), or None if absent."""
    entry = PS.get(name)
    if not entry: return None
    b = entry.get(basis_key)
    if not b or not b.get("rows"): return None
    psplan = entry.get("plan")
    if psplan is None: psplan = plan
    return ps_table(b["rows"], b.get("basis", ""), psplan, dirn, fmt, frows=b.get("frows"))

def ps_section(name, plan, dirn, fmt, qm):
    """Per-store breakdown with weekly + QTD sub-divs, switched by the period selector. Company-only
    metrics (no per_store) show the company figure on both; a basis missing per store shows a note."""
    parts = []
    for key in ("weekly", "qtd"):
        disp = "block" if key == "weekly" else "none"
        inner = _ps_one(name, key, plan, dirn, fmt)
        if inner is None:
            if name not in PS:
                inner = company_only(name, qm)
            else:
                lbl = "weekly" if key == "weekly" else "quarter-to-date"
                other = "quarter-to-date" if key == "weekly" else "weekly"
                inner = ('<div class="md-note">No per-store %s breakdown for this measure — '
                         'switch to the %s view.</div>' % (lbl, other))
        parts.append('<div class="ps-basis" data-basis="%s" style="display:%s">%s</div>' % (key, disp, inner))
    return '<div class="ps-dual">%s</div>' % "".join(parts)

def _extra_dual(d, plan, dirn, fmt, informational=False, target_txt=""):
    """weekly+QTD sub-divs for the ATV / food-attach extras (same period selector)."""
    parts = []
    for key in ("weekly", "qtd"):
        disp = "block" if key == "weekly" else "none"
        b = (d or {}).get(key)
        if b and b.get("rows"):
            inner = ps_table(b["rows"], b.get("basis", "") + target_txt, plan, dirn, fmt, informational=informational)
        else:
            inner = '<div class="md-note">Not available for this period.</div>'
        parts.append('<div class="ps-basis" data-basis="%s" style="display:%s">%s</div>' % (key, disp, inner))
    return '<div class="ps-dual">%s</div>' % "".join(parts)

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
    per-store (weekly/QTD), and per-store food-attachment % (weekly/QTD)."""
    if not YOY:
        return ""
    parts = []
    atv_target = YOY.get("atv_target")
    atv_col = YOY.get("atv_trend_col", "estate_atv")
    parts.append('<div class="md-section-h">Average spend (ATV) — estate trend</div>')
    if any(r.get(atv_col) not in (None, "") for r in _hist):
        parts.append(_trend_core(atv_col, "gbp2", atv_target, "high"))
    else:
        parts.append('<div class="md-note">No weekly ATV trend yet.</div>')
    parts.append('<div class="md-section-h">Average spend (ATV) — by store</div>')
    parts.append(_extra_dual(YOY.get("atv"), atv_target, "high", "gbp2", target_txt=" · target £6.80"))
    parts.append('<div class="md-section-h">Food attachment % — by store</div>')
    parts.append(_extra_dual(YOY.get("food_attach"), None, "high", "pct1", informational=True))
    return "".join(parts)


def _weekend_svg(days, this_vals, last_vals, fmt, label_this, label_last):
    """Grouped-bar SVG: for each of Fri/Sat/Sun, this year vs the equivalent day last year, with a
    per-day YoY% underneath. Pure function of the numbers -> auto-refreshes each week."""
    W, H = 680, 300
    padL, padR, padT, padB = 44, 16, 40, 60
    plotW = W - padL - padR; plotH = H - padT - padB
    allv = [x for x in (list(this_vals) + list(last_vals)) if x is not None]
    mx = max(allv) if allv else 1
    if mx <= 0: mx = 1
    yB = padT + plotH
    def Y(v): return padT + plotH * (1 - (v or 0) / mx)
    n = len(days); groupW = plotW / n; barW = groupW * 0.30; gap = groupW * 0.06
    C_THIS, C_LAST = "var(--brown)", "#d9c39a"
    P = ['<svg class="md-svg" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">' % (W, H)]
    P.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--line)"/>' % (padL, yB, W - padR, yB))
    for i, day in enumerate(days):
        cx = padL + groupW * i + groupW / 2
        tv = this_vals[i] or 0; lv = last_vals[i] or 0
        x_last = cx - barW - gap / 2; x_this = cx + gap / 2
        P.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s"/>' % (x_last, Y(lv), barW, yB - Y(lv), C_LAST))
        P.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s"/>' % (x_this, Y(tv), barW, yB - Y(tv), C_THIS))
        P.append('<text x="%.1f" y="%.1f" font-size="9.5" text-anchor="middle" fill="var(--muted)">%s</text>' % (x_last + barW / 2, Y(lv) - 4, esc(fmt_val(lv, fmt))))
        P.append('<text x="%.1f" y="%.1f" font-size="10" font-weight="700" text-anchor="middle" fill="var(--brown)">%s</text>' % (x_this + barW / 2, Y(tv) - 4, esc(fmt_val(tv, fmt))))
        yoy = (100 * (tv / lv - 1)) if lv else None
        yoytxt = ("%+.1f%%" % yoy) if yoy is not None else "n/a"
        yoycol = "var(--green)" if (yoy is not None and yoy >= 0) else "var(--red)"
        P.append('<text x="%.1f" y="%.1f" font-size="12" font-weight="700" text-anchor="middle" fill="var(--ink)">%s</text>' % (cx, yB + 18, esc(day)))
        P.append('<text x="%.1f" y="%.1f" font-size="11" font-weight="800" text-anchor="middle" fill="%s">%s</text>' % (cx, yB + 34, yoycol, yoytxt))
    ly = H - 8
    P.append('<rect x="%.1f" y="%.1f" width="11" height="11" rx="2" fill="%s"/><text x="%.1f" y="%.1f" font-size="10.5" fill="var(--muted)">This weekend (%s)</text>' % (padL, ly - 10, C_THIS, padL + 15, ly - 1, esc(label_this)))
    lx2 = padL + 200
    P.append('<rect x="%.1f" y="%.1f" width="11" height="11" rx="2" fill="%s"/><text x="%.1f" y="%.1f" font-size="10.5" fill="var(--muted)">Last year (%s)</text>' % (lx2, ly - 10, C_LAST, lx2 + 15, ly - 1, esc(label_last)))
    P.append('</svg>')
    return "".join(P)


def weekend_html(kind):
    """Fri/Sat/Sun weekend visual for the YoY detail views. kind='sales' (£) or 'tx' (transactions)."""
    wk = YOY.get("weekend")
    if not wk:
        return ""
    data = (wk.get("sales") if kind == "sales" else wk.get("tx")) or {}
    fmt = "gbp0" if kind == "sales" else "num0"
    unit = "sales" if kind == "sales" else "transactions"
    tv, lv = data.get("this"), data.get("last")
    if not tv or not lv:
        return ""
    tt = sum(x or 0 for x in tv); tl = sum(x or 0 for x in lv)
    overall = ("%+.1f%%" % (100 * (tt / tl - 1))) if tl else "n/a"
    svg = _weekend_svg(wk.get("days", ["Fri", "Sat", "Sun"]), tv, lv, fmt, wk.get("label_this", ""), wk.get("label_last", ""))
    return ('<div class="md-section-h">Last weekend &mdash; Fri / Sat / Sun %s vs last year</div>'
            '<div class="md-note">Weekend total %s vs %s the equivalent weekend last year (<b>%s</b>). '
            'Each bar pair is this year vs the same day of last year&rsquo;s weekend.</div>%s'
            % (unit, esc(fmt_val(tt, fmt)), esc(fmt_val(tl, fmt)), overall, svg))


def _yoycell(v):
    if v is None:
        return '<td><span class="tag t-na">n/a</span></td>'
    return '<td><span class="tag %s">%s%s%%</span></td>' % (("t-ok" if v >= 0 else "t-red"), ("+" if v >= 0 else ""), round(v, 1))


def yoy_bystore_html(title):
    """By-store last-week table mirroring the Company Dashboard Sales tab exactly:
    Store | Sales | YoY | Av spend | YoY | Guest counts | YoY. Sorted by last-week sales desc,
    COMPANY total row at the bottom (YoY on the like-for-like subset, as the company dashboard does)."""
    rows = YOY.get("by_store") or []
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: -(r.get("lw26") or 0))
    body = ""; A = [0, 0, 0, 0]; sl = 0; stt = 0
    for r in rows:
        lw = r.get("lw26") or 0; lw25 = r.get("lw25") or 0; t26 = r.get("tx26") or 0; t25 = r.get("tx25") or 0
        sl += lw; stt += t26
        sy = None if not lw25 else 100 * (lw / lw25 - 1)
        avs = (lw / t26) if t26 else 0
        avs25 = (lw25 / t25) if t25 else None
        ay = None if avs25 in (None, 0) else 100 * (avs / avs25 - 1)
        gy = None if not t25 else 100 * (t26 / t25 - 1)
        if lw25 > 0 and lw > 0:
            A[0] += lw; A[1] += lw25; A[2] += t26; A[3] += t25
        body += ('<tr><td>%s</td><td style="font-weight:700">£%s</td>%s<td>£%.2f</td>%s<td>%s</td>%s</tr>'
                 % (esc(r.get("store", "")), format(int(round(lw)), ","), _yoycell(sy), avs, _yoycell(ay), format(int(t26), ","), _yoycell(gy)))
    asy = 100 * (A[0] / A[1] - 1) if A[1] else None
    aavs = (sl / stt) if stt else 0
    aay = 100 * ((A[0] / A[2]) / (A[1] / A[3]) - 1) if (A[3] and A[2]) else None
    agy = 100 * (A[2] / A[3] - 1) if A[3] else None
    total = ('<tr style="border-top:2px solid var(--line)"><td style="font-weight:800">COMPANY (%d stores)</td>'
             '<td style="font-weight:800">£%s</td>%s<td style="font-weight:700">£%.2f</td>%s<td style="font-weight:700">%s</td>%s</tr>'
             % (len(rows), format(int(round(sl)), ","), _yoycell(asy), aavs, _yoycell(aay), format(int(stt), ","), _yoycell(agy)))
    return ('<div class="md-section-h">%s</div>'
            '<table class="md-ps" style="max-width:760px"><thead><tr><th>Store</th><th>Sales</th><th>YoY</th>'
            '<th>Av spend</th><th>YoY</th><th>Guest counts</th><th>YoY</th></tr></thead><tbody>%s%s</tbody></table>'
            % (esc(title), body, total))


def openclose_bystore_html():
    """Per-store open/close checklist completion for the Brand Audit tab, from openclose_feed.json
    (HRP open/close log + live Process Street status). Target >=90% green. Worst/awaiting first."""
    try:
        OC = json.load(open(os.path.join(HERE, "openclose_feed.json")))
    except Exception:
        return ""
    rows = OC.get("stores") or []
    if not rows:
        return ""
    SH = lambda x: F1_SHORT.get(x, x)
    tgt = OC.get("target", 90)
    green = red = 0
    body = ""
    for r in rows:
        st = r.get("store"); pct = r.get("pct"); on = r.get("on_checklist"); aw = r.get("awaiting")
        if pct is None or aw:
            cell = '<span class="tag t-na">awaiting first rows</span>'
        else:
            ok = pct >= tgt
            green += 1 if ok else 0; red += 0 if ok else 1
            cell = '<span class="tag %s">%d%%</span>' % ("t-ok" if ok else "t-red", round(pct))
        badge = '' if on else ' <span class="tag t-na">not yet on Process St</span>'
        body += '<tr><td class="s">%s%s</td><td class="v">%s</td></tr>' % (esc(SH(st)), badge, cell)
    return ('<div class="md-section-h">By store &mdash; open/close checklist completion</div>'
            '<div class="md-ps-basis">Daily open &amp; close checklist completion per store (target &ge;%d%% green). '
            'Two stores (Glenvale, Leamington) are on the live Process Street digital checklist; the rest run the HRP '
            'open/close log until Process Street rolls out estate-wide. Lowest first &mdash; %d green / %d red.</div>'
            '<table class="md-ps" style="max-width:540px"><thead><tr><th>Store</th>'
            '<th class="v">Completion</th></tr></thead><tbody>%s</tbody></table>'
            % (tgt, green, red, body))


def accidents_bystore_html():
    """Per-store accident/incident log for the Brand Audit tab (H&S), from accidents_feed.json
    (HRP 'Accident Forms'). Recent incidents with date + person + short description, per-store
    count. Most incidents first. Contact number / address are not carried in the feed."""
    try:
        AC = json.load(open(os.path.join(HERE, "accidents_feed.json")))
    except Exception:
        return ""
    stores = AC.get("stores") or []
    win = AC.get("window_days", 180)
    total = AC.get("total", 0)
    SH = lambda x: F1_SHORT.get(x, x)
    if not stores:
        return ('<div class="md-section-h">Accidents &amp; incidents (H&amp;S) &mdash; last %d days</div>'
                '<div class="md-ps-basis">No accidents or incidents logged in the last %d days. &#10003;</div>'
                % (win, win))
    body = ""
    for sdat in stores:
        st = sdat.get("store"); cnt = sdat.get("count", 0)
        li = ""
        for it in (sdat.get("items") or []):
            person = it.get("person") or ""
            ptxt = (" &middot; <b>%s</b>" % esc(person)) if person else ""
            fa = ' <span class="tag t-red">first aid</span>' if it.get("first_aid") else ""
            desc = esc(it.get("incident") or it.get("injury") or "incident")
            inj = it.get("injury")
            injtxt = (" (%s)" % esc(inj)) if (inj and inj != it.get("incident")) else ""
            det = it.get("details")
            dtxt = (" &mdash; %s" % esc(det)) if det else ""
            li += ('<div class="md-note" style="margin:3px 0"><b>%s</b>%s%s: %s%s%s</div>'
                   % (esc(it.get("date", "")), ptxt, fa, desc, injtxt, dtxt))
        body += ('<tr><td class="s" style="vertical-align:top">%s <span class="tag t-red">%d</span></td>'
                 '<td>%s</td></tr>' % (esc(SH(st)), cnt, li))
    return ('<div class="md-section-h">Accidents &amp; incidents (H&amp;S) &mdash; last %d days</div>'
            '<div class="md-ps-basis">Logged accidents/incidents per store from the HRP Accident Forms log '
            '(%d in total). Date, person and a short description; contact details are intentionally omitted. '
            'Most incidents first.</div>'
            '<table class="md-ps" style="max-width:780px"><thead><tr><th>Store</th>'
            '<th>Recent incidents</th></tr></thead><tbody>%s</tbody></table>'
            % (win, total, body))


def blend_detail_html():
    """Per-store Brand & Remote Assessment: brand audit (/5), remote assessment (/100), and the
    50/50 blended score (/5), from D['brand_remote']. Estate footer row. Best blended first."""
    br = D.get("brand_remote") or {}
    rows = br.get("rows") or []
    if not rows:
        return ""
    SH = lambda x: F1_SHORT.get(x, x)
    tgt = br.get("target", 4.6)
    def cell5(v):
        if v is None:
            return '<td class="v"><span class="tag t-na">n/a</span></td>'
        k = "t-ok" if v >= tgt else ("t-amber" if v >= tgt - 0.3 else "t-red")
        return '<td class="v"><span class="tag %s">%.2f</span></td>' % (k, v)
    body = ""
    for r in rows:
        b = r.get("brand"); r100 = r.get("remote100"); src = r.get("src")
        srctag = "" if src == "both" else ' <span class="tag t-na">%s only</span>' % src
        body += ('<tr><td class="s">%s%s</td><td class="v">%s</td><td class="v">%s</td>%s</tr>'
                 % (esc(SH(r.get("store", ""))), srctag,
                    ("%.2f" % b) if b is not None else "&mdash;",
                    ("%d" % round(r100)) if r100 is not None else "&mdash;",
                    cell5(r.get("blend"))))
    foot = ('<tr style="border-top:2px solid var(--line)"><td class="s" style="font-weight:800">ESTATE</td>'
            '<td class="v">%s</td><td class="v">%s</td>%s</tr>'
            % (("%.2f" % br["estate_brand"]) if br.get("estate_brand") is not None else "&mdash;",
               ("%d" % round(br["estate_remote100"])) if br.get("estate_remote100") is not None else "&mdash;",
               cell5(br.get("estate_blend"))))
    return ('<div class="md-ps-basis">Each store&rsquo;s QTD <b>brand audit</b> (/5) and <b>remote assessment</b> (/100), and the <b>50/50 blended</b> score (/5, target %.1f). A store with only one assessment this period uses that one (flagged). Best blended first.</div>'
            '<table class="md-ps" style="max-width:560px"><thead><tr><th>Store</th>'
            '<th class="v">Brand /5</th><th class="v">Remote /100</th><th class="v">Blended /5</th></tr></thead>'
            '<tbody>%s%s</tbody></table>' % (tgt, body, foot))

def google_reviews_bystore_html():
    """Per-store Google reviews: average rating + review count for the previous week and QTD,
    from reviews_feed.json (regenerated by build_reviews.py before this generator each run).
    Estate footer = review-count-weighted rating + total counts. Most QTD reviews first."""
    try:
        R = json.load(open(os.path.join(HERE, "reviews_feed.json")))
    except Exception:
        return ""
    stores = R.get("stores") or {}
    if not stores:
        return ""
    SH = lambda x: F1_SHORT.get(x, x)
    ww = R.get("_wtd_window"); qtd_lbl = R.get("_qtd_label", "QTD")
    wtd_txt = ("%s to %s" % (ww[0], ww[1])) if isinstance(ww, list) and len(ww) == 2 else "previous week"
    def rc(v):
        return ('%.2f&#9733;' % v) if isinstance(v, (int, float)) else '&mdash;'
    rows = []
    for st, d in stores.items():
        w = d.get("wtd") or {}; q = d.get("qtd") or {}
        rows.append((st, w.get("avg"), w.get("n") or 0, q.get("avg"), q.get("n") or 0))
    rows.sort(key=lambda r: (-(r[4] or 0), -(r[3] or 0)))
    body = ""
    for st, wavg, wn, qavg, qn in rows:
        body += ('<tr><td class="s">%s</td><td class="v">%s</td><td class="v">%s</td>'
                 '<td class="v">%s</td><td class="v">%s</td></tr>'
                 % (esc(SH(st)), rc(wavg), wn, rc(qavg), qn))
    wn_t = sum(r[2] for r in rows); qn_t = sum(r[4] for r in rows)
    e_w = round(sum((r[1] or 0) * r[2] for r in rows) / wn_t, 2) if wn_t else None
    e_q = round(sum((r[3] or 0) * r[4] for r in rows) / qn_t, 2) if qn_t else None
    foot = ('<tr style="border-top:2px solid var(--line)"><td class="s" style="font-weight:800">ESTATE</td>'
            '<td class="v">%s</td><td class="v">%s</td><td class="v">%s</td><td class="v">%s</td></tr>'
            % (rc(e_w), wn_t, rc(e_q), qn_t))
    return ('<div class="md-section-h">By store &mdash; Google reviews: rating &amp; count</div>'
            '<div class="md-ps-basis">Average star rating and number of reviews submitted, per store &mdash; '
            'previous week (%s) and quarter-to-date (%s). Most QTD reviews first; estate rating is review-weighted.</div>'
            '<table class="md-ps" style="max-width:620px"><thead><tr><th>Store</th>'
            '<th class="v">Rating (wk)</th><th class="v">Reviews (wk)</th>'
            '<th class="v">Rating (QTD)</th><th class="v">Reviews (QTD)</th></tr></thead>'
            '<tbody>%s%s</tbody></table>' % (esc(wtd_txt), esc(qtd_lbl), body, foot))


def weekend_bystore_html(kind):
    """Per-store weekend cut: each store's ACTUAL Fri / Sat / Sun figure (sales £ or guest checks)
    for the previous completed weekend, each with its YoY vs the equivalent day last year, plus a
    weekend total. Data (this-year actuals + last-year) already pulled into weekend_by_store."""
    wbs = YOY.get("weekend_by_store") or {}
    if not wbs:
        return ""
    SH = lambda x: F1_SHORT.get(x, x)
    is_sales = (kind == "sales")
    def fmtv(v):
        return ("£" + format(int(round(v)), ",")) if is_sales else format(int(round(v)), ",")
    def _yoy(t, l):
        return None if not l else 100 * (t / l - 1)
    def cell(t, l):
        y = _yoy(t, l)
        tag = ('<span class="tag t-na">n/a</span>' if y is None
               else '<span class="tag %s">%s%s%%</span>' % (("t-ok" if y >= 0 else "t-red"),
                                                            ("+" if y >= 0 else ""), round(y, 1)))
        return '<td class="v"><div>%s</div>%s</td>' % (fmtv(t), tag)
    items = []
    for st, v in wbs.items():
        d = v.get(kind) or {}
        tv = d.get("this") or [0, 0, 0]; lv = d.get("last") or [0, 0, 0]
        items.append((st, tv, lv, sum(tv)))
    items.sort(key=lambda x: -x[3])
    body = "".join(
        '<tr><td class="s">%s</td>%s%s</tr>' % (
            esc(SH(st)),
            "".join(cell(tv[i], lv[i]) for i in range(3)),
            cell(sum(tv), sum(lv)))
        for (st, tv, lv, _tot) in items)
    unit = "sales" if is_sales else "guest checks"
    return ('<div class="md-section-h">Weekend by store &mdash; Fri / Sat / Sun %s (actual &amp; YoY)</div>'
            '<div class="md-ps-basis">Each store&rsquo;s <b>actual</b> %s for Friday, Saturday and Sunday of the previous weekend, '
            'each with the year-on-year change vs the equivalent day last year (%s). Weekend total on the right; best weekend first.</div>'
            '<table class="md-ps" style="max-width:640px"><thead><tr><th>Store</th>'
            '<th class="v">Fri</th><th class="v">Sat</th><th class="v">Sun</th><th class="v">Weekend</th></tr></thead>'
            '<tbody>%s</tbody></table>'
            % (unit, unit, unit, body))

# ============ F1 Op's Excellence detail (mirrors the Company Dashboard 'Op's Excellence' tab) ============
# Reuses the SAME source files the company dashboard renders from — f1_detail.json (race / qualifying /
# QTD aggregates) and allstores.json['champ'] (drivers + constructors standings) — so the EOS F1 detail
# and the Company Op's Excellence tab are identical and in sync. Fully fault-tolerant: any missing or
# broken input degrades to an empty string and never breaks the EOS build. Idempotent (pure function of
# the committed JSONs). Column layout & colour thresholds are copied verbatim from gen_company.py.
F1_SHORT = {"Burton Latimer":"Burton","Corby":"Corby","Higham Ferrers":"Higham","Kettering":"Kettering","Olney":"Olney",
"Peterborough Bridge Street":"P'boro Bridge St","Peterborough Fletton Quays":"P'boro Fletton","Rothwell":"Rothwell","Rushden Lakes":"Rushden Lakes",
"Attleborough":"Attleborough","Billing Drive Thru":"Billing DT","Glenvale Drive Thru":"Glenvale DT","HOE Balsall Common":"Balsall Common",
"Leamington Parade":"Leam Parade","Lower Heathcote":"Lower Heathcote","Market Harborough":"Mkt Harborough","Northampton":"Northampton",
"Northampton Drive-Thru":"Northampton DT","Rugby":"Rugby","Wellingborough":"Wellingborough","Wellingborough Train Station":"W'boro Train Stn",
"Leam Retail":"Leam Retail"}


def backtoschool_tab():
    """Build the EOS 5th tab (Back-to-School forecast) — a tab button + a pane with a store
    dropdown (reusing the generic .stsel/.st-scope/[data-store] switcher). Estate view + a panel
    per store. Returns (button_html, pane_html). '' on any failure so the EOS build never breaks."""
    try:
        B = json.load(open(os.path.join(HERE, "backtoschool_feed.json")))
    except Exception:
        return "", ""
    est = B.get("estate") or {}
    stores = B.get("stores") or []
    if not stores:
        return "", ""
    SH = lambda x: F1_SHORT.get(x, x)
    def gbp(v):
        return ("£" + format(int(round(v)), ",")) if v is not None else "&mdash;"
    def pc(v, inv=False):
        if v is None: return '<span class="bts-nn">&mdash;</span>'
        k = ("bts-dn" if v < -3 else ("bts-up" if v > 3 else "bts-fl"))
        return '<span class="%s">%s%d%%</span>' % (k, "+" if v > 0 else "", v)
    wk = B.get("weeks", {})

    # ---- estate DOW chart ----
    dow = est.get("dow") or []
    mx = max([max(d["hol"], d["term"]) for d in dow] or [1]) or 1
    dcols = ""
    for d in dow:
        hh = max(3, round(70 * d["hol"] / mx)); th = max(3, round(70 * d["term"] / mx))
        tk = "bts-bt-up" if d["pct"] > 3 else ("bts-bt-dn" if d["pct"] < -3 else "bts-bt-fl")
        dcin = "bts-up" if d["pct"] > 3 else ("bts-dn" if d["pct"] < -3 else "bts-fl")
        dcols += ('<div class="bts-dcol"><div class="bts-bars"><span class="bts-bh" style="height:%dpx" title="hol %s"></span>'
                  '<span class="bts-bt %s" style="height:%dpx" title="term %s"></span></div>'
                  '<div class="bts-dl">%s</div><div class="bts-dc %s">%s%d%%</div></div>'
                  % (hh, gbp(d["hol"]), tk, th, gbp(d["term"]), d["day"], dcin, "+" if d["pct"] > 0 else "", d["pct"]))
    dow_html = ('<div class="bts-h3">The weekday &rarr; weekend shift (estate)</div>'
                '<div class="bts-hs">Average day&rsquo;s sales &mdash; school holidays vs term-time (2025). Term hollows out Mon&ndash;Thu and pushes the peak onto Sat/Sun.</div>'
                '<div class="bts-dowwrap"><div class="bts-dowrow">' + dcols + '</div>'
                '<div class="bts-legend"><span class="bts-swh"></span> holidays &nbsp; <span class="bts-swt"></span> term-time &nbsp;&middot;&nbsp; %% = term vs holiday for that day &nbsp;&middot;&nbsp; weekend share of week %d%% &rarr; %d%%</div></div>'
                % (est.get("weekend_share_hol", 0), est.get("weekend_share_term", 0)))

    # ---- week cards (estate framing, reused per store with store £) ----
    def week_cards(pk, tr, se, pk_se=None):
        note1 = "Kids still off · trade spread across the whole week · staff &amp; stock UP"
        note2 = "<b>Term-time from Wed 2 Sep.</b> Mon 31 (bank hol) + Tue 1 (INSET) trade holiday-like; kids back Wed"
        note3 = "Weekdays fully quiet · peak now on Fri&ndash;Sun · scale midweek back to this"
        extra = (' &middot; Pk&rarr;Settled ' + pc(pk_se)) if pk_se is not None else ''
        return ('<div class="bts-win">'
                '<div class="bts-wk bts-peak"><div class="bts-l">&#9312; Peak &mdash; last holiday week</div><div class="bts-d">%s</div><div class="bts-v">%s</div><div class="bts-n">%s</div></div>'
                '<div class="bts-wk bts-back"><div class="bts-l">&#9313; Transition week</div><div class="bts-d">%s</div><div class="bts-v">%s</div><div class="bts-n">%s</div></div>'
                '<div class="bts-wk bts-settle"><div class="bts-l">&#9314; Settled &mdash; first full term week</div><div class="bts-d">%s</div><div class="bts-v">%s</div><div class="bts-n">%s%s</div></div>'
                '</div>' % (wk.get("peak",""), gbp(pk), note1, wk.get("transition",""), gbp(tr), note2,
                            wk.get("settled",""), gbp(se), note3, extra))

    # ---- estate KPIs ----
    kpis = ('<div class="bts-kpis">'
            '<div class="bts-kpi"><div class="bts-kl">Estate peak week (fcast)</div><div class="bts-kv">%s</div><div class="bts-ks">last full holiday week</div></div>'
            '<div class="bts-kpi"><div class="bts-kl">Term-time weekday</div><div class="bts-kv bts-dn">%d%%</div><div class="bts-ks">Mon&ndash;Thu, holiday &rarr; term</div></div>'
            '<div class="bts-kpi"><div class="bts-kl">Term-time weekend</div><div class="bts-kv bts-up">+%d%%</div><div class="bts-ks">Sat &amp; Sun vs holidays</div></div>'
            '<div class="bts-kpi"><div class="bts-kl">Weekend share of week</div><div class="bts-kv">%d%% &rarr; %d%%</div><div class="bts-ks">holiday &rarr; term (Fri&ndash;Sun)</div></div>'
            '</div>' % (gbp(est.get("peak")), est.get("weekday_pct",0), est.get("weekend_pct",0),
                        est.get("weekend_share_hol",0), est.get("weekend_share_term",0)))

    # ---- per-store forecast table (estate view) ----
    rows = ""
    for s in stores:
        newb = ' <span class="bts-new">new</span>' if s.get("new") else ''
        if s.get("wk_share_hol") is not None:
            ws = '%d%%&rarr;%d%% <b class="%s">(%+dpp)</b>' % (s["wk_share_hol"], s["wk_share_term"],
                 "bts-wkend" if s["wk_share_pp"] >= 0 else "bts-wkday", s["wk_share_pp"])
        else:
            ws = '<span class="bts-nn">&mdash;</span>'
        food = ('%s / %s / %s' % (s["food_peak"], s["food_trans"], s["food_settled"])) if s.get("food_peak") is not None else '<span class="bts-nn">&mdash;</span>'
        rows += ('<tr><td class="bts-st">%s%s</td><td class="bts-num bts-pk">%s</td><td class="bts-num">%s</td>'
                 '<td class="bts-num">%s</td><td class="bts-num">%s</td><td class="bts-ws">%s</td><td class="bts-fd">%s</td></tr>'
                 % (esc(SH(s["store"])), newb, gbp(s["peak"]), gbp(s["trans"]), gbp(s["settled"]),
                    pc(s.get("pk_settled_pct")), ws, food))
    store_table = ('<div class="bts-h3">Per-store &mdash; forecast &amp; the weekend shift</div>'
                   '<div class="bts-hs">Forecast weeks (&pound;) + how each store&rsquo;s mix moves to the weekend once term&rsquo;s back. <b>+pp</b> = shifts to Fri&ndash;Sun (pull midweek down); <b>&minus;pp</b> = stays weekday-led.</div>'
                   '<table class="bts-t"><thead><tr><th class="l">Store</th><th>Peak wk</th><th>Transition</th><th>Settled</th><th>Pk&rarr;Settled</th><th class="l">Weekend share hol&rarr;term</th><th class="l">Food P/B/S</th></tr></thead><tbody>'
                   + rows + '</tbody></table>')

    # ---- estate food lines ----
    fl = est.get("food_lines") or []
    frows = ""
    for r in fl:
        frows += ('<tr><td class="l">%s</td><td class="bts-cat">%s</td><td class="bts-num">%s</td><td class="bts-num">%s</td><td class="bts-num">%s</td><td class="bts-num">%s</td></tr>'
                  % (esc(r["item"]), esc(r["cat"]), r["peak"], r["trans"], r["settled"], pc(r["pct"])))
    idx = est.get("food_index_peak"); idxs = est.get("food_index_settled")
    food_table = ('<div class="bts-h3">Food usage &mdash; order lighter midweek, keep weekends stocked</div>'
                  '<div class="bts-hs">Food &amp; bakery volume follows the same weekly reshape: lighter Mon&ndash;Thu, hold Fri&ndash;Sun in term. Estate food seasonal index: peak %s &middot; settled %s (normal week = 1.00).</div>'
                  '<table class="bts-t"><thead><tr><th class="l">Line</th><th class="l">Category</th><th>Peak wk</th><th>Transition</th><th>Settled</th><th>Change</th></tr></thead><tbody>'
                  % (idx, idxs) + frows + '</tbody></table>')

    method = ('<div class="bts-note"><b>Method &amp; caveats.</b> Actuals from BigQuery <code>v_sales_details_flat</code>. '
              '2026 forecast = 2025 same-week actual &times; each store&rsquo;s recent 8-week YoY (capped 0.85&ndash;1.25). '
              'Weekday/weekend profile compares 3 holiday weeks (11&ndash;31 Aug 2025) with 3 term weeks (8&ndash;28 Sep 2025); weekend = Fri&ndash;Sun. '
              'Schools return <b>Wed 2 Sep 2026</b> &mdash; Mon 31 Aug (bank hol) &amp; Tue 1 Sep (INSET) still trade holiday-like, so the transition week is a hybrid. '
              'New stores (Billing DT, Attleborough, Olney) have no 2025 history &mdash; sales estimated from run-rate &times; estate seasonal shape; weekend-shift &amp; food not shown for them.</div>')

    est_trans = sum(s.get("trans") or 0 for s in stores)
    est_settled = sum(s.get("settled") or 0 for s in stores)
    estate_panel = ('<div class="bts-panel" data-store="estate" style="display:block">'
                    + week_cards(est.get("peak"), est_trans, est_settled)
                    + kpis + dow_html + store_table + food_table + method + '</div>')

    # ---- per-store panels ----
    def store_panel(s):
        newb = ' <span class="bts-new">new store</span>' if s.get("new") else ''
        if s.get("wk_share_hol") is not None:
            shift = ('<div class="bts-shift"><div class="bts-sh1">Weekend reshape (holiday &rarr; term)</div>'
                     '<div class="bts-shrow"><div><div class="bts-shk">Weekend share</div><div class="bts-shv">%d%% &rarr; %d%% <b class="%s">(%+dpp)</b></div></div>'
                     '<div><div class="bts-shk">Weekday Mon&ndash;Thu</div><div class="bts-shv">%s</div></div>'
                     '<div><div class="bts-shk">Weekend Fri&ndash;Sun</div><div class="bts-shv">%s</div></div></div>'
                     '<div class="bts-shn">%s</div></div>'
                     % (s["wk_share_hol"], s["wk_share_term"], "bts-wkend" if s["wk_share_pp"]>=0 else "bts-wkday", s["wk_share_pp"],
                        pc(s.get("weekday_delta")), pc(s.get("weekend_delta")),
                        ("Destination/retail-park pattern &mdash; cut Mon&ndash;Thu hours &amp; perishable orders, protect Fri&ndash;Sun cover &amp; stock." if (s["wk_share_pp"] or 0) >= 4
                         else ("Office/commuter pattern &mdash; midweek firms up in term, keep weekday cover." if (s["wk_share_pp"] or 0) < 0
                               else "Modest shift to the weekend &mdash; trim midweek gently, hold Fri&ndash;Sun."))))
        else:
            shift = '<div class="bts-shift"><div class="bts-shn">Weekend-shift not available (new store &mdash; no 2025 history).</div></div>'
        if s.get("food_peak") is not None:
            food = ('<div class="bts-foodline"><b>Food &amp; bakery units (forecast):</b> Peak <b>%s</b> &middot; Transition <b>%s</b> &middot; Settled <b>%s</b> '
                    '&mdash; order close to peak for the holiday week, then trim midweek deliveries from Wed 2 Sep and hold weekend stock.</div>'
                    % (s["food_peak"], s["food_trans"], s["food_settled"]))
        else:
            food = '<div class="bts-foodline"><b>Food &amp; bakery:</b> per-store forecast not available (new store).</div>'
        return ('<div class="bts-panel" data-store="%s" style="display:none">'
                '<div class="bts-storehd">%s%s</div>'
                % (esc(s["store"]), esc(SH(s["store"])), newb)
                + week_cards(s.get("peak"), s.get("trans"), s.get("settled"), s.get("pk_settled_pct"))
                + shift + food
                + '<div class="bts-note">Forecast = this store&rsquo;s 2025 same-week actuals &times; its capped recent-8wk YoY. The estate weekday&rarr;weekend chart on the <b>All stores</b> view shows the wider pattern.</div>'
                + '</div>')
    store_panels = "".join(store_panel(s) for s in stores)

    opts = '<option value="estate" selected>All stores (estate)</option>' + "".join(
        '<option value="%s">%s%s</option>' % (esc(s["store"]), esc(SH(s["store"])), " (new)" if s.get("new") else "")
        for s in stores)

    STYLE = ("<style>"
     "#pane-backtoschool .bts-sub{color:var(--muted);font-size:13px;line-height:1.55;margin:2px 0 14px;max-width:900px}"
     "#pane-backtoschool .bts-selbar{display:flex;align-items:center;gap:10px;margin:4px 0 16px}"
     "#pane-backtoschool .bts-selbar label{font-size:11px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);font-weight:800}"
     "#pane-backtoschool .stsel{font:inherit;font-size:14px;font-weight:800;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 14px;min-width:280px;cursor:pointer}"
     "#pane-backtoschool .bts-win{display:flex;gap:12px;flex-wrap:wrap;margin:6px 0 14px}"
     "#pane-backtoschool .bts-wk{flex:1;min-width:220px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}"
     "#pane-backtoschool .bts-wk .bts-l{font-size:10px;letter-spacing:.8px;text-transform:uppercase;color:var(--muted);font-weight:800}"
     "#pane-backtoschool .bts-wk .bts-d{font-size:14px;font-weight:800;margin-top:3px}"
     "#pane-backtoschool .bts-wk .bts-v{font-size:22px;font-weight:800;margin:4px 0 2px}"
     "#pane-backtoschool .bts-wk .bts-n{font-size:11px;color:var(--muted);line-height:1.4}"
     "#pane-backtoschool .bts-peak{border-top:3px solid var(--green)} #pane-backtoschool .bts-back{border-top:3px solid var(--gold)} #pane-backtoschool .bts-settle{border-top:3px solid var(--red)}"
     "#pane-backtoschool .bts-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:6px 0 16px}"
     "#pane-backtoschool .bts-kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px}"
     "#pane-backtoschool .bts-kl{font-size:10.5px;letter-spacing:.4px;text-transform:uppercase;color:var(--muted);font-weight:800}"
     "#pane-backtoschool .bts-kv{font-size:22px;font-weight:800;margin-top:5px} #pane-backtoschool .bts-ks{font-size:11px;color:var(--muted);margin-top:3px}"
     "#pane-backtoschool .bts-h3{font-size:15px;font-weight:800;margin:22px 0 3px;color:var(--ink)}"
     "#pane-backtoschool .bts-hs{font-size:12px;color:var(--muted);margin-bottom:9px;line-height:1.5}"
     "#pane-backtoschool table.bts-t{width:100%;border-collapse:separate;border-spacing:0;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:12.5px}"
     "#pane-backtoschool .bts-t thead th{font-size:10px;letter-spacing:.4px;text-transform:uppercase;color:var(--muted);font-weight:800;text-align:right;padding:9px 8px;background:var(--greybg);border-bottom:1px solid var(--line);white-space:nowrap}"
     "#pane-backtoschool .bts-t thead th.l{text-align:left}"
     "#pane-backtoschool .bts-t tbody td{padding:8px;border-bottom:1px solid #eef1f5;text-align:right;white-space:nowrap} #pane-backtoschool .bts-t tbody tr:last-child td{border-bottom:none}"
     "#pane-backtoschool .bts-st{text-align:left;font-weight:800} #pane-backtoschool .bts-fd,#pane-backtoschool .bts-ws{text-align:left;color:#4a4038;font-size:11.5px} #pane-backtoschool .bts-cat{text-align:left;color:var(--muted);font-size:11px} #pane-backtoschool td.l{text-align:left}"
     "#pane-backtoschool .bts-num{font-variant-numeric:tabular-nums} #pane-backtoschool .bts-pk{font-weight:800}"
     "#pane-backtoschool .bts-up{color:var(--green);font-weight:800} #pane-backtoschool .bts-dn{color:var(--red);font-weight:800} #pane-backtoschool .bts-fl{color:var(--muted);font-weight:800} #pane-backtoschool .bts-nn{color:var(--muted)}"
     "#pane-backtoschool .bts-wkend{color:var(--green)} #pane-backtoschool .bts-wkday{color:#7a5cff}"
     "#pane-backtoschool .bts-new{font-size:9px;background:var(--cream);color:var(--brown);border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-weight:800}"
     "#pane-backtoschool .bts-note{font-size:11.5px;color:var(--muted);line-height:1.6;margin-top:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 15px} #pane-backtoschool .bts-note b{color:var(--ink)} #pane-backtoschool code{background:var(--greybg);padding:1px 4px;border-radius:4px;font-size:11px}"
     "#pane-backtoschool .bts-dowwrap{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:15px 18px}"
     "#pane-backtoschool .bts-dowrow{display:flex;align-items:flex-end;gap:12px;justify-content:space-between;padding:6px 4px 0}"
     "#pane-backtoschool .bts-dcol{flex:1;text-align:center} #pane-backtoschool .bts-bars{display:flex;gap:3px;align-items:flex-end;justify-content:center;height:74px}"
     "#pane-backtoschool .bts-bh{width:15px;background:#c9bdae;border-radius:3px 3px 0 0} #pane-backtoschool .bts-bt{width:15px;border-radius:3px 3px 0 0} #pane-backtoschool .bts-bt-up{background:var(--green)} #pane-backtoschool .bts-bt-dn{background:var(--red)} #pane-backtoschool .bts-bt-fl{background:var(--gold)}"
     "#pane-backtoschool .bts-dl{font-size:11px;font-weight:800;margin-top:5px} #pane-backtoschool .bts-dc{font-size:10.5px;font-weight:800}"
     "#pane-backtoschool .bts-legend{font-size:11px;color:var(--muted);margin-top:8px} #pane-backtoschool .bts-swh{display:inline-block;width:10px;height:10px;background:#c9bdae;border-radius:2px;vertical-align:middle} #pane-backtoschool .bts-swt{display:inline-block;width:10px;height:10px;background:var(--green);border-radius:2px;vertical-align:middle}"
     "#pane-backtoschool .bts-storehd{font-size:19px;font-weight:800;margin:2px 0 10px}"
     "#pane-backtoschool .bts-shift{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:4px 0 12px}"
     "#pane-backtoschool .bts-sh1{font-size:12px;letter-spacing:.4px;text-transform:uppercase;color:var(--muted);font-weight:800;margin-bottom:8px}"
     "#pane-backtoschool .bts-shrow{display:flex;gap:26px;flex-wrap:wrap} #pane-backtoschool .bts-shk{font-size:10.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);font-weight:800} #pane-backtoschool .bts-shv{font-size:18px;font-weight:800;margin-top:3px}"
     "#pane-backtoschool .bts-shn{font-size:11.5px;color:var(--muted);margin-top:9px;line-height:1.5}"
     "#pane-backtoschool .bts-foodline{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 15px;font-size:12.5px;color:#4a4038;line-height:1.5} #pane-backtoschool .bts-foodline b{color:var(--ink)}"
     "</style>")

    pane = ('\n  <section class="pane" id="pane-backtoschool">\n'
            + STYLE
            + '<div class="bts-sub">The end-of-summer peak, the back-to-school fall-away, and how trade <b>reconcentrates onto the weekend</b> once term restarts. '
              'Built from BigQuery 2025 actuals scaled by each store&rsquo;s recent year-on-year trend. Schools return <b>Wednesday 2 September 2026</b>. '
              'Generated ' + esc(B.get("_generated","")) + '.</div>'
            + '<div class="st-scope"><div class="bts-selbar"><label>Store</label><select class="stsel">' + opts + '</select></div>'
            + estate_panel + store_panels
            + '</div>\n  </section>\n')

    button = '<button class="tab" data-pane="backtoschool">Back to School <span class="cnt">forecast</span></button>'
    return button, pane


def f1_ops_html():
    """Build the F1 'Op's Excellence' presentation for the EOS metric-detail view, mirroring the
    Company Dashboard tab. Returns '' on any failure so the EOS build is never broken."""
    try:
        F1D = json.load(open(os.path.join(HERE, "f1_detail.json")))
        champ = json.load(open(os.path.join(HERE, "allstores.json"))).get("champ", {}) or {}
    except Exception:
        return ""
    from statistics import mean
    def SH(s): return F1_SHORT.get(s, s)
    def tag(t, k): return '<span class="tag %s">%s</span>' % (k, t)
    def cls(v, g, a, rev=False):
        if v is None: return "t-na"
        if rev: return "t-ok" if v <= g else ("t-amber" if v <= a else "t-red")
        return "t-ok" if v >= g else ("t-amber" if v >= a else "t-red")
    def _iscomp(s): return isinstance(F1D.get(s), dict) and F1D[s].get('comp')
    def _nm(s): return SH(s) + (' <span class="tag t-na">benchmark</span>' if _iscomp(s) else '')
    def _rs(s): return ' style="background:#f6efe7;color:#8a7a6d"' if _iscomp(s) else ''
    def _hosp(x):
        try: v = float(x)
        except Exception: return tag("n/a", "t-na")
        p = round(v * 100); k = "t-ok" if v >= 1 else ("t-amber" if v >= 0.5 else "t-red"); return tag("%d%%" % p, k)
    def _q(x):
        try: v = float(x)
        except Exception: return tag("n/a", "t-na")
        k = "t-ok" if v <= 180 else ("t-amber" if v <= 300 else "t-red"); return tag("%ds" % int(round(v)), k)
    def _rk(x):
        try: v = int(float(x))
        except Exception: return tag(str(x), "t-na")
        k = "t-ok" if v <= 6 else ("t-amber" if v <= 15 else "t-red"); return tag(str(v), k)
    def _scrag(x):
        try: v = float(x)
        except Exception: return tag(str(x), "t-na")
        return tag(("%g" % v), cls(v, 210, 285, rev=True))
    def _qcallpct(x):
        if x is None: return tag("n/a", "t-na")
        k = "t-ok" if x >= 75 else ("t-amber" if x >= 50 else "t-red"); return tag("%d%%" % int(round(x)), k)
    def _na(): return tag("n/a", "t-na")
    def _greet(x):
        if x is None: return _na()
        k = "t-ok" if x >= 90 else ("t-amber" if x >= 70 else "t-red"); return tag("%d%%" % int(round(x)), k)

    stores = [s for s in F1D if not str(s).startswith('_') and isinstance(F1D[s], dict)
              and F1D[s].get('race') and not _iscomp(s)]
    if not stores:
        return ""
    def fin(s): return F1D[s]['race'][7]
    def cpts(s): return F1D[s]['race'][6]
    def scr(s): return F1D[s]['race'][5]

    avg_fin = round(mean([fin(s) for s in stores]), 1)
    champ_avg = round(mean([cpts(s) for s in stores]), 1)
    bestf = sorted(stores, key=lambda x: fin(x)); worstf = bestf[::-1]
    f1_top = "%s P%s" % (SH(bestf[0]), int(fin(bestf[0])))
    f1_top_meta = ("%s P%s next" % (SH(bestf[1]), int(fin(bestf[1])))) if len(bestf) > 1 else ""

    _qoq = champ.get("f1_qoq", {}) or {}
    _ql = champ.get("f1_qoq_labels", {}) or {}
    def _qpc(v): return "&mdash;" if v is None else ("%g%%" % v)
    def _qar(a, b): return "" if (a is None or b is None) else (" &#9650;" if a > b else (" &#9660;" if a < b else " &#9644;"))
    ql3 = esc(_ql.get("q3", "Q3")); ql2 = esc(_ql.get("q2", "Q2"))
    cards = ('<div class="f1cards">'
             '<div class="f1card"><div class="lbl">Avg Queue Worked</div><div class="val">%s</div><div class="meta">%s &middot; vs %s %s%s</div></div>'
             '<div class="f1card"><div class="lbl">Avg Greet / Goodbye</div><div class="val">%s</div><div class="meta">%s &middot; vs %s %s%s</div></div>'
             '<div class="f1card"><div class="lbl">Top of the grid</div><div class="val" style="color:var(--green)">%s</div><div class="meta">%s</div></div>'
             '</div>' % (_qpc(_qoq.get("qw_q3")), ql3, _qpc(_qoq.get("qw_q2")), ql2, _qar(_qoq.get("qw_q3"), _qoq.get("qw_q2")),
                         _qpc(_qoq.get("gg_q3")), ql3, _qpc(_qoq.get("gg_q2")), ql2, _qar(_qoq.get("gg_q3"), _qoq.get("gg_q2")),
                         f1_top, f1_top_meta))
    intro = ('<div class="f1note"><b>How F1 works.</b> Stores are audited unannounced weekly. Each Area '
             'Coach is a <b>constructor</b>; their stores are the drivers (Jon, Ian &amp; Rich across %d stores). '
             'Field of ~25 includes competitor benchmark audits.</div>' % len(stores))

    # ---- Constructors' Championship + Drivers' leaderboard ----
    cons = sorted(champ.get('cons', []), key=lambda x: -x[3])
    con_html = ""; con_note = ""
    if cons:
        maxavg = max(c[3] for c in cons) or 1
        for i, c in enumerate(cons):
            cc, total, nst, avg = c; w = round(100 * avg / maxavg)
            con_html += ('<div class="crow"><div class="crank">%d</div><div class="cbody"><div class="cname">%s</div>'
                         '<div class="cbar"><i style="width:%d%%"></i></div><div class="csub">%s pts total &middot; %s stores</div></div>'
                         '<div class="cval">%s<small>pts/store</small></div></div>'
                         % (i + 1, cc, w, total, nst, avg))
        leadc = cons[0]
        con_note = ("Constructors&rsquo; Championship across all three areas &mdash; <b>%s</b> leads on %s pts/store. "
                    "Every weekend finish lifts a constructor&rsquo;s average; the bottom-third stores are where the title is won."
                    % (leadc[0], leadc[3]))
    COACHCHIP = {"Jon": "t-ok", "Rich": "t-amber", "Ian": "t-amber"}
    drv_rows = ""
    for i, row in enumerate(champ.get('drivers', [])):
        stn, cc, pts = row[0], row[1], row[2]
        drv_rows += ('<tr><td>%d</td><td class="l">%s</td><td>%s</td><td style="font-weight:700">%s</td></tr>'
                     % (i + 1, stn, tag(cc, COACHCHIP.get(cc, "t-na")), pts))
    champ_block = ('<div class="f1sub">&#127942; Constructors&rsquo; Championship <span class="mini">&middot; avg points/store &middot; this quarter</span></div>'
                   '<div class="f1grid2">'
                   '<div class="f1panel"><div class="f1ph">Constructors&rsquo; standings <span class="mini">&middot; area coaches by avg pts/store</span></div>%s<div class="mini" style="margin-top:9px">%s</div></div>'
                   '<div class="f1panel"><div class="f1ph">Drivers&rsquo; leaderboard <span class="mini">&middot; all stores by total pts</span></div>'
                   '<table class="f1t"><thead><tr><th>#</th><th class="l">Store (driver)</th><th>Coach</th><th>Pts</th></tr></thead><tbody>%s</tbody></table></div>'
                   '</div>' % (con_html, con_note, drv_rows))

    # ---- Constructors' Championship — QUARTER TO DATE (Option A: resets each quarter, visualised, always on) ----
    cons_s = sorted(champ.get('cons_qtd', []) or [], key=lambda x: -x[3])
    _cons_season_sorted = sorted(champ.get('cons_season', []) or [], key=lambda x: -x[3])
    season_cons_block = ""
    if cons_s:
        _qf = champ.get('qtd_from')
        try:
            _qflab = dt.date.fromisoformat(_qf).strftime('%-d %b %Y') if _qf else ''
        except Exception:
            _qflab = _qf or ''
        maxavg = max(c[3] for c in cons_s) or 1
        rowsh = ""
        MED = ["#e7b35a", "#b8b8be", "#c8925a"]
        for i, c in enumerate(cons_s):
            cc, total, nst, avg = c; w = round(100 * avg / maxavg)
            barcol = MED[i] if i < 3 else "var(--brown)"
            rowsh += ('<div class="crow"><div class="crank">%d</div><div class="cbody">'
                      '<div class="cname">%s</div><div class="cbar"><i style="width:%d%%;background:%s"></i></div>'
                      '<div class="csub">%s pts total &middot; %s stores</div></div>'
                      '<div class="cval">%s<small>pts/store</small></div></div>'
                      % (i + 1, esc(cc), w, barcol, total, nst, avg))
        _seasftr = ""
        if _cons_season_sorted:
            _seasftr = (' Season-to-date (since 10 Apr), <b>%s</b> leads on %s pts/store.'
                        % (esc(_cons_season_sorted[0][0]), _cons_season_sorted[0][3]))
        season_cons_block = (
            '<div class="f1sub">&#127942; Constructors&rsquo; Championship <span class="mini">&middot; QUARTER TO DATE &middot; avg points per store'
            + ((' &middot; since %s' % esc(_qflab)) if _qflab else '') + '</span></div>'
            '<div class="f1panel"><div class="f1ph">Area-coach constructors &mdash; quarter-to-date standings <span class="mini">&middot; ranked by average championship points per store</span></div>'
            + rowsh +
            '<div class="mini" style="margin-top:9px">Resets each quarter &mdash; only this quarter&rsquo;s weekend races count. '
            '<b>%s</b> leads the constructors&rsquo; title on %s pts/store.%s</div></div>'
            % (esc(cons_s[0][0]), cons_s[0][3], _seasftr))

    # ---- Drivers' Championship — SEASON TO DATE (stores as drivers; reconciles to constructors) ----
    drv_s = list(champ.get('drivers_qtd', []) or [])
    _drv_season = list(champ.get('drivers_season', []) or [])
    season_drv_block = ""
    if drv_s:
        _sf2 = champ.get('qtd_from')
        try:
            _sflab2 = dt.date.fromisoformat(_sf2).strftime('%-d %b %Y') if _sf2 else ''
        except Exception:
            _sflab2 = _sf2 or ''
        maxpts = max((r[2] for r in drv_s), default=0) or 1
        leadpts = drv_s[0][2]
        maxraces = max((r[3] for r in drv_s), default=0) or 0
        MED2 = ["#e7b35a", "#b8b8be", "#c8925a"]
        COACHCHIP2 = {"Jon": "t-ok", "Rich": "t-amber", "Ian": "t-amber"}
        rowsd = ""; any_partial = False
        for i, r in enumerate(drv_s):
            stn, cc, pts, nraces = r[0], r[1], r[2], (r[3] if len(r) > 3 else None)
            fr = r[4] if len(r) > 4 else None
            w = round(100 * pts / maxpts)
            barcol = MED2[i] if i < 3 else "var(--brown)"
            gap = "leader" if i == 0 else ("&minus;%d to leader" % (leadpts - pts))
            # partial season = store joined the grid materially after season start (new store),
            # so its lower points reflect fewer audited races, not weaker performance.
            partial = False
            _sfr = champ.get('qtd_from')
            if fr and _sfr:
                try: partial = (dt.date.fromisoformat(fr) - dt.date.fromisoformat(_sfr)).days > 21
                except Exception: partial = False
            if nraces is not None and maxraces and nraces < 0.6 * maxraces:
                partial = True
            if partial: any_partial = True
            racetxt = ("%s races" % nraces) if nraces is not None else ""
            ptag = ' <span class="tag t-na">partial season</span>' if partial else ''
            chip = '<span class="tag %s">%s</span>' % (COACHCHIP2.get(cc, "t-na"), esc(cc))
            rowsd += ('<div class="crow"><div class="crank">%d</div><div class="cbody">'
                      '<div class="cname">%s &nbsp;%s%s</div>'
                      '<div class="cbar"><i style="width:%d%%;background:%s"></i></div>'
                      '<div class="csub">%s pts &middot; %s &middot; %s</div></div>'
                      '<div class="cval">%s<small>pts</small></div></div>'
                      % (i + 1, esc(SH(stn)), chip, ptag, w, barcol, pts, racetxt, gap, pts))
        note_extra = (' Stores flagged <b>partial season</b> joined the grid mid-season (fewer audited races) &mdash; ranked on points earned, not pro-rated.'
                      if any_partial else '')
        _seasdrv = ""
        if _drv_season:
            _dss = sorted(_drv_season, key=lambda x: -x[2])
            _seasdrv = (' Season-to-date (since 10 Apr), <b>%s</b> leads on %s pts.'
                        % (esc(SH(_dss[0][0])), _dss[0][2]))
        season_drv_block = (
            '<div class="f1sub">&#127942; Drivers&rsquo; Championship <span class="mini">&middot; QUARTER TO DATE &middot; championship points by store'
            + ((' &middot; since %s' % esc(_sflab2)) if _sflab2 else '') + '</span></div>'
            '<div class="f1panel"><div class="f1ph">Stores as drivers &mdash; quarter-to-date standings <span class="mini">&middot; ranked by total championship points</span></div>'
            + rowsd +
            '<div class="mini" style="margin-top:9px"><b>%s</b> leads the drivers&rsquo; title on %s pts this quarter. '
            'Each driver&rsquo;s points roll up into their Area Coach&rsquo;s constructor total above (the two reconcile exactly).%s%s</div></div>'
            % (esc(SH(drv_s[0][0])), drv_s[0][2], note_extra, _seasdrv))

    # ---- FULL RACE BREAKDOWN: every scored section, per store + estate (visualised) ----
    _rsec = F1D.get("_race_sections") or {}
    breakdown_block = ""
    if _rsec and _rsec.get("order"):
        order = _rsec["order"]; mx = _rsec.get("maxpoints", {}); est = _rsec.get("estate", {})
        def _ach(pen, m):        # penalty -> achievement % (higher = better)
            if pen is None or not m: return None
            return max(0, min(100, round(100 * (1 - pen / m))))
        def _acls(a):            # colour by achievement %
            if a is None: return "t-na"
            return "t-ok" if a >= 85 else ("t-amber" if a >= 65 else "t-red")
        # estate bars
        ebars = ""
        for lab in order:
            m = mx.get(lab); pen = est.get(lab); a = _ach(pen, m)
            k = _acls(a); col = {"t-ok": "var(--green)", "t-amber": "#c8912f", "t-red": "var(--red)", "t-na": "#c9bdae"}[k]
            aw = a if a is not None else 0
            pv = ("%.1f" % pen) if pen is not None else "&mdash;"
            av = ("%d%%" % a) if a is not None else "n/a"
            ebars += ('<div class="crow"><div class="cbody"><div class="cname" style="font-size:12.5px">%s</div>'
                      '<div class="cbar"><i style="width:%d%%;background:%s"></i></div>'
                      '<div class="csub">%s achieved &middot; avg %s / %g penalty pts</div></div>'
                      '<div class="cval" style="min-width:52px">%s</div></div>'
                      % (esc(lab), aw, col, av, pv, m or 0, av))
        # per-store heatmap (best Total score first)
        bstores = [x for x in sorted(stores, key=lambda z: fin(z))]
        head = "".join('<th class="mini" style="writing-mode:vertical-rl;transform:rotate(180deg);height:96px;padding:4px 2px">%s</th>' % esc(l) for l in order)
        body = ""
        for st in sorted(stores, key=lambda z: (F1D[z].get('race_qtd') or {}).get('score') or 999):
            sec = (F1D[st].get("sections") or {})
            cells = ""
            for lab in order:
                a = _ach(sec.get(lab), mx.get(lab))
                cells += '<td>%s</td>' % tag(("%d%%" % a) if a is not None else "n/a", _acls(a))
            body += '<tr><td class="l">%s</td>%s</tr>' % (esc(SH(st)), cells)
        breakdown_block = (
            '<div class="f1sub">Full race breakdown <span class="mini">&middot; every scored section &middot; quarter-to-date</span></div>'
            '<div class="f1panel"><div class="f1ph">Estate average by section <span class="mini">&middot; % of full marks achieved (longer/greener = better)</span></div>'
            + ebars +
            '<div class="f1ph" style="margin-top:14px">By store &amp; section <span class="mini">&middot; % of full marks per section &middot; best Total Score first</span></div>'
            '<div style="overflow-x:auto"><table class="f1t"><thead><tr><th class="l">Store</th>' + head + '</tr></thead><tbody>'
            + body +
            '</tbody></table></div>'
            '<div class="mini" style="margin-top:9px">Each section is scored as penalty points that roll into the Total Score (0 = full marks). '
            'Shown here as <b>% of full marks achieved</b> so higher &amp; greener = better. '
            'Greetings (Hello/Goodbye/How-are-you/Working-the-queue) are marked out of 25; the operational sections '
            '(Food &amp; syrups, Tables &lt;3 mins, Tables brand standard, Virtual section plan, No late team) out of 31.25. '
            'This is where you can see, section by section, where the estate and each store win and lose.</div></div>')

    # ---- Latest race finish by store (finish / champ pts / score / last-6 sparkline) ----
    f1tbl = ""
    for s in sorted(stores, key=lambda x: fin(x)):
        last6 = F1D[s].get('last6', []) or []
        spk = "".join('<span class="spk" style="height:%dpx" title="P%s"></span>'
                      % (max(2, round((26 - int(p)) / 26 * 18)), p) for p in last6)
        _sc = scr(s)
        f1tbl += ('<tr><td class="l">%s</td><td>%s</td><td>%s</td><td>%s</td><td class="l"><span class="spkwrap">%s</span></td></tr>'
                  % (s, tag("P" + str(fin(s)), cls(fin(s), 6, 15, rev=True)),
                     cpts(s), tag(("%g" % _sc) if _sc is not None else "n/a", cls(_sc, 210, 285, rev=True)), spk))
    finish_block = ('<div class="f1sub">Latest race finish by store <span class="mini">&middot; lower is better</span></div>'
                    '<div class="f1panel"><table class="f1t"><thead><tr><th class="l">Store</th><th>Finish</th><th>Champ pts</th><th>Score</th><th class="l">Last 6 races</th></tr></thead><tbody>%s</tbody></table>'
                    '<div class="mini" style="margin-top:9px"><b>Race Total Score benchmark</b> (lower = better): '
                    '<span style="color:var(--green);font-weight:700">&le;210 good</span> &middot; <span style="color:#b8860b;font-weight:700">&le;285 watch</span> &middot; '
                    '<span style="color:var(--red);font-weight:700">&gt;285 act</span>.</div></div>' % f1tbl)

    # ---- Qualifying detail (latest audit by store) ----
    qlist = [(s, F1D[s]['quali']) for s in F1D if not str(s).startswith('_')
             and isinstance(F1D[s], dict) and F1D[s].get('quali')]
    qlist.sort(key=lambda x: int(float(x[1][6])))
    quali_rows = "".join('<tr%s><td class="l">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class="mini">%s</td></tr>'
                         % (_rs(s), _nm(s), _rk(q[6]), _q(q[0]), _hosp(q[1]), _hosp(q[2]), _hosp(q[3]), _hosp(q[4]), q[5], q[7]) for s, q in qlist)
    quali_block = ('<div class="f1sub">Qualifying detail <span class="mini">&middot; latest audit by store</span></div>'
                   '<div class="f1panel"><table class="f1t"><thead><tr><th class="l">Store</th><th>Rank</th><th>Queue avg</th><th>Hello</th><th>Goodbye</th><th>How are you</th><th>Working queue</th><th>Total score</th><th>Audited</th></tr></thead><tbody>%s</tbody></table>'
                   '<div class="mini" style="margin-top:9px">Hospitality scored 0&ndash;100%% per greeting; queue average in seconds (lower is better).</div></div>' % quali_rows)

    # ---- Qualifying — quarter-to-date by store ----
    qqlist = [(s, F1D[s]['quali_qtd']) for s in F1D if not str(s).startswith('_')
              and isinstance(F1D.get(s), dict) and F1D[s].get('quali_qtd') and not _iscomp(s)]
    qqlist.sort(key=lambda x: (x[1]['rank'] if x[1].get('rank') is not None else 99))
    quali_qtd_rows = "".join('<tr><td class="l">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                             % (_nm(s), d["n"], _rk(round(d["rank"])) if d.get("rank") is not None else _na(),
                                _q(d["queue_s"]) if d.get("queue_s") is not None else _na(),
                                _qcallpct(d.get("qcall")), _greet(d.get("hello")), _greet(d.get("goodbye")), _greet(d.get("howareyou"))) for s, d in qqlist)
    quali_qtd_block = ('<div class="f1sub">Qualifying <span class="mini">&middot; quarter-to-date by store</span></div>'
                       '<div class="f1panel"><table class="f1t"><thead><tr><th class="l">Store</th><th>Audits</th><th>Avg rank</th><th>Avg queue</th><th>Queue calling</th><th>Hello</th><th>Goodbye</th><th>How are you</th></tr></thead><tbody>%s</tbody></table>'
                       '<div class="mini" style="margin-top:9px">Quarter-to-date averages across every qualifying audit this quarter (rank 1 = top of the grid). Queue-calling &amp; sub-scores are on an inconsistent scale in the qualifying sheet, so the race view below is the clean source for those.</div></div>' % quali_qtd_rows)

    # ---- Race detail (latest audit by store) ----
    rlist = [(s, F1D[s]['race']) for s in F1D if not str(s).startswith('_')
             and isinstance(F1D[s], dict) and F1D[s].get('race')]
    rlist.sort(key=lambda x: int(float(x[1][7])))
    race_rows = "".join('<tr%s><td class="l">%s</td><td>%s</td><td style="font-weight:700">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class="mini">%s</td></tr>'
                        % (_rs(s), _nm(s), _rk(r[7]), r[6], _q(r[0]), _hosp(r[1]), _hosp(r[2]), _hosp(r[3]), _hosp(r[4]), _scrag(r[5]), r[8]) for s, r in rlist)
    race_block = ('<div class="f1sub">Race detail <span class="mini">&middot; latest audit by store</span></div>'
                  '<div class="f1panel"><table class="f1t"><thead><tr><th class="l">Store</th><th>Finish</th><th>Champ pts</th><th>Queue avg</th><th>Hello</th><th>Goodbye</th><th>How are you</th><th>Working queue</th><th>Total score</th><th>Audited</th></tr></thead><tbody>%s</tbody></table>'
                  '<div class="mini" style="margin-top:9px">Finishing position across the full field of ~25 (incl. competitor benchmark audits).</div></div>' % race_rows)

    # ---- Race — quarter-to-date by store ----
    rqlist = [(s, F1D[s]['race_qtd']) for s in F1D if not str(s).startswith('_')
              and isinstance(F1D.get(s), dict) and F1D[s].get('race_qtd') and F1D[s]['race_qtd'].get('score') is not None and not _iscomp(s)]
    rqlist.sort(key=lambda x: x[1]['score'])
    race_qtd_rows = "".join('<tr><td class="l">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                            % (_nm(s), d["n"], _scrag(d["score"]),
                               _q(d["queue_s"]) if d.get("queue_s") is not None else _na(),
                               _qcallpct(d.get("qcall")), _greet(d.get("hello")), _greet(d.get("goodbye")), _greet(d.get("howareyou"))) for s, d in rqlist)
    race_qtd_block = ('<div class="f1sub">Race <span class="mini">&middot; quarter-to-date by store</span></div>'
                      '<div class="f1panel"><table class="f1t"><thead><tr><th class="l">Store</th><th>Audits</th><th>Avg total score</th><th>Avg queue</th><th>Avg queue-calling</th><th>Hello</th><th>Goodbye</th><th>How are you</th></tr></thead><tbody>%s</tbody></table>'
                      '<div class="mini" style="margin-top:9px">Quarter-to-date averages across every race audit this quarter. Lower total score &amp; queue seconds = better; higher queue-calling = better. This is the same QTD average that feeds the F1 Score KPI headline above.</div></div>' % race_qtd_rows)

    focus = ('<div class="f1focus"><span class="ar">&rarr;</span> Reset the weekend routine at <b>%s</b> &amp; <b>%s</b>; lift qualifying to fix the handicapped grid start.</div>'
             % (SH(worstf[0]), SH(worstf[1]) if len(worstf) > 1 else SH(worstf[0])))

    # Gate the tables by the existing Weekly/Quarterly period toggle (#pdsel -> .ps-basis divs).
    # WEEKLY = this week's race only (latest-race cards + latest race finish + weekly race detail +
    # weekly qualifying detail + focus). QUARTERLY = cumulative championship + QTD tables. The KPI
    # headline (This week / QTD) sits above this, on both. Same data/layout as the Company Op's tab.
    hint = ('<div class="md-note" style="margin-bottom:12px">Use the <b>period toggle</b> above '
            '(Weekly / Quarterly) to switch between <b>this week&rsquo;s race</b> and the '
            '<b>quarter-to-date</b> championship &amp; averages.</div>')
    always_on = season_cons_block + season_drv_block
    weekly_group = ('<div class="ps-basis" data-basis="weekly" style="display:block">'
                    + cards + finish_block + race_block + quali_block + focus + '</div>')
    qtd_group = ('<div class="ps-basis" data-basis="qtd" style="display:none">'
                 + champ_block + breakdown_block + race_qtd_block + quali_qtd_block + '</div>')
    _f1st = F1D.get("_stale") or {}
    _badge = ('<div class="md-note" style="background:var(--redbg);border:1px solid #eccfca;color:#8c2f22;font-weight:800;margin-bottom:12px">&#9888; %s &mdash; the F1 figures below are the last completed audit, not this week\'s.</div>'
              % esc(_f1st.get("badge", "F1 awaiting this week's audit"))) if _f1st.get("stale") else ""
    return (_badge + intro + always_on + hint + weekly_group + qtd_group)


# ============ Bench detail (mirrors the Company Dashboard 'Bench' tab) ============
# Reuses the SAME shared renderer the company/area/kel dashboards use (bench_render.build_bench off
# bench.json) with the SAME store REC + short-name map, so the EOS Bench detail and the Company
# Dashboard bench tab are byte-identical and always in sync — including the NEW hierarchy-gap status
# rule (green = full core line SM+AM+Sup1 + a named successor; amber = AM/Sup1 gap or thin; red = SM
# vacancy), the estate star map, and the per-store management-team names table. Fault-tolerant:
# any missing input degrades to '' and never breaks the EOS build. The map's own script initialises
# when its (hidden) data-tab="bench" control is clicked — the metric selector triggers that on show.
def bench_detail_html():
    try:
        from bench_render import build_bench
        REC = json.load(open(os.path.join(HERE, "allstores.json"))).get("rec", {})
        _BN, _BP = build_bench(REC, F1_SHORT)
        if not _BP:
            return ""
        return '<div class="eosbench"><div style="display:none">%s</div>%s</div>' % (_BN, _BP)
    except Exception:
        return ""


# ============ Rate My Shift detail (store-by-store participation + 'shift voice' comments) ============
# Reads rms_feed.json (written by run_weekly.pull_rms_storehealth): per-store weekly + QTD submission
# counts / avg ratings for EVERY store (non-posters shown as 0 / 'no submissions'), plus recent (last
# ~2 weeks) free-text shift comments with sentiment (from the 1-5 rating) and the manager's SMT reply
# when present — mirroring the Google-reviews 'Customer Voice' box. Fault-tolerant: '' on any failure.
def rms_detail_html():
    try:
        F = json.load(open(os.path.join(HERE, "rms_feed.json")))
    except Exception:
        return ""
    ps = F.get("per_store") or {}
    if not ps:
        return ""
    SH = lambda x: F1_SHORT.get(x, x)
    STAR = "\u2605"
    def _avg(a):
        return ("%.2f%s" % (a, STAR)) if a is not None else "&mdash;"
    rows = sorted(ps.items(), key=lambda kv: (-(kv[1]["weekly"]["n"] or 0), -(kv[1]["qtd"]["n"] or 0)))
    posted = sum(1 for _, v in rows if (v["weekly"]["n"] or 0) > 0)
    silent = len(rows) - posted
    body = ""
    for st, v in rows:
        wn = v["weekly"]["n"] or 0; qn = v["qtd"]["n"] or 0
        chip = '<span class="chip green">posting</span>' if wn > 0 else '<span class="chip red">no submissions</span>'
        body += ('<tr><td class="s">%s</td><td class="v">%d</td><td class="v">%s</td>'
                 '<td class="v">%d</td><td class="v">%s</td><td class="st">%s</td></tr>'
                 % (esc(SH(st)), wn, _avg(v["weekly"]["avg"]), qn, _avg(v["qtd"]["avg"]), chip))
    table = ('<div class="md-ps-basis">Last completed week (%s) &amp; quarter-to-date (%s) &middot; '
             '<b>%d of %d stores</b> submitted last week &middot; %d silent</div>'
             '<table class="md-ps"><thead><tr><th>Store</th><th class="v">Last wk subs</th>'
             '<th class="v">Last wk %s</th><th class="v">QTD subs</th><th class="v">QTD %s</th>'
             '<th class="st">Participation</th></tr></thead><tbody>%s</tbody></table>'
             % (esc(F.get("_weekly_label", "")), esc(F.get("_qtd_label", "")), posted, len(rows), silent, STAR, STAR, body))
    TAGK = {"Positive": "t-ok", "Negative": "t-red", "Mixed": "t-amber"}
    cm = F.get("comments") or []
    if cm:
        cards = ""
        for c in cm[:14]:
            chip = '<span class="tag %s">%s</span>' % (TAGK.get(c.get("sentiment"), "t-na"), esc(c.get("sentiment", "")))
            smt = ('<div style="font-size:11.5px;color:#8a7a6d;margin-top:4px">&#8627; Manager: %s</div>' % esc(c["smt"])) if c.get("smt") else ""
            try: rt = ("%g" % float(c.get("rating")))
            except Exception: rt = esc(str(c.get("rating", "")))
            cards += ('<div style="border:1px solid #ece3d6;border-radius:10px;padding:8px 11px;margin-bottom:8px">'
                      '<div style="font-size:12.5px"><b>%s</b> %s <span class="mini">%s%s &middot; %s</span></div>'
                      '<div style="font-size:12px;color:#5b4a37;margin:3px 0 0;line-height:1.45">&ldquo;%s&rdquo;</div>%s</div>'
                      % (esc(SH(c.get("store", ""))), chip, rt, STAR, esc(c.get("date", "")), esc(c.get("text", "")), smt))
        voice = '<div class="md-section-h">%s</div>%s' % (esc(F.get("_comments_label", "Recent shift voice")), cards)
    else:
        voice = '<div class="md-note">No recent shift-rating comments in the last two weeks.</div>'
    # ---- LEAD: last week's WORST-rated shifts (lowest first) with date + day-of-week + suggested action on outliers ----
    worst = F.get("worst") or []
    outliers = F.get("outlier_stores") or []
    lw_label = esc(F.get("_weekly_label", "")); lw_count = F.get("_lastweek_count")
    worst_html = ""
    if worst:
        wcards = ""
        for w in worst:
            try: rt = ("%g" % float(w.get("rating")))
            except Exception: rt = esc(str(w.get("rating", "")))
            tagk = {"Positive": "t-ok", "Negative": "t-red", "Mixed": "t-amber"}.get(w.get("sentiment"), "t-na")
            chip = '<span class="tag %s">%s%s</span>' % (tagk, rt, STAR)
            txt = ('<div style="font-size:12px;color:#5b4a37;margin:3px 0 0;line-height:1.45">&ldquo;%s&rdquo;</div>' % esc(w["text"])) if w.get("text") else '<div style="font-size:11.5px;color:#a99;margin:3px 0 0">(no comment left)</div>'
            smt = ('<div style="font-size:11.5px;color:#8a7a6d;margin-top:4px">&#8627; Manager: %s</div>' % esc(w["smt"])) if w.get("smt") else ""
            action = ('<div style="font-size:11.5px;color:#8a3b2b;background:#fbeee9;border-radius:7px;padding:5px 8px;margin-top:6px"><b>Action:</b> %s</div>' % esc(w["action"])) if w.get("action") else ""
            wcards += ('<div style="border:1px solid #f0ddd5;border-left:3px solid var(--red);border-radius:10px;padding:8px 11px;margin-bottom:8px">'
                       '<div style="font-size:12.5px"><b>%s</b> %s <span class="mini">%s</span></div>%s%s%s</div>'
                       % (esc(SH(w.get("store", ""))), chip, esc(w.get("dow", "")), txt, smt, action))
        cnt = (" &middot; <b>%d</b> submissions logged last week" % lw_count) if lw_count is not None else ""
        worst_html = ('<div class="md-section-h">Last week&rsquo;s lowest-rated shifts &mdash; worst first (%s%s)</div>%s'
                      % (lw_label, cnt, wcards))
    if outliers:
        orows = ""
        for o in outliers:
            orows += ('<div style="font-size:12px;color:#5b4a37;margin-bottom:6px;padding:5px 10px;border-left:3px solid var(--red);background:#fbf4f1;border-radius:6px">'
                      '<b>%s</b> &mdash; %.2f%s avg (%d shifts). %s</div>'
                      % (esc(SH(o.get("store", ""))), o.get("avg", 0), STAR, o.get("n", 0), esc(o.get("action", ""))))
        worst_html += '<div class="md-section-h">Suggested actions &mdash; store outliers</div>' + orows
    # ---- store dropdown: All (company view) + per-store filtered detail ----
    psd = F.get("per_store_detail") or {}
    # ---- Sickness / RTW (mirrors Kel's engagement Sentiment tab) + OUTSTANDING named RTW (last 4 weeks) ----
    def _tag(txt, k): return '<span class="tag %s">%s</span>' % (k, txt)
    _MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    def _dfmt(iso):
        try:
            y, m, d = iso.split("-"); return "%d %s" % (int(d), _MON[int(m)])
        except Exception:
            return iso
    sickrtw_html = ""
    try:
        SR = json.load(open(os.path.join(HERE, "sickness_rtw.json")))
    except Exception:
        SR = None
    if SR:
        out = SR.get("outstanding") or []
        if out:
            orows = ""
            for o in out:
                orows += ('<tr><td class="s">%s</td><td>%s</td><td class="v">%s</td><td style="font-size:11px;color:#8a7a6d">%s</td></tr>'
                          % (esc(o.get("name", "")), esc(SH(o.get("store", ""))), esc(_dfmt(o.get("date", ""))), esc(o.get("reason", ""))))
            out_block = ('<div class="md-section-h" style="color:#8a3b2b">Outstanding RTW &mdash; action needed <span class="mini">&middot; last 4 weeks &middot; %d due</span></div>'
                         '<div class="md-ps-basis">Named individuals with a sickness absence in the last 4 weeks and <b>no return-to-work interview logged</b>. Managers to conduct the RTW chat and record it on the HRP RTW log.</div>'
                         '<table class="md-ps"><thead><tr><th>Employee</th><th>Store</th><th class="v">Absence date</th><th>Reason</th></tr></thead><tbody>%s</tbody></table>'
                         % (len(out), orows))
        else:
            out_block = '<div class="md-section-h">Outstanding RTW &mdash; action needed</div><div class="md-note">All return-to-work interviews are up to date for the last 4 weeks.</div>'
        tbl = SR.get("per_store") or []
        trows = ""
        for t in tbl:
            rr = t.get("rtw_rate"); rrk = "t-ok" if (rr is not None and rr >= 80) else ("t-amber" if (rr is not None and rr >= 50) else "t-red")
            rep = t.get("rep_pct"); repk = "t-ok" if (rep is not None and rep >= 90) else ("t-amber" if (rep is not None and rep >= 70) else "t-red")
            trows += ('<tr><td class="s">%s</td><td class="v">%s</td><td class="v">%s</td><td class="v">%s</td><td class="v">%s</td><td class="v">%s</td></tr>'
                      % (esc(SH(t.get("store", ""))), t.get("sickfs", 0), t.get("late", 0),
                         _tag(("%s%%" % rep) if rep is not None else "n/a", repk),
                         t.get("rtw", 0), _tag(("%s%%" % rr) if rr is not None else "n/a", rrk)))
        sick_block = ('<div class="md-section-h">Sickness &amp; return-to-work &mdash; by store <span class="mini">&middot; YTD to %s</span></div>'
                      '<div class="md-ps-basis">From the HRP <b>Sickness / late</b> &amp; <b>RTW</b> logs. RTW policy: a return-to-work chat after every sickness absence. Mirrors Kel&rsquo;s engagement dashboard.</div>'
                      '<table class="md-ps"><thead><tr><th>Store</th><th class="v">Sick-for-shift</th><th class="v">Late</th><th class="v">Reported&nbsp;%%</th><th class="v">RTW done</th><th class="v">RTW&nbsp;%%</th></tr></thead><tbody>%s</tbody></table>'
                      % (esc(SR.get("generated", "")), trows))
        sickrtw_html = out_block + sick_block
    all_view = (worst_html + sickrtw_html + '<div class="md-section-h">Store-by-store &mdash; who is posting</div>' + table + voice)
    outmap = {o.get("store"): o for o in (F.get("outlier_stores") or [])}
    opts = ['<option value="__all__">All stores</option>']
    variants = ['<div data-store="__all__">%s</div>' % all_view]
    for st in sorted(ps.keys(), key=lambda x: SH(x)):
        v = ps[st]; wn = v["weekly"]["n"] or 0; wa = v["weekly"]["avg"]; qn = v["qtd"]["n"] or 0; qa = v["qtd"]["avg"]
        opts.append('<option value="%s">%s</option>' % (esc(st), esc(SH(st))))
        head = ('<div class="md-section-h">%s &mdash; Rate My Shift</div>'
                '<div class="md-ps-basis">Last week: <b>%d</b> submission%s%s &middot; QTD: <b>%d</b>%s</div>'
                % (esc(SH(st)), wn, "" if wn == 1 else "s", (" &middot; avg %s" % _avg(wa)) if wa is not None else "",
                   qn, (" &middot; avg %s" % _avg(qa)) if qa is not None else ""))
        o = outmap.get(st)
        act = ('<div style="font-size:12px;color:#8a3b2b;background:#fbeee9;border-radius:7px;padding:6px 9px;margin:6px 0 8px"><b>Outlier:</b> %s</div>' % esc(o["action"])) if o else ""
        rows_s = psd.get(st) or []
        if rows_s:
            cards = ""
            for w in rows_s:
                try: rt = ("%g" % float(w.get("rating")))
                except Exception: rt = esc(str(w.get("rating", "")))
                tagk = {"Positive": "t-ok", "Negative": "t-red", "Mixed": "t-amber"}.get(w.get("sentiment"), "t-na")
                chip = '<span class="tag %s">%s%s</span>' % (tagk, rt, STAR)
                txt = ('<div style="font-size:12px;color:#5b4a37;margin:3px 0 0;line-height:1.45">&ldquo;%s&rdquo;</div>' % esc(w["text"])) if w.get("text") else '<div style="font-size:11.5px;color:#a99;margin:3px 0 0">(no comment left)</div>'
                smt = ('<div style="font-size:11.5px;color:#8a7a6d;margin-top:4px">&#8627; Manager: %s</div>' % esc(w["smt"])) if w.get("smt") else ""
                action = ('<div style="font-size:11.5px;color:#8a3b2b;background:#fbeee9;border-radius:7px;padding:5px 8px;margin-top:6px"><b>Action:</b> %s</div>' % esc(w["action"])) if w.get("action") else ""
                cards += ('<div style="border:1px solid #f0ddd5;border-left:3px solid var(--red);border-radius:10px;padding:8px 11px;margin-bottom:8px">'
                          '<div style="font-size:12.5px"><b>%s</b> %s <span class="mini">%s</span></div>%s%s%s</div>'
                          % (esc(SH(st)), chip, esc(w.get("dow", "")), txt, smt, action))
            body = '<div class="md-section-h">Last week&rsquo;s shifts &mdash; worst first</div>' + cards
        else:
            body = '<div class="md-note">No Rate My Shift submissions logged last week for this store.</div>'
        variants.append('<div data-store="%s" style="display:none">%s%s%s</div>' % (esc(st), head, act, body))
    bar = ('<div class="md-storebar"><span class="lbl">Store:</span> <select class="stsel mdsel">%s</select></div>' % "".join(opts))
    return '<div class="st-scope">%s%s</div>' % (bar, "".join(variants))



def _se_fmt_int(v):
    try: return format(int(round(float(v))), ",")
    except Exception: return "&mdash;"

def _se_nice_date(x):
    try:
        import datetime as _dt
        return _dt.datetime.strptime(str(x)[:10], "%Y-%m-%d").date().strftime("%-d %b")
    except Exception:
        return ""

def _se_load():
    try:
        return json.load(open(os.path.join(HERE, "sales_extras.json")))
    except Exception:
        return None

def dt_lanes_html():
    """TOP of the Sales view: drive-thru lane throughput per lane. All of a site's 'drive'-named
    registers are aggregated into one lane figure (Northampton has two DT tills). QTD + last week
    with YoY vs 52 weeks earlier. A lane with no prior-year DT history (Billing DT, opened May 2026)
    shows 'new' rather than a fabricated YoY. Reads sales_extras.json. Fault-tolerant."""
    S = _se_load()
    if not S: return ""
    lanes = S.get("dt_lanes") or []
    if not lanes: return ""
    def _pct(v):
        if v is None: return "&mdash;"
        return ("+%.1f%%" % v) if v >= 0 else ("%.1f%%" % v)
    tiles = ""
    for L in lanes:
        new = L.get("new"); yoy = L.get("qtd_yoy")
        if new:
            accent = "var(--gold)"
            badge = ('<span style="display:inline-block;background:var(--gold);color:#fff;font-size:10.5px;'
                     'font-weight:800;padding:1px 8px;border-radius:9px;letter-spacing:.03em">NEW LANE</span>')
            sub = "last wk <b>%s</b> &middot; opened May 2026, no prior-year baseline" % _se_fmt_int(L.get("lw"))
        else:
            up = (yoy is not None and yoy >= 0)
            accent = "var(--green)" if up else "var(--red)"
            badge = ('<span style="font-size:14px;font-weight:800;color:%s">%s '
                     '<span style="color:var(--muted);font-weight:600;font-size:11px">YoY</span></span>'
                     % (accent, _pct(yoy)))
            sub = ("last wk <b>%s</b> (%s vs %s LY)"
                   % (_se_fmt_int(L.get("lw")), _pct(L.get("lw_yoy")), _se_fmt_int(L.get("lw_ly"))))
        tiles += ('<div style="flex:1 1 210px;min-width:200px;border:1px solid var(--line);border-top:3px solid %s;'
                  'border-radius:12px;padding:12px 14px;background:#fff">'
                  '<div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:700">%s</div>'
                  '<div style="font-size:27px;font-weight:800;color:var(--brown);line-height:1.1;margin:5px 0 3px">%s '
                  '<span style="font-size:12px;color:var(--muted);font-weight:600">cars QTD</span></div>'
                  '<div style="margin:2px 0 4px">%s</div>'
                  '<div style="font-size:11.5px;color:var(--muted)">%s</div></div>'
                  % (accent, esc(L.get("store","")), _se_fmt_int(L.get("qtd")), badge, sub))
    note = ('Each lane counts the distinct orders taken through that site&rsquo;s drive-thru till(s) '
            '&mdash; Northampton aggregates both its DT registers &mdash; a fair proxy for cars served '
            'through the lane. YoY compares the same window 52 weeks earlier.')
    return ('<div class="md-section-h">Drive-thru &mdash; cars through the lane, by site '
            '<span style="font-weight:600;color:var(--muted);font-size:12px">(%s)</span></div>'
            '<div style="display:flex;gap:12px;flex-wrap:wrap;margin:2px 0 6px">%s</div>'
            '<div class="md-note">%s</div>' % (esc(S.get("qtd_label","")), tiles, note))

def fridge_items_html():
    """TOP of the Sales view: top chilled grab-and-go 'fridge' food items estate-wide, QTD units
    (with last week + estate share), the recent range-refresh SKUs flagged NEW (spotlight strip +
    inline badges). Reads sales_extras.json. Fault-tolerant."""
    S = _se_load()
    if not S: return ""
    F = S.get("fridge") or {}
    items = F.get("items") or []
    if not items: return ""
    new_items = [i for i in items if i.get("new")]
    top = items[:12]
    mx = max((i.get("qtd") or 0) for i in top) or 1
    spot = ""
    for i in new_items:
        spot += ('<div style="flex:1 1 170px;min-width:158px;border:1px solid var(--line);border-top:3px solid var(--gold);'
                 'border-radius:12px;padding:10px 12px;background:#fffdf6">'
                 '<div style="display:flex;justify-content:space-between;align-items:center;gap:6px">'
                 '<span style="font-size:10px;font-weight:800;color:#fff;background:var(--gold);padding:1px 7px;'
                 'border-radius:9px;letter-spacing:.03em">NEW</span>'
                 '<span style="font-size:11px;color:var(--muted)">%s units</span></div>'
                 '<div style="font-size:13px;font-weight:700;color:var(--brown);margin:6px 0 2px;line-height:1.2">%s</div>'
                 '<div style="font-size:11px;color:var(--muted)">%s last wk &middot; launched %s</div></div>'
                 % (_se_fmt_int(i.get("qtd")), esc(i.get("name","")),
                    _se_fmt_int(i.get("lw")), esc(_se_nice_date(i.get("first_sold")))))
    spot_block = ('<div style="font-size:12px;font-weight:700;color:var(--brown);margin:4px 0 5px">'
                  '&#10024; New this range refresh</div>'
                  '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:0 0 13px">%s</div>' % spot) if spot else ""
    bars = ""
    for idx, i in enumerate(top, 1):
        new = i.get("new"); w = 100.0 * (i.get("qtd") or 0) / mx
        barcol = ("linear-gradient(90deg,var(--gold),#e0a92e)" if new
                  else "linear-gradient(90deg,#8a6d4b,#b98a5e)")
        namehtml = esc(i.get("name",""))
        if new:
            namehtml += (' <span style="font-size:9px;font-weight:800;color:#fff;background:var(--gold);'
                         'padding:0 6px;border-radius:8px;vertical-align:1px">NEW</span>')
        bars += ('<div style="display:flex;align-items:center;gap:10px;margin:3px 0">'
                 '<div style="width:18px;text-align:right;font-size:11px;color:var(--muted);font-weight:700">%d</div>'
                 '<div style="width:215px;font-size:12.5px;color:var(--brown);font-weight:600;overflow:hidden;'
                 'text-overflow:ellipsis;white-space:nowrap">%s</div>'
                 '<div style="flex:1;min-width:70px;background:#f0ece6;border-radius:6px;height:18px">'
                 '<div style="width:%.1f%%;background:%s;height:100%%;border-radius:6px"></div></div>'
                 '<div style="width:135px;text-align:right;font-size:12px;color:var(--brown);font-weight:700">%s '
                 '<span style="color:var(--muted);font-weight:500">units &middot; %s%%</span></div></div>'
                 % (idx, namehtml, w, barcol, _se_fmt_int(i.get("qtd")), ("%.0f" % (i.get("share") or 0))))
    header = ('<div class="md-section-h">Food fridge &mdash; top chilled grab-and-go items '
              '<span style="font-weight:600;color:var(--muted);font-size:12px">(%s)</span></div>'
              % esc(S.get("qtd_label","")))
    note = ('<div class="md-note">Chilled grab-and-go range only (sandwiches, ciabattas, wraps, salads, '
            'bagels, croques &amp; toasties); cooked-to-order baps, hot sausage rolls and the kids range '
            'excluded. Estate units for %s; eat-in and takeaway variants combined; share = %% of these items.</div>'
            % esc(S.get("qtd_label","")))
    return header + spot_block + ('<div style="margin:2px 0 6px">%s</div>' % bars) + note

def sales_records_html():
    """Two all-time company record widgets for the top of the Sales (YoY Sales Growth) view:
    record weekly sales + record busiest single trading hour. Reads sales_records.json
    (written by run_weekly.pull_sales from full BigQuery history). Fault-tolerant."""
    try:
        R = json.load(open(os.path.join(HERE, "sales_records.json")))
    except Exception:
        return ""
    rw = R.get("record_week") or {}; rh = R.get("record_hour") or {}
    if not rw and not rh:
        return ""
    def gbp0(v):
        try: return "\u00a3%s" % format(int(round(float(v))), ",")
        except Exception: return "&mdash;"
    cards = ""
    if rw:
        cards += ('<div style="flex:1 1 230px;min-width:215px;border:1px solid var(--line);border-top:3px solid var(--green);'
                  'border-radius:12px;padding:12px 14px;background:#fff">'
                  '<div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:700">&#127942; Record weekly sales</div>'
                  '<div style="font-size:26px;font-weight:800;color:var(--brown);line-height:1.1;margin:5px 0 2px">%s</div>'
                  '<div style="font-size:12px;color:var(--muted)">all-time company best &middot; <b>%s</b></div></div>'
                  % (gbp0(rw.get("rev")), esc(rw.get("label", ""))))
    if rh:
        cards += ('<div style="flex:1 1 230px;min-width:215px;border:1px solid var(--line);border-top:3px solid var(--gold);'
                  'border-radius:12px;padding:12px 14px;background:#fff">'
                  '<div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:700">&#127942; Record sales hour</div>'
                  '<div style="font-size:26px;font-weight:800;color:var(--brown);line-height:1.1;margin:5px 0 2px">%s</div>'
                  '<div style="font-size:12px;color:var(--muted)">all-time busiest trading hour &middot; <b>%s</b> &middot; %s</div></div>'
                  % (gbp0(rh.get("rev")), esc(rh.get("hour_label", "")), esc(rh.get("dow_label", ""))))
    return ('<div class="md-section-h">Company records</div>'
            '<div style="display:flex;gap:12px;flex-wrap:wrap;margin:2px 0 12px">%s</div>' % cards)


def avg_per_store_html():
    """Sales-view widget: average gross weekly sales PER STORE last week vs the same week last year,
    each year divided by ITS OWN actual trading-store count (fair YoY, since the estate grew), with a
    flat \u00f7N variant noted. Reads sales_records.json['avg_per_store']. Fault-tolerant."""
    try:
        R = json.load(open(os.path.join(HERE, "sales_records.json")))
    except Exception:
        return ""
    a = R.get("avg_per_store") or {}
    if not a.get("ty_avg") or not a.get("ly_avg"):
        return ""
    def gbp0(v):
        try: return "\u00a3%s" % format(int(round(float(v))), ",")
        except Exception: return "&mdash;"
    def pct(v):
        if v is None: return "&mdash;"
        return ("+%.1f%%" % v) if v >= 0 else ("%.1f%%" % v)
    yoy = a.get("yoy_pct"); yc = "var(--green)" if (yoy is not None and yoy >= 0) else "var(--red)"
    card = ('<div style="flex:1 1 150px;min-width:140px;border:1px solid var(--line);border-radius:12px;padding:11px 13px;background:#fff">'
            '<div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:700">%s</div>'
            '<div style="font-size:23px;font-weight:800;color:%s;margin:4px 0 1px">%s</div>'
            '<div style="font-size:11.5px;color:var(--muted)">%s</div></div>')
    cards = card % ("This year / store", "var(--brown)", gbp0(a["ty_avg"]), "last wk &middot; &#247; %d stores" % a.get("ty_stores", 0))
    cards += card % ("Last year / store", "var(--brown)", gbp0(a["ly_avg"]), "same wk LY &middot; &#247; %d stores" % a.get("ly_stores", 0))
    cards += card % ("YoY per store", yc, pct(yoy), "each yr &#247; its own store count")
    note = ('Each year&rsquo;s total company sales &#247; that year&rsquo;s actual trading-store count '
            '(this year <b>%d</b>, last year <b>%d</b>) &mdash; a fair per-store average both years. '
            'On a flat &#247;%d both years it is %s vs %s (<b>%s</b>).'
            % (a.get("ty_stores", 0), a.get("ly_stores", 0), a.get("fixed_n", 21),
               gbp0(a.get("ty_avg_fixed")), gbp0(a.get("ly_avg_fixed")), pct(a.get("yoy_fixed_pct"))))
    return ('<div class="md-section-h">Average gross weekly sales per store &mdash; vs last year</div>'
            '<div style="display:flex;gap:12px;flex-wrap:wrap;margin:2px 0 6px">%s</div>'
            '<div class="md-note">%s</div>' % (cards, note))


def wastage_gp_html():
    """EOS Food GP% detail: mirror of the Company 'Wastage & Yield' Food/Bakery tables, with REAL sold
    units (EPOS-matched) and explicit coverage dates. Reads company_wastage.json. Fault-tolerant."""
    import re as _re
    try:
        Wj = json.load(open(os.path.join(HERE, "company_wastage.json")))
    except Exception:
        return ""
    rows = Wj.get("rows") or []
    if not rows:
        return ""
    lw = esc(Wj.get("_window_lw_label", "")); w4 = esc(Wj.get("_window4_label", ""))
    FOOD = _re.compile(r'croque|ciabatta|bap|wrap|sandwich|bagel|salad|tuna|panini|toastie|soup|breakfast|meal deal|chorizo|mozzarella|ham|cheese', _re.I)
    BAK = _re.compile(r'traybake|brownie|slice|croissant|pastry|muffin|cookie|cake|bakewell|millionaire|teacake|scone|flapjack|twist|doughnut|cinnamon|sausage roll', _re.I)
    def _norm(n): return _re.sub(r'^[0-9*]+ *', '', str(n)).strip()
    def _cat(n):
        if BAK.search(n) and ('pastry' in n.lower() or 'sausage roll' in n.lower()) and FOOD.search(n): return 'Food'
        if FOOD.search(n): return 'Food'
        if BAK.search(n): return 'Bakery'
        return 'Other'
    def _rcls(wr): return "t-na" if wr is None else ("t-ok" if wr <= 4 else ("t-amber" if wr <= 8 else "t-red"))
    agg = {}
    for nm_raw, w, ret, sold in rows:
        nm = _norm(nm_raw); cat = _cat(nm)
        if cat == 'Other': continue
        a = agg.setdefault(nm, {'w': 0.0, 'ret': 0.0, 'sold': 0.0, 'known': False, 'cat': cat})
        a['w'] += w or 0; a['ret'] += ret or 0
        if sold is not None: a['sold'] += sold; a['known'] = True
    def _tbl(cat):
        items = sorted([(n, a) for n, a in agg.items() if a['cat'] == cat], key=lambda x: -x[1]['ret'])[:15]
        if not items: return '<div class="md-note">No %s wastage lines this window.</div>' % cat.lower()
        body = ""
        for n, a in items:
            if a['known'] and (a['w'] + a['sold']) > 0:
                wr = round(100 * a['w'] / (a['w'] + a['sold']), 1)
                soldc = "{:,}".format(int(a['sold'])); wrc = '<span class="tag %s">%s%%</span>' % (_rcls(wr), wr)
            else:
                soldc = '<span class="mini" style="color:#9a8a7c">no EPOS match</span>'; wrc = '<span class="tag t-na">n/a</span>'
            body += '<tr><td class="l">%s</td><td>%d</td><td>%s</td><td>%s</td><td>&pound;%.0f</td></tr>' % (esc(n), int(a['w']), soldc, wrc, a['ret'])
        return ('<table class="f1t"><thead><tr><th class="l">Product</th><th>Wasted</th><th>Sold</th>'
                '<th>Waste rate</th><th>Retail lost</th></tr></thead><tbody>%s</tbody></table>' % body)
    return ('<div class="md-section-h">Wastage &amp; yield &mdash; Food &amp; Bakery</div>'
            '<div class="md-ps-basis">Waste rate = wasted &divide; (wasted + sold). Sold = actual EPOS units matched to each wasted line over the same window; unmatched lines show &ldquo;no EPOS match&rdquo;. '
            '<b>Coverage:</b> last week %s &middot; 4-week trend %s.</div>'
            '<div class="f1sub">Food</div>%s<div class="f1sub" style="margin-top:12px">Bakery</div>%s'
            % (lw, w4, _tbl('Food'), _tbl('Bakery')))


def cos_extra_html():
    """EOS Food GP detail: ONE consolidated per-store table — GP% (vs 71% target), stock holding % and
    delivery cost % each traffic-lit vs that store's OWN volume-based planned target (target shown
    alongside actual), plus the per-supplier delivery split (Select / Fresh / K&W / Simply) and a
    company total row. Targets are fitted per run (base + % of the store's weekly sales). Reads
    cos_metrics.json. Fault-tolerant."""
    try:
        C = json.load(open(os.path.join(HERE, "cos_metrics.json")))
    except Exception:
        return ""
    stores = C.get("stores", {}) or {}
    if not stores:
        return ""
    def gbp(x):
        try: return "&pound;" + format(int(round(float(x))), ",")
        except Exception: return "&mdash;"
    def sub(txt): return f' <span class="mini" style="color:#8a7a6d">{txt}</span>'
    try: _HW = json.load(open(os.path.join(HERE, "cos_history.json"))).get("weeks", {})
    except Exception: _HW = {}
    _wk4 = sorted(_HW.keys())[-4:]
    def series(store, key): return [(_HW[w].get(store) or {}).get(key) for w in _wk4]
    def spark(vals):
        vals = [v for v in vals if v is not None]
        if not vals: return ""
        WV, HV, pd = 44, 13, 2
        if len(vals) == 1:
            return ' <svg width="%d" height="%d" style="vertical-align:middle"><circle cx="%d" cy="%d" r="2" fill="var(--muted)"/></svg>' % (WV, HV, WV // 2, HV // 2)
        lo, hi = min(vals), max(vals); n = len(vals) - 1
        xf = lambda i: pd + (i / n) * (WV - 2 * pd)
        yf = lambda v: pd + (1 - ((v - lo) / (hi - lo) if hi > lo else 0.5)) * (HV - 2 * pd)
        poly = " ".join("%.1f,%.1f" % (xf(i), yf(v)) for i, v in enumerate(vals))
        return (' <svg width="%d" height="%d" style="vertical-align:middle"><polyline points="%s" fill="none" stroke="var(--brown)" stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"/><circle cx="%.1f" cy="%.1f" r="1.6" fill="var(--brown)"/></svg>' % (WV, HV, poly, xf(n), yf(vals[-1])))
    dt = C.get("delivery_target", 23.0); med = C.get("holding_median")
    cp = C.get("delivery_company_pct"); cq = C.get("delivery_company_qtd"); opp = C.get("delivery_opportunity_gbp")
    smod = C.get("stock_model") or {}; dmod = C.get("deliv_model") or {}
    GP_TGT = 71.0; egp = C.get("estate_gp_wk")
    def gp_cell(x, sp=""):
        if x is None: return '<span class="tag t-na">&mdash;</span>'
        return f'<span class="tag {"t-ok" if x >= GP_TGT else "t-red"}">{x:g}%</span>' + sp
    def stock_cell(h, tgt, sp=""):
        if h is None: return '<span class="tag t-na">&mdash;</span>'
        if tgt is None: return f'<span class="tag t-na">{h:g}%</span>' + sp
        k = "t-red" if h > tgt * 1.15 else ("t-amber" if h < tgt * 0.85 else "t-ok")
        return f'<span class="tag {k}">{h:g}%</span>' + sub(f"tgt {tgt:g}%") + sp
    def deliv_cell(d, tgt, sp=""):
        if d is None: return '<span class="tag t-na">&mdash;</span>'
        ref = tgt if tgt is not None else dt
        k = "t-red" if d > ref * 1.05 else "t-ok"
        return f'<span class="tag {k}">{d:g}%</span>' + sub(f"tgt {ref:g}%") + sp
    P = ['<div class="md-section-h">GP cost drivers &mdash; stock, delivery &amp; suppliers by store</div>']
    SUP = [("Select Catering", "Select"), ("Fresh Ideas", "Fresh"), ("K&W", "K&amp;W"), ("Simply", "Simply")]
    _stot = {full: 0.0 for full, _ in SUP}; _grand = 0.0
    for _v in stores.values():
        _sp = _v.get("suppliers") or {}; _ss = sum((_sp.get(full) or 0) for full, _ in SUP)
        if _ss > 0:
            for full, _ in SUP: _stot[full] += (_sp.get(full) or 0)
            _grand += _ss
    norm = {full: (100 * _stot[full] / _grand) if _grand else None for full, _ in SUP}
    def sup_cell(x, full, tsum):
        if x is None: return "<td>&mdash;</td>"
        nm = norm.get(full)
        if not (nm and tsum): return f"<td>{gbp(x)}</td>"
        ratio = (100 * x / tsum) / nm
        kk = "t-red" if ratio > 1.25 else ("t-amber" if ratio < 0.75 else "t-ok")
        return f'<td><span class="tag {kk}">{gbp(x)}</span></td>'
    leg = ""
    if smod: leg += f'Stock holding traffic-lit vs each store&rsquo;s <b>volume-based target</b> ({esc(smod.get("_basis",""))}): green within &plusmn;15%, red over (too much stock), amber under (too lean). '
    if dmod: leg += f'Delivery cost (ordering) vs each store&rsquo;s <b>volume-based target</b> ({esc(dmod.get("_basis",""))}). '
    _normstr = ", ".join(f"{ab} {norm[full]:.0f}%" for full, ab in SUP if norm.get(full) is not None)
    leg += f'GP% vs the <b>{GP_TGT:g}%</b> Food GP target. Supplier columns = &pound; delivered that week (<b>Select</b> = Select Catering, <b>Fresh</b> = Fresh Ideas, <b>K&amp;W</b> = Kirby &amp; West, <b>Simply</b> = Simply Lunch), each traffic-lit by the store&rsquo;s SHARE of its supplier mix vs the estate norm ({_normstr}): red = over-indexed (&gt;1.25&times;), amber = notably low, green = in line. GP%, stock and delivery cells carry a 4-week trend sparkline (short until history builds).'
    if cp is not None:
        tail = (f'&rarr; company target {dt:g}% &rarr; <b>{gbp(opp)}/yr</b> opportunity' if (opp and opp > 0) else f'&mdash; company already at/below the {dt:g}% reference')
        leg += f' Company delivery cost <b>{cp:g}%</b> (QTD {cq:g}%) {tail}; every 1pp &asymp; &pound;31k/yr.'
    P.append(f'<div class="md-ps-basis">{leg}</div>')
    body = ""; sup_tot = {full: 0 for full, _ in SUP}
    for st, v in sorted(stores.items(), key=lambda kv: -(kv[1].get("delivery_pct") or 0)):
        h = v.get("holding_pct"); d = v.get("delivery_pct")
        cells = ""
        _sp = v.get("suppliers") or {}; _ts = sum((_sp.get(full) or 0) for full, _ in SUP)
        for full, _ in SUP:
            x = _sp.get(full); sup_tot[full] += (x or 0)
            cells += sup_cell(x, full, _ts)
        body += (f'<tr><td class="l">{esc(st)}</td><td>{gp_cell(v.get("gp_pct"), spark(series(st, "gp")))}</td>'
                 f'<td>{stock_cell(h, v.get("stock_target_pct"), spark(series(st, "stock")))}</td>'
                 f'<td>{deliv_cell(d, v.get("deliv_target_pct"), spark(series(st, "deliv")))}</td>{cells}</tr>')
    medc = f'<span class="mini" style="color:#8a7a6d">est. med {med:g}%</span>' if med is not None else "&mdash;"
    compd = deliv_cell(cp, None) if cp is not None else '<span class="tag t-na">&mdash;</span>'
    totc = "".join(f'<td>{gbp(sup_tot[full])}</td>' for full, _ in SUP)
    body += (f'<tr style="font-weight:700;border-top:2px solid var(--line)"><td class="l">COMPANY</td>'
             f'<td>{gp_cell(egp)}</td><td>{medc}</td><td>{compd}</td>{totc}</tr>')
    heads = "".join(f'<th>{ab} &pound;</th>' for _, ab in SUP)
    P.append(f'<table class="f1t"><thead><tr><th class="l">Store</th><th>GP %</th><th>Stock hold % (vs tgt)</th><th>Delivery % (vs tgt)</th>{heads}</tr></thead><tbody>{body}</tbody></table>')
    return "".join(P)

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
    disp = "block" if i == 0 else "none"
    # Headline (KPI status) block shared by all metrics
    headline = ('<div class="md-section-h">Current status</div>'
        + '<div class="md-stats">%s%s</div>' % (ministat(wm, "This week"), ministat(qm, "Quarter to date")))
    if name == "F1 Score":
        # Detail mirrors the Company Dashboard 'Op's Excellence' tab (same f1_detail.json + champ data).
        _ops = f1_ops_html()
        detail = ('<div class="md-section-h">Op\'s Excellence — F1 detail</div>'
                  + (_ops if _ops else '<div class="md-note">F1 detail unavailable this run (f1_detail.json / champ missing).</div>'))
    elif name == "Bench":
        # Detail mirrors the Company Dashboard 'Bench' tab (same bench.json via build_bench).
        _bd = bench_detail_html()
        detail = ('<div class="md-section-h">Bench — estate &amp; succession (mirrors the Company Dashboard bench tab)</div>'
                  + (_bd if _bd else '<div class="md-note">Bench detail unavailable this run (bench.json missing).</div>'))
    elif name == "Rate My Shift Health":
        # Store-by-store participation (weekly + QTD, non-posters surfaced) + 'shift voice' comments.
        _rms = rms_detail_html()
        detail = ('<div class="md-section-h">This quarter, week by week</div>'
                  + trend_svg(name, plan, dirn)
                  + (_rms if _rms else '<div class="md-note">Rate My Shift detail unavailable this run (rms_feed.json missing).</div>'))
    elif name == "YoY Sales Growth":
        detail = (dt_lanes_html()
                  + fridge_items_html()
                  + sales_records_html()
                  + avg_per_store_html()
                  + '<div class="md-section-h">This quarter, week by week</div>'
                  + trend_svg(name, plan, dirn)
                  + yoy_bystore_html("Sales last week (%s) — by store, this year vs last year" % D.get("week_label", ""))
                  + weekend_bystore_html("sales")
                  + yoy_extras_html())
    elif name == "YoY Transactional Growth":
        detail = ('<div class="md-section-h">This quarter, week by week</div>'
                  + trend_svg(name, plan, dirn)
                  + yoy_bystore_html("Guest checks last week (%s) — by store, this year vs last year" % D.get("week_label", ""))
                  + weekend_html("tx") + weekend_bystore_html("tx"))
    elif name == "Brand & Remote Assessment":
        _br = blend_detail_html()
        detail = ('<div class="md-section-h">This quarter, week by week</div>'
                  + trend_svg(name, plan, dirn)
                  + '<div class="md-section-h">Per-store breakdown &mdash; brand audit / remote / blended</div>'
                  + (_br if _br else '<div class="md-note">Brand &amp; remote breakdown unavailable this run.</div>')
                  + openclose_bystore_html()
                  + accidents_bystore_html())
    elif name == "New Starter Health":
        _ns = ns_detail.new_starter_detail_html(D) if ns_detail else ""
        detail = ('<div class="md-section-h">New Starter Health &mdash; onboarding compliance (first 90 days)</div>'
                  + (_ns if _ns else '<div class="md-note">New Starter Health detail unavailable this run (new_starter.json / ns_detail missing).</div>'))
    elif name == "Google Health":
        ps_block = ps_section(name, plan, dirn, fm, qm)
        detail = ('<div class="md-section-h">This quarter, week by week</div>'
                  + trend_svg(name, plan, dirn)
                  + google_reviews_bystore_html()
                  + '<div class="md-section-h">Per-store breakdown &mdash; Google health score</div>'
                  + ps_block)
    elif name == "Food GP%":
        # Combined GP table (cos_extra_html) now carries GP% per store, so the old standalone
        # per-store GP breakdown below it is removed as redundant.
        detail = ('<div class="md-section-h">This quarter, week by week</div>'
                  + trend_svg(name, plan, dirn)
                  + wastage_gp_html()
                  + cos_extra_html())
    else:
        ps_block = ps_section(name, plan, dirn, fm, qm)   # weekly + QTD sub-tables (period selector)
        detail = ('<div class="md-section-h">This quarter, week by week</div>'
                  + trend_svg(name, plan, dirn)
                  + '<div class="md-section-h">Per-store breakdown</div>'
                  + ps_block)
    md_details += (
        '<div class="md-detail" id="md-%d" style="display:%s">' % (i, disp)
        + '<div class="md-title">%s<span class="md-owner">Owner: <b>%s</b></span></div>' % (esc(name), esc(owner))
        + '<div class="md-def">%s</div>' % definition
        + '<div class="md-planline">Plan: <b>%s</b> · Owner: <b>%s</b> · %s</div>' % (esc(plan_txt), esc(owner), dir_txt)
        + headline
        + detail
        + '<div class="md-section-h">How it\'s calculated</div>'
        + '<div class="md-calc">%s</div>' % calc
        + '</div>'
    )

bts_btn, bts_pane = backtoschool_tab()

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
  /* Issues 'home in on' panel */
  .issues{{background:#fdf1ef;border:1px solid #eccfca;border-left:5px solid var(--red);border-radius:12px;padding:12px 16px;margin:12px 0 2px;}}
  .iss-h{{font-size:12px;text-transform:uppercase;letter-spacing:.6px;font-weight:800;color:var(--red);margin-bottom:8px}}
  .iss-none{{font-size:13px;font-weight:700;color:var(--green)}}
  ol.iss-list{{list-style:none;margin:0;padding:0;counter-reset:iss}}
  ol.iss-list li{{counter-increment:iss;display:flex;align-items:baseline;gap:10px;padding:6px 0;border-top:1px solid #f2ded9;font-size:13px}}
  ol.iss-list li:first-child{{border-top:0}}
  ol.iss-list li::before{{content:counter(iss);flex:none;width:18px;height:18px;border-radius:50%;background:var(--red);color:#fff;font-size:10.5px;font-weight:800;display:inline-flex;align-items:center;justify-content:center;align-self:center}}
  .iss-name{{font-weight:800;color:var(--ink);flex:1;min-width:150px}}
  .iss-vs{{color:#8a3b30;font-variant-numeric:tabular-nums}} .iss-vs b{{color:var(--red)}}
  .iss-own{{margin-left:auto;font-size:11.5px;font-weight:700;color:var(--brown);background:var(--cream);border:1px solid var(--line);border-radius:999px;padding:2px 10px;white-space:nowrap}}
  .gridwrap{{overflow-x:auto;border:1px solid var(--line);border-radius:14px;background:var(--card);padding:6px;box-shadow:0 1px 2px rgba(80,50,30,.04)}}
  table.scgrid{{border-collapse:collapse;font-size:12px;width:auto;table-layout:auto}}
  table.scgrid th,table.scgrid td{{padding:3px 7px;text-align:center;border-bottom:1px solid var(--line);white-space:nowrap}}
  table.scgrid thead th{{font-size:10.5px;text-transform:uppercase;color:var(--muted);font-weight:700;position:sticky;top:0;background:#fff;z-index:1}}
  th.gm,td.gm{{text-align:left;position:sticky;left:0;background:#fff;min-width:96px;max-width:118px;border-right:1px solid var(--line);z-index:2}}
  table.scgrid thead th.gm{{z-index:3}}
  .scgrid td:not(.gm):not(.gp),.scgrid th:not(.gm):not(.gp){{min-width:62px}}
  td.gm .gmn{{font-weight:600;font-size:10.5px;display:block;line-height:1.12;white-space:normal}} td.gm .gmo{{font-size:9px;color:var(--muted)}} td.gm .gmo b{{color:var(--brown)}}
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
  .md-storebar{{display:flex;align-items:center;gap:8px;margin:2px 0 12px}} .md-storebar .lbl{{font-size:12.5px;color:var(--muted);font-weight:600}}
  .md-storebar .stsel{{font-size:13px;padding:6px 10px}}
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
  /* F1 Op's Excellence detail (mirrors Company Dashboard) */
  .tag{{display:inline-block;padding:2px 7px;border-radius:6px;font-size:11px;font-weight:800;line-height:1.3}}
  .tag.t-ok{{background:var(--greenbg);color:var(--green)}} .tag.t-amber{{background:#f6ecd7;color:#8a6d3b}}
  .tag.t-red{{background:var(--redbg);color:var(--red)}} .tag.t-na{{background:#efe8df;color:#9a8c7c}}
  /* Bench detail — mirrors the Company Dashboard bench tab; scoped so panel classes don't clash */
  .eosbench .tab-panel{{display:block}}
  .eosbench .cards{{display:grid;gap:12px;margin:4px 0 10px}}
  .eosbench .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}
  .eosbench .card .lbl{{font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.03em}}
  .eosbench .card .val{{font-size:26px;font-weight:800;line-height:1.1;margin-top:2px}}
  .eosbench .card .meta{{font-size:11px;color:var(--muted);margin-top:3px}}
  .eosbench .note{{font-size:12px;color:#5b4a3d;line-height:1.5;margin:8px 0}}
  .eosbench .section-title{{font-size:14px;font-weight:800;color:var(--ink);margin:16px 0 7px}}
  .eosbench .panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}}
  .eosbench .mini{{font-size:11px;color:var(--muted);line-height:1.45;margin-top:8px}}
  .eosbench table.scorecard{{border-collapse:collapse;width:100%;font-size:12px}}
  .eosbench table.scorecard th,.eosbench table.scorecard td{{border:1px solid var(--line);padding:5px 8px;text-align:center}}
  .eosbench table.scorecard thead th{{background:var(--greybg);font-weight:800;color:var(--brown)}}
  .f1cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:2px 0 12px}}
  .f1card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 14px}}
  .f1card .lbl{{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:800}}
  .f1card .val{{font-size:26px;font-weight:800;color:var(--brown);line-height:1.1;margin-top:3px}}
  .f1card .meta{{font-size:11px;color:var(--muted);margin-top:2px}}
  .f1note{{font-size:12px;color:#3f5b45;background:var(--greenbg);border:1px solid #cfe6d8;border-radius:10px;padding:10px 13px;margin:4px 0 14px;line-height:1.5}}
  .f1sub{{font-size:13px;font-weight:800;color:var(--brown);margin:18px 0 9px}}
  .f1grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  @media (max-width:720px){{.f1grid2{{grid-template-columns:1fr}} .f1cards{{grid-template-columns:1fr}}}}
  .f1panel{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 14px;overflow-x:auto}}
  .f1ph{{font-size:12.5px;font-weight:800;color:var(--brown);margin-bottom:9px}}
  table.f1t{{border-collapse:collapse;width:100%;font-size:12px;min-width:420px}}
  table.f1t th,table.f1t td{{padding:5px 8px;border-bottom:1px solid var(--line);text-align:center;white-space:nowrap}}
  table.f1t th{{font-size:10px;text-transform:uppercase;color:var(--muted);font-weight:700}}
  table.f1t td.l,table.f1t th.l{{text-align:left}}
  .crow{{display:flex;align-items:center;gap:10px;margin:7px 0}}
  .crank{{width:20px;height:20px;border-radius:50%;background:var(--brown);color:#fff;font-size:11px;font-weight:800;display:flex;align-items:center;justify-content:center;flex:none}}
  .cbody{{flex:1;min-width:0}} .cname{{font-size:12.5px;font-weight:800;color:var(--ink)}}
  .cbar{{height:9px;border-radius:5px;background:var(--greybg);overflow:hidden;margin:3px 0}} .cbar>i{{display:block;height:100%;background:var(--gold)}}
  .csub{{font-size:10.5px;color:var(--muted)}}
  .cval{{font-size:16px;font-weight:800;color:var(--brown);text-align:right;flex:none}} .cval small{{font-size:9px;color:var(--muted);display:block;font-weight:600}}
  .spkwrap{{display:inline-flex;align-items:flex-end;gap:2px;height:20px}}
  .spk{{width:5px;background:var(--brown);border-radius:1px;display:inline-block}}
  .f1focus{{margin-top:16px;background:#fdf1ef;border:1px solid #eccfca;border-left:5px solid var(--red);border-radius:12px;padding:11px 15px;font-size:13px;color:#5b4a3d;line-height:1.5}} .f1focus .ar{{color:var(--red);font-weight:800;margin-right:6px}}
  .mini{{font-size:10.5px;color:var(--muted)}}
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
    {bts_btn}
  </div>

  <section class="pane active" id="pane-weekly">
    <div class="panehead">
      <span class="lbl">Week: <b>{WK}</b></span>
      <span class="tallychips"><span><span class="dot green"></span>{wg} on plan</span><span><span class="dot red"></span>{wr} off plan</span><span><span class="dot tbc"></span>{wt} TBC / awaiting</span></span>
    </div>
    {weekly_issues_html}
    <div class="grid">{weekly_html}</div>
  </section>

  <section class="pane" id="pane-quarterly">
    <div class="panehead">
      <span class="lbl">Quarter: <b>{QL}</b></span>
      <span class="tallychips"><span><span class="dot green"></span>{qg} on plan</span><span><span class="dot red"></span>{qr} off plan</span><span><span class="dot tbc"></span>{qt} TBC / awaiting</span></span>
    </div>
    {quarterly_issues_html}
    <div class="grid">{quarterly_html}</div>
  </section>

  <section class="pane" id="pane-grid">
    <div class="panehead">
      <span class="lbl">Quarter: <b>{QL}</b> · {n_grid_weeks} week{'' if n_grid_weeks==1 else 's'} · one column per week (Week 1…{n_grid_weeks}, hover for the date) · each cell traffic-lit vs plan</span>
    </div>
    <div class="gridwrap">{grid_html}</div>
    <div class="legend"><span><span class="sw" style="background:var(--greenbg);border:1px solid #cfe6d8"></span>on plan</span><span><span class="sw" style="background:var(--redbg);border:1px solid #eccfca"></span>off plan</span><span><span class="sw" style="background:var(--greybg);border:1px solid var(--line)"></span>no data</span><span>F1 is lower-is-better (green ≤ 175)</span></div>
  </section>

  <section class="pane" id="pane-detail">
    <div class="panehead mdbar">
      <span class="lbl">Measurable:</span>
      <select id="mdsel" class="mdsel">{md_options}</select>
      <span class="lbl">Per-store basis:</span>
      <select id="pdsel" class="mdsel"><option value="weekly" selected>Weekly (last week)</option><option value="qtd">Quarterly (QTD)</option></select>
    </div>
    <div class="md-wrap">{md_details}</div>
  </section>
{bts_pane}

  <div class="legend">
    <span><span class="sw" style="background:var(--greenbg);border:1px solid #cfe6d8"></span>actual ≥ plan (on plan)</span>
    <span><span class="sw" style="background:var(--redbg);border:1px solid #eccfca"></span>below plan (off plan)</span>
    <span><span class="sw" style="background:var(--greybg);border:1px solid var(--line)"></span>not yet defined / awaiting data</span>
  </div>

  <footer>Bewiched Limited · internal use · EOS Scorecard. Generated {GEN}.</footer>
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
      if(el){{ el.style.display='block';
        var bb = el.querySelector('[data-tab="bench"]');
        if(bb) bb.click();   // fires the bench map's own init()+invalidateSize once visible
      }}
    }}
    sel.addEventListener('change', function(){{ show(sel.value); }});
    show(sel.value);
  }})();
  (function(){{
    var pd = document.getElementById('pdsel');
    if(!pd) return;
    function period(basis){{
      document.querySelectorAll('.ps-basis').forEach(function(d){{
        d.style.display = (d.getAttribute('data-basis') === basis) ? 'block' : 'none';
      }});
    }}
    pd.addEventListener('change', function(){{ period(pd.value); }});
    period(pd.value);
  }})();
  (function(){{
    document.querySelectorAll('.stsel').forEach(function(sel){{
      var scope = sel.closest('.st-scope') || document;
      function show(v){{
        scope.querySelectorAll('[data-store]').forEach(function(d){{
          d.style.display = (d.getAttribute('data-store') === v) ? 'block' : 'none';
        }});
      }}
      sel.addEventListener('change', function(){{ show(sel.value); }});
      show(sel.value);
    }});
  }})();
</script>
</body>
</html>"""

open(os.path.join(HERE, "EOS_Scorecard.html"), "w").write(HTML)
print("Wrote EOS_Scorecard.html  (%d bytes)" % len(HTML))
print("Weekly: %dG/%dR/%dgrey | Quarterly: %dG/%dR/%dgrey" % (wg, wr, wt, qg, qr, qt))
print("leftover placeholders: none")
