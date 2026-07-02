#!/usr/bin/env python3
"""Render Maintenance_Dashboard.html from maintenance.json (written by pull_maintenance
in run_weekly.py) into the maint_template.html shell.

Idempotent: the whole HTML/JS is fixed in maint_template.html; this only injects the
three data blobs (DATA / CMS / AUDIT), the "generated" line, the audit count and the
as-of date. If maintenance.json is absent it exits 0 without touching the page (so a
maintenance-source hiccup degrades that dashboard instead of breaking the run).

compute_maintenance (raw sheet rows -> data blobs) also lives here so run_weekly can
import it and it can be unit-tested locally.
"""
import os, sys, json, datetime, re

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- store model (mirrors run_weekly.CANON / COACH / normalize) ----------
CANON = ["Attleborough", "Billing Drive Thru", "Burton Latimer", "Corby",
         "Glenvale Drive Thru", "HOE Balsall Common", "Higham Ferrers", "Kettering",
         "Leamington Parade", "Lower Heathcote", "Market Harborough", "Northampton",
         "Northampton Drive-Thru", "Olney", "Peterborough Bridge Street",
         "Peterborough Fletton Quays", "Rothwell", "Rugby", "Rushden Lakes",
         "Wellingborough", "Wellingborough Train Station"]
COACH = {
    "Burton Latimer": "Jon", "Peterborough Fletton Quays": "Jon", "Rothwell": "Jon",
    "Corby": "Jon", "Kettering": "Jon", "Rushden Lakes": "Jon",
    "Peterborough Bridge Street": "Jon", "Higham Ferrers": "Jon", "Olney": "Jon",
    "Leamington Parade": "Rich", "Northampton": "Rich", "Wellingborough Train Station": "Rich",
    "Market Harborough": "Rich", "Wellingborough": "Rich", "Lower Heathcote": "Rich",
    "Rugby": "Rich", "Northampton Drive-Thru": "Rich", "Billing Drive Thru": "Rich",
    "Attleborough": "Ian", "HOE Balsall Common": "Ian", "Glenvale Drive Thru": "Ian"}
DT_STORES = ["Billing Drive Thru", "Glenvale Drive Thru", "Northampton Drive-Thru"]
DISPLAY = {
    "Attleborough": "Attleborough", "Billing Drive Thru": "Billing DT",
    "Burton Latimer": "Burton", "Corby": "Corby", "Glenvale Drive Thru": "Glenvale DT",
    "HOE Balsall Common": "Balsall Common", "Higham Ferrers": "Higham", "Kettering": "Kettering",
    "Leamington Parade": "Leamington Parade", "Lower Heathcote": "Lower Heathcote",
    "Market Harborough": "Market Harborough", "Northampton": "Northampton",
    "Northampton Drive-Thru": "Northampton DT", "Olney": "Olney",
    "Peterborough Bridge Street": "P'boro Bridge St",
    "Peterborough Fletton Quays": "P'boro Fletton", "Rothwell": "Rothwell", "Rugby": "Rugby",
    "Rushden Lakes": "Rushden Lakes", "Wellingborough": "W'boro Market St",
    "Wellingborough Train Station": "W'boro Train Stn"}
_MAP = {
    "lower heathcote, warwick": "Lower Heathcote", "lower heathcote": "Lower Heathcote",
    "warwick": "Lower Heathcote", "burton": "Burton Latimer",
    "peterborough": "Peterborough Bridge Street", "p'boro bridge st": "Peterborough Bridge Street",
    "fletton": "Peterborough Fletton Quays", "p'boro fletton quays": "Peterborough Fletton Quays",
    "p'boro fletton": "Peterborough Fletton Quays",
    "market street": "Wellingborough", "w'boro market st": "Wellingborough",
    "market st w'boro": "Wellingborough",
    "northampton grosvenor": "Northampton", "npton grosvenor": "Northampton",
    "northampton (grosvenor)": "Northampton", "drive thru n'pton": "Northampton Drive-Thru",
    "train station": "Wellingborough Train Station", "w'boro train stn": "Wellingborough Train Station",
    "lakes": "Rushden Lakes", "rushden lakes": "Rushden Lakes",
    "higham": "Higham Ferrers", "balsall": "HOE Balsall Common",
    "balsall common": "HOE Balsall Common",
    "northampton drive thru": "Northampton Drive-Thru", "npton drive thru": "Northampton Drive-Thru",
    "northampton dt": "Northampton Drive-Thru",
    "glenvale dt": "Glenvale Drive Thru", "glenvale drive thru": "Glenvale Drive Thru",
    "billing dt": "Billing Drive Thru", "billing drive thru": "Billing Drive Thru",
    "leamington retail": None, "leamington spa": None, "royal leamington spa": None}
