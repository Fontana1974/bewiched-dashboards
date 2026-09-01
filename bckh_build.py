#!/usr/bin/env python3
"""BCKH (Brew Crew Kudos Hour) engagement feed builder.

Route (C): a scheduled Cowork task pulls #company-newsfeed posts from Slack in the three
BCKH windows, saves them as a raw-messages JSON, then runs THIS script to attribute stores,
classify tone and tally participation -> bckh_feed.json (committed for the Sunday EOS build).

The Slack fetch itself is done by the Cowork task (Slack MCP); this script is pure transform
so the parsing/attribution logic is version-controlled and unit-testable.

Usage: python3 bckh_build.py RAW.json [--emp-map EMP.json] [--wc YYYY-MM-DD] [--status live|collecting]
RAW.json = list of {user, email, ts(epoch), text, reactions, replies}
EMP.json = optional {email_lower: canonical_store} from HRP Employee List (poster->store fallback)
"""
import json, sys, re, datetime, argparse
try:
    from zoneinfo import ZoneInfo
    LON = ZoneInfo('Europe/London')
except Exception:
    LON = None

CANON = ["Attleborough", "Billing Drive Thru", "Burton Latimer", "Corby",
         "Glenvale Drive Thru", "HOE Balsall Common", "Higham Ferrers", "Kettering",
         "Leamington Parade", "Lower Heathcote", "Market Harborough", "Northampton",
         "Northampton Drive-Thru", "Olney", "Peterborough Bridge Street",
         "Peterborough Fletton Quays", "Rothwell", "Rugby", "Rushden Lakes",
         "Warwick", "Wellingborough", "Wellingborough Train Station"]
COACH = {
    "Burton Latimer": "Jon", "Peterborough Fletton Quays": "Jon", "Rothwell": "Jon",
    "Corby": "Jon", "Kettering": "Jon", "Rushden Lakes": "Jon",
    "Peterborough Bridge Street": "Jon", "Higham Ferrers": "Jon", "Olney": "Jon",
    "Leamington Parade": "Rich", "Northampton": "Rich", "Wellingborough Train Station": "Rich",
    "Market Harborough": "Rich", "Wellingborough": "Rich", "Lower Heathcote": "Rich",
    "Rugby": "Rich", "Northampton Drive-Thru": "Rich", "Billing Drive Thru": "Rich",
    "Attleborough": "Ian", "HOE Balsall Common": "Ian", "Glenvale Drive Thru": "Ian",
    "Warwick": "Ian"}
_MAP = {
    "lower heathcote, warwick": "Lower Heathcote", "lower heathcote": "Lower Heathcote",
    "warwick": "Warwick", "warwick market square": "Warwick", "warwick market place": "Warwick",
    "burton": "Burton Latimer",
    "peterborough": "Peterborough Bridge Street", "bridge street": "Peterborough Bridge Street",
    "peterborough massive": "Peterborough Bridge Street",
    "fletton": "Peterborough Fletton Quays", "fletton quays": "Peterborough Fletton Quays",
    "market street": "Wellingborough", "market st": "Wellingborough",
    "grosvenor": "Northampton", "northampton grosvenor": "Northampton",
    "train station": "Wellingborough Train Station", "station": "Wellingborough Train Station",
    "lakes": "Rushden Lakes", "the lakes": "Rushden Lakes", "rushden": "Rushden Lakes",
    "higham": "Higham Ferrers", "harbs": "Market Harborough", "harborough": "Market Harborough",
    "balsall": "HOE Balsall Common", "balsall common": "HOE Balsall Common", "hoe balsall common": "HOE Balsall Common",
    "billing": "Billing Drive Thru", "billing dt": "Billing Drive Thru", "billing drive thru": "Billing Drive Thru",
    "glenvale": "Glenvale Drive Thru", "glenvale dt": "Glenvale Drive Thru",
    "northampton drive thru": "Northampton Drive-Thru", "northampton drive-thru": "Northampton Drive-Thru",
    "npton drive thru": "Northampton Drive-Thru", "dt": "Northampton Drive-Thru", "drive thru": "Northampton Drive-Thru",
    "moulton": "Northampton Drive-Thru", "moulton dt": "Northampton Drive-Thru",
    "parade": "Leamington Parade", "leamington": "Leamington Parade",
    "olney": "Olney", "attleborough": "Attleborough", "corby": "Corby", "kettering": "Kettering",
    "rothwell": "Rothwell", "rugby": "Rugby", "wellingborough": "Wellingborough", "northampton": "Northampton",
    "market harborough": "Market Harborough"}

