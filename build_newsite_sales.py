#!/usr/bin/env python3
# Build newsite_sales.json (per-store Sales-tab data) for the 5 new-site dashboards.
# Reads three BigQuery raw result files (each a JSON list of {"k","cur","ly"}):
#   ns_daypart_raw.json  k = "<store>|<daypart>"
#   ns_dow_raw.json      k = "<store>|<DAYOFWEEK 1-7>"   (BigQuery: 1=Sun ... 7=Sat)
#   ns_food_raw.json     k = "<store>|<daypart>|<clean product>"  (Food+Bakery, names cleaned)
# Window: 4 weeks to cur_end (Sun before this Monday) vs the same 4 weeks last year.
# New sites (no prior-year sales) render YoY as "new site" and the food panel as TOP SELLERS.
import json, os, sys, datetime as _dt

BASE = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
def L(fn): return json.load(open(os.path.join(BASE, fn), encoding="utf-8"))

# cur_end = last complete Sunday (the Sunday before this week's Monday) — matches the BigQuery window
_t = _dt.date.today(); _mon = _t - _dt.timedelta(days=_t.weekday()); _cur_end = _mon - _dt.timedelta(days=1)
WINDOW = "4 weeks to %d %s %d vs the same 4 weeks in %d" % (_cur_end.day, _cur_end.strftime("%b"), _cur_end.year, _cur_end.year-1)
HOURS  = {"Morning":"5am–11am","Lunch":"11am–2pm","Afternoon":"2pm–5pm","Evening":"5pm+"}
DP_ORDER = ["Morning","Lunch","Afternoon","Evening"]
DOW_MAP = {2:"Mon",3:"Tue",4:"Wed",5:"Thu",6:"Fri",7:"Sat",1:"Sun"}
DOW_ORDER = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
STORES = ["Olney","Attleborough","Billing Drive Thru","Glenvale Drive Thru","Northampton Drive-Thru"]
NEW_MIN = 80           # mature-site "new this year" threshold (£ in 4wk)
EXCL = ["(Copy)", " SL"]
WEEKS = 4              # window = 4 complete weeks; DOW average divisor (a typical weekday)
DAYS  = 28            # 4 weeks × 7 days; daypart average divisor (a typical day)

def i(v):
    try: return int(round(float(v)))
    except: return 0

dp_rows  = L("ns_daypart_raw.json")
dow_rows = L("ns_dow_raw.json")
food_rows= L("ns_food_raw.json")

# index by store
dp = {s:{} for s in STORES}
for r in dp_rows:
    s, d = r["k"].rsplit("|",1); dp.setdefault(s,{})[d] = (i(r["cur"]), i(r["ly"]))
dow = {s:{} for s in STORES}
for r in dow_rows:
    s, n = r["k"].rsplit("|",1); dow.setdefault(s,{})[int(n)] = (i(r["cur"]), i(r["ly"]))
food = {s:{} for s in STORES}
for r in food_rows:
    s, d, p = r["k"].split("|",2)
    food.setdefault(s,{}).setdefault(d,[]).append((p, i(r["cur"]), i(r["ly"])))

def excl(n): return any(x in n for x in EXCL)

out = {"_window": WINDOW, "hours": HOURS, "stores": {}}
for s in STORES:
    has_ly = sum(ly for (_, ly) in dp.get(s,{}).values()) > 0
    # day-of-week — AVERAGE per weekday = 4-week total ÷ WEEKS (a typical Mon, Tue, …)
    dseries = []
    for n in (2,3,4,5,6,7,1):
        cur, ly = dow.get(s,{}).get(n,(0,0))
        dseries.append([DOW_MAP[n], round(cur/WEEKS), round(ly/WEEKS)])
    # daypart — AVERAGE per day = 4-week total ÷ DAYS (a typical day's Morning/Lunch/…)
    dpser = []
    for d in DP_ORDER:
        cur, ly = dp.get(s,{}).get(d,(0,0))
        dpser.append([d, round(cur/DAYS), round(ly/DAYS)])
    # food per daypart
    fout = {}
    for d in DP_ORDER:
        items = food.get(s,{}).get(d,[])
        gain, new, sell = [], [], []
        if has_ly:
            g = [(p,c,l) for (p,c,l) in items if l>0 and c>l and not excl(p)]
            g.sort(key=lambda x:(x[1]-x[2]), reverse=True)
            for p,c,l in g[:3]:
                gain.append([p, c, round(100*(c-l)/l), c-l])
            nw = [(p,c) for (p,c,l) in items if l==0 and c>=NEW_MIN and not excl(p)]
            nw.sort(key=lambda x:x[1], reverse=True)
            new = [[p,c] for p,c in nw[:2]]
        else:
            sl = [(p,c) for (p,c,l) in items if c>0 and not excl(p)]
            sl.sort(key=lambda x:x[1], reverse=True)
            sell = [[p,c] for p,c in sl[:3]]
        fout[d] = {"gain":gain, "new":new, "sell":sell}
    out["stores"][s] = {"has_ly":has_ly, "dow":dseries, "daypart":dpser, "food":fout}

json.dump(out, open(os.path.join(BASE,"newsite_sales.json"),"w"), ensure_ascii=False, indent=1)

# console summary
print("newsite_sales.json written ·", WINDOW)
for s in STORES:
    st = out["stores"][s]
    tag = "YoY" if st["has_ly"] else "NEW SITE (no prior yr)"
    print(f"  {s}: {tag}")
    if st["has_ly"]:
        for d in DP_ORDER:
            g = st["food"][d]["gain"]
            if g: print(f"     {d}: top gainer {g[0][0]} £{g[0][1]} (+{g[0][2]}%)")
