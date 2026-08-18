#!/usr/bin/env python3
"""gen_franchise.py — Franchise Fees Scale dashboard (HoE / Ian's franchise stores).

Reads franchise_fees.json (written by run_weekly.pull_franchise) and writes franchise-fees.html:
a month dropdown driving a per-store view of Brand score, Remote score, Combined (/5 and /100),
the resulting royalty tier (fee scale keyed off the combined /5 where 4.6 = target), Royalty %,
Marketing %, Total Fee %, and the £ franchise fee for the month (Total% x monthly turnover).
A reference panel shows the full five-tier fee scale. Gated by apply_gate.py.
"""
import os, json, datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def _esc(s):
    import html
    return html.escape(str(s)) if s is not None else ""


def _mlabel(ym):
    try:
        return datetime.datetime.strptime(ym, "%Y-%m").strftime("%b %Y")
    except Exception:
        return ym


TIER_COL = {"Excelling": "#1f8a4c", "Above Target": "#c8912f", "On Target": "#1f8a4c",
            "Fail": "#c0392b", "Breakdown": "#8c2f22"}
TIER_BG = {"Excelling": "#e7f3ea", "Above Target": "#fbf1dd", "On Target": "#e7f3ea",
           "Fail": "#fbeae7", "Breakdown": "#f6dcd7"}