_COMPET = {"costa", "nero", "starbucks", "coffee#1", "coffee #1", "pret"}

def normalize(name):
    if name is None: return None
    s = str(name).replace("﻿", "").replace("​", "").strip()
    if not s: return None
    low = s.lower()
    if low.rstrip("'s") in {c.rstrip("'s") for c in _COMPET}: return None
    if low in _MAP: return _MAP[low]
    if s in CANON: return s
    flat = low.replace("-", " ").replace("  ", " ")
    for c in CANON:
        if c.lower().replace("-", " ") == flat: return c
    return None

def disp(canon): return DISPLAY.get(canon, canon)

EPOCH = datetime.date(1899, 12, 30)
_MON = {m: i for i, m in enumerate(
    ["", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
def parse_date(v, dayfirst=False):
    if v is None or v == "": return None
    s = str(v).strip()
    if not s: return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        n = int(float(s))
        if 30000 < n < 80000: return EPOCH + datetime.timedelta(days=n)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try: return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception: return None
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100: y += 2000
        first, second = (b, a) if dayfirst else (a, b)
        if first > 12 and second <= 12: first, second = second, first
        try: return datetime.date(y, first, second)
        except Exception: return None
    m = re.match(r"^(\d{1,2})[ -]([A-Za-z]{3,})[ -](\d{4})$", s)
    if m and m.group(2)[:3].lower() in _MON:
        try: return datetime.date(int(m.group(3)), _MON[m.group(2)[:3].lower()], int(m.group(1)))
        except Exception: return None
    return None

def fmt(d): return d.strftime("%d %b %Y") if d else "—"

_OTHER_RULES = [
    ("Pest control (flies/rodents/ants)", r"\b(fly|flies|fruit fl|ant|ants|rodent|mouse|mice|rat|pest|silverfish|wasp|moth|cockroach|infestation)\b"),
    ("Doors / locks / cupboards", r"\b(door|lock|latch|hinge|cupboard|handle|keypad|shutter)\b"),
    ("Fittings / consumables", r"\b(soap|napkin|dispenser|sock|coffee.?catcher|bulb|filter|hook|shelf|shelving|bracket|screw)\b"),
    ("Plumbing / leaks", r"\b(leak|drip|drain|blocked|water|pipe|tap|flush)\b"),
    ("Fridge / cooling / smells", r"\b(fridge|freez|cooling|smell|odour|odor)\b"),
    ("IT / tills / comms", r"\b(till|ipad|tablet|printer|wifi|internet|router|card reader|izettle|network|pc|computer|screen)\b"),
    ("Lighting", r"\b(light|lamp|led|spotlight)\b"),
    ("Cleaning / decor / windows", r"\b(window|clean|paint|decor|mould|mold|wall|graffiti|mess)\b"),
    ("Furniture / fixtures", r"\b(table|chair|stool|sofa|seat|bench|furniture)\b"),
    ("Flooring / trip hazards", r"\b(floor|tile|trip|mat|carpet|grout)\b"),
    ("Signage / boards", r"\b(sign|signage|board|menu board|poster)\b"),
]
def other_bucket(text):
    t = (text or "").lower()
    for label, rx in _OTHER_RULES:
        if re.search(rx, t): return label
    return "Unclassified / misc"

def _sortcount(d, top=None):
    out = sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))
    return [[k, v] for k, v in out][:top] if top else [[k, v] for k, v in out]


def compute_maintenance(reactive_rows, coffee_rows, planned_rows, audit_rows, run_date):
    AREAS = ["company", "Jon", "Ian", "Rich"]

    win_start = run_date - datetime.timedelta(days=90)
    r_tot = {a: {} for a in AREAS}; r_comp = {a: {} for a in AREAS}; r_open = {a: {} for a in AREAS}
    st = {a: {"comp": 0, "fwr": 0, "out": 0} for a in AREAS}
    issues = {a: {} for a in AREAS}; other = {a: {} for a in AREAS}; other_tot = {a: 0 for a in AREAS}
    for row in reactive_rows[1:]:
        if not row: continue
        g = (lambda i: row[i] if len(row) > i else "")
        d = parse_date(g(0))
        if not d or not (win_start <= d <= run_date): continue
        canon = normalize(g(1))
        if canon is None: continue
        status = str(g(4)).strip().lower()
        if status == "test": continue
        itype = str(g(7)).strip() or "Other"
        if "complet" in status: cls = "comp"
        elif "further" in status: cls = "fwr"
        else: cls = "out"
        dl = disp(canon)
        for a in ("company", COACH.get(canon, "")):
            if a not in st: continue
            r_tot[a][dl] = r_tot[a].get(dl, 0) + 1
            if cls == "comp": r_comp[a][dl] = r_comp[a].get(dl, 0) + 1
            else: r_open[a][dl] = r_open[a].get(dl, 0) + 1
            st[a][cls] += 1
            if itype.lower() == "other":
                other_tot[a] += 1
                b = other_bucket(g(3))
                other[a][b] = other[a].get(b, 0) + 1
            else:
                issues[a][itype] = issues[a].get(itype, 0) + 1

    reactive = {}
    for a in AREAS:
        comp, fwr, out = st[a]["comp"], st[a]["fwr"], st[a]["out"]
        total = comp + fwr + out; opn = fwr + out
        bystore = [[s2, r_tot[a][s2], r_comp[a].get(s2, 0), r_open[a].get(s2, 0)]
                   for s2 in sorted(r_tot[a], key=lambda k: (-r_tot[a][k], k))]
        open_store = sorted([[s2, o] for s2, o in r_open[a].items() if o > 0], key=lambda x: (-x[1], x[0]))
        reactive[a] = {"comp": comp, "fwr": fwr, "out": out, "open": opn, "total": total,
                       "rate": round(100 * comp / total) if total else 0,
                       "open_store": open_store, "bystore": bystore,
                       "issues": _sortcount(issues[a]), "other": _sortcount(other[a]),
                       "other_total": other_tot[a], "njobs": total}

    months = []; y, mth = run_date.year, run_date.month
    for _ in range(12):
        months.append((y, mth)); mth -= 1
        if mth == 0: mth = 12; y -= 1
    months = list(reversed(months))
    mlabels = [datetime.date(yy, mm, 1).strftime("%b %y") for yy, mm in months]
    midx = {ym: i for i, ym in enumerate(months)}
    pcount = {}; plast = {}
    for row in planned_rows[1:]:
        if not row: continue
        canon = normalize(row[0] if len(row) > 0 else "")
        if canon is None: continue
        d = parse_date(row[1] if len(row) > 1 else "")
        if not d: continue
        if (d.year, d.month) in midx:
            pcount.setdefault(canon, [0] * 12)[midx[(d.year, d.month)]] += 1
        if canon not in plast or d > plast[canon]: plast[canon] = d
    planned = {}
    for a in AREAS:
        rows = [(disp(c), arr, plast.get(c)) for c, arr in pcount.items()
                if a == "company" or COACH.get(c) == a]
        rows.sort(key=lambda r: (-sum(1 for v in r[1] if v > 0), -sum(r[1]), r[0]))
        matrix = [[r[0]] + r[1] for r in rows]
        permonth = [sum(1 for r in rows if r[1][i] > 0) for i in range(12)]
        planned[a] = {"months": mlabels, "matrix": matrix, "permonth": permonth,
                      "nstores": len(rows), "last": {r[0]: fmt(r[2]) for r in rows},
                      "thismonth": permonth[-1] if permonth else 0}

    DATA = {a: {"reactive": reactive[a], "planned": planned[a]} for a in AREAS}

    INTERVAL_D = 183
    c_last = {}; c_count = {}; c_type = {}; types = {}
    for row in coffee_rows[1:]:
        if not row: continue
        canon = normalize(row[0] if len(row) > 0 else "")
        if canon is None or canon in DT_STORES: continue
        d = parse_date(row[1] if len(row) > 1 else "")
        if not d or d > run_date: continue
        cmt = str(row[4]).lower() if len(row) > 4 else ""
        if "it is a test" in cmt or "this is a test" in cmt: continue
        stype = (str(row[2]).strip() if len(row) > 2 else "") or "Unspecified"
        c_count[canon] = c_count.get(canon, 0) + 1
        types[stype] = types.get(stype, 0) + 1
        if canon not in c_last or d > c_last[canon]:
            c_last[canon] = d; c_type[canon] = stype
    rows_out = []
    for canon, d in c_last.items():
        days = (run_date - d).days
        status = "overdue" if days > INTERVAL_D else ("due" if days > INTERVAL_D - 30 else "indate")
        rows_out.append({"store": disp(canon), "last": fmt(d), "days": days, "count": c_count[canon],
                         "type": c_type[canon], "status": status, "sort": d.toordinal()})
    rows_out.sort(key=lambda r: r["days"], reverse=True)
    have = set(c_last)
    norecord = sorted(disp(c) for c in CANON if c not in DT_STORES and c not in have)
    CMS = {"rows": rows_out,
           "indate": sum(1 for r in rows_out if r["status"] == "indate"),
           "due": sum(1 for r in rows_out if r["status"] == "due"),
           "overdue": sum(1 for r in rows_out if r["status"] == "overdue"),
           "nstores": len(rows_out), "norecord": norecord, "interval_months": 6,
           "excluded": [disp(c) for c in DT_STORES], "types": types}

    aud_dated = []; ap_count = 0
    for row in audit_rows[1:]:
        if not row or len(row) < 11: continue
        ap = str(row[10]).strip()
        if not ap: continue
        ap_count += 1
        d = parse_date(row[3] if len(row) > 3 else "")
        name = str(row[2]).strip() if len(row) > 2 else ""
        aud_dated.append((d or datetime.date(1900, 1, 1), name, ap))
    aud_dated.sort(key=lambda x: x[0], reverse=True)
    AUDIT = []
    for d, name, ap in aud_dated:
        items = []
        for part in re.split(r"[\n;]+|(?<=[.!])\s+", ap):
            t = part.strip(" .-•\t")
            if len(t) < 4: continue
            tl = t.lower()
            if re.search(r"clos|fixed|resolv|complet|done|repaired|replaced", tl): tag = "done"
            elif re.search(r"monitor|awaiting|ongoing|chase|to be|order", tl): tag = "mon"
            else: tag = "open"
            items.append([tag, t[:160]])
            if len(items) >= 4: break
        if items:
            AUDIT.append([fmt(d) if d.year > 1900 else "—", name or "—", items])
        if len(AUDIT) >= 10: break

    asof = fmt(run_date)
    return {"DATA": DATA, "CMS": CMS, "AUDIT": AUDIT, "audit_count": ap_count, "as_of": asof,
            "gen_text": "Data as of %s — reactive, planned, coffee servicing & audit re-pulled from source." % asof}


def render():
    mp = os.path.join(HERE, "maintenance.json")
    if not os.path.exists(mp) or os.path.getsize(mp) == 0:
        print("[gen_maintenance] no/empty maintenance.json - leaving Maintenance_Dashboard.html untouched (source degraded)")
        return
    try:
        m = json.load(open(mp, encoding="utf-8"))
    except Exception as e:
        print("[gen_maintenance] maintenance.json unreadable (%s) - leaving Maintenance_Dashboard.html untouched (source degraded)" % e)
        return
    tpl = open(os.path.join(HERE, "maint_template.html"), encoding="utf-8").read()
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    out = (tpl.replace("__DATA__", j(m["DATA"]))
              .replace("__CMS__", j(m["CMS"]))
              .replace("__AUDIT__", j(m["AUDIT"]))
              .replace("__GENTEXT__", j(m.get("gen_text", "")))
              .replace("__AUDITCOUNT__", str(m.get("audit_count", "") or ""))
              .replace("__ASOF__", m.get("as_of", "")))
    left = [p for p in ("__DATA__", "__CMS__", "__AUDIT__", "__GENTEXT__", "__AUDITCOUNT__", "__ASOF__") if p in out]
    open(os.path.join(HERE, "Maintenance_Dashboard.html"), "w", encoding="utf-8").write(out)
    print("[gen_maintenance] Maintenance_Dashboard.html written - leftover placeholders: %s"
          % ("none" if not left else ",".join(left)))

if __name__ == "__main__":
    render()