def normalize(name):
    if not name: return None
    s = re.sub(r'^bewiched\s*[-–]?\s*', '', str(name).strip(), flags=re.I).strip()
    if not s: return None
    low = s.lower().rstrip("!.:")
    if low in _MAP: return _MAP[low]
    if s in CANON: return s
    flat = low.replace("-", " ")
    for c in CANON:
        if c.lower().replace("-", " ") == flat: return c
    return None

PROMPT_RX = re.compile(r"\b(this or that|question time|one hour warning|kudos is open|that'?s a wrap|"
                       r"relaunch|remember\b.*bckh|rate my shift)\b", re.I)
KUDOS_RX = re.compile(r"#?\s*b\s*c\s*k\s*h|brew\s*crew\s*kudos|#brewcrewkudos", re.I)
SHOUT_RX = re.compile(r"\b(thank you|thankyou|shout ?out|well done|big up|massive (thank|well|shout)|"
                      r"proud of|smash|legend|amazing|superstar|super star|going the extra mile)\b", re.I)
NEG_RX = re.compile(r"\b(not happy|unhappy|disappoint|poor show|let down|complaint|unacceptable|"
                    r"frustrat|sadly|sorry to say|fell short)\b", re.I)
CELEB_RX = re.compile(r"\b(birthday|anniversary|record|milestone|latte art|coffee art|"
                      r"employee of the month|passed|assessment|sign ?off|budget by)\b", re.I)
RECOG_RX = re.compile(r"\b(above and beyond|leadership|growth|integrity|receptive|feedback|owner|"
                      r"mentor|supervisor|figure of 8|delegat)\b", re.I)
MENTION_RX = re.compile(r"<@[UW][A-Z0-9]+\|([^>]+)>")

