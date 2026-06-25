#!/usr/bin/env python3
# Build the "Simply Lunch food order forecast" for the stores that stock the chilled food-to-go
# range (Glenvale Drive Thru + Leamington Parade — each adapts to its OWN day-of-week demand / mix).
# Input : sl_<key>_raw.json  (cur_end, window_weeks, dowdays[{dow,nd}], itemdow[{nm,dow,units}])
#         dow = BigQuery EXTRACT(DAYOFWEEK): 1=Sun 2=Mon 3=Tue 4=Wed 5=Thu 6=Fri 7=Sat
# Output: simply_lunch_<key>.json — per-item avg daily demand + Tue/Thu/Sat delivery orders incl. 15%
#         buffer + weekly total + sparse flag + meta — consumed by patch_newsite.inject_simply_lunch().
import json, math

BUFFER = 0.15
SPARSE_WEEKLY = 10
SHELF_LIFE_DAYS = 3
# Deliveries land Tue / Thu / Sat (midday). Each order covers demand only for days WITHIN the 3-day
# shelf life, with no gaps and no double-ordering (BQ dow codes 1=Sun..7=Sat):
#   Tue -> Tue+Wed (2 days) · Thu -> Thu+Fri (2 days) · Sat -> Sat+Sun+Mon (3 days, the binding one)
COVER = {"Tue": [3, 4], "Thu": [5, 6], "Sat": [7, 1, 2]}
DELIV_ORDER = ["Tue", "Thu", "Sat"]
COVER_LABEL = {"Tue": "covers Tue–Wed", "Thu": "covers Thu–Fri", "Sat": "covers Sat–Mon"}
DOW_NAME = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}

def _validate_cover():
    """Fail loudly if the delivery windows leave any day uncovered, double-order a day, or breach the
    3-day shelf life — rather than silently shipping a gap."""
    seen = {}
    for deliv, days in COVER.items():
        if len(days) > SHELF_LIFE_DAYS:
            raise SystemExit(f"COVER ERROR: {deliv} covers {len(days)} days > {SHELF_LIFE_DAYS}-day shelf life")
        for d in days:
            seen[d] = seen.get(d, 0) + 1
    missing = [DOW_NAME[d] for d in range(1, 8) if d not in seen]
    doubled = [DOW_NAME[d] for d, n in seen.items() if n > 1]
    if missing: raise SystemExit(f"COVER ERROR: days with NO delivery cover: {missing}")
    if doubled: raise SystemExit(f"COVER ERROR: days covered by >1 delivery (double-order): {doubled}")
    return max(len(v) for v in COVER.values())

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
    "Bacon Bap": "Breakfast baps & bagel", "Sausage Bap": "Breakfast baps & bagel",
    "Breakfast Bagel": "Breakfast baps & bagel",
}
CAT_ORDER = ["Breakfast baps & bagel", "Sandwiches", "Croques", "Ciabattas", "Wraps", "Salads", "Pots", "Filled croissant"]

STORES = {
    "Glenvale Drive Thru": ("sl_glenvale_raw.json", "simply_lunch_glenvale.json"),
    "Leamington Parade":   ("sl_leamington_raw.json", "simply_lunch_leamington.json"),
}

def build_one(store, raw_file, out_file, max_cov):
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
        orders = {dv: int(math.ceil(sum(dd.get(d, 0.0) for d in days) * (1 + BUFFER))) for dv, days in COVER.items()}
        items.append({"item": nm, "category": CATEGORY.get(nm, "Other"), "daily": daily,
                      "weekly_mean": weekly_mean, "tue": orders["Tue"], "thu": orders["Thu"], "sat": orders["Sat"],
                      "weekly_order": orders["Tue"] + orders["Thu"] + orders["Sat"],
                      "sparse": weekly_mean < SPARSE_WEEKLY})
    items.sort(key=lambda x: (CAT_ORDER.index(x["category"]) if x["category"] in CAT_ORDER else 99, -x["weekly_mean"]))
    out = {"store": store, "cur_end": raw["cur_end"], "window_weeks": raw["window_weeks"],
           "buffer_pct": int(BUFFER * 100), "sparse_threshold_weekly": SPARSE_WEEKLY,
           "delivery_days": DELIV_ORDER, "cover_label": COVER_LABEL,
           "max_coverage_days": max_cov, "shelf_life_days": SHELF_LIFE_DAYS, "items": items}
    json.dump(out, open(out_file, "w"), indent=1)
    tot = lambda k: sum(it[k] for it in items)
    print(f"{store}: {len(items)} lines · Tue {tot('tue')} / Thu {tot('thu')} / Sat {tot('sat')} = {tot('weekly_order')}/wk (window {out['window_weeks']}wk, buffer {out['buffer_pct']}%, max cover {max_cov}d ≤ {SHELF_LIFE_DAYS}d shelf)")
    for it in items[:6]:
        print(f"   {it['item']:30s} wk~{it['weekly_mean']:5.1f}  Tue {it['tue']:3d} Thu {it['thu']:3d} Sat {it['sat']:3d}{'  SPARSE' if it['sparse'] else ''}")

def main():
    max_cov = _validate_cover()
    print(f"coverage OK: Tue→Tue+Wed, Thu→Thu+Fri, Sat→Sat+Sun+Mon · all 7 days covered once · max run {max_cov}d ≤ {SHELF_LIFE_DAYS}d shelf life")
    for store, (rf, of) in STORES.items():
        build_one(store, rf, of, max_cov)

if __name__ == "__main__":
    main()
