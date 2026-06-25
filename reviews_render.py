#!/usr/bin/env python3
"""reviews_render.py — shared Customer (Google-reviews) rendering for the area /
company / coach generators. Renders the Overall / QTD / WTD tier table and the
Customer Voice sentiment block from the cust / cust_qtd / cust_wtd / cust_voice
fields that build_reviews.py writes into allstores.json. Pure HTML helpers — no
state — so every generator renders the same way and re-renders cleanly each run.
"""
import json

TAGK = {"Positive": "t-ok", "Mixed": "t-amber", "Negative": "t-red"}

def _ratk(v):
    return "t-ok" if v >= 4.7 else ("t-amber" if v >= 4.5 else "t-red")

def qlabel():
    try:
        return json.load(open("reviews_feed.json")).get("_qtd_label", "QTD")
    except Exception:
        return "QTD"

def _tier_cell(d):
    """QTD/WTD cell. Graceful: a dash when no reviews landed in that window."""
    if not d or not d.get("n"):
        return '<td><span style="color:#9a8a7c">&mdash;</span></td>'
    a = d.get("avg")
    if a is None:
        return f'<td><span class="mini">{d["n"]}</span></td>'
    return f'<td><span class="tag {_ratk(a)}">{a:.2f}&#9733;</span> <span class="mini">{d["n"]}</span></td>'

def cust_rows(stores, R, short):
    """Per-store row: Store | Overall (lifetime) | QTD | WTD."""
    cu = {s: R[s].get("cust", {"rating": None, "reviews": 0}) for s in stores}
    rated = [s for s in stores if cu[s].get("rating") is not None]
    out = ""
    for s in sorted(rated, key=lambda x: -(cu[x]["rating"] or 0)):
        v = cu[s]["rating"]
        ov = f'<td><span class="tag {_ratk(v)}">{v:.2f}&#9733;</span> <span class="mini">{cu[s].get("reviews",0):,}</span></td>'
        out += (f'<tr><td class="ms">{short(s)}</td>{ov}'
                f'{_tier_cell(R[s].get("cust_qtd"))}{_tier_cell(R[s].get("cust_wtd"))}</tr>')
    return out

def cust_voice(stores, R, short):
    """Customer Voice cards: sentiment label + recurring themes + recent quotes,
    for the in-scope stores that have recent comments (most active first)."""
    vs = [s for s in stores if R[s].get("cust_voice")]
    vs.sort(key=lambda s: -((R[s].get("cust_qtd") or {}).get("n") or 0))
    if not vs:
        return ('<div class="note">No recent customer comments in the review feed yet &mdash; '
                'stores appear here as their Google-review feed goes live.</div>')
    html = ""
    for s in vs:
        v = R[s]["cust_voice"]
        chip = f'<span class="tag {TAGK.get(v["label"],"t-na")}">{v["label"]}</span>'
        themes = (' <span class="mini">&middot; ' + " &middot; ".join(v["themes"]) + "</span>") if v.get("themes") else ""
        qs = "".join(
            f'<div style="font-size:12px;color:#5b4a37;margin:3px 0 0;line-height:1.45">'
            f'&ldquo;{q["t"]}&rdquo; <span class="mini">&mdash; {q["stars"]}&#9733; &middot; {q["d"]}</span></div>'
            for q in v.get("quotes", []))
        html += (f'<div style="border:1px solid #ece3d6;border-radius:10px;padding:8px 11px;margin-bottom:8px">'
                 f'<div style="font-size:12.5px"><b>{short(s)}</b> {chip}{themes}</div>{qs}</div>')
    return html
