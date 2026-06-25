#!/usr/bin/env python3
"""build_reviews.py — Customer / Google-reviews feed for the Bewiched dashboards.

Reads the "Bewiched - Google Reviews" sheet rows (saved verbatim by the weekly
runbook to reviews_raw.json) and computes, per canonical store, the QTD and WTD
review count + average rating and a short "Customer Voice" sentiment read from the
most recent comments. Merges the result into allstores.json (rec[store] gains
cust_qtd / cust_wtd / cust_voice) and also writes a standalone reviews_feed.json.

OVERALL (lifetime) rating+count is NOT touched here — it stays sourced as today
(rec[store]['cust'], the lifetime headline). This script only ADDS the QTD/WTD/voice
tiers, so it is safe to run after the existing STEP 2l cust computation.

Usage:  python3 build_reviews.py [cur_end=YYYY-MM-DD]
  cur_end = the run's "last complete Sunday" (the Sunday-preview run passes its
  Sunday override). Defaults to the last complete Sunday relative to today.
  QTD = calendar quarter containing cur_end, up to cur_end.
  WTD = the Mon-Sun week ending on cur_end (the just-completed trading week).
"""
import json, re, sys, datetime as dt
from collections import Counter

RAW   = "reviews_raw.json"
STORE = "allstores.json"
FEED  = "reviews_feed.json"

# ---- review-sheet label -> canonical dashboard store (mirrors gen_company.DRVMAP,
#      extended). Value None => drop (not a current dashboard store). ----
REVIEW_MAP = {
    # live-fed labels (2026)
    "Attleborough": "Attleborough",
    "Billing Drive Thru": "Billing Drive Thru",
    "Billing DT": "Billing Drive Thru",
    "Burton": "Burton Latimer",
    "Corby": "Corby",
    "Glenvale Drive Thru": "Glenvale Drive Thru",
    "Olney": "Olney",
    "Train Station": "Wellingborough Train Station",
    # historical / other GBP-style labels
    "Fletton": "Peterborough Fletton Quays",
    "Lakes": "Rushden Lakes",
    "Rushden Lakes": "Rushden Lakes",
    "Peterborough": "Peterborough Bridge Street",
    "Kettering": "Kettering",
    "Rothwell": "Rothwell",
    "Rugby": "Rugby",
    "Higham": "Higham Ferrers",
    "Higham Ferrers": "Higham Ferrers",
    "Market Harborough": "Market Harborough",
    "Northampton Grosvenor": "Northampton",
    "Northampton": "Northampton",
    "Northampton Drive Thru": "Northampton Drive-Thru",
    "Northampton Drive-Thru": "Northampton Drive-Thru",
    "Market Street": "Wellingborough",
    "Wellingborough": "Wellingborough",
    "Wellingborough Train Station": "Wellingborough Train Station",
    "Lower Heathcote": "Lower Heathcote",
    "Lower Heathcote, Warwick": "Lower Heathcote",
    "Balsall Common": "HOE Balsall Common",
    "HOE Balsall Common": "HOE Balsall Common",
    "Leamington Parade": "Leamington Parade",
    "Leamington Retail": None,   # OLD/closed retail-park site - NOT Leamington Parade. Drop.
    "Leam Retail": None,
    "Olney Drive Thru": "Olney",
}

