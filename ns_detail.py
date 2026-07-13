#!/usr/bin/env python3
"""New Starter Health metric-detail renderer for the EOS Scorecard.
Adds an All-stores / per-store dropdown (mirrors the EOS per-store pattern): the company view is the
default; selecting a store filters the journey matrix, step completion, compliance and watchlist to
that store's starters only. Self-contained (inline styles + the dashboard's --green/--red vars).
Reads D['new_starter'] (per_starter/per_site/per_step) from eos_scorecard.json; '' -> safe on missing."""
import html as _html


def _esc(s):
    return _html.escape(str(s)) if s is not None else ""


def _step_stats(subset, labels):
    """Recompute per-step completion for a subset of starters (used for the per-store views)."""
    out = []
    for l in labels:
        present = done = overdue = 0
        for r in subset:
            st = (r.get("steps") or {}).get(l)
            if st in ("done", "overdue", "due"):
                present += 1
                if st == "done":
                    done += 1
                elif st == "overdue":
                    overdue += 1
        pct = round(100 * done / present) if present else None
        out.append({"label": l, "pct": pct, "done": done, "present": present, "overdue": overdue, "target": 90})
    return out


def _body(starters, steps, sites, head, comp, n):
    """Headline + step completion + journey matrix + by-site + watchlist for a (possibly filtered) set."""
    P = []
    hcol = "var(--green)" if (isinstance(head, (int, float)) and head >= 90) else "var(--red)"
    P.append(
        '<div style="margin:4px 0 16px;padding:14px 16px;border-radius:12px;background:#faf6f0;border:1px solid #ece3d6">'
        '<div style="font-size:13px;color:#8a7a6d;letter-spacing:.02em">ONBOARDING COMPLIANCE &middot; FIRST 90 DAYS</div>'
        '<div style="margin-top:2px"><span style="font-size:30px;font-weight:800;color:%s">%s%%</span> '
        '<span style="color:#5c5148">fully compliant</span> '
        '<span style="color:#8a7a6d">&mdash; %s of %s starters are clear of every step that is due. Target 90%%.</span></div></div>'
        % (hcol, _esc(head), _esc(comp), _esc(n)))

    P.append('<h4 style="margin:16px 0 4px;font-size:15px">Step completion</h4>')
    P.append('<p style="margin:0 0 8px;color:#8a7a6d;font-size:13px">Of the starters who have each step '
             'active on their Youda checklist, the share marked <b>done</b>.</p>')
    P.append('<table style="width:100%;border-collapse:collapse;font-size:14px">')
    for s in steps:
        lab = s.get("label", ""); pct = s.get("pct"); tgt = s.get("target", 90)
        done = s.get("done", 0); pres = s.get("present", 0); ovd = s.get("overdue", 0)
        if pct is None:
            barw, col, val = 0, "#ccc", "&mdash;"; chip = '<span style="color:#8a7a6d">not tracked</span>'
        else:
            barw = max(2, min(100, pct)); ok = pct >= tgt; col = "var(--green)" if ok else "var(--red)"
            chip = '<span style="color:%s;font-weight:700">%s</span>' % (col, "ON" if ok else "OFF"); val = "%s%%" % pct
        meta = "%s/%s active" % (done, pres) + (" &middot; %s overdue" % ovd if ovd else "")
        P.append(
            '<tr style="border-bottom:1px solid #f0e9de">'
            '<td style="padding:7px 8px;white-space:nowrap">%s</td>'
            '<td style="padding:7px 8px;width:42%%"><div style="background:#efe8dd;border-radius:6px;height:14px">'
            '<div style="width:%s%%;height:14px;border-radius:6px;background:%s"></div></div></td>'
            '<td style="padding:7px 8px;text-align:right;font-weight:700;width:52px">%s</td>'
            '<td style="padding:7px 8px;text-align:right;color:#8a7a6d;white-space:nowrap">%s</td>'
            '<td style="padding:7px 8px;text-align:right;width:44px">%s</td></tr>'
            % (_esc(lab), barw, col, val, meta, chip))
    P.append('</table>')

    if starters:
        labels = [s.get("label", "") for s in steps]
        DOT = {"done": "var(--green)", "overdue": "var(--red)", "due": "#d99a2b"}
        P.append('<h4 style="margin:20px 0 4px;font-size:15px">Employee journey matrix</h4>')
        P.append('<p style="margin:0 0 10px;color:#8a7a6d;font-size:13px">Every first-90-day starter '
                 '(row) against each onboarding step (column). '
                 '<span style="color:var(--green);font-weight:700">&#9679; complete</span> &middot; '
                 '<span style="color:var(--red);font-weight:700">&#9679; overdue</span> &middot; '
                 '<span style="color:#d99a2b;font-weight:700">&#9679; due / in progress</span> &middot; '
                 '<span style="color:#c9bcab;font-weight:700">&#9679; not yet due</span>.</p>')
        P.append('<div style="overflow-x:auto"><table style="border-collapse:collapse;font-size:12px">')
        hd = ('<tr><th style="text-align:left;vertical-align:bottom;padding:4px 8px;'
              'color:#8a7a6d;font-size:11px">Starter</th>')
        for l in labels:
            hd += ('<th style="vertical-align:bottom;padding:4px 3px">'
                   '<div style="writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;'
                   'height:104px;font-size:11px;font-weight:700;color:#5c5148">%s</div></th>' % _esc(l))
        hd += '</tr>'
        P.append(hd)
        for r in sorted(starters, key=lambda x: -(x.get("tenure") or 0)):
            sm = r.get("steps") or {}; cells = ""
            for l in labels:
                st = sm.get(l, "na"); c = DOT.get(st)
                if c:
                    dot = ('<span style="display:inline-block;width:13px;height:13px;border-radius:50%%;'
                           'background:%s"></span>' % c)
                else:
                    dot = ('<span style="display:inline-block;width:7px;height:7px;border-radius:50%%;'
                           'background:#ddd3c4"></span>')
                cells += ('<td title="%s: %s" style="text-align:center;padding:5px 7px;'
                          'border-bottom:1px solid #f4efe6">%s</td>' % (_esc(l), _esc(st), dot))
            cn = ('<td style="padding:5px 8px;white-space:nowrap;border-bottom:1px solid #f4efe6">'
                  '%s <span style="color:#a99;font-size:10px">%s</span></td>'
                  % (_esc(r.get("name", "")), _esc(r.get("site", ""))))
            P.append('<tr>' + cn + cells + '</tr>')
        P.append('</table></div>')

    if sites:
        P.append('<h4 style="margin:20px 0 4px;font-size:15px">By site</h4>')
        P.append('<table style="width:100%;border-collapse:collapse;font-size:14px">')
        for r in sites:
            site = r.get("site", ""); c = r.get("compliant", 0); tot = r.get("total", 0); pct = r.get("pct", 0)
            col = "var(--green)" if pct >= 90 else "var(--red)"
            P.append(
                '<tr style="border-bottom:1px solid #f0e9de"><td style="padding:6px 8px">%s</td>'
                '<td style="padding:6px 8px;text-align:right;color:#8a7a6d">%s of %s on track</td>'
                '<td style="padding:6px 8px;text-align:right;font-weight:700;color:%s;width:52px">%s%%</td></tr>'
                % (_esc(site), _esc(c), _esc(tot), col, _esc(pct)))
        P.append('</table>')

    if starters:
        P.append('<h4 style="margin:20px 0 4px;font-size:15px">Starter watchlist</h4>')
        P.append('<p style="margin:0 0 8px;color:#8a7a6d;font-size:13px">Every first-90-day '
                 'starter with the steps still outstanding against them, longest-tenure first.</p>')
        P.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
        P.append('<tr style="text-align:left;color:#8a7a6d;border-bottom:2px solid #ece3d6">'
                 '<th style="padding:6px 8px">Starter</th><th style="padding:6px 8px">Site</th>'
                 '<th style="padding:6px 8px;text-align:right">Tenure</th>'
                 '<th style="padding:6px 8px">Outstanding</th></tr>')
        for r in sorted(starters, key=lambda r: -(r.get("tenure") or 0)):
            out = r.get("outstanding") or []
            oc = ('<span style="color:var(--red)">%s</span>' % ", ".join(_esc(x) for x in out)) if out \
                else '<span style="color:var(--green)">clear</span>'
            P.append(
                '<tr style="border-bottom:1px solid #f4efe6">'
                '<td style="padding:6px 8px;white-space:nowrap">%s</td>'
                '<td style="padding:6px 8px;color:#5c5148">%s</td>'
                '<td style="padding:6px 8px;text-align:right;color:#8a7a6d">%sd</td>'
                '<td style="padding:6px 8px">%s</td></tr>'
                % (_esc(r.get("name", "")), _esc(r.get("site", "")), _esc(r.get("tenure", "")), oc))
        P.append('</table>')

    return "".join(P)


