#!/usr/bin/env python3
# Build the "Simply Lunch food order forecast" for the stores that stock the chilled food-to-go
# range. Generalised to BOTH Glenvale Drive Thru and Leamington Parade (each adapts to its OWN
# day-of-week demand / product mix — Leamington has no porridge/yoghurt pots or kids sandwiches).
# Input : sl_<key>_raw.json  (cur_end, window_weeks, dowdays[{dow,nd}], itemdow[{nm,dow,units}])
#         dow = BigQuery EXTRACT(DAYOFWEEK): 1=Sun 2=Mon 3=Tue 4=Wed 5=Thu 6=Fri 7=Sat
# Output: simply_lunch_<key>.json  (per-item avg daily demand by weekday + Mon/Wed/Sat delivery
#         orders incl. 15% buffer + weekly total + sparse flag + meta), consumed by
#         patch_newsite.inject_simply_lunch() on each store's Commercial tab.
import json, math

BUFFER = 0.15
SPARSE_WEEKLY = 10
COVER = {"Mon": [2, 3], "Wed": [4, 5, 6], "Sat": [7, 1]}   # Mon->Mon+Tue, Wed->Wed+Thu+Fri, Sat->Sat+Sun
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

# store -> (raw file, output file)
STORES = {
    "Glenvale Drive Thru": ("sl_glenvale_raw.json", "simply_lunch_glenvale.json"),
    "Leamington Parade":   ("sl_leamington_raw.json", "simply_lunch_leamington.json"),
}

def build_one(store, raw_file, out_file):
    try:
        raw = json.load(open(raw_file))
    except (FileNotFoundError, ValueError):
        print(f"  {store}: no {raw_file} — skipped"); return
    nd = {d["dow"]: d["nd"] for d in raw["dowdays"]}
    demand = {}
    for r in raw["itemdow"]:
        demand.setdefault(r["nm"], {})[r["dow"]] = r["units"] / nd.get(r["dow"], raw["window_weeks"])
    items = []
    for nm, dd in demand.items():
        daily = {d: round(dd.get(d, 0.0), 2) for d in range(1, 8)}
        weekly_mean = round(sum(daily.values()), 1)
        orders = {}
        for deliv, days in COVER.items():
            base = sum(dd.get(d, 0.0) for d in days)
            orders[deliv] = int(math.ceil(base * (1 + BUFFER)))
        items.append({"item": nm, "category": CATEGORY.get(nm, "Other"), "daily": daily,
                      "weekly_mean": weekly_mean, "mon": orders["Mon"], "wed": orders["Wed"], "sat": orders["Sat"],
                      "weekly_order": orders["Mon"] + orders["Wed"] + orders["Sat"],
                      "sparse": weekly_mean < SPARSE_WEEKLY})
    items.sort(key=lambda x: (CAT_ORDER.index(x["category"]) if x["category"] in CAT_ORDER else 99, -x["weekly_mean"]))
    out = {"store": store, "cur_end": raw["cur_end"], "window_weeks": raw["window_weeks"],
           "buffer_pct": int(BUFFER * 100), "sparse_threshold_weekly": SPARSE_WEEKLY,
           "max_coverage_days": max(len(v) for v in COVER.values()), "shelf_life_days": 3, "items": items}
    json.dump(out, open(out_file, "w"), indent=1)
    tot = lambda k: sum(it[k] for it in items)
    print(f"{store}: {len(items)} lines · weekly order Mon {tot('mon')} / Wed {tot('wed')} / Sat {tot('sat')} = {tot('weekly_order')} (window {out['window_weeks']}wk, buffer {out['buffer_pct']}%)")
    for it in items[:6]:
        print(f"   {it['item']:30s} wk~{it['weekly_mean']:5.1f}  Mon {it['mon']:3d} Wed {it['wed']:3d} Sat {it['sat']:3d}{'  SPARSE' if it['sparse'] else ''}")

def main():
    for store, (rf, of) in STORES.items():
        build_one(store, rf, of)

if __name__ == "__main__":
    main()