def build(raw, emp_map=None, wc=None, status="live"):
    emp_map = emp_map or {}
    if wc:
        mon = datetime.date.fromisoformat(wc)
    else:
        ds = [datetime.datetime.fromtimestamp(m["ts"], LON).date() for m in raw] or [datetime.date.today()]
        d = max(ds); mon = d - datetime.timedelta(days=d.weekday())
    windows = {
        "Tue": (datetime.datetime.combine(mon + datetime.timedelta(days=1), datetime.time(17, 30), LON),
                datetime.datetime.combine(mon + datetime.timedelta(days=1), datetime.time(18, 30), LON)),
        "Thu": (datetime.datetime.combine(mon + datetime.timedelta(days=3), datetime.time(12, 0), LON),
                datetime.datetime.combine(mon + datetime.timedelta(days=3), datetime.time(13, 0), LON)),
        "Sun": (datetime.datetime.combine(mon + datetime.timedelta(days=6), datetime.time(9, 0), LON),
                datetime.datetime.combine(mon + datetime.timedelta(days=6), datetime.time(10, 0), LON)),
    }
    def which_window(dt):
        for day, (a, b) in windows.items():
            if a <= dt <= b: return day
        return None
    contribs = []
    for m in raw:
        dt = datetime.datetime.fromtimestamp(m["ts"], LON)
        day = which_window(dt)
        if not day: continue
        text = m.get("text", "") or ""
        if PROMPT_RX.search(text): continue
        if not (KUDOS_RX.search(text) or SHOUT_RX.search(text)): continue
        user = (m.get("user") or "").strip()
        email = (m.get("email") or "").strip().lower()
        mentions = MENTION_RX.findall(text)
        store_mentions = []
        for mn in mentions:
            st = normalize(mn) if mn.lower().startswith("bewiched") else None
            if st: store_mentions.append(st)
        poster_store = emp_map.get(email)
        if not poster_store and store_mentions: poster_store = store_mentions[0]
        if not poster_store:
            for tok in re.findall(r"[A-Za-z][A-Za-z' ]{2,20}", text):
                st = normalize(tok.strip())
                if st: poster_store = st; break
        if NEG_RX.search(text):     tone = "flagged"
        elif CELEB_RX.search(text): tone = "celebration"
        elif RECOG_RX.search(text): tone = "recognition"
        else:                       tone = "warm"
        contribs.append({"day": day, "ts": m["ts"], "user": user, "email": email,
                         "store": poster_store, "shoutout_stores": store_mentions,
                         "reactions": int(m.get("reactions", 0) or 0),
                         "replies": int(m.get("replies", 0) or 0), "tone": tone,
                         "excerpt": re.sub(r"<[^>]+>", "", text).strip()[:160]})
    total = len(contribs)
    by_day = {d: sum(1 for c in contribs if c["day"] == d) for d in ("Tue", "Thu", "Sun")}
    store_ct = {}; store_people = {}; shout_recv = {}; people = {}; unmapped = 0
    for c in contribs:
        st = c["store"]
        if st:
            store_ct[st] = store_ct.get(st, 0) + 1
            store_people.setdefault(st, set()).add(c["user"] or c["email"])
        else: unmapped += 1
        for ss in c["shoutout_stores"]: shout_recv[ss] = shout_recv.get(ss, 0) + 1
        key = c["user"] or c["email"] or "?"
        p = people.setdefault(key, {"name": key, "store": st, "count": 0})
        p["count"] += 1
        if st and not p["store"]: p["store"] = st
    by_store = [{"store": st, "coach": COACH[st], "count": store_ct.get(st, 0),
                 "contributors": len(store_people.get(st, set())),
                 "shoutouts_received": shout_recv.get(st, 0)} for st in CANON]
    stores_contributing = sum(1 for s in by_store if s["count"] > 0)
    zero_stores = [s["store"] for s in by_store if s["count"] == 0]
    by_area = []
    for coach in ("Jon", "Rich", "Ian"):
        mem = [s for s in by_store if s["coach"] == coach]
        by_area.append({"coach": coach, "count": sum(s["count"] for s in mem),
                        "stores_contributing": sum(1 for s in mem if s["count"] > 0),
                        "stores_total": len(mem)})
    top_individuals = sorted(people.values(), key=lambda p: -p["count"])[:12]
    engagement = {"reactions": sum(c["reactions"] for c in contribs),
                  "replies": sum(c["replies"] for c in contribs),
                  "avg_reactions": round(sum(c["reactions"] for c in contribs) / total, 1) if total else 0}
    tone = {t: sum(1 for c in contribs if c["tone"] == t) for t in ("celebration", "recognition", "warm", "flagged")}
    flagged = [{"user": c["user"], "store": c["store"], "day": c["day"], "excerpt": c["excerpt"]}
               for c in contribs if c["tone"] == "flagged"]
    return {
        "generated": datetime.datetime.now().strftime("%d %b %Y %H:%M"),
        "status": status, "week_commencing": mon.isoformat(),
        "windows": [{"day": "Tue", "when": "17:30–18:30"}, {"day": "Thu", "when": "12:00–13:00"},
                    {"day": "Sun", "when": "09:00–10:00"}],
        "total": total, "distinct_contributors": len(people),
        "stores_contributing": stores_contributing, "stores_total": len(CANON),
        "by_day": by_day, "by_store": by_store, "zero_stores": zero_stores, "by_area": by_area,
        "top_individuals": top_individuals, "engagement": engagement, "tone": tone,
        "flagged": flagged, "unmapped": unmapped,
        "note": ("Collecting — the 3-window BCKH format relaunched w/c 1 Sep 2026; the first full "
                 "week's data lands after this week's Tue/Thu/Sun windows." if status == "collecting"
                 else "Pulled from Slack #company-newsfeed, three BCKH windows (Europe/London). "
                      "Engagement prompts excluded. Store via @-mention, HRP employee→store, then free-text."),
        "_source": "Slack #company-newsfeed (C9HSYV1PA), #BCKH/#BrewCrewKudosHour, via scheduled Cowork task",
    }

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("raw"); ap.add_argument("--emp-map", default=None)
    ap.add_argument("--wc", default=None); ap.add_argument("--status", default="live")
    ap.add_argument("--out", default="bckh_feed.json")
    a = ap.parse_args()
    raw = json.load(open(a.raw))
    emp = json.load(open(a.emp_map)) if a.emp_map else None
    feed = build(raw, emp, a.wc, a.status)
    json.dump(feed, open(a.out, "w"), ensure_ascii=False, indent=1)
    print("[bckh] %s: total=%d contributors=%d stores=%d/%d unmapped=%d (status=%s)" % (
        a.out, feed["total"], feed["distinct_contributors"], feed["stores_contributing"],
        feed["stores_total"], feed["unmapped"], feed["status"]))