def new_starter_detail_html(D):
    ns = (D or {}).get("new_starter")
    if not ns:
        return ('<p style="color:#8a7a6d">New Starter Health detail unavailable this '
                'run (no Youda onboarding pull).</p>')
    steps = ns.get("per_step", []) or []
    sites = ns.get("per_site", []) or []
    starters = ns.get("per_starter", []) or []
    n = ns.get("cohort_n", 0); comp = ns.get("compliant", 0); head = ns.get("headline", 0)
    src = ns.get("generated", "")
    labels = [s.get("label", "") for s in steps]
    site_row = {r.get("site"): r for r in sites}

    all_view = _body(starters, steps, sites, head, comp, n)
    stores = sorted({(r.get("site") or "").strip() for r in starters if (r.get("site") or "").strip()})
    opts = ['<option value="__all__">All stores</option>']
    variants = ['<div data-store="__all__">%s</div>' % all_view]
    for st in stores:
        sub = [r for r in starters if (r.get("site") or "").strip() == st]
        sr = site_row.get(st, {})
        s_comp = sr.get("compliant", sum(1 for r in sub if not (r.get("outstanding") or [])))
        s_tot = sr.get("total", len(sub))
        s_head = sr.get("pct", round(100 * s_comp / s_tot) if s_tot else 0)
        s_steps = _step_stats(sub, labels)
        opts.append('<option value="%s">%s</option>' % (_esc(st), _esc(st)))
        variants.append('<div data-store="%s" style="display:none">%s</div>'
                        % (_esc(st), _body(sub, s_steps, [sr] if sr else [], s_head, s_comp, s_tot)))
    bar = ('<div class="md-storebar"><span class="lbl">Store:</span> '
           '<select class="stsel mdsel">%s</select></div>' % "".join(opts))
    foot = ('<p style="margin:12px 0 0;color:#a99;font-size:12px">Source: Youda '
            'onboarding journey &middot; pulled %s</p>' % _esc(src)) if src else ""
    return '<div class="st-scope">%s%s%s</div>' % (bar, "".join(variants), foot)
