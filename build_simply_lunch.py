#!/usr/bin/env python3
# Build the Glenvale "Simply Lunch food order forecast" from a raw BigQuery pull.
# Input : sl_glenvale_raw.json  (cur_end, dowdays[{dow,nd}], itemdow[{nm,dow,units}])
#         dow uses BigQuery EXTRACT(DAYOFWEEK): 1=Sun 2=Mon 3=Tue 4=Wed 5=Thu 6=Fri 7=Sat
# Output: simply_lunch_glenvale.json (per-item avg daily demand by weekday + Mon/Wed/Sat
#         delivery orders incl. buffer + weekly total + sparse flag + meta), consumed by
#         patch_newsite.py inject_simply_lunch() on the Glenvale Mix & opportunity tab.
import json, math

BUFFER = 0.15            # service-level buffer on mean demand (see method note)
SPARSE_WEEKLY = 10       # weekly units below this -> flagged "too sparse to forecast reliably"

# delivery -> weekdays it must cover until the next delivery (BQ dow codes)
COVER = {"Mon": [2, 3],        # Mon delivery covers Mon+Tue   (2 days)
         "Wed": [4, 5, 6],     # Wed delivery covers Wed+Thu+Fri (3 days)
         "Sat": [7, 1]}        # Sat delivery covers Sat+Sun   (2 days)
DOW_NAME = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}

CATEGORY = {
    "Ham & Cheese Croque": "Croques", "Cheese & Onion Croque": "Croques",
    "Chicken & Chorizo Ciabatta": "Ciabattas", "Tuna Ciabatta": "Ciabattas",
    "Mozzarella & Tomato Ciabatta": "Ciabattas",
    "Egg & Spinach Sandwich": "Sandwiches", "Chicken Caprese Sandwich": "Sandwiches",
    "Kids Ham Sandwich": "Sandwiches", "Kids Cheese Sandwich": "Sandwiches",
    "Caesar Wrap": "Wraps", "Falafel Wrap": "Wraps",
    "Greek Style Chicken Salad": "Salads", "Green & Grain Salad": "Salads",
    "Yoghurt Granola Pot": "Pots", "Egg & Spinach Pot": "Pots",
    "Golden Oat Porridge Pot": "Pots", "Simple Porridge Pot": "Pots",
    "Ham & Mozzarella Croissant": "Filled croissant",
}
CAT_ORDER = ["Sandwiches", "Croques", "Ciabattas", "Wraps", "Salads", "Pots", "Filled croissant"]

def main():
    raw = json.load(open("sl_glenvale_raw.json"))
    nd = {d["dow"]: d["nd"] for d in raw["dowdays"]}     # trading days per weekday in window
    # avg daily demand per item per weekday = total units / trading-days-of-that-weekday
    demand = {}                                          # item -> {dow: avg_daily}
    for r in raw["itemdow"]:
        demand.setdefault(r["nm"], {})[r["dow"]] = r["units"] / nd.get(r["dow"], raw["window_weeks"])

    items = []
    for nm, dd in demand.items():
        daily = {d: round(dd.get(d, 0.0), 2) for d in range(1, 8)}
        weekly_mean = round(sum(daily.values()), 1)
        orders = {}
        for deliv, days in COVER.items():
            base = sum(dd.get(d, 0.0) for d in days)     # mean demand across covered days
            orders[deliv] = int(math.ceil(base * (1 + BUFFER)))
        items.append({
            "item": nm,
            "category": CATEGORY.get(nm, "Other"),
            "daily": daily,                              # avg daily units by weekday
            "weekly_mean": weekly_mean,                  # mean weekly units sold
            "mon": orders["Mon"], "wed": orders["Wed"], "sat": orders["Sat"],
            "weekly_order": orders["Mon"] + orders["Wed"] + orders["Sat"],
            "sparse": weekly_mean < SPARSE_WEEKLY,
        })

    items.sort(key=lambda x: (CAT_ORDER.index(x["category"]) if x["category"] in CAT_ORDER else 99,
                              -x["weekly_mean"]))
    out = {
        "store": "Glenvale Drive Thru",
        "cur_end": raw["cur_end"],
        "window_weeks": raw["window_weeks"],
        "buffer_pct": int(BUFFER * 100),
        "sparse_threshold_weekly": SPARSE_WEEKLY,
        "max_coverage_days": max(len(v) for v in COVER.values()),
        "shelf_life_days": 3,
        "items": items,
    }
    json.dump(out, open("simply_lunch_glenvale.json", "w"), indent=1)
    # console summary for validation
    print(f"cur_end {out['cur_end']}  window {out['window_weeks']}wk  buffer {out['buffer_pct']}%  max coverage {out['max_coverage_days']}d (shelf {out['shelf_life_days']}d)")
    print(f"{'item':32s} {'Mon':>5} {'Tue':>5} {'Wed':>5} {'Thu':>5} {'Fri':>5} {'Sat':>5} {'Sun':>5} | {'MonO':>4} {'WedO':>4} {'SatO':>4} {'Wk':>4}  flag")
    for it in items:
        d = it["daily"]
        flag = "SPARSE" if it["sparse"] else ""
        print(f"{it['item']:32s} {d[2]:5.1f} {d[3]:5.1f} {d[4]:5.1f} {d[5]:5.1f} {d[6]:5.1f} {d[7]:5.1f} {d[1]:5.1f} | {it['mon']:4d} {it['wed']:4d} {it['sat']:4d} {it['weekly_order']:4d}  {flag}")
    tot=lambda k: sum(it[k] for it in items)
    print(f"{'TOTAL':32s} {'':>41} | {tot('mon'):4d} {tot('wed'):4d} {tot('sat'):4d} {tot('weekly_order'):4d}")

if __name__ == "__main__":
    main()
