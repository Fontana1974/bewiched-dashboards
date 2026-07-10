#!/usr/bin/env python3
"""Bespoke 'New Starter Health' metric-detail renderer for the EOS Scorecard.
Self-contained (inline styles, only the dashboard's --green/--red colour vars) so it
never depends on other CSS. Reads D['new_starter'] written into eos_scorecard.json.
Returns '' -> safe placeholder on any missing data, so the EOS build never breaks."""
import html as _html


def _esc(s):
    return _html.escape(str(s)) if s is not None else ""


def new_starter_detail_html(D):
    ns = (D or {}).get("new_starter")
    if not ns:
        return ('<p style="color:#8a7a6d">New Starter Health detail unavailable this '
                'run (no Youda onboarding pull).</p>')

    steps = ns.get("per_step", []) or []
    sites = ns.get("per_site", []) or []
    starters = ns.get("per_starter", []) or []
    n = ns.get("cohort_n", 0)
    comp = ns.get("compliant", 0)
    head = ns.get("headline", 0)
    src = ns.get("generated", "")

    P = []

    # ---- headline banner ----
    P.append(
        '<div style="margin:4px 0 16px;padding:14px 16px;border-radius:12px;'
        'background:#faf6f0;border:1px solid #ece3d6">'
        '<div style="font-size:13px;color:#8a7a6d;letter-spacing:.02em">'
        'ONBOARDING COMPLIANCE &middot; FIRST 90 DAYS</div>'
        '<div style="margin-top:2px"><span style="font-size:30px;font-weight:800;'
        'color:var(--red)">%s%%</span> '
        '<span style="color:#5c5148">fully compliant</span> '
        '<span style="color:#8a7a6d">&mdash; %s of %s starters are clear of every '
        'step that is due. Target 90%%.</span></div></div>' % (_esc(head), _esc(comp), _esc(n)))

    # ---- per-step completion bars ----
    P.append('<h4 style="margin:16px 0 4px;font-size:15px">Step completion</h4>')
    P.append('<p style="margin:0 0 8px;color:#8a7a6d;font-size:13px">Of the new starters '
             'who have each step active on their Youda checklist, the share marked '
             '<b>done</b>. Right to Work is verified for the whole cohort; the timed '
             'check-ins are largely unlogged in Youda &mdash; the clearest lever here.</p>')
    P.append('<table style="width:100%;border-collapse:collapse;font-size:14px">')
    for s in steps:
        lab = s.get("label", "")
        pct = s.get("pct")
        tgt = s.get("target", 90)
        done = s.get("done", 0)
        pres = s.get("present", 0)
        ovd = s.get("overdue", 0)
        if pct is None:
            barw, col, val = 0, "#ccc", "&mdash;"
            chip = '<span style="color:#8a7a6d">not tracked</span>'
        else:
            barw = max(2, min(100, pct))
            ok = pct >= tgt
            col = "var(--green)" if ok else "var(--red)"
            chip = ('<span style="color:%s;font-weight:700">%s</span>'
                    % (col, "ON" if ok else "OFF"))
            val = "%s%%" % pct
        meta = "%s/%s active" % (done, pres) + (" &middot; %s overdue" % ovd if ovd else "")
        P.append(
            '<tr style="border-bottom:1px solid #f0e9de">'
            '<td style="padding:7px 8px;white-space:nowrap">%s</td>'
            '<td style="padding:7px 8px;width:42%%">'
            '<div style="background:#efe8dd;border-radius:6px;height:14px">'
            '<div style="width:%s%%;height:14px;border-radius:6px;background:%s"></div></div></td>'
            '<td style="padding:7px 8px;text-align:right;font-weight:700;width:52px">%s</td>'
            '<td style="padding:7px 8px;text-align:right;color:#8a7a6d;white-space:nowrap">%s</td>'
            '<td style="padding:7px 8px;text-align:right;width:44px">%s</td>'
            '</tr>' % (_esc(lab), barw, col, val, meta, chip))
    P.append('</table>')

    # ---- by site ----
    if sites:
        P.append('<h4 style="margin:20px 0 4px;font-size:15px">By site</h4>')
        P.append('<p style="margin:0 0 8px;color:#8a7a6d;font-size:13px">New starters fully '
                 'on track vs total new starters, per site (first 90 days).</p>')
        P.append('<table style="width:100%;border-collapse:collapse;font-size:14px">')
        for r in sites:
            site = r.get("site", ""); c = r.get("compliant", 0)
            tot = r.get("total", 0); pct = r.get("pct", 0)
            col = "var(--green)" if pct >= 90 else "var(--red)"
            P.append(
                '<tr style="border-bottom:1px solid #f0e9de">'
                '<td style="padding:6px 8px">%s</td>'
                '<td style="padding:6px 8px;text-align:right;color:#8a7a6d">%s of %s on track</td>'
                '<td style="padding:6px 8px;text-align:right;font-weight:700;color:%s;width:52px">%s%%</td>'
                '</tr>' % (_esc(site), _esc(c), _esc(tot), col, _esc(pct)))
        P.append('</table>')

    # ---- starter watchlist ----
    if starters:
        P.append('<h4 style="margin:20px 0 4px;font-size:15px">Starter watchlist</h4>')
        P.append('<p style="margin:0 0 8px;color:#8a7a6d;font-size:13px">Every first-90-day '
                 'starter with the steps still outstanding against them, longest-tenure first.</p>')
        P.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
        P.append('<tr style="text-align:left;color:#8a7a6d;border-bottom:2px solid #ece3d6">'
                 '<th style="padding:6px 8px">Starter</th><th style="padding:6px 8px">Site</th>'
                 '<th style="padding:6px 8px;text-align:right">Tenure</th>'
                 '<th style="padding:6px 8px">Outstanding</th></tr>')
        rows = sorted(starters, key=lambda r: -(r.get("tenure") or 0))
        for r in rows:
            out = r.get("outstanding") or []
            if out:
                items = ", ".join(_esc(x) for x in out)
                oc = '<span style="color:var(--red)">%s</span>' % items
            else:
                oc = '<span style="color:var(--green)">clear</span>'
            P.append(
                '<tr style="border-bottom:1px solid #f4efe6">'
                '<td style="padding:6px 8px;white-space:nowrap">%s</td>'
                '<td style="padding:6px 8px;color:#5c5148">%s</td>'
                '<td style="padding:6px 8px;text-align:right;color:#8a7a6d">%sd</td>'
                '<td style="padding:6px 8px">%s</td></tr>'
                % (_esc(r.get("name", "")), _esc(r.get("site", "")),
                   _esc(r.get("tenure", "")), oc))
        P.append('</table>')

    if src:
        P.append('<p style="margin:12px 0 0;color:#a99;font-size:12px">Source: Youda '
                 'onboarding journey &middot; pulled %s</p>' % _esc(src))
    return "".join(P)