MONTHS = ["", "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)          # M/D/YYYY
    if m:
        mo, da, yr = map(int, m.groups())
        try: return dt.date(yr, mo, da)
        except ValueError: return None
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', s)            # ISO YYYY-MM-DD[ HH:MM:SS]
    if m:
        yr, mo, da = map(int, m.groups())
        try: return dt.date(yr, mo, da)
        except ValueError: return None
    m = re.match(r'Date\((\d+),(\d+),(\d+)', s)                 # Date(y,m0,d) - month 0-based
    if m:
        yr, mo, da = int(m.group(1)), int(m.group(2)) + 1, int(m.group(3))
        try: return dt.date(yr, mo, da)
        except ValueError: return None
    return None

def clean_comment(c):
    """De-mojibake (UTF-8 bytes shown as Latin-1) and strip non-text noise."""
    c = c or ""
    if any(ch in c for ch in ("Ã", "ð", "â", "Â")):
        try: c = c.encode("latin-1", "ignore").decode("utf-8", "ignore")
        except Exception: pass
    c = re.sub(r'\\([!.])', r'\1', c)            # unescape markdown \! \.
    c = "".join(ch for ch in c if ch == "\n" or ord(ch) >= 32)
    c = re.sub(r'[^\x09\x0a\x20-\x7e -ɏ‘’“”–—]', '', c)  # drop emoji/symbols
    c = re.sub(r'\s+', ' ', c).strip()
    return c

# ---- Customer Voice theme lexicon (recurring-theme tagging) ----
THEMES = [
    ("Friendly service", ["friend", "staff", "service", "welcom", "helpful", "lovely team",
                            "polite", "smile", "kind", "team"]),
    ("Great coffee",      ["coffee", "latte", "cappuccino", "flat white", "espresso", "mocha",
                            "americano", "barista", "brew"]),
    ("Food & bakery",     ["food", "breakfast", "cake", "bap", "sandwich", "pastry", "panini",
                            "toastie", "bagel", "lunch", "bacon", "sausage"]),
    ("Speed & queue",     ["quick", "fast", "speedy", "wait", "queue", "slow", "prompt", "efficient"]),
    ("Atmosphere & clean",["clean", "atmosphere", "ambien", "cosy", "cozy", "tidy", "comfortable",
                            "decor", "relax"]),
    ("Value",             ["price", "expensive", "value", "cheap", "cost", "overpriced", "worth"]),
]

def voice_for(rows, ref_end):
    """rows: [(date, stars, comment)] for one store (all time). Build the Voice box."""
    cutoff = ref_end - dt.timedelta(days=90)
    recent = [(d, st, c) for (d, st, c) in rows if d and d <= ref_end and d >= cutoff]
    recent.sort(key=lambda x: x[0])
    with_text = [(d, st, clean_comment(c)) for (d, st, c) in recent if clean_comment(c)]
    if not with_text:
        return None
    # sentiment label from the recent reviews that carry a rating (text ones)
    stars = [st for (d, st, c) in with_text if st is not None]
    avg = round(sum(stars) / len(stars), 2) if stars else None
    if avg is None:           label = "Positive"
    elif avg >= 4.5:          label = "Positive"
    elif avg >= 3.5:          label = "Mixed"
    else:                     label = "Negative"
    # recurring themes
    counts = Counter()
    for (d, st, c) in with_text:
        lc = c.lower()
        for name, kws in THEMES:
            if any(k in lc for k in kws):
                counts[name] += 1
    themes = [t for (t, n) in counts.most_common(3) if n >= 2] or [t for (t, n) in counts.most_common(2)]
    # 2-3 representative recent quotes (latest first, prefer ones with a bit of substance)
    pool = sorted(with_text, key=lambda x: x[0], reverse=True)
    quotes = []; seen = set()
    for (d, st, c) in pool:
        if len(c) < 15:
            continue
        key = c[:60].lower()
        if key in seen:        # skip near-identical duplicates
            continue
        seen.add(key)
        q = c if len(c) <= 160 else c[:157].rsplit(" ", 1)[0] + "…"
        quotes.append({"t": q, "stars": st, "d": f"{d.day} {MONTHS[d.month]}"})
        if len(quotes) == 3:
            break
    if not quotes:  # fall back to any non-empty
        for (d, st, c) in pool[:3]:
            quotes.append({"t": c, "stars": st, "d": f"{d.day} {MONTHS[d.month]}"})
    return {"label": label, "avg": avg, "themes": themes, "quotes": quotes, "n": len(with_text)}

def main():
    cur_end = None
    for a in sys.argv[1:]:
        if a.startswith("cur_end="):
            cur_end = parse_date(a.split("=", 1)[1])
    if cur_end is None:
        today = dt.date.today()
        week_monday = today - dt.timedelta(days=today.weekday())
        cur_end = week_monday - dt.timedelta(days=1)   # last complete Sunday
    # window bounds
    q_start = dt.date(cur_end.year, 3 * ((cur_end.month - 1) // 3) + 1, 1)
    w_start = cur_end - dt.timedelta(days=6)
    qlabel = f"Q{(cur_end.month - 1)//3 + 1} {cur_end.year}"

    rows = json.load(open(RAW))
    by_store = {}   # canonical -> list[(date, stars, comment)]
    dropped = Counter(); unmapped = Counter()
    for r in rows:
        lbl = (r.get("store") or "").strip()
        if not lbl:
            continue
        if lbl in REVIEW_MAP:
            canon = REVIEW_MAP[lbl]
            if canon is None:
                dropped[lbl] += 1
                continue
        else:
            unmapped[lbl] += 1
            continue
        d = parse_date(r.get("time"))
        try:
            st = int(float(r.get("star_rating"))) if str(r.get("star_rating")).strip() else None
        except (TypeError, ValueError):
            st = None
        by_store.setdefault(canon, []).append((d, st, r.get("comment") or ""))

    A = json.load(open(STORE))
    REC = A["rec"]
    feed = {"_qtd_label": qlabel, "_qtd_window": [q_start.isoformat(), cur_end.isoformat()],
            "_wtd_window": [w_start.isoformat(), cur_end.isoformat()], "stores": {}}

    for s in REC.keys():
        srows = by_store.get(s, [])
        def window(lo):
            sub = [(d, st) for (d, st, c) in srows if d and lo <= d <= cur_end and st is not None]
            n = len(sub)
            avg = round(sum(st for _, st in sub) / n, 2) if n else None
            return {"n": n, "avg": avg}
        qtd = window(q_start)
        wtd = window(w_start)
        voice = voice_for(srows, cur_end)
        REC[s]["cust_qtd"] = qtd
        REC[s]["cust_wtd"] = wtd
        REC[s]["cust_voice"] = voice
        feed["stores"][s] = {"overall": REC[s].get("cust"), "qtd": qtd, "wtd": wtd, "voice": voice}

    json.dump(A, open(STORE, "w"), ensure_ascii=False)
    json.dump(feed, open(FEED, "w"), ensure_ascii=False)

    fed = sorted([s for s in REC if REC[s]["cust_qtd"]["n"] > 0], key=lambda s: -REC[s]["cust_qtd"]["n"])
    print(f"build_reviews: cur_end={cur_end} {qlabel} QTD[{q_start}..{cur_end}] WTD[{w_start}..{cur_end}]")
    print(f"  rows={len(rows)} mapped-stores={len(by_store)} dropped={dict(dropped)} unmapped={dict(unmapped)}")
    print(f"  stores WITH QTD reviews ({len(fed)}):")
    for s in fed:
        q = REC[s]["cust_qtd"]; w = REC[s]["cust_wtd"]; v = REC[s]["cust_voice"]
        print(f"    {s:30s} QTD n={q['n']:3d} avg={q['avg']}  WTD n={w['n']:2d} avg={w['avg']}  "
              f"voice={(v['label']+' '+str(v['themes'])) if v else '-'}")

if __name__ == "__main__":
    main()
