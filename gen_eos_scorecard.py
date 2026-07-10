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
    ("Google Health", "google_health_pct", 100, "pct0"),
    ("Rate My Shift Health", "rms_pct", 100, "pct0"),
    ("Brew Crew Kudos Participation", "kudos_pct", 50, "pct0"),
    ("Social Media Engagement", None, None, "pct0"),
    ("SPH Labour (incl holiday pay)", "sph", 55, "gbp1"),
    ("Bench", None, 3, "num_signed"),
    ("F1 Score", "f1_avg", 220, "num1"),
    ("Brand & Remote Assessment", "brand_audit", 4.6, "score2"),
    ("Food GP%", "estate_gp_pct", 71, "pct1"),
    ("Net Profit After Tax (projected)", "npat_proj_pct", 18, "pct1"),
    ("New Starter Health", None, 90, "pct0"),
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
    "Bench": "Net Store Managers on the bench — the surplus (or shortfall) of ready SM cover. Target is a +3 surplus; the actual goes negative while SM vacancies exist (each open Store Manager = -1).",
    "F1 Score": "Average F1 'race' total score across the estate — operational excellence. Lower is better (target ≤220).",
    "Brand & Remote Assessment": "50/50 blend of brand audit + remote assessment, out of 5.",
    "Food GP%": "Estate gross-profit margin from the Cost-of-Sales sheet (authoritative Gross Profit%, col Q).",
    "Net Profit After Tax (projected)": "Projected net-profit margin after tax, flexed off the latest P&L.",
    "New Starter Health": "Share of first-90-day new starters compliant on every due onboarding step (Youda). Target 90%.",
}
CALCS = {
    "YoY Sales Growth": "Σ this-period sales ÷ Σ same-period-last-year sales − 1, across stores trading in BOTH periods (like-for-like). New and closed sites are excluded.",
    "YoY Transactional Growth": "Same like-for-like basis as sales, but using distinct order counts instead of value.",
    "Google Health": "Average of (reviews ÷ 40) and (rating ÷ 4.6), each capped at 100%, ×100. The QTD volume divisor scales by the number of weeks in the quarter.",
    "Rate My Shift Health": "Average of (submissions ÷ 70) and (average score ÷ 4.6), each capped at 100%, ×100. The QTD volume divisor scales by weeks in the quarter.",
    "Brew Crew Kudos Participation": "Distinct employees who gave kudos (BCKH tab, matched by email to the Employee List) ÷ total employee headcount.",
    "Social Media Engagement": "Not yet defined — awaiting the metric definition and target.",
    "SPH Labour (incl holiday pay)": "Estate sales ÷ labour hours used (from the area planners, Section A), hours-weighted. QTD is hours-weighted across the quarter's weeks in weekly_history.csv.",
    "Bench": "MAIN KPI = net SM on the bench. Actual = -(number of Store Manager vacancies) from the HRP 'HRP & Bench' roster (the red 'Gap / no SM' stores); target = +3; miss = target - actual (e.g. -3 vs +3 = 6 off, red). The star map, management-team table and Bench-ready / Thin / Capability-gap cards below are unchanged and byte-identical to the Company Dashboard bench tab (hierarchy-gap rule).",
    "F1 Score": "Average of each store's race Total Score. Weekly = last completed week's race; QTD = quarter-to-date average. LOWER IS BETTER on this scale — green at or below the target of ≤220, red above.",
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

def ps_table(rows_in, basis, psplan, dirn, fmt, informational=False):
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
    return ('<div class="md-ps-basis">%s · %s <b>%s</b> · %d stores</div>'
            '<table class="md-ps"><thead><tr><th>Store</th><th class="v">Value</th>%s<th class="st">%s</th>'
            '<th class="bar"></th></tr></thead><tbody>%s</tbody></table>'
            % (esc(basis), ref_lbl, ref_txt, len(rows), tgt_head, ("" if informational else "vs plan"), body))

def _ps_one(name, basis_key, plan, dirn, fmt):
    """One per-store table for the given basis ('weekly'|'qtd'), or None if absent."""
    entry = PS.get(name)
    if not entry: return None
    b = entry.get(basis_key)
    if not b or not b.get("rows"): return None
    psplan = entry.get("plan")
    if psplan is None: psplan = plan
    return ps_table(b["rows"], b.get("basis", ""), psplan, dirn, fmt)

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

    cards = ('<div class="f1cards">'
             '<div class="f1card"><div class="lbl">Constructor &mdash; avg race finish</div><div class="val">P%s</div><div class="meta">across %d stores &middot; latest race</div></div>'
             '<div class="f1card"><div class="lbl">Avg championship points</div><div class="val">%s</div><div class="meta">latest race &middot; higher = better</div></div>'
             '<div class="f1card"><div class="lbl">Top of the grid</div><div class="val" style="color:var(--green)">%s</div><div class="meta">%s</div></div>'
             '</div>' % (avg_fin, len(stores), champ_avg, f1_top, f1_top_meta))
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
    champ_block = ('<div class="f1sub">&#127942; Constructors&rsquo; Championship <span class="mini">&middot; avg points/store &middot; since 25 Apr</span></div>'
                   '<div class="f1grid2">'
                   '<div class="f1panel"><div class="f1ph">Constructors&rsquo; standings <span class="mini">&middot; area coaches by avg pts/store</span></div>%s<div class="mini" style="margin-top:9px">%s</div></div>'
                   '<div class="f1panel"><div class="f1ph">Drivers&rsquo; leaderboard <span class="mini">&middot; all stores by total pts</span></div>'
                   '<table class="f1t"><thead><tr><th>#</th><th class="l">Store (driver)</th><th>Coach</th><th>Pts</th></tr></thead><tbody>%s</tbody></table></div>'
                   '</div>' % (con_html, con_note, drv_rows))

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
    weekly_group = ('<div class="ps-basis" data-basis="weekly" style="display:block">'
                    + cards + finish_block + race_block + quali_block + focus + '</div>')
    qtd_group = ('<div class="ps-basis" data-basis="qtd" style="display:none">'
                 + champ_block + race_qtd_block + quali_qtd_block + '</div>')
    _f1st = F1D.get("_stale") or {}
    _badge = ('<div class="md-note" style="background:var(--redbg);border:1px solid #eccfca;color:#8c2f22;font-weight:800;margin-bottom:12px">&#9888; %s &mdash; the F1 figures below are the last completed audit, not this week\'s.</div>'
              % esc(_f1st.get("badge", "F1 awaiting this week's audit"))) if _f1st.get("stale") else ""
    return (_badge + intro + hint + weekly_group + qtd_group)


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
    return '<div class="md-section-h">Store-by-store &mdash; who is posting</div>' + table + voice


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
        detail = ('<div class="md-section-h">This quarter, week by week</div>'
                  + trend_svg(name, plan, dirn)
                  + yoy_bystore_html("Sales last week (%s) — by store, this year vs last year" % D.get("week_label", ""))
                  + weekend_html("sales") + weekend_bystore_html("sales")
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
                  + (_br if _br else '<div class="md-note">Brand &amp; remote breakdown unavailable this run.</div>'))
    elif name == "New Starter Health":
        _ns = ns_detail.new_starter_detail_html(D) if ns_detail else ""
        detail = ('<div class="md-section-h">New Starter Health &mdash; onboarding compliance (first 90 days)</div>'
                  + (_ns if _ns else '<div class="md-note">New Starter Health detail unavailable this run (new_starter.json / ns_detail missing).</div>'))
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
    <div class="legend"><span><span class="sw" style="background:var(--greenbg);border:1px solid #cfe6d8"></span>on plan</span><span><span class="sw" style="background:var(--redbg);border:1px solid #eccfca"></span>off plan</span><span><span class="sw" style="background:var(--greybg);border:1px solid var(--line)"></span>no data</span><span>F1 is lower-is-better (green ≤ 220)</span></div>
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
</script>
</body>
</html>"""

open(os.path.join(HERE, "EOS_Scorecard.html"), "w").write(HTML)
print("Wrote EOS_Scorecard.html  (%d bytes)" % len(HTML))
print("Weekly: %dG/%dR/%dgrey | Quarterly: %dG/%dR/%dgrey" % (wg, wr, wt, qg, qr, qt))
print("leftover placeholders: none")