def build():
    try:
        D = json.load(open(os.path.join(HERE, "franchise_fees.json")))
    except Exception as e:
        html = ("<!doctype html><html><head><meta charset='utf-8'><title>Franchise Fees Scale</title></head>"
                "<body><h2>Franchise Fees Scale</h2><p>Awaiting franchise_fees.json (%s).</p></body></html>" % _esc(e))
        open(os.path.join(HERE, "franchise-fees.html"), "w", encoding="utf-8").write(html)
        print("[gen_franchise] placeholder written (no feed): %s" % e)
        return

    months = D.get("months") or []
    stores = D.get("stores") or []
    new_stores = D.get("new_stores") or []
    data = D.get("data") or {}
    scale = D.get("scale") or []
    updated = D.get("_updated", "")
    latest = months[-1] if months else None

    opts = "".join('<option value="%s"%s>%s</option>'
                   % (_esc(m), " selected" if m == latest else "", _esc(_mlabel(m)))
                   for m in reversed(months))

    def _pct(v):
        return ("%g%%" % v) if v is not None else "&mdash;"

    def _gbp(v):
        try:
            return "£%s" % format(int(round(float(v))), ",")
        except Exception:
            return "&mdash;"

    def _store_row(st, m):
        r = (data.get(st) or {}).get(m)
        if not r or not r.get("audit"):
            return ('<tr class="noaudit"><td class="l">%s</td>'
                    '<td colspan="9" class="na">no audit this month</td></tr>' % _esc(st))
        tier = r.get("tier", ""); col = TIER_COL.get(tier, "#5b3a29"); bg = TIER_BG.get(tier, "#efe9e2")
        badge = ('<span class="tier" style="color:%s;background:%s;border:1px solid %s">%s %s</span>'
                 % (col, bg, col, _esc(r.get("emoji", "")), _esc(tier)))
        b_n = r.get("brand_n", 0)
        brand = ("%.2f <span class='sub'>(%d)</span>" % (r["brand5"], b_n)) if r.get("brand5") is not None else "&mdash;"
        rem = ("%.1f <span class='sub'>/100</span>" % r["remote100"]) if r.get("remote100") is not None else "&mdash;"
        fee_gbp = _gbp(r.get("fee_gbp")) if r.get("fee_gbp") is not None else "<span class='pend'>pending turnover</span>"
        turn = ("<span class='sub'>on %s</span>" % _gbp(r.get("turnover"))) if r.get("turnover") is not None else ""
        return ('<tr><td class="l">%s</td>'
                '<td>%s</td><td>%s</td>'
                '<td class="cmb">%.2f</td><td class="cmb">%.1f</td>'
                '<td>%s</td>'
                '<td>%s</td><td>%s</td><td class="tot">%s</td>'
                '<td class="fee">%s %s</td></tr>'
                % (_esc(st), brand, rem, r["comb5"], r["comb100"], badge,
                   _pct(r.get("royalty")), _pct(r.get("marketing")), _pct(r.get("total_pct")),
                   fee_gbp, turn))

    def _new_row(ns):
        return ('<tr class="noaudit"><td class="l">%s</td>'
                '<td colspan="9" class="na">&#128679; opening soon &mdash; no assessments yet</td></tr>'
                % _esc(ns.get("store", "")))

    panels = ""
    for m in months:
        rows = "".join(_store_row(st, m) for st in stores)
        rows += "".join(_new_row(ns) for ns in new_stores)
        panels += (
            '<div class="mpanel" data-month="%s" style="display:%s">'
            '<table class="ft"><thead><tr>'
            '<th class="l">Store</th><th>Brand /5</th><th>Remote /100</th>'
            '<th>Combined /5</th><th>Combined /100</th><th>Tier</th>'
            '<th>Royalty %%</th><th>Marketing %%</th><th>Total Fee %%</th><th>&pound; Fee (month)</th>'
            '</tr></thead><tbody>%s</tbody></table></div>'
            % (_esc(m), "block" if m == latest else "none", rows))

    srows = "".join(
        '<tr><td class="l">%s</td><td><b style="color:%s">%s %s</b></td>'
        '<td>%g%%</td><td>%g%%</td><td class="tot">%g%%</td></tr>'
        % (_esc(s["band"]), TIER_COL.get(s["tier"], "#5b3a29"), _esc(s.get("emoji", "")),
           _esc(s["tier"]), s["royalty"], s["marketing"], s["total"])
        for s in scale)

    note = _esc(D.get("note", ""))
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Franchise Fees Scale &mdash; HoE / Ian's stores</title>
<style>
:root{--brown:#5b3a29;--brown2:#3f281c;--ink:#2b211b;--muted:#8a7a6d;--line:#e7ddd2;--bg:#f4efe9;--gold:#e7b35a;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.brandbar{background:linear-gradient(180deg,var(--brown),var(--brown2));color:#f6efe7;padding:16px 22px}
.brandbar h1{margin:0;font-size:20px;font-weight:800}
.brandbar .sub{font-size:12.5px;color:#e8dccf;margin-top:3px}
.wrap{max-width:1080px;margin:0 auto;padding:18px 22px 34px}
.bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:6px 0 16px}
.bar label{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:800}
select{font-size:15px;font-weight:700;color:var(--brown);padding:7px 12px;border:1px solid var(--line);border-radius:9px;background:#fff}
.legend{font-size:12.5px;color:var(--muted);background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px 13px;margin-bottom:14px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}
.ft th,.ft td{padding:9px 11px;font-size:13px;text-align:center;border-bottom:1px solid var(--line)}
.ft th{background:#efe7dd;color:var(--brown);font-weight:800;font-size:11.5px;text-transform:uppercase;letter-spacing:.03em}
.ft td.l,.ft th.l{text-align:left;font-weight:700;color:var(--brown)}
.ft td.cmb{font-weight:800;color:var(--brown)}
.ft td.tot{font-weight:800}
.ft td.fee{font-weight:800;color:var(--brown)}
.ft tr:last-child td{border-bottom:none}
.tier{display:inline-block;font-size:11.5px;font-weight:800;padding:2px 9px;border-radius:9px}
.sub{color:var(--muted);font-weight:500;font-size:11px}
.pend{color:var(--muted);font-style:italic;font-weight:500;font-size:11.5px}
.na{color:var(--muted);font-style:italic}
.noaudit td{background:#faf7f3}
.sech{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:800;margin:22px 0 9px;border-top:1px solid var(--line);padding-top:14px}
.scale th,.scale td{padding:8px 11px;font-size:13px;text-align:center;border-bottom:1px solid var(--line)}
.scale th{background:#efe7dd;color:var(--brown);font-weight:800;font-size:11.5px;text-transform:uppercase}
.scale td.l,.scale th.l{text-align:left}
.foot{font-size:11.5px;color:var(--muted);margin-top:12px}
</style></head>
<body>
<div class="brandbar"><h1>&#127970; Franchise Fees Scale &mdash; HoE / Ian&rsquo;s stores</h1>
<div class="sub">Royalty fees linked to brand execution &middot; keyed off the monthly Brand + Remote combined score (target 4.6/5 = 100/100) &middot; updated {updated}</div></div>
<div class="wrap">
<div class="bar"><label for="msel">Month</label>
<select id="msel">{opts}</select></div>
<div class="legend">Combined score = 50/50 blend of the <b>Brand audit</b> (/5) and <b>Remote assessment</b> (/100 &rarr; /5), on the /5 scale where <b>4.6 = the 100/100 target</b>. The royalty tier &amp; fee flex off that combined score; <b>&pound; Fee = Total Fee % &times; that month&rsquo;s turnover</b> (BigQuery). Months with no audit show &ldquo;no audit this month&rdquo;.</div>
{panels}
<div class="sech">Fee scale &mdash; royalty fees linked to brand execution (Proposed, NSO Month 2 onwards)</div>
<table class="scale"><thead><tr><th class="l">Combined score</th><th>Tier</th><th>Royalty %</th><th>Marketing %</th><th>Total Fee %</th></tr></thead>
<tbody>{srows}</tbody></table>
<div class="foot">{note} Boundary rule: score at a band&rsquo;s lower bound sits in that band (4.6 = On Target, 4.9 = Excelling, 4.4 = Fail). Both percentages are of the store&rsquo;s turnover.</div>
</div>
<script>
(function(){{
  var sel=document.getElementById('msel');
  var panels=[].slice.call(document.querySelectorAll('.mpanel'));
  function show(m){{panels.forEach(function(p){{p.style.display=(p.getAttribute('data-month')===m)?'block':'none';}});}}
  sel.addEventListener('change',function(){{show(sel.value);}});
}})();
</script>
</body></html>""".format(updated=_esc(updated), opts=opts, panels=panels, srows=srows, note=note)

    open(os.path.join(HERE, "franchise-fees.html"), "w", encoding="utf-8").write(html)
    print("[gen_franchise] wrote franchise-fees.html (%d months, %d stores + %d new)"
          % (len(months), len(stores), len(new_stores)))


if __name__ == "__main__":
    build()
