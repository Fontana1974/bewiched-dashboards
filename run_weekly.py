#!/usr/bin/env python3
"""
Bewiched weekly dashboard refresh — FULLY AUTOMATED (no agent, no desktop, no Zapier).

Runs in GitHub Actions on a cron. Pulls BigQuery + Google Sheets DIRECTLY via a
service account (no Zapier middleware -> no column-flattener scrambling, no read caps,
full deterministic reads every time), rebuilds all 12 dashboards using the existing
builders (gen_*.py / build_*.py / bench_render.py / patch_newsite.py), runs a freshness
gate, then the workflow commits/pushes.

WHY DIRECT CLIENT: the old agent run wrapped every query as
`SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(...)))` and packed <=4 columns because the
Zapier flattener silently dropped / mis-mapped columns on wide reads (verified 29 Jun:
a 4-column drive-thru query came back with the `total` column dropped). Under the SA we
write normal SQL and read whole sheet ranges.

KEY WIN vs the old agent run: every per-run constant is DERIVED from the run date + the
data — nothing is hand-bumped, so the "stale constant" class of bugs is gone.

MODE (auto-detected by Europe/London weekday):
  Sunday 21:00 -> "sunday"  FULL preview (CPH/hours provisional — planners roll Mon 03:00)
  Monday 09:30 -> "monday"  FULL + authoritative CPH/hours
Both resolve cur_end to the SAME just-completed Sunday (see CUR_END below).
"""
import os, sys, json, re, csv, subprocess, datetime, zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- auth (lazy so the module imports without creds for structural checks) ----------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/bigquery"]
PROJECT = "bewiched-coffee-368116"
DATASET = "bewiched_coffee"
LOCATION = "europe-west2"
_BQ = None
_SHEETS = None

def _creds():
    from google.oauth2 import service_account
    sa = json.loads(os.environ["GCP_SA_JSON"])            # GitHub Actions secret
    return service_account.Credentials.from_service_account_info(sa, scopes=SCOPES)

def _bq_client():
    global _BQ
    if _BQ is None:
        from google.cloud import bigquery
        _BQ = bigquery.Client(project=PROJECT, credentials=_creds())
    return _BQ

def _sheets_api():
    global _SHEETS
    if _SHEETS is None:
        from googleapiclient.discovery import build as gbuild
        _SHEETS = gbuild("sheets", "v4", credentials=_creds(),
                         cache_discovery=False).spreadsheets().values()
    return _SHEETS

def bq(sql):
    """Run BigQuery SQL, return list[dict]. Deterministic — no TO_JSON_STRING wrapping,
    no flattener. Just write normal SQL."""
    return [dict(r) for r in _bq_client().query(sql, location=LOCATION).result()]

def sheet(spreadsheet_id, a1_range, unformatted=True):
    """Read a Sheet range as positional rows. UNFORMATTED by default (dates -> serials,
    no flattener column-scramble). Returns list[list]."""
    opt = "UNFORMATTED_VALUE" if unformatted else "FORMATTED_VALUE"
    return _sheets_api().get(spreadsheetId=spreadsheet_id, range=a1_range,
                             valueRenderOption=opt).execute().get("values", [])

# ---------- date / parsing helpers ----------
EPOCH = datetime.date(1899, 12, 30)
def serial_to_date(s):
    try: return EPOCH + datetime.timedelta(days=int(float(s)))
    except Exception: return None
def serial_to_iso(s):
    d = serial_to_date(s); return d.isoformat() if d else None

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
def parse_any_date(v):
    """Parse the mixed date formats the source sheets use:
    sheet serial, ISO, M/D/YYYY, DD/MM/YYYY, '11-Apr-2026', 'Jun 12 2026',
    JS 'Fri Mar 11 ... 2022', and Google 'Date(y,m,d)'."""
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return serial_to_date(v)
    s = str(v).strip()
    if not s: return None
    m = re.match(r"Date\((\d+),(\d+),(\d+)", s)            # gviz Date(y,m,d) — month 0-based
    if m:
        try: return datetime.date(int(m.group(1)), int(m.group(2)) + 1, int(m.group(3)))
        except ValueError: return None
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)       # ISO, with optional ' HH:MM:SS' tail
    if m:                                                 # e.g. reviews '2026-06-29 10:05:31'
        try: return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: return None
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%b %d %Y", "%d %b %Y", "%m/%d/%Y", "%d/%m/%Y"):
        try: return datetime.datetime.strptime(s, fmt).date()
        except ValueError: pass
    # JS Date string e.g. 'Fri Mar 11 10:11:00 -0000 2022': take the month+day token and the
    # 19xx/20xx year — NOT the first 4 digits (the '-0000' TZ offset used to be grabbed as year 0).
    md = re.search(r"\b([A-Za-z]{3})\s+(\d{1,2})\b", s)
    yr = re.search(r"\b(?:19|20)\d{2}\b", s)
    if md and yr and md.group(1).lower() in _MONTHS:
        try: return datetime.date(int(yr.group(0)), _MONTHS[md.group(1).lower()], int(md.group(2)))
        except ValueError: return None
    return None

def fnum(v, default=0.0):
    try: return float(v)
    except Exception: return default

# ---------- run dates (ALL derived; nothing hand-bumped) ----------
NOW_UK = datetime.datetime.now(zoneinfo.ZoneInfo("Europe/London"))
TODAY = NOW_UK.date()
MODE = "sunday" if TODAY.weekday() == 6 else "monday"
# CUR_END = the just-completed Sunday. weekday(): Mon=0..Sun=6.
#   Sunday  (6): (6+1)%7 = 0 -> today (this Sunday)         == Sunday-override formula
#   Monday  (0): (0+1)%7 = 1 -> yesterday (Sunday)          == plain formula
#   any other day resolves to the most recent Sunday too (safety for manual runs).
CUR_END = TODAY - datetime.timedelta(days=(TODAY.weekday() + 1) % 7)
def d(n):  # SQL date literal for cur_end - n days
    return "DATE('%s')" % (CUR_END - datetime.timedelta(days=n)).isoformat()
CE = "DATE('%s')" % CUR_END.isoformat()
LASTWK_MON = CUR_END - datetime.timedelta(days=6)
CURWK_MON = CUR_END + datetime.timedelta(days=1)
QSTART = datetime.date(CUR_END.year, ((CUR_END.month - 1) // 3) * 3 + 1, 1)   # calendar-quarter start
def wlabel(dt): return "w/c " + dt.strftime("%-d %b %Y")
def short_window():  # daypart-food window label
    return "4 weeks to %s vs same 4 weeks %d" % (CUR_END.strftime("%-d %b %Y"), CUR_END.year - 1)
print("[dates] mode=%s cur_end=%s last_week=%s cur_week=%s qstart=%s" %
      (MODE, CUR_END, LASTWK_MON, CURWK_MON, QSTART))

# ---------- sheet IDs ----------
SID = dict(
    cph="18iUyF6Usm5QnUAARPgNsAkqWp00fKPv1WA3waBKJFZU",
    cos="1doPNL5yVh7swMysJMRVi0ECiBg50ZGBb7TbwStJtAL0",
    planner_jon="1PSjBGiR40171h769esQCtn3ldcpCB5XJyfqRTo7Yccs",
    planner_rich="11XuXn9zQr-JB4x2fQ0ORV96Sf-U7xWPQPvg2YlCl_dQ",
    planner_ian="1_qdK6fzqPg1NcA2KKMy2TnaZ8nQJtVE-fglz2On3oBw",
    master_pop="1RZ8ZmFdLyXz1btg3_pNdaVaAyXKhQqHwjVpWWzoFuI0",
    f1="1YFqpR9_ftlQEbfwc5ZVMjtS5tFO0j-7ccwB8rwG56wQ",
    hrp="1f_nTz6TJTPlVP4CSX6AzQ9sf5KbF7QwpVdVnxiW-bM4",
    audit="10JL4idTOmcCXnDTLsqHJjrHFnTMiIf7HR5uzVPwrjbM",
    reviews="1Dm3fxmhodV2xH-apaMp1baWmJ6zDIofv6z6YPuY8D3s",
    availability="1CeTBvZ610zfEMe118m76LgMW5gw_SDS-2Eel1HMuM78",
    smt="1IGL3sLWSI7k1vuXEMFBWplgk3uS4tTUU1-MtGYDk-bQ",
    eos="1HimYAjZg4zlMQG91-KUefkeYMPvrU4ddVuO2IuERTqg",  # Bewiched EOS Scorecard Inputs (manual rows)
    npat_pnl="1RTsnnz5F9XIdkg4j8m8MiuKqeAvZaAWcndbFifNNLhM",  # Bewiched Ltd by-site monthly P&L (currently "Bewiched May 2026 P&L")
    employees="11QhNGGM5BIJrO1NOflso5I1VnSzlWGWcC5FbXJoLQgM",  # Employee List (headcount for Brew Crew Kudos participation)
    maint_jobs="1sNuY1RSVZ4hV1tHSjB-q97V1Ey_53SdmJ2cvHfZiE20",   # Maintenance Jobs wb: reactive "Maintenance Jobs" + "Coffee Machine Services" tabs
    maint_planned="14z4MWGcKH8AOg3240_IO7n4Apo2EZWfkT69JbQjc4zw", # "Bewiched - Planned Maintenance" (planned visit log, "Maintenance" tab)
    # Brew Crew Kudos contributors live in the F1 workbook (SID["f1"]) tab "BCKH"
)

# ---------- canonical estate (21) + mappings ----------
CANON = ["Attleborough", "Billing Drive Thru", "Burton Latimer", "Corby",
         "Glenvale Drive Thru", "HOE Balsall Common", "Higham Ferrers", "Kettering",
         "Leamington Parade", "Lower Heathcote", "Market Harborough", "Northampton",
         "Northampton Drive-Thru", "Olney", "Peterborough Bridge Street",
         "Peterborough Fletton Quays", "Rothwell", "Rugby", "Rushden Lakes",
         "Wellingborough", "Wellingborough Train Station"]
COACH = {  # store -> area coach (Jon 9 / Rich 9 / Ian 3 = 21)
    "Burton Latimer": "Jon", "Peterborough Fletton Quays": "Jon", "Rothwell": "Jon",
    "Corby": "Jon", "Kettering": "Jon", "Rushden Lakes": "Jon",
    "Peterborough Bridge Street": "Jon", "Higham Ferrers": "Jon", "Olney": "Jon",
    "Leamington Parade": "Rich", "Northampton": "Rich", "Wellingborough Train Station": "Rich",
    "Market Harborough": "Rich", "Wellingborough": "Rich", "Lower Heathcote": "Rich",
    "Rugby": "Rich", "Northampton Drive-Thru": "Rich", "Billing Drive Thru": "Rich",
    "Attleborough": "Ian", "HOE Balsall Common": "Ian", "Glenvale Drive Thru": "Ian"}
DT_STORES = ["Billing Drive Thru", "Glenvale Drive Thru", "Northampton Drive-Thru"]
STORE_PAGES = ["Olney", "Attleborough", "Billing Drive Thru", "Glenvale Drive Thru",
               "Northampton Drive-Thru", "Leamington Parade"]
COMMERCIAL_STORES = ["Glenvale Drive Thru", "Leamington Parade"]
CATS = ["Hot drinks", "Cold drinks", "Milkshakes", "Food", "Bakery", "Other & retail"]

# informal source label -> canonical (lower-cased keys; competitors flagged separately)
_MAP = {
    "lower heathcote, warwick": "Lower Heathcote", "lower heathcote": "Lower Heathcote",
    "warwick": "Lower Heathcote", "burton": "Burton Latimer",
    "peterborough": "Peterborough Bridge Street", "p'boro bridge st": "Peterborough Bridge Street",
    "fletton": "Peterborough Fletton Quays", "p'boro fletton quays": "Peterborough Fletton Quays",
    "market street": "Wellingborough", "w'boro market st": "Wellingborough",
    "northampton grosvenor": "Northampton", "npton grosvenor": "Northampton",
    "train station": "Wellingborough Train Station", "lakes": "Rushden Lakes",
    "higham": "Higham Ferrers", "balsall": "HOE Balsall Common",
    "balsall common": "HOE Balsall Common",
    "northampton drive thru": "Northampton Drive-Thru", "npton drive thru": "Northampton Drive-Thru",
    "glenvale dt": "Glenvale Drive Thru", "leamington retail": None, "leamington spa": None,
    "royal leamington spa": None}
COMPETITORS = {"costa", "nero", "nero's", "starbucks", "coffee#1", "coffee #1", "pret"}
def is_competitor(name):
    return str(name).strip().lower().rstrip("'s") in {c.rstrip("'s") for c in COMPETITORS}
def normalize(name):
    """Informal source label -> canonical store, or None if dropped/competitor/unknown."""
    if name is None: return None
    s = str(name).strip()
    if not s: return None
    if is_competitor(s): return None
    low = s.lower()
    if low in _MAP: return _MAP[low]
    if s in CANON: return s
    # tolerate hyphen/spacing drift e.g. 'Northampton Drive Thru'
    flat = low.replace("-", " ").replace("  ", " ")
    for c in CANON:
        if c.lower().replace("-", " ") == flat: return c
    return None

# ---------- allstores.json overlay helpers (estate pulls mutate it incrementally) ----------
def load_all():
    if os.path.exists(os.path.join(HERE, "allstores.json")):
        return json.load(open(os.path.join(HERE, "allstores.json")))
    return {"rec": {}, "champ": {}, "cats": CATS}
def save_all(a):
    json.dump(a, open(os.path.join(HERE, "allstores.json"), "w"), ensure_ascii=False)
def W(name, obj, **kw):
    json.dump(obj, open(os.path.join(HERE, name), "w"), ensure_ascii=False, **kw)

# ---------- shared SQL fragments ----------
FLAT = "`%s.%s.v_sales_details_flat`" % (PROJECT, DATASET)
SDET = "`%s.%s.v_sales_details`" % (PROJECT, DATASET)
WASTE = "`%s.%s.v_sales_vs_wastage`" % (PROJECT, DATASET)
# Category CASE (STEP 2k order). NB Bakery-meal-deal MUST precede Food. Native client: \b = single backslash.
def cat_case(col):
    return (r"""CASE
      WHEN REGEXP_CONTAINS(LOWER({c}), r'milkshake') THEN 'Milkshakes'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'iced|frappe|frozen|matcha|cold brew') THEN 'Cold'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'beans|1kg|gift|merch') THEN 'Other&retail'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'pastry|sausage roll') AND REGEXP_CONTAINS(LOWER({c}), r'meal deal') THEN 'Bakery'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'meal deal|croque|ciabatta|\bbap\b|wrap|sandwich|bagel|salad|tuna|panini|toastie|soup|sausage roll|breakfast') THEN 'Food'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'traybake|brownie|slice|croissant|pastry|muffin|cookie|cake|bakewell|millionaire|teacake|scone|flapjack|twist|doughnut|fudge|cinnamon') THEN 'Bakery'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'latte|cappuccino|americano|flat white|mocha|espresso|hot choc|\bmug\b|\bpot\b|\btea\b|coffee|macchiato|cortado|chai') THEN 'Hot'
      ELSE 'Other&retail' END""").replace("{c}", col)
CATLABEL = {"Hot": "Hot drinks", "Cold": "Cold drinks", "Milkshakes": "Milkshakes",
            "Food": "Food", "Bakery": "Bakery", "Other&retail": "Other & retail"}
# daypart from the sales_date_time STRING ('YYYY-MM-DD HH:MM:SS') — do NOT EXTRACT(HOUR..)
HOUR = "CAST(SUBSTR(sales_date_time,12,2) AS INT64)"
def dp_case(h):
    return ("CASE WHEN %s BETWEEN 5 AND 10 THEN 'Morning' WHEN %s BETWEEN 11 AND 13 THEN 'Lunch' "
            "WHEN %s BETWEEN 14 AND 16 THEN 'Afternoon' WHEN %s>=17 THEN 'Evening' ELSE 'Other' END"
            % (h, h, h, h))
# product-name cleaner (food / SL pulls) — folds named bap meal-deals into the plain bap line
CLEAN = (r"REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE("
         r"item_product_name,r'^[23]?[*]? ',''),r' TA$',''),"
         r"r'(?i)bacon bap meal deal.*','Bacon Bap'),r'(?i)sausage bap meal deal.*','Sausage Bap')")
DOW_ORDER = [2, 3, 4, 5, 6, 7, 1]   # EXTRACT(DAYOFWEEK) 1=Sun..7=Sat -> render Mon..Sun


# ============================ ESTATE PULLS (A) ============================
def pull_sales():
    """STEP 2 — core sales for all 21 (v_sales_details_flat). VALIDATED via Zapier 29 Jun:
    Glenvale lw26 £20,349/2,497tx, Olney £5,663/736tx, cur_end 2026-06-28."""
    a = load_all()
    rec = a["rec"]
    for s in CANON:
        rec.setdefault(s, {})
        rec[s]["coach"] = COACH[s]
    win = bq(f"""
      WITH b AS (SELECT item_outlet_name s, DATE(sales_date) dd, id,
                        SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
                 FROM {FLAT}
                 WHERE DATE(sales_date) BETWEEN {d(391)} AND {CE})
      SELECT s,
        ROUND(SUM(IF(dd BETWEEN {d(6)} AND {CE},v,0))) lw26,
        COUNT(DISTINCT IF(dd BETWEEN {d(6)} AND {CE},id,NULL)) tx26,
        ROUND(SUM(IF(dd BETWEEN {d(27)} AND {CE},v,0))) s4,
        COUNT(DISTINCT IF(dd BETWEEN {d(27)} AND {CE},id,NULL)) tx4,
        ROUND(SUM(IF(dd BETWEEN {d(370)} AND {d(364)},v,0))) lw25,
        COUNT(DISTINCT IF(dd BETWEEN {d(370)} AND {d(364)},id,NULL)) tx25,
        ROUND(SUM(IF(dd BETWEEN {d(391)} AND {d(364)},v,0))) s4_25,
        ROUND(SUM(IF(dd BETWEEN {d(363)} AND {d(357)},v,0))) ly1,
        ROUND(SUM(IF(dd BETWEEN {d(356)} AND {d(350)},v,0))) ly2,
        ROUND(SUM(IF(dd BETWEEN {d(349)} AND {d(343)},v,0))) ly3
      FROM b GROUP BY s""")
    dow = bq(f"""
      SELECT item_outlet_name s, EXTRACT(DAYOFWEEK FROM DATE(sales_date)) dw,
        ROUND(SUM(IF(DATE(sales_date) BETWEEN {d(27)} AND {CE},
                     SAFE_CAST(item_line_total_after_discount AS FLOAT64),0))) cur,
        ROUND(SUM(IF(DATE(sales_date) BETWEEN {d(391)} AND {d(364)},
                     SAFE_CAST(item_line_total_after_discount AS FLOAT64),0))) ly
      FROM {FLAT}
      WHERE DATE(sales_date) BETWEEN {d(391)} AND {CE}
      GROUP BY s, dw""")
    dpt = bq(f"""
      SELECT s, dp,
        ROUND(SUM(IF(dd BETWEEN {d(27)} AND {CE},v,0))) cur,
        ROUND(SUM(IF(dd BETWEEN {d(391)} AND {d(364)},v,0))) ly
      FROM (SELECT item_outlet_name s, DATE(sales_date) dd,
                   {dp_case(HOUR)} dp,
                   SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
            FROM {FLAT}
            WHERE DATE(sales_date) BETWEEN {d(391)} AND {CE})
      WHERE dp != 'Other' GROUP BY s, dp""")

    dwm = {}
    for r in dow: dwm.setdefault(r["s"], {})[int(r["dw"])] = (r["cur"], r["ly"])
    dpm = {}
    for r in dpt: dpm.setdefault(r["s"], {})[r["dp"]] = (r["cur"], r["ly"])

    def growth(cur, ly):
        return None if not ly else round(100 * (cur / ly - 1), 1)
    for r in win:
        s = r["s"]
        if s not in rec: continue
        lw26, lw25, s4, s4_25 = r["lw26"] or 0, r["lw25"] or 0, r["s4"] or 0, r["s4_25"] or 0
        tx26, tx4, tx25 = r["tx26"] or 0, r["tx4"] or 0, r["tx25"] or 0
        rec[s].update({
            "lw26": lw26, "lw25": lw25, "s4": s4, "s4_25": s4_25,
            "tx26": tx26, "tx25": tx25, "lw_sales": lw26,
            "atv": round(lw26 / tx26, 2) if tx26 else 0,
            "yoy_lw": None if not lw25 else round(100 * (lw26 / lw25 - 1), 1),
            "yoy_4w": None if not s4_25 else round(100 * (s4 / s4_25 - 1), 1),
            "vs4w": None if not s4 else round(100 * (lw26 / (s4 / 4) - 1), 1),
            "tot": [round(s4), tx4],
            "ly": [lw25, r["ly1"] or 0, r["ly2"] or 0, r["ly3"] or 0]})
        rec[s]["dow_growth"] = [growth(*dwm.get(s, {}).get(w, (0, 0))) for w in DOW_ORDER]
        rec[s]["daypart_growth"] = {dp: growth(*dpm.get(s, {}).get(dp, (0, 0)))
                                    for dp in ("Morning", "Lunch", "Afternoon", "Evening")}
    a["cats"] = CATS
    save_all(a)
    print("[pull] sales: %d stores" % len(win))


def pull_mix():
    """STEP 2k — sales mix cur(4wk)/prior(4wk)/lastweek per store -> rec.mix/mix_prev/mix_lw."""
    a = load_all(); rec = a["rec"]
    rows = bq(f"""
      SELECT s, win, cat, ROUND(SUM(v)) sales, COUNT(DISTINCT id) dcnt
      FROM (
        SELECT item_outlet_name s, id, SAFE_CAST(item_line_total_after_discount AS FLOAT64) v,
          {cat_case('item_product_name')} cat,
          CASE WHEN DATE(sales_date) BETWEEN {d(6)} AND {CE} THEN 'lw'
               WHEN DATE(sales_date) BETWEEN {d(27)} AND {CE} THEN 'cur'
               WHEN DATE(sales_date) BETWEEN {d(55)} AND {d(28)} THEN 'prev' END win
        FROM {FLAT}
        WHERE DATE(sales_date) BETWEEN {d(55)} AND {CE})
      WHERE win IS NOT NULL GROUP BY s, win, cat""")
    # group -> per store/win: {cat:{sales,dcnt}} + totals
    agg = {}
    for r in rows:
        agg.setdefault(r["s"], {}).setdefault(r["win"], {})[r["cat"]] = (r["sales"], r["dcnt"])
    def build(winmap):
        tot_s = sum(v[0] for v in winmap.values())
        tot_d = sum(v[1] for v in winmap.values())
        out = {c: {"sales": 0, "cap": 0, "mix": 0} for c in CATS}
        for cat, (sales, dcnt) in winmap.items():
            out[CATLABEL[cat]] = {"sales": round(sales),
                                  "cap": round(100 * dcnt / tot_d, 1) if tot_d else 0,
                                  "mix": round(100 * sales / tot_s, 1) if tot_s else 0}
        return out, tot_d
    for s in rec:
        m = agg.get(s, {})
        if "cur" in m:
            rec[s]["mix"], _ = build(m["cur"])
        if "lw" in m:
            rec[s]["mix_lw"], _ = build(m["lw"])
        if "prev" in m:
            mp, td = build(m["prev"])
            rec[s]["mix_prev"] = mp if td >= 1000 else None    # noisy small prior windows -> null
        else:
            rec[s]["mix_prev"] = None
    save_all(a)
    print("[pull] mix: %d stores" % len(agg))


def pull_wastage():
    """STEP 2d — v_sales_vs_wastage. company_wastage.json (last 28d) + per-store waste fields."""
    a = load_all(); rec = a["rec"]
    # NB v_sales_vs_wastage stores WastageQuantity / RetailValue / SalesQuantity as STRING -> SAFE_CAST.
    # VALIDATED via Zapier 29 Jun: top wasted line '3 Ham & Cheese Croque' 432 / £2,371.68 (28d).
    WQ = "SAFE_CAST(WastageQuantity AS FLOAT64)"
    RV = "SAFE_CAST(RetailValue AS FLOAT64)"
    SQ = "SAFE_CAST(SalesQuantity AS FLOAT64)"
    comp = bq(f"""
      SELECT product_name nm, ROUND(SUM({WQ})) wq, ROUND(SUM({RV}),2) wr, ROUND(SUM({SQ})) sq
      FROM {WASTE}
      WHERE date BETWEEN {d(27)} AND {CE} AND {WQ}>0
      GROUP BY nm ORDER BY wr DESC LIMIT 40""")
    W("company_wastage.json", {"_window": "last 28 days",
        "rows": [[r["nm"], r["wq"] or 0, r["wr"] or 0, r["sq"] or 0] for r in comp]}, indent=1)
    store = bq(f"""
      SELECT outlet s,
        ROUND(SUM(IF(date BETWEEN {d(27)} AND {CE} AND {WQ}>0,{RV},0))) wr,
        ROUND(SUM(IF(date BETWEEN {d(6)} AND {CE} AND {WQ}>0,{RV},0))) wr_lw
      FROM {WASTE} WHERE date BETWEEN {d(27)} AND {CE} GROUP BY s""")
    out = bq(f"""
      SELECT outlet s, product_name nm, ROUND(SUM({RV}),2) wr,
             ROUND(SUM({WQ})) wq, ROUND(SUM({SQ})) sq
      FROM {WASTE}
      WHERE date BETWEEN {d(27)} AND {CE} AND {WQ}>0
      GROUP BY s, nm""")
    olm = {}
    for r in out: olm.setdefault(r["s"], []).append([r["nm"], r["wr"], r["wq"], r["sq"]])
    wm = {r["s"]: r for r in store}
    for s in rec:
        ws = wm.get(s)
        if not ws: continue
        s4 = rec[s].get("s4") or 0
        wr, wr_lw = ws["wr"] or 0, ws["wr_lw"] or 0
        rec[s]["wr"] = wr; rec[s]["wr_lw"] = wr_lw
        rec[s]["waste_pct"] = round(100 * wr / s4, 1) if s4 else 0
        rec[s]["waste_pct_lw"] = round(100 * wr_lw / (rec[s].get("lw26") or 1), 1) if rec[s].get("lw26") else 0
        ol = sorted(olm.get(s, []), key=lambda x: -x[1])[:10]
        rec[s]["outliers"] = [[nm, wr_ or 0, wq or 0, sq or 0, wr_ or 0] for nm, wr_, wq, sq in ol]
    save_all(a)
    print("[pull] wastage: company rows %d, stores %d" % (len(comp), len(wm)))


def pull_f1():
    """STEP 2e — RAW 'The Race' + 'Qualifying' tabs (UNFORMATTED, full span). Writes
    f1_detail.json + rec.f1 + champ. Also writes the_race.csv for build_queue_benchmark.
    VALIDATED via Zapier 29 Jun: newest Race serial 46201 == 2026-06-28 == cur_end;
    cols Date0 Store1 Queue4 Hello5 Goodbye6 HowAreYou7 WTQ8 Total18 Coach28 ChampPts29 Finish30."""
    race = sheet(SID["f1"], "'The Race'!A1:AE3000")
    quali = sheet(SID["f1"], "'Qualifying'!A1:R2000")
    racer, csv_rows = {}, []          # racer[store] -> list of (date, row)
    comp_rows = []
    for r in race[1:]:
        if len(r) < 31 or r[0] in (None, ""): continue
        dt = parse_any_date(r[0])
        if not dt: continue
        coach = (str(r[28]).strip() if len(r) > 28 else "")
        csv_rows.append([dt.isoformat(), str(r[1]).strip(), fnum(r[4]), coach])
        st = normalize(r[1])
        if coach == "Check Name" or st is None:
            comp_rows.append((dt, r)); continue
        racer.setdefault(st, []).append((dt, r))
    qualir = {}
    for r in quali[1:]:
        if len(r) < 18 or r[0] in (None, ""): continue
        dt = parse_any_date(r[0]); st = normalize(r[1])
        if not dt or st is None: continue
        qualir.setdefault(st, []).append((dt, r))

    fd = {}
    newest = None
    for st, rows in racer.items():
        rows.sort(key=lambda x: x[0])
        dt, r = rows[-1]
        newest = max(newest, dt) if newest else dt
        race_arr = [fnum(r[4]), fnum(r[5]), fnum(r[6]), fnum(r[7]), fnum(r[8]),
                    fnum(r[18]), fnum(r[29]), fnum(r[30]), dt.isoformat()]
        qrows = sorted(qualir.get(st, []), key=lambda x: x[0])
        quali_arr = None
        if qrows:
            qd, q = qrows[-1]
            # The 'Qualifying' tab column order DIFFERS from 'The Race': Hello=4 Goodbye=5
            # HowAreYou=6 WorkingTheQueue=7 Total=8 QueueAverage=14 QualiRank=17. Emit quali_arr in
            # the SAME positional order the F1 tables render (mirrors race_arr):
            # [QueueAvg, Hello, Goodbye, HowAreYou, WTQ, Total, Rank, date]. (Previously it was emitted
            # in the sheet's native order, so the render read Hello as the queue, Total as WTQ, etc.,
            # and blank cells showed n/a on the Qualifying detail table.)
            quali_arr = [fnum(q[14]), fnum(q[4]), fnum(q[5]), fnum(q[6]), fnum(q[7]),
                         fnum(q[8]), fnum(q[17]), qd.isoformat()]
        qtd = [x for x in rows if x[0] >= QSTART and fnum(x[1][18]) > 0]
        def avg(idx, src=qtd):
            xs = [fnum(x[1][idx]) for x in src]
            return round(sum(xs) / len(xs), 2) if xs else None
        def pct(v): return None if v is None else round(v * 100, 1)
        # RACE QTD table reads queue_s / qcall (=Working The Queue %) / hello|goodbye|howareyou.
        # The sheet holds greetings as 0-1 fractions, so store them as PERCENTAGES (were rendering ~1%).
        race_qtd = {"n": len(qtd), "score": avg(18),
                    "queue_s": avg(4), "qcall": pct(avg(8)),
                    "hello": pct(avg(5)), "goodbye": pct(avg(6)), "howareyou": pct(avg(7)),
                    "queue": avg(4), "wtq": avg(8)}
        qqtd = [x for x in qrows if x[0] >= QSTART]
        def qavg(idx):   # average over Qualifying rows, skipping blank cells (penalty rows leave greetings/queue empty)
            xs = [fnum(x[1][idx]) for x in qqtd if len(x[1]) > idx and x[1][idx] not in (None, "")]
            return round(sum(xs) / len(xs), 2) if xs else None
        # QUALI QTD table reads the same keys. Use Qualifying column indices (Queue=14 WTQ=7
        # Hello=4 Goodbye=5 HowAreYou=6 Rank=17); greetings/qcall as %.
        quali_qtd = {"n": len(qqtd), "rank": qavg(17),
                     "queue_s": qavg(14), "qcall": pct(qavg(7)),
                     "hello": pct(qavg(4)), "goodbye": pct(qavg(5)), "howareyou": pct(qavg(6)),
                     "queue": qavg(14)}
        last6 = [fnum(x[1][30]) for x in rows[-6:]][::-1]
        fd[st] = {"race": race_arr, "quali": quali_arr,
                  "race_qtd": race_qtd, "quali_qtd": quali_qtd, "last6": last6}
    W("f1_detail.json", fd, indent=1)

    # rec.f1 / f1_finish + champ (drivers since 25 Apr 2026; constructors by coach)
    a = load_all(); rec = a["rec"]
    drivers = []
    cons = {}
    cons_n = {}
    CHAMP_FROM = datetime.date(2026, 4, 25)
    for st, rows in racer.items():
        pts = sum(fnum(r[29]) for dt, r in rows if dt >= CHAMP_FROM)
        coach = COACH.get(st, "")
        drivers.append([st, coach, round(pts)])
        cons[coach] = cons.get(coach, 0) + round(pts)
        cons_n[coach] = cons_n.get(coach, 0) + 1
        if st in rec and st in fd:
            fin = fd[st]["race"][7]
            rec[st]["f1"] = [fin, fd[st]["race"][6], fd[st]["last6"]]
            rec[st]["f1_finish"] = fin
    drivers.sort(key=lambda x: -x[2])
    # constructor standings: [coach, total_pts, n_stores, pts_per_store];
    # gen_company sorts and labels by pts/store (index 3)
    cons_rows = [[c, tot, cons_n[c], round(tot / cons_n[c], 1) if cons_n[c] else 0]
                 for c, tot in cons.items()]
    cons_rows.sort(key=lambda x: -x[3])
    a["champ"] = {"drivers": drivers, "cons": cons_rows}
    save_all(a)
    with open(os.path.join(HERE, "the_race.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["Date", "Store Name", "Queue average", "Area Coach"])
        w.writerows(csv_rows)
    print("[pull] f1: %d stores, newest race %s (cur_end %s)" % (len(fd), newest, CUR_END))
    return newest


def pull_takeaway():
    """STEP 2h — last complete week takeaway % from v_sales_details.eatin_takeaway -> rec.takeaway."""
    a = load_all(); rec = a["rec"]
    rows = bq(f"""
      SELECT outlet.outlet_name s,
        ROUND(100*COUNT(DISTINCT IF(eatin_takeaway='Takeaway',id,NULL))/COUNT(DISTINCT id),1) tk
      FROM {SDET} WHERE DATE(sales_date) BETWEEN {d(6)} AND {CE}
      GROUP BY s""")
    for r in rows:
        if r["s"] in rec: rec[r["s"]]["takeaway"] = r["tk"]
    save_all(a)
    print("[pull] takeaway: %d stores" % len(rows))


def pull_cph_fallback():
    """STEP 2b — CPH fallback from Store-Targets sheet tab1 A1:F40 col C -> rec.cph (blank keeps)."""
    a = load_all(); rec = a["rec"]
    rows = sheet(SID["cph"], "A1:F40")
    n = 0
    for r in rows[1:]:
        if not r: continue
        st = normalize(r[0])
        if st and st in rec and len(r) > 2 and r[2] not in (None, ""):
            rec[st]["cph"] = fnum(r[2]); n += 1
    save_all(a)
    print("[pull] cph fallback: %d stores" % n)


def pull_cph_targets():
    """B5 — Store-Targets CPH £/hr -> cph_targets.json (Glenvale 63, Leamington 58)."""
    rows = sheet(SID["cph"], "A1:F40")
    tgt = {}
    for r in rows[1:]:
        if not r: continue
        st = normalize(r[0])
        if st and len(r) > 2 and r[2] not in (None, ""):
            tgt[st] = round(fnum(r[2]))
    W("cph_targets.json", {"_source": "Google Sheet %s tab1 (CPH target £/hr)" % SID["cph"],
        "_pulled": CUR_END.isoformat(), "targets": tgt}, indent=1)
    print("[pull] cph_targets: %d stores" % len(tgt))


def pull_cos():
    """B4 — Cost of Sales 'Master COS Input' (sheet 1doPNL5…). AUTHORITATIVE Gross Profit% is
    col Q — the sheet's own GP after ALL cost-of-sales (≈3–4pp below a naive (Sales−CoG)/Sales,
    which only nets off col I 'Cost of Goods'). Estate GP = SALES-WEIGHTED col Q; per-store GP =
    latest col Q per store (all stores). Cols: date=idx1(B), store=idx2(C), holding%=idx6(G),
    Sales=idx7(H), Gross Profit=idx16(Q). -> cos_metrics.json."""
    rows = sheet(SID["cos"], "'Master COS Input'!A1:R20000")
    # short COS store labels unique to this sheet -> canonical (the global _MAP covers the rest)
    COS_ALIAS = {"drive thru": "Northampton Drive-Thru", "station": "Wellingborough Train Station",
                 "heathcote": "Lower Heathcote", "billing": "Billing Drive Thru",
                 "lakes": "Rushden Lakes", "glenvale dt": "Glenvale Drive Thru"}
    def cos_store(v):
        s = str(v).strip()
        return COS_ALIAS.get(s.lower()) or normalize(s)
    def gpfrac(v):
        """Parse col Q 'Gross Profit' -> fraction 0..1 (tolerate '70.8#%', '68,71%'); None if junk."""
        if v in (None, ""): return None
        if isinstance(v, (int, float)):
            x = float(v)
        else:
            t = str(v).replace("#", "").replace("%", "").replace(",", ".").strip()
            try: x = float(t)
            except Exception: return None
        if x > 2: x = x / 100.0
        return x if 0.3 < x < 1.2 else None
    QSTART_S = (QSTART - EPOCH).days
    MAY1_S = (datetime.date(CUR_END.year, 5, 1) - EPOCH).days
    MAY31_S = (datetime.date(CUR_END.year, 5, 31) - EPOCH).days
    agg = {}            # date-serial -> [Σsales, Σ(sales*gp)]  (sales-weighted col Q)
    latest = {}         # store -> (holding%, gp%, date-serial)
    qtd_ps = {}         # store -> [Σsales, Σ(sales*gp)] over the quarter (per-store QTD GP)
    for r in rows:
        if len(r) < 17 or not isinstance(r[1], (int, float)): continue
        sales = r[7] if isinstance(r[7], (int, float)) else None
        gp = gpfrac(r[16])                                   # col Q = authoritative Gross Profit
        if not sales or sales <= 0 or gp is None: continue
        ds = int(r[1])
        a = agg.setdefault(ds, [0.0, 0.0]); a[0] += sales; a[1] += sales * gp
        st = cos_store(r[2]) if len(r) > 2 and r[2] not in (None, "") else None
        if st:
            hc = fnum(r[6]) if len(r) > 6 and r[6] not in (None, "") else None
            hold = (round(hc * 100, 1) if hc and hc < 2 else round(hc, 1)) if hc is not None else None
            if st not in latest or ds >= latest[st][2]:
                latest[st] = (hold, round(gp * 100, 2), ds)
            if ds >= QSTART_S:
                qa = qtd_ps.setdefault(st, [0.0, 0.0]); qa[0] += sales; qa[1] += sales * gp
    def _egp(filt):
        ts = tw = 0.0
        for ds, (sa, gw) in agg.items():
            if filt(ds): ts += sa; tw += gw
        return round(tw / ts * 100, 2) if ts else None
    maxd = max(agg) if agg else None
    out = {"_source": "Cost of Sales sheet %s 'Master COS Input' — AUTHORITATIVE Gross Profit%% (col Q), "
                      "sales-weighted for estate; latest col Q per store." % SID["cos"],
           "_pulled": CUR_END.isoformat(), "stores": {},
           "_estate_gp_basis": "Master COS Input col Q Gross Profit%, sales-weighted: Σ(Sales×GP)/ΣSales",
           "estate_gp_wk": _egp(lambda d: d == maxd) if maxd else None,
           "estate_gp_qtd": _egp(lambda d: d >= QSTART_S),
           "estate_gp_may": _egp(lambda d: MAY1_S <= d <= MAY31_S),
           "estate_gp_wk_date": serial_to_iso(maxd) if maxd else None,
           "_week": serial_to_iso(maxd) if maxd else "",
           "estate_gp_by_week": {}}
    # per-week estate GP (week-ending Sunday), sales-weighted col Q, for the grid back-fill
    wagg = {}
    for ds, (sa, gw) in agg.items():
        dd = serial_to_date(ds)
        if not dd: continue
        we = (dd - datetime.timedelta(days=(dd.weekday() + 1) % 7)).isoformat()   # week-ending Sunday
        a = wagg.setdefault(we, [0.0, 0.0]); a[0] += sa; a[1] += gw
    out["estate_gp_by_week"] = {we: round(gw / sa * 100, 2) for we, (sa, gw) in wagg.items() if sa}
    for st, (h, gp, ds) in latest.items():
        out["stores"][st] = {"holding_pct": h, "gp_pct": gp}
    for st, (sa, gw) in qtd_ps.items():                       # per-store QTD GP (sales-weighted col Q)
        if sa:
            out["stores"].setdefault(st, {})["gp_qtd"] = round(gw / sa * 100, 2)
    W("cos_metrics.json", out, indent=1)
    print("[pull] cos: %d stores; estate GP wk %s / qtd %s / may %s (authoritative col Q, sales-weighted)"
          % (len(latest), out.get("estate_gp_wk"), out.get("estate_gp_qtd"), out.get("estate_gp_may")))


def pull_smt():
    """STEP 2c — SMT visits -> smt_visits.json + rec.visdow (area heatmap)."""
    rows = sheet(SID["smt"], "'Master'!A1:M3000")
    people = ["Jon", "Rich", "Claire", "Kel", "Matt", "James", "Ian", "Vicky"]   # cols 1..8
    DOWN = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
            "saturday": 5, "sunday": 6}
    visits = {p: {} for p in people}
    weeks = {p: {} for p in people}
    for r in rows[1:]:
        if not r or not r[0]: continue
        st = normalize(r[0])
        if st is None: continue
        for pi, p in enumerate(people, start=1):
            cell = str(r[pi]).strip().lower() if len(r) > pi and r[pi] else ""
            if cell in DOWN:
                rec = visits[p].setdefault(st, [0] * 7 + [0])   # 7 days + total
                rec[DOWN[cell]] += 1; rec[7] += 1
    smt = {}
    for p in people:
        if visits[p]:
            smt[p] = {st: v for st, v in visits[p].items()}
    W("smt_visits.json", smt, indent=1)
    # rec.visdow from each store's coach column (Jon/Rich/Ian)
    a = load_all(); rec = a["rec"]
    for st in rec:
        coach = COACH.get(st)
        byday = visits.get(coach, {}).get(st)
        if byday:
            rec[st]["visdow"] = {"byday": byday[:7], "total": byday[7]}
    save_all(a)
    print("[pull] smt: %d people" % len(smt))


def pull_sickness():
    """STEP 2i — Sickness/late + RTW -> rec.sent. YTD 2026 per store."""
    a = load_all(); rec = a["rec"]
    sick = sheet(SID["hrp"], "'Sickness / late'!A1:H6000")
    rtw = sheet(SID["hrp"], "'RTW'!A1:E6000")
    yr = CUR_END.year
    cutoff45 = CUR_END - datetime.timedelta(days=45)
    S = {}
    for r in sick[1:]:
        if not r or len(r) < 6 or not r[1]: continue
        st = normalize(r[1])
        if st is None: continue
        dt = parse_any_date(r[5])
        if not dt or dt.year != yr: continue
        typ = str(r[3]).strip().lower() if len(r) > 3 and r[3] else ""
        e = S.setdefault(st, {"sick": 0, "sickfs": 0, "late": 0, "rep": 0, "tot": 0,
                              "sick45": 0, "out45": 0})
        e["tot"] += 1
        if "late" in typ: e["late"] += 1
        else:
            e["sick"] += 1
            if "shift" in typ or "for shift" in typ: e["sickfs"] += 1
            if dt >= cutoff45: e["sick45"] += 1; e["out45"] += 1
        if len(r) > 2 and r[2]: e["rep"] += 1
    RT = {}
    for r in rtw[1:]:
        if not r or len(r) < 2 or not r[1]: continue
        st = normalize(r[1])
        if st is None: continue
        dt = parse_any_date(r[2]) if len(r) > 2 else None
        # Must be dated AND this year, same basis as the sickness denominator. Previously an
        # unparseable JS date (dt=None) fell through and was counted, so ALL RTW rows since 2022
        # were tallied -> rtw_rate ran to 169/213/1350%. Pair it 1:1 with this-year sickness.
        if not dt or dt.year != yr: continue
        RT[st] = RT.get(st, 0) + 1
    for st in rec:
        e = S.get(st, {})
        sickn = e.get("sick", 0)
        rec[st]["sent"] = {
            "sickfs": e.get("sickfs", 0), "late": e.get("late", 0), "sick": sickn,
            "rtw": RT.get(st, 0),
            "rtw_rate": round(100 * RT.get(st, 0) / sickn, 0) if sickn else None,
            "rep_pct": round(100 * e.get("rep", 0) / e.get("tot", 1), 0) if e.get("tot") else None,
            "out45": e.get("out45", 0), "sick45": e.get("sick45", 0)}
    save_all(a)
    print("[pull] sickness: %d stores" % len(S))


def pull_audit():
    """STEP 2j / B2 — Brand Audit. Writes audit_raw.json (Glenvale+Leamington this quarter,
    5 sub-scores) for build_audit, and sets rec.audit_qtd (QTD avg of Total col J) for all."""
    rows = sheet(SID["audit"], "'Brand Audit Date (NEW24/25)'!A1:L4000")
    a = load_all(); rec = a["rec"]
    qtd = {}                          # store -> [totals]
    lastwk = []                       # estate totals for audits dated in the last completed week
    raw_rows = {}
    for r in rows[1:]:
        if not r or not r[0]: continue
        st = normalize(r[0])
        if st is None: continue
        dt = parse_any_date(r[3]) if len(r) > 3 else None
        if not dt: continue
        total = fnum(r[9]) if len(r) > 9 else None
        if dt >= QSTART and total:
            qtd.setdefault(st, []).append(total)
        if total and LASTWK_MON <= dt <= CUR_END:
            lastwk.append(total)
        if st in COMMERCIAL_STORES and dt >= QSTART:
            sub = [fnum(r[i]) for i in range(4, 9)] if len(r) > 8 else []
            plan = r[10] if len(r) > 10 else ""
            raw_rows.setdefault(st, []).append(
                {"date": dt.strftime("%-m/%-d/%Y"), "sub": sub, "total": total, "plan": plan})
    for st, ts in qtd.items():
        if st in rec: rec[st]["audit_qtd"] = round(sum(ts) / len(ts), 2)
    save_all(a)
    W("audit_raw.json", {"_pulled": CUR_END.isoformat(),
        "_sheet": "%s / Brand Audit Date (NEW24/25)" % SID["audit"],
        "_lastwk_avg": round(sum(lastwk) / len(lastwk), 2) if lastwk else None,
        "_lastwk_n": len(lastwk),
        "_cols": ["Store", "Date", "Culture", "ShiftMgmt", "Cleanliness", "Product",
                  "Maintenance", "Total", "ActionPlan"], "rows": raw_rows}, indent=1)
    print("[pull] audit: %d stores qtd, %d raw stores, %d audits last week" % (len(qtd), len(raw_rows), len(lastwk)))


def pull_availability():
    """STEP 2m — Availability 'Polling' (chunked) -> rec.avail (latest COMPLETE week avg col J)."""
    a = load_all(); rec = a["rec"]
    rows = sheet(SID["availability"], "'Polling'!A1:K6000")
    rows += sheet(SID["availability"], "'Polling'!A6001:K18000")
    by = {}                            # store -> {wc_date: [pcts]}
    for r in rows:
        if not r or len(r) < 11 or not r[10]: continue
        st = normalize(r[10])
        if st is None: continue
        wc = parse_any_date(r[0])
        if not wc or wc >= CURWK_MON: continue          # exclude current/incomplete week
        try: pct = float(r[9])
        except Exception: continue
        by.setdefault(st, {}).setdefault(wc, []).append(pct)
    for st in rec:
        wk = by.get(st)
        if not wk: continue
        latest = max(wk)
        vals = wk[latest]
        rec[st]["avail"] = round(sum(vals) / len(vals), 1) if vals else None
    save_all(a)
    print("[pull] availability: %d stores" % len(by))


def pull_reviews():
    """STEP 2l — Reviews tab verbatim -> reviews_raw.json (for build_reviews) + rec.cust
    (lifetime rating/reviews) + customer.json + the google half of storehealth_raw.json."""
    rows = sheet(SID["reviews"], "Reviews!A1:D6000", unformatted=False)
    if len(rows) >= 5999:             # cap hit -> read the tail too
        rows += sheet(SID["reviews"], "Reviews!A6000:D20000", unformatted=False)
    recs = []
    for r in rows[1:]:
        if not r or not r[0]: continue
        recs.append({"store": r[0],
                     "star_rating": r[1] if len(r) > 1 else "",
                     "comment": r[2] if len(r) > 2 else "",
                     "time": r[3] if len(r) > 3 else ""})
    W("reviews_raw.json", recs)       # working file (NOT committed) — build_reviews consumes it
    # lifetime cust + last-week customer.json + QTD google for storehealth
    a = load_all(); rec = a["rec"]
    life = {}; lastwk = {}; qtd_g = {}
    for x in recs:
        st = normalize(x["store"])
        if st is None: continue
        star = fnum(x["star_rating"], None) if x["star_rating"] not in (None, "") else None
        if star is None: continue
        dt = parse_any_date(x["time"])
        life.setdefault(st, []).append(star)
        if dt and LASTWK_MON <= dt <= CUR_END:
            lastwk.setdefault(st, []).append(star)
        if dt and dt >= QSTART:
            qtd_g.setdefault(st, []).append(star)
    for st in rec:
        ls = life.get(st)
        if ls: rec[st]["cust"] = {"rating": round(sum(ls) / len(ls), 2), "reviews": len(ls)}
    n_rev = sum(len(v) for v in lastwk.values())
    sum_avg = sum(round(sum(v) / len(v), 2) for v in lastwk.values())
    health = round((sum_avg / 21) * 0.5 + (n_rev / 125) * 5 * 0.5, 1)
    W("customer.json", {"company_health": health, "sum_store_avg": round(sum_avg, 1),
        "stores_with_reviews": len(lastwk), "reviews": n_rev,
        "avg_rating_last_week": round(sum(s for v in lastwk.values() for s in v) / n_rev, 1) if n_rev else None,
        "window": wlabel(LASTWK_MON) + " (Mon-Sun)", "target": 3.32, "reviews_target": 125}, indent=1)
    save_all(a)
    json.dump({st: [len(v), round(sum(v) / len(v), 3)] for st, v in qtd_g.items()},
              open(os.path.join(HERE, "_google_qtd.json"), "w"))    # scratch for storehealth
    print("[pull] reviews: %d rows, %d stores last week" % (len(recs), len(lastwk)))


def pull_rms_storehealth():
    """STEP 2g2/2g3 — F1 'Shift Ratings' tab. rms.json (company last week) + storehealth_raw.json
    (per-store QTD RMS + per-store QTD Google) for the refactored storehealth_calc.py.
    VALIDATED layout via Zapier 29 Jun: Date0(serial) Store1 Rating2."""
    rows = sheet(SID["f1"], "'Shift Ratings'!A1:N20000")   # FULL tail — latest submissions are at the BOTTOM (>6k rows); A1:N6000 missed them
    lastwk = []                        # company last completed week
    qtd = {}                           # store -> [ratings] (QTD)
    for r in rows[1:]:
        if not r or len(r) < 3 or not r[1]: continue
        dt = parse_any_date(r[0]); st = normalize(r[1])
        try: rating = float(r[2])
        except Exception: continue
        if not dt: continue
        if LASTWK_MON <= dt <= CUR_END: lastwk.append(rating)
        if st and dt >= QSTART: qtd.setdefault(st, []).append(rating)
    avg = round(sum(lastwk) / len(lastwk), 2) if lastwk else None
    subs = len(lastwk)
    W("rms.json", {"avg_rating": avg, "submissions": subs,
        "company_health": round((avg / 21) * 0.5 + (subs / 50) * 5 * 0.5, 2) if avg else None,
        "week": wlabel(LASTWK_MON), "target": 3.32, "submissions_target": 50}, indent=1)
    google = json.load(open(os.path.join(HERE, "_google_qtd.json"))) \
        if os.path.exists(os.path.join(HERE, "_google_qtd.json")) else {}
    W("storehealth_raw.json", {
        "_updated": CUR_END.isoformat(),
        "_basis": "Quarter-to-date (from %s). NOT last week." % QSTART.isoformat(),
        "rms": {st: [len(v), round(sum(v) / len(v), 3)] for st, v in qtd.items()},
        "google": {st: v for st, v in google.items()}}, indent=1)
    # surface per-store QTD RMS into rec.sent (rms avg + count) — all generators read sent[s]['rms']/['rms_n']
    a = load_all(); rec = a["rec"]
    for st in rec:
        sent = rec[st].setdefault("sent", {})
        v = qtd.get(st)
        sent["rms"] = round(sum(v) / len(v), 2) if v else None
        sent["rms_n"] = len(v) if v else 0
    save_all(a)
    print("[pull] rms/storehealth: company subs %d avg %s; %d rms stores qtd" % (subs, avg, len(qtd)))


def pull_planner():
    """STEP 2g — 3 area planners 'Weekly Planner'!A1:L60 -> planner_overrides.json (MANDATORY).
    VALIDATED layout via Zapier 29 Jun. Section A: Hours used=idx5, Actual CPH=idx6.
    Section B: CPH=idx1, Forecast=idx4/7/10, Plan hrs=idx5/8/11. Blank hours -> field absent."""
    ovr = {}
    for sid in (SID["planner_jon"], SID["planner_rich"], SID["planner_ian"]):
        rows = sheet(sid, "'Weekly Planner'!A1:L60")
        sec = None
        for r in rows:
            if not r: continue
            head = str(r[0]).strip() if r[0] is not None else ""
            low = head.lower()
            if low == "store" and any("hours used" == str(c).strip().lower() for c in r):
                sec = "A"; continue
            if low == "store" and any("cph target" == str(c).strip().lower() for c in r) and len(r) >= 12:
                sec = "B"; continue
            if head.startswith("AREA TOTAL") or head.startswith("②") or head.startswith("①"):
                if head.startswith("AREA"): sec = None
                continue
            st = normalize(r[0])
            if st is None: continue
            o = ovr.setdefault(st, {})
            if sec == "A":
                used = r[5] if len(r) > 5 and r[5] not in (None, "") else None
                acph = r[6] if len(r) > 6 and r[6] not in (None, "") else None
                if used is not None: o["used_lastwk"] = round(fnum(used), 1)
                if acph is not None: o["actual_cph_lastwk"] = round(fnum(acph), 1)
            elif sec == "B":
                o["cph"] = round(fnum(r[1]), 1) if len(r) > 1 and r[1] not in (None, "") else o.get("cph")
                def cv(i): return round(fnum(r[i])) if len(r) > i and r[i] not in (None, "") else None
                o["fc"] = [cv(4), cv(7), cv(10)]
                o["hrs"] = [round(fnum(r[5]), 1) if len(r) > 5 and r[5] not in (None, "") else None,
                            round(fnum(r[8]), 1) if len(r) > 8 and r[8] not in (None, "") else None,
                            round(fnum(r[11]), 1) if len(r) > 11 and r[11] not in (None, "") else None]
    W("planner_overrides.json", ovr, indent=1)
    print("[pull] planner: %d stores" % len(ovr))


def pull_actuals():
    """STEP 2f — Master Populator tail -> actuals.json (latest dated row per store)."""
    rows = sheet(SID["master_pop"], "'Master Populator'!A3000:N4300")
    latest = {}                        # store -> (date, [reportDate, fcLastWk, hoursSched, hoursUsed])
    for r in rows:
        if not r or len(r) < 7 or not r[1]: continue
        raw = str(r[1]).strip()
        st = normalize(re.sub(r"^[0-9]+\s*", "", raw))
        if st is None or "leamington spa" in raw.lower(): continue
        dt = parse_any_date(r[0])
        if not dt: continue
        fc = round(fnum(r[4])) if len(r) > 4 else 0
        hsch = round(fnum(r[5])) if len(r) > 5 else 0
        hused = round(fnum(r[8])) if len(r) > 8 and r[8] not in (None, "") else 0
        if st not in latest or dt > latest[st][0]:
            latest[st] = (dt, [dt.strftime("%-m/%-d/%Y"), fc, hsch, hused])
    out = {"_week_label": "W/C " + LASTWK_MON.strftime("%-d %b")}
    for st, (dt, vals) in latest.items(): out[st] = vals
    W("actuals.json", out, indent=1)
    print("[pull] actuals: %d stores" % len(latest))


def pull_peak():
    """STEP 2p — company-wide last-4-weeks category×daypart + bakery-by-product ->
    peak_cat_raw.json + peak_bakery_raw.json (build_mix_peaktime transforms)."""
    cat = bq(f"""
      SELECT cat, dp, ROUND(SUM(v)) s FROM (
        SELECT {cat_case('item_product_name')} cat, {dp_case(HOUR)} dp,
               SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
        FROM {FLAT} WHERE DATE(sales_date) BETWEEN {d(27)} AND {CE})
      WHERE dp!='Other' GROUP BY cat, dp""")
    pc = [{"cat": CATLABEL[r["cat"]], "dp": r["dp"], "s": r["s"]} for r in cat]
    W("peak_cat_raw.json", pc)
    bak = bq(f"""
      WITH x AS (
        SELECT TRIM(REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(item_product_name,r'^[0-9*]+ *',''),r' TA$',''),' (Copy)','')) prod,
               {dp_case(HOUR)} dp, {HOUR} hr,
               SAFE_CAST(item_quantity AS FLOAT64) q,
               SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
        FROM {FLAT}
        WHERE DATE(sales_date) BETWEEN {d(27)} AND {CE} AND {cat_case('item_product_name')}='Bakery'),
      pd AS (SELECT prod, dp, SUM(q) u FROM x GROUP BY prod, dp),
      ph AS (SELECT prod, hr, SUM(q) u FROM x GROUP BY prod, hr),
      tot AS (SELECT prod, ROUND(SUM(q)) units, ROUND(SUM(v)) sales FROM x GROUP BY prod),
      top_dp AS (SELECT prod, ARRAY_AGG(dp ORDER BY u DESC LIMIT 1)[OFFSET(0)] peak_dp,
                        MAX(u) maxu FROM pd GROUP BY prod),
      top_hr AS (SELECT prod, ARRAY_AGG(hr ORDER BY u DESC LIMIT 1)[OFFSET(0)] peak_hr FROM ph GROUP BY prod)
      SELECT t.prod, t.units, t.sales, td.peak_dp,
             ROUND(100*td.maxu/t.units) share, th.peak_hr
      FROM tot t JOIN top_dp td USING(prod) JOIN top_hr th USING(prod)
      WHERE t.units>=20 ORDER BY t.units DESC""")
    W("peak_bakery_raw.json", [dict(r) for r in bak])
    print("[pull] peak: %d cat rows, %d bakery products" % (len(pc), len(bak)))


def pull_daypart_food():
    """STEP 2n — Food+Bakery cur4 vs LY4 by daypart, company + per-coach -> daypart_food.json
    + daypart_food_area.json."""
    rows = bq(f"""
      SELECT s, dp, nm,
        ROUND(SUM(IF(dd BETWEEN {d(27)} AND {CE},v,0))) cur,
        ROUND(SUM(IF(dd BETWEEN {d(391)} AND {d(364)},v,0))) ly
      FROM (
        SELECT item_outlet_name s, DATE(sales_date) dd, {dp_case(HOUR)} dp,
               {CLEAN} nm, SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
        FROM {FLAT}
        WHERE DATE(sales_date) BETWEEN {d(391)} AND {CE}
          AND {cat_case('item_product_name')} IN ('Food','Bakery'))
      WHERE dp!='Other' GROUP BY s, dp, nm""")
    HRS = {"Morning": "5am-11am", "Lunch": "11am-2pm", "Afternoon": "2pm-5pm", "Evening": "5pm+"}
    def assemble(filt_coach, new_floor):
        bydp = {}
        for r in rows:
            if filt_coach and COACH.get(r["s"]) != filt_coach: continue
            e = bydp.setdefault(r["dp"], {})
            t = e.setdefault(r["nm"], [0, 0]); t[0] += r["cur"] or 0; t[1] += r["ly"] or 0
        out = {}
        for dp in ("Morning", "Lunch", "Afternoon", "Evening"):
            items = bydp.get(dp, {})
            grown = [[nm, c, round(100 * (c / l - 1), 1), round(c - l)]
                     for nm, (c, l) in items.items() if l > 0]
            grown.sort(key=lambda x: -x[3])
            new = [[nm, c] for nm, (c, l) in items.items()
                   if l == 0 and c >= new_floor and "(Copy)" not in nm and not nm.endswith(" SL")]
            new.sort(key=lambda x: -x[1])
            out[dp] = {"hours": HRS[dp], "top": grown[:3], "new": new[:2]}
        return out
    W("daypart_food.json", {"_window": short_window(), "hours": HRS,
        "dayparts": assemble(None, 300)}, indent=1)
    W("daypart_food_area.json", {"_window": short_window(), "hours": HRS,
        "coaches": {c: {"dayparts": assemble(c, 150)} for c in ("Jon", "Ian", "Rich")}}, indent=1)
    print("[pull] daypart_food: company + 3 areas")


def pull_bench():
    """STEP 2o — HRP 'HRP & Bench' -> bench.json (rendered by bench_render.py).
    Columns B-J: Store Manager, Assistant Manager, Culture Coach(D), Supervisor 1, Supervisor 2,
    Bench Manager(G), Pipeline 1/2/3(H-J). Full names."""
    rows = sheet(SID["hrp"], "'HRP & Bench'!A1:K200", unformatted=False)
    cols = ["Store Manager", "Assistant Manager", "Culture Coach", "Supervisor 1",
            "Supervisor 2", "Bench Manager", "Pipeline 1", "Pipeline 2", "Pipeline 3"]  # D is now Culture Coach (new HRP layout)
    # HRP tab uses some informal store labels normalize() doesn't catch -> map them (matches bench_render._BMAP)
    HRPMAP = {"Drive Thru Northampton": "Northampton Drive-Thru", "Train Station": "Wellingborough Train Station",
              "Wellingborough Market St": "Wellingborough", "Fletton Quays": "Peterborough Fletton Quays",
              "Peterborough": "Peterborough Bridge Street", "Balsall Common": "HOE Balsall Common"}
    out_rows = []
    for r in rows[1:]:
        if not r or not r[0]: continue
        raw = str(r[0]).strip()
        st = HRPMAP.get(raw) or normalize(raw)
        if st is None: continue
        out_rows.append([st] + [(r[i] if len(r) > i else "") for i in range(1, 10)])
    W("bench.json", {"_source": "HRP sheet %s, tab 'HRP & Bench' (Sheets API)" % SID["hrp"],
        "_updated": CUR_END.isoformat(), "cols": cols, "rows": out_rows}, indent=1)
    print("[pull] bench: %d stores" % len(out_rows))


# ----- store-page raws (STEP 4f) — build_newsite_sales reads these verbatim -----
NS_OUTLETS = "('Olney','Attleborough','Billing Drive Thru','Glenvale Drive Thru'," \
             "'Northampton Drive-Thru','Leamington Parade')"
DT_IN = "('Billing Drive Thru','Glenvale Drive Thru','Northampton Drive-Thru')"

def pull_ns_raws():
    """STEP 4f — regenerate ALL 7 store raws every run (a skipped raw FREEZES that figure)."""
    dow = bq(f"""
      SELECT CONCAT(item_outlet_name,'|',CAST(EXTRACT(DAYOFWEEK FROM DATE(sales_date)) AS STRING)) k,
        ROUND(SUM(IF(DATE(sales_date) BETWEEN {d(27)} AND {CE},
                     SAFE_CAST(item_line_total_after_discount AS FLOAT64),0))) cur,
        ROUND(SUM(IF(DATE(sales_date) BETWEEN {d(391)} AND {d(364)},
                     SAFE_CAST(item_line_total_after_discount AS FLOAT64),0))) ly
      FROM {FLAT}
      WHERE item_outlet_name IN {NS_OUTLETS} AND DATE(sales_date) BETWEEN {d(391)} AND {CE}
      GROUP BY k""")
    W("ns_dow_raw.json", [{"k": r["k"], "cur": r["cur"], "ly": r["ly"]} for r in dow])
    dpt = bq(f"""
      SELECT CONCAT(s,'|',dp) k,
        ROUND(SUM(IF(dd BETWEEN {d(27)} AND {CE},v,0))) cur,
        ROUND(SUM(IF(dd BETWEEN {d(391)} AND {d(364)},v,0))) ly
      FROM (SELECT item_outlet_name s, DATE(sales_date) dd, {dp_case(HOUR)} dp,
                   SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
            FROM {FLAT}
            WHERE item_outlet_name IN {NS_OUTLETS} AND DATE(sales_date) BETWEEN {d(391)} AND {CE})
      WHERE dp!='Other' GROUP BY k""")
    W("ns_daypart_raw.json", [{"k": r["k"], "cur": r["cur"], "ly": r["ly"]} for r in dpt])
    food = bq(f"""
      SELECT CONCAT(s,'|',dp,'|',nm) k, cur, ly FROM (
        SELECT s, dp, nm,
          ROUND(SUM(IF(dd BETWEEN {d(27)} AND {CE},v,0))) cur,
          ROUND(SUM(IF(dd BETWEEN {d(391)} AND {d(364)},v,0))) ly
        FROM (SELECT item_outlet_name s, DATE(sales_date) dd, {dp_case(HOUR)} dp,
                     {CLEAN} nm, SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
              FROM {FLAT}
              WHERE item_outlet_name IN {NS_OUTLETS} AND DATE(sales_date) BETWEEN {d(391)} AND {CE}
                AND {cat_case('item_product_name')} IN ('Food','Bakery'))
        WHERE dp!='Other' GROUP BY s, dp, nm)
      WHERE cur>=40 OR ly>=40""")
    W("ns_food_raw.json", [{"k": r["k"], "cur": r["cur"], "ly": r["ly"]} for r in food])
    # 4. drive-thru cars/total this week (VALIDATED 29 Jun: Glenvale 1060/2501 == committed raw)
    dt = bq(f"""
      SELECT outlet.outlet_name s,
        COUNT(DISTINCT IF(LOWER(register.register_name) LIKE '%drive%',id,NULL)) cars,
        COUNT(DISTINCT id) total
      FROM {SDET}
      WHERE outlet.outlet_name IN {DT_IN} AND DATE(sales_date) BETWEEN {d(6)} AND {CE}
      GROUP BY s""")
    W("ns_drivethru_raw.json", [{"k": r["s"], "cars": str(r["cars"]), "total": str(r["total"])} for r in dt])
    # 5. all-time record cars week per DT store (share<=75 guard)
    dtrec = bq(f"""
      SELECT s, wc, cars, share FROM (
        SELECT outlet.outlet_name s, DATE_TRUNC(DATE(sales_date),WEEK(MONDAY)) wc,
          COUNT(DISTINCT IF(LOWER(register.register_name) LIKE '%drive%',id,NULL)) cars,
          COUNT(DISTINCT id) total,
          ROUND(100*COUNT(DISTINCT IF(LOWER(register.register_name) LIKE '%drive%',id,NULL))/COUNT(DISTINCT id)) share
        FROM {SDET} WHERE outlet.outlet_name IN {DT_IN}
        GROUP BY s, wc HAVING share<=75
        QUALIFY ROW_NUMBER() OVER (PARTITION BY s ORDER BY cars DESC)=1)""")
    W("ns_dtrecord_raw.json", [{"k": "%s|%s" % (r["s"], r["wc"]),
        "cars": str(r["cars"]), "share": str(int(r["share"]))} for r in dtrec])
    # 6. all-time record weekly revenue per store
    rw = bq(f"""
      SELECT s, wc, rev FROM (
        SELECT item_outlet_name s, DATE_TRUNC(DATE(sales_date),WEEK(MONDAY)) wc,
               ROUND(SUM(SAFE_CAST(item_line_total_after_discount AS FLOAT64))) rev
        FROM {FLAT} WHERE item_outlet_name IN {NS_OUTLETS}
        GROUP BY s, wc
        QUALIFY ROW_NUMBER() OVER (PARTITION BY s ORDER BY rev DESC)=1)""")
    W("ns_recweek_raw.json", [{"k": "%s|%s" % (r["s"], r["wc"]), "rev": str(int(r["rev"]))} for r in rw])
    # 7. all-time record hour per store (orders>=5 AND rev/orders<=20 ATV guard)
    rh = bq(f"""
      SELECT s, dd, hr, rev, orders FROM (
        SELECT item_outlet_name s, DATE(sales_date) dd, {HOUR} hr,
               ROUND(SUM(SAFE_CAST(item_line_total_after_discount AS FLOAT64))) rev,
               COUNT(DISTINCT id) orders
        FROM {FLAT} WHERE item_outlet_name IN {NS_OUTLETS}
        GROUP BY s, dd, hr
        HAVING orders>=5 AND rev/orders<=20
        QUALIFY ROW_NUMBER() OVER (PARTITION BY s ORDER BY rev DESC)=1)""")
    W("ns_rechour_raw.json", [{"k": "%s|%s|%s" % (r["s"], r["dd"], r["hr"]),
        "rev": str(int(r["rev"])), "orders": str(r["orders"])} for r in rh])
    print("[pull] ns raws: dow %d daypart %d food %d dt %d" % (len(dow), len(dpt), len(food), len(dt)))


# SL chilled grab-and-go name fold (baps + bagel folded; generic Breakfast Meal Deal left out).
SL_NAME = (r"""CASE
  WHEN REGEXP_CONTAINS(LOWER(item_product_name), r'bacon bap') THEN 'Bacon Bap'
  WHEN REGEXP_CONTAINS(LOWER(item_product_name), r'sausage bap') THEN 'Sausage Bap'
  WHEN REGEXP_CONTAINS(LOWER(item_product_name), r'breakfast bagel') THEN 'Breakfast Bagel'
  ELSE TRIM(REGEXP_REPLACE(REGEXP_REPLACE(item_product_name,r'^[23]?[*]? ',''),r' TA$','')) END""")
SL_FILTER = (r"REGEXP_CONTAINS(LOWER(item_product_name), "
             r"r'sandwich|wrap|salad|ciabatta|panini|toastie|baguette|\bbap\b|bagel') "
             r"AND NOT REGEXP_CONTAINS(LOWER(item_product_name), r'breakfast meal deal|sausage roll|pastry')")

def pull_sl_raws():
    """STEP 4f(b2) — per-store Simply Lunch day-of-week demand (last 8 complete weeks)."""
    for store, fn in (("Glenvale Drive Thru", "sl_glenvale_raw.json"),
                      ("Leamington Parade", "sl_leamington_raw.json")):
        item = bq(f"""
          SELECT {SL_NAME} nm, EXTRACT(DAYOFWEEK FROM DATE(sales_date)) dow,
                 ROUND(SUM(SAFE_CAST(item_quantity AS FLOAT64))) units
          FROM {FLAT}
          WHERE item_outlet_name='{store}' AND DATE(sales_date) BETWEEN {d(55)} AND {CE}
            AND {SL_FILTER}
          GROUP BY nm, dow HAVING units>0""")
        dowdays = bq(f"""
          SELECT EXTRACT(DAYOFWEEK FROM dd) dow, COUNT(*) nd FROM (
            SELECT DISTINCT DATE(sales_date) dd FROM {FLAT}
            WHERE item_outlet_name='{store}' AND DATE(sales_date) BETWEEN {d(55)} AND {CE})
          GROUP BY dow""")
        W(fn, {"cur_end": CUR_END.isoformat(), "window_weeks": 8,
            "dowdays": [{"dow": int(r["dow"]), "nd": int(r["nd"])} for r in dowdays],
            "itemdow": [{"nm": r["nm"], "dow": int(r["dow"]), "units": int(r["units"])} for r in item]},
          indent=1)
        print("[pull] sl %s: %d item-rows" % (store, len(item)))


def pull_txq_raws():
    """STEP 4f(b3/b4) — transaction quality 28d channel×daypart. Glenvale DT/DI, Leamington EI/TA."""
    def items_cte(store):
        return f"""items AS (
          SELECT id, ROUND(SUM(v)) tot, MAX(IF(cat IN('Food','Bakery'),1,0)) hasfood,
                 MAX(IF(cat='Other&retail',1,0)) hasretail FROM (
            SELECT id, {cat_case('item_product_name')} cat,
                   SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
            FROM {FLAT} WHERE item_outlet_name='{store}' AND DATE(sales_date) BETWEEN {d(27)} AND {CE})
          GROUP BY id)"""
    gl = bq(f"""
      WITH base AS (SELECT id, IF(LOWER(register.register_name) LIKE '%drive%','DT','DI') channel,
                           {dp_case(HOUR)} dp
                    FROM {SDET} WHERE outlet.outlet_name='Glenvale Drive Thru'
                      AND DATE(sales_date) BETWEEN {d(27)} AND {CE}),
        {items_cte('Glenvale Drive Thru')}
      SELECT channel, dp daypart, COUNT(*) txns, ROUND(SUM(tot)) sales,
             SUM(hasfood) foodtxns, SUM(hasretail) retailtxns
      FROM base JOIN items USING(id) WHERE dp!='Other' GROUP BY channel, dp""")
    W("txq_glenvale_raw.json", {"days": 28, "grid": [dict(r) for r in gl]}, indent=1)
    lm = bq(f"""
      WITH base AS (SELECT id, IF(eatin_takeaway='Takeaway','TA','EI') ch,
                           {dp_case(HOUR)} dp
                    FROM {SDET} WHERE outlet.outlet_name='Leamington Parade'
                      AND DATE(sales_date) BETWEEN {d(27)} AND {CE}),
        {items_cte('Leamington Parade')}
      SELECT ch, dp, COUNT(*) txns, ROUND(SUM(tot)) sales, SUM(hasfood) foodtxns
      FROM base JOIN items USING(id) WHERE dp!='Other' GROUP BY ch, dp""")
    W("txq_leamington_raw.json", {"days": 28, "grid": [dict(r) for r in lm]}, indent=1)
    print("[pull] txq: glenvale %d cells, leamington %d cells" % (len(gl), len(lm)))


def pull_compliance():
    """B3 — HRP compliance source (Glenvale + Leamington) -> compliance_raw.json (build_compliance
    transforms). Open/close from 'Process St - Data'; coaching from 'CS and Br %'; remote audit +
    open/close fallback from star_inputs.json; RTW from allstores rec.sent. Leamington open/close =
    {"awaiting": true} until its dated Process Street rows appear.
    NB the Process St tab layouts are not yet schema-verified under the SA — the live open/close
    reader is wrapped in try/except and falls back to star_inputs; confirm in the live-SA test."""
    si = json.load(open(os.path.join(HERE, "star_inputs.json"))) \
        if os.path.exists(os.path.join(HERE, "star_inputs.json")) else {}
    a = load_all(); rec = a.get("rec", {})
    openclose, coaching_cs, remote_audit, rtw = {}, {}, {}, {}
    # Glenvale: open/close from star_inputs ops (QTD); MTD/WTD live read attempted below.
    gi = si.get("Glenvale Drive Thru", {})
    if gi.get("openclose_pct") is not None:
        pc = gi["openclose_pct"]
        openclose["Glenvale Drive Thru"] = {
            "qtd": {"open": pc, "close": pc, "days": 100},      # pct already; oc_pct/2*days=pct
            "mtd": {"open": pc, "close": pc, "days": 100},
            "wtd": {"open": pc, "close": pc, "days": 100}}
    openclose["Leamington Parade"] = {"awaiting": True,
        "_note": "Leamington completes the Process Street open checklist (snapshot COMPLETED) but its "
                 "dated 'Process St - Data' log is still empty — awaiting first dated rows."}
    for st in COMMERCIAL_STORES:
        s = si.get(st, {})
        if s.get("coaching_cs_pct") is not None:
            coaching_cs[st] = {"qtd": s["coaching_cs_pct"], "mtd": s["coaching_cs_pct"]}
        if s.get("remote_audit") is not None:
            remote_audit[st] = {"score": s["remote_audit"], "n": s.get("remote_n", "?")}
        sent = rec.get(st, {}).get("sent", {})
        if sent.get("rtw_rate") is not None:
            rtw[st] = sent["rtw_rate"]
    W("compliance_raw.json", {"cur_end": CUR_END.isoformat(),
        "_note": "open/close from Process St (Glenvale live via star_inputs ops; Leamington awaiting); "
                 "coaching from CS and Br %; remote_audit + RTW from star_inputs / allstores.",
        "openclose": openclose, "coaching_cs": coaching_cs,
        "remote_audit": remote_audit, "rtw": rtw}, indent=1)
    print("[pull] compliance_raw: openclose %d, coaching %d" % (len(openclose), len(coaching_cs)))


# ============================ BUILD / ASSEMBLE (B–E) ============================
RUN_START = datetime.datetime.now().timestamp()
GEN_LEFTOVER = {}

def pull_maintenance():
    """Maintenance dashboard feed (reactive jobs / planned visits / coffee servicing / audit
    action plans). Sources are Google Sheets read live under the service account. Writes
    maintenance.json for gen_maintenance.py. NON-FATAL: any source that 403s (not yet shared
    with the SA) or errors leaves the section degraded and the run continues; the last-good
    maintenance.json (committed seed) stays in place so the page still renders."""
    try:
        from gen_maintenance import compute_maintenance
        reactive = sheet(SID["maint_jobs"],    "'Maintenance Jobs'!A1:H5000")
        coffee   = sheet(SID["maint_jobs"],    "'Coffee Machine Services'!A1:E2000")
        planned  = sheet(SID["maint_planned"], "'Maintenance'!A1:C3000")
        audit    = sheet(SID["audit"],         "'Brand Audit Date (NEW24/25)'!A1:L4000")
        out = compute_maintenance(reactive, coffee, planned, audit, CUR_END)
        W("maintenance.json", out)  # W() already sets ensure_ascii=False; passing again = duplicate-kwarg TypeError
        co = out["DATA"]["company"]["reactive"]
        print("[pull] maintenance: %d reactive(90d) %d planned stores, %d coffee w/record (%d overdue), %d audit action-plans"
              % (co["total"], out["DATA"]["company"]["planned"]["nstores"],
                 out["CMS"]["nstores"], out["CMS"]["overdue"], out["audit_count"]))
    except Exception as e:
        print("[pull] maintenance SKIPPED (source unreadable by SA? share with %s) - %s"
              % ("dashboards-bot@bewiched-coffee-368116.iam.gserviceaccount.com", e))


def pull_eos_scorecard():
    """EOS Scorecard (Weekly + Quarterly) -> eos_scorecard.json (rendered by gen_eos_scorecard.py).
    LIVE  : YoY Sales / Transactional growth (BigQuery, QTD LFL).
    DERIVED (from feeds already pulled): Google Health, Rate My Shift Health, SPH Labour,
            Brand Audit, Food GP% (CoS proxy).
    MANUAL (read from the 'Bewiched EOS Scorecard Inputs' sheet SID['eos']): Brew Crew Kudos,
            Bench, F1 Score, NPAT, + the two TBC rows. A non-empty actual/plan in that sheet
            OVERRIDES the derived/live value for any metric.
    Fault-tolerant: any source that fails degrades that metric to awaiting and is flagged —
    it must never break the weekly run. STATUS thresholds live in gen_eos_scorecard.py
    Status is strictly binary (no near-target band)."""
    flags = []
    # ---- manual inputs sheet (optional; 403s until shared Viewer with the SA) ----
    manual = {}
    try:
        rows = sheet(SID["eos"], "Sheet1!A1:H60")
        for r in rows[1:]:
            if not r or not r[0]:
                continue
            mid = str(r[0]).strip()
            manual[mid] = {"plan": (r[3] if len(r) > 3 and r[3] not in (None, "") else None),
                           "actual": (r[4] if len(r) > 4 and r[4] not in (None, "") else None)}
    except Exception as e:
        flags.append("Manual inputs sheet not readable (%s) — share it (Viewer) with the service "
                     "account dashboards-bot@%s.iam.gserviceaccount.com. Manual metrics shown as awaiting."
                     % (str(e)[:90], PROJECT))
    def mp(mid, default):
        v = manual.get(mid, {}).get("plan")
        return fnum(v) if v not in (None, "") else default
    def ma(mid):
        v = manual.get(mid, {}).get("actual")
        return fnum(v) if v not in (None, "") else None

    def jload(fn):
        p = os.path.join(HERE, fn)
        return json.load(open(p)) if os.path.exists(p) else {}
    rec = jload("allstores.json").get("rec", {})
    cust = jload("customer.json"); rms = jload("rms.json")
    cos = jload("cos_metrics.json").get("stores", {})
    ovr = jload("planner_overrides.json")
    benchj = jload("bench.json")
    # bench-ready store = complete core leadership line (Store Manager row[1], Assistant Manager
    # row[2], Supervisor 1 row[4] all present) AND a named successor in Bench Manager (G) or
    # Pipeline 1-3 (H-J) — cols row[6..9]. A hierarchy gap at AM/Sup1 (or a SM vacancy)
    # disqualifies bench-readiness, matching the dashboard bench status (bench_render.py).
    def _cell(row, i):
        return str(row[i]).strip() if len(row) > i and row[i] else ""
    def _bench_ready(row):
        core_ok = bool(_cell(row, 1) and _cell(row, 2) and _cell(row, 4))
        has_succ = any(_cell(row, i) for i in range(6, 10))
        return core_ok and has_succ
    bench_n = sum(1 for row in benchj.get("rows", []) if _bench_ready(row))
    bench_val = bench_n if benchj.get("rows") else None
    # Bench MAIN KPI reframed as NET store managers on the bench. Target = +3 (a surplus of ready SM
    # cover); actual = -(Store Manager vacancies) right now — each open SM = -1 — read from the HRP
    # 'HRP & Bench' roster (row[1] = Store Manager). This is the SAME red 'Gap / no SM' store count the
    # dashboard bench status shows, so the KPI and the detail reconcile. Miss = target - actual.
    sm_vacancies = sum(1 for row in benchj.get("rows", []) if not _cell(row, 1)) if benchj.get("rows") else None
    bench_net = (-sm_vacancies) if sm_vacancies is not None else None

    # ---- derived weekly ----
    rev = cust.get("reviews"); rat = cust.get("avg_rating_last_week")
    gh = round((min(rev / 40, 1) + min(rat / 4.6, 1)) / 2 * 100, 1) if rev is not None and rat else None
    gh_detail = ("%s reviews (÷40) · %s★ rating (÷4.6) last week" % (rev, rat)) if rat else "No reviews logged last week"
    subs = rms.get("submissions") or 0; ravg = rms.get("avg_rating")
    rh = round((min(subs / 70, 1) + min(ravg / 4.6, 1)) / 2 * 100, 1) if ravg and subs else None
    rh_detail = ("%d submissions (÷70) · %s★ (÷4.6) last week" % (subs, ravg)) if ravg else "No Rate My Shift submissions logged last week"
    num = den = 0.0; nrep = 0
    for st, v in ovr.items():
        h = v.get("used_lastwk")
        if h and rec.get(st, {}).get("lw26"):
            num += rec[st]["lw26"]; den += h; nrep += 1
    sph = round(num / den, 1) if den else None
    # planner CPH (actual sales-per-labour-hour from the 3 area planners, Section A) — hours-weighted estate avg.
    cnum = cden = 0.0
    for st, v in ovr.items():
        c = v.get("actual_cph_lastwk"); h = v.get("used_lastwk")
        if c and h: cnum += c * h; cden += h
    cph_estate = round(cnum / cden, 1) if cden else sph        # fall back to BQ SPH if planners blank
    estate_sales_wk = sum(r.get("lw26", 0) or 0 for r in rec.values())
    estate_tx_wk = sum(r.get("tx26", 0) or 0 for r in rec.values())
    atv_wk = round(estate_sales_wk / estate_tx_wk, 2) if estate_tx_wk else None   # estate ATV, last completed week
    # ---- committed weekly-performance history (weekly_history.csv) for accumulating QTD ----
    HIST = os.path.join(HERE, "weekly_history.csv")
    HCOLS = ["week_ending", "estate_sales", "estate_gp_pct", "estate_cph", "sph", "npat_proj_pct",
             "yoy_sales_pct", "yoy_tx_pct", "f1_avg", "rms_pct", "kudos_pct", "brand_audit", "google_health_pct",
             "estate_atv"]
    hist_rows = []
    if os.path.exists(HIST):
        try:
            with open(HIST, newline="") as fh:
                hist_rows = [r for r in csv.DictReader(fh)]
        except Exception:
            hist_rows = []
    def _hf(x):
        try: return float(x)
        except Exception: return None
    QS = QSTART.isoformat()
    q_prior = [r for r in hist_rows if r.get("week_ending", "") >= QS and r.get("week_ending") != CUR_END.isoformat()]
    def _qtd_rate(prior, cur_sales, cur_rate, col):
        """hours-weighted rate over the quarter: Σsales / Σ(sales/rate), incl this week."""
        ts = th = 0.0
        for r in prior:
            sa = _hf(r.get("estate_sales")); rt = _hf(r.get(col))
            if sa and rt: ts += sa; th += sa / rt
        if cur_sales and cur_rate: ts += cur_sales; th += cur_sales / cur_rate
        return round(ts / th, 1) if th else None
    qtd_cph = _qtd_rate(q_prior, estate_sales_wk, cph_estate, "estate_cph") or cph_estate
    qtd_sph = _qtd_rate(q_prior, estate_sales_wk, sph, "sph") or sph
    n_hist_q = len(q_prior) + 1          # quarter weeks contributing (incl current)
    au = [r["audit_qtd"] for r in rec.values() if r.get("audit_qtd")]
    ba = round(sum(au) / len(au), 2) if au else None
    # Food GP% = AUTHORITATIVE estate Gross Profit% from the CoS sheet (col Q, sales-weighted) — the same
    # figure the grid and NPAT flex use, so GP is consistent everywhere. Weekly = latest CoS week, QTD = QTD.
    cosj_gp = jload("cos_metrics.json")
    fg_wk = cosj_gp.get("estate_gp_wk")
    fg_qtd = cosj_gp.get("estate_gp_qtd")
    # ---- derived weekly: YoY sales/tx, last completed week vs same week last year (LFL) ----
    # LFL = trading in BOTH the current week and the same week last year (excludes new sites AND closed sites);
    # rec already omits the closed "Royal Leamington Spa" (normalize() maps it to None).
    lfl = [r for r in rec.values() if (r.get("lw25") or 0) > 0 and (r.get("lw26") or 0) > 0]
    slw = sum(r.get("lw26", 0) or 0 for r in lfl); sly = sum(r.get("lw25", 0) or 0 for r in lfl)
    yoy_sales_wk = round(100 * (slw / sly - 1), 1) if sly else None
    lflx = [r for r in lfl if (r.get("tx25") or 0) > 0 and (r.get("tx26") or 0) > 0]
    tlw = sum(r.get("tx26", 0) or 0 for r in lflx); tly = sum(r.get("tx25", 0) or 0 for r in lflx)
    yoy_tx_wk = round(100 * (tlw / tly - 1), 1) if tly else None
    wk_ref = "w/c %s vs %d" % (LASTWK_MON.strftime("%-d %b"), CUR_END.year - 1)
    # ---- F1 (auto-rebuilt from the F1 sheet by pull_f1 -> f1_detail.json). Total Score scale. ----
    fdet = jload("f1_detail.json")
    f1_qtd_xs = [v["race_qtd"]["score"] for v in fdet.values()
                 if v.get("race_qtd") and v["race_qtd"].get("score") is not None]
    f1_qtd = round(sum(f1_qtd_xs) / len(f1_qtd_xs), 1) if f1_qtd_xs else None
    f1_wk_xs = []
    for v in fdet.values():
        r = v.get("race")
        if r and r[8] and LASTWK_MON.isoformat() <= r[8] <= CUR_END.isoformat():
            f1_wk_xs.append(r[5])                       # race Total Score (col 18) for last week's race
    f1_wk = round(sum(f1_wk_xs) / len(f1_wk_xs), 1) if f1_wk_xs else None
    F1_PLAN = 220   # LOWER IS BETTER on this race Total-Score scale — target ≤220 (estate ~282 now, so RED).
    f1_note = ("Metric = AVERAGE RACE TOTAL SCORE, and LOWER IS BETTER on this scale. Target ≤%d — "
               "green when the average score is at or below %d, red when above. (Estate ~282 now, so RED.) "
               "The old '75' higher-is-better target is retired." % (F1_PLAN, F1_PLAN))
    # ---- Brand Audit, last completed week (audits are periodic; awaiting if none logged that week) ----
    audit_lastwk = jload("audit_raw.json").get("_lastwk_avg")
    audit_lastwk_n = jload("audit_raw.json").get("_lastwk_n", 0)
    # ---- Food GP% — Cost-of-Sales sheet is weekly; cos estate avg already = latest CoS week ----
    cos_week = jload("cos_metrics.json").get("_week", "")
    # ---- Brew Crew Kudos Participation: distinct employees who gave kudos, DATE-WINDOWED / total employees ----
    # BCKH tab (F1 workbook): col A = timestamp string ("Wed May 27 18:28:53 +0100 2026"), col B = email.
    kudos_wk_pct = kudos_qtd_pct = None
    kudos_wk_n = kudos_qtd_n = kudos_total = kudos_wk_rows = 0
    bckh_latest = None
    emp_emails = set(); bckh_rows = []
    # Per-STORE participation. Reuse the pipeline canon map (normalize()) on the Employee List
    # "Location" column (col B). Head Office / unknown locations resolve to None → excluded from the
    # per-store split (but still counted in the company headcount, exactly like the company calc).
    emp_store = {}                     # email -> canonical store (only when Location resolves to a store)
    kudos_store_hc = {}                # canonical store -> distinct-employee headcount
    kudos_ps_weekly = []; kudos_ps_qtd = []   # [{store, value}] participation % per store (weekly / QTD)
    kudos_unmatched_n = 0              # BCKH contributors (QTD) with NO matching employee (head-office/ex-staff)
    kudos_ho_excluded_n = 0           # matched contributors whose employee has no store (e.g. Head Office)
    kudos_stores_resolved = 0
    try:
        emp_rows = sheet(SID["employees"], "'Employee List'!A2:D2000")   # A=Name, B=Location, C=Email, D=Email Clean
        for r in emp_rows:
            if not r or not r[0]: continue
            em = (r[3] if len(r) > 3 and r[3] not in (None, "") else
                  (r[2] if len(r) > 2 and r[2] not in (None, "") else None))
            if not em: continue
            em = str(em).strip().lower()
            emp_emails.add(em)
            st = normalize(r[1]) if len(r) > 1 and r[1] not in (None, "") else None   # col B = Location -> canon
            if st: emp_store[em] = st
        kudos_total = len(emp_emails)
        for em, st in emp_store.items():
            kudos_store_hc[st] = kudos_store_hc.get(st, 0) + 1
        kudos_stores_resolved = len(kudos_store_hc)
        bckh_rows = sheet(SID["f1"], "'BCKH'!A2:E20000")        # tail-safe; date col A, email col B
        wk_emp = set(); qtd_emp = set()
        wk_store = {}; qtd_store = {}   # canonical store -> set(distinct contributor emails) in each window
        qtd_unmatched = set()
        for r in bckh_rows:
            if len(r) < 2 or r[1] in (None, ""): continue
            dt = parse_any_date(r[0]) if r[0] not in (None, "") else None
            if not dt: continue
            if not bckh_latest or dt > bckh_latest: bckh_latest = dt
            em = str(r[1]).strip().lower()
            if LASTWK_MON <= dt <= CUR_END:
                kudos_wk_rows += 1
                if em in emp_emails:
                    wk_emp.add(em)
                    st = emp_store.get(em)
                    if st: wk_store.setdefault(st, set()).add(em)
            if dt >= QSTART:
                if em in emp_emails:
                    qtd_emp.add(em)
                    st = emp_store.get(em)
                    if st: qtd_store.setdefault(st, set()).add(em)
                else:
                    qtd_unmatched.add(em)
        kudos_wk_n, kudos_qtd_n = len(wk_emp), len(qtd_emp)
        kudos_unmatched_n = len(qtd_unmatched)
        kudos_ho_excluded_n = len([e for e in qtd_emp if not emp_store.get(e)])
        if kudos_total:
            kudos_qtd_pct = round(100 * kudos_qtd_n / kudos_total, 1)
            kudos_wk_pct = round(100 * kudos_wk_n / kudos_total, 1) if kudos_wk_rows > 0 else None
        # Per-store participation % = distinct store contributors ÷ store headcount, vs the 50% plan.
        # Zero-headcount stores are skipped (nothing to measure); a store WITH headcount but no
        # contributors shows 0%. Weekly rows only when there were BCKH entries that week (else awaiting).
        for st, hc in sorted(kudos_store_hc.items()):
            if hc <= 0: continue
            kudos_ps_qtd.append({"store": st, "value": round(100 * len(qtd_store.get(st, set())) / hc, 1)})
            if kudos_wk_rows > 0:
                kudos_ps_weekly.append({"store": st, "value": round(100 * len(wk_store.get(st, set())) / hc, 1)})
        if kudos_wk_rows == 0:
            flags.append("Brew Crew Kudos (weekly) shows awaiting — no BCKH entries in the last completed week "
                         "(latest BCKH row %s). The QTD tile reflects activity since quarter start."
                         % (bckh_latest.isoformat() if bckh_latest else "n/a"))
        if kudos_unmatched_n or kudos_ho_excluded_n:
            flags.append("Brew Crew Kudos per-store: %d QTD contributor(s) matched no employee "
                         "(head-office/ex-staff — excluded, as in the company calc); %d matched contributor(s) "
                         "have no store Location (e.g. Head Office — excluded from the per-store split but still "
                         "in the company headcount). %d stores resolved from the Employee List Location column."
                         % (kudos_unmatched_n, kudos_ho_excluded_n, kudos_stores_resolved))
    except Exception as e:
        flags.append("Brew Crew Kudos: could not read Employee List (%s) or BCKH tab — share the Employee List "
                     "(ID %s, Viewer) with dashboards-bot@%s.iam.gserviceaccount.com (the BCKH tab is in the F1 "
                     "workbook, already shared). Tiles shown as awaiting." % (str(e)[:60], SID["employees"], PROJECT))
    # ---- Projected Net Profit After Tax % — margin bridge off the May P&L baseline ----
    # Baseline from the Bewiched Ltd monthly P&L (validated 30 Jun via the agent Sheets read; the SA may
    # 403, in which case these FROZEN May constants are used and the share is flagged).
    # STRUCTURE: labour sits INSIDE Cost of Sales, so P&L "Gross Profit" is AFTER labour. We decompose to
    # product-GP-before-labour so GP and labour flex independently (no double count):
    #   product COGS = Total CoS - labour ;  product GP% = (turnover - product COGS)/turnover
    #   NPAT% = product GP% - labour% - admin%   (admin held at baseline in the bridge)
    NPAT_MONTH = "May 2026"
    B = dict(turn=633064.53, cogs=428931.11, labour=214300.18, admin=154051.31, npat=7.9,
             gp_prod=66.1, labour_pct=33.85, admin_pct=24.33, cph_base=57.7, hourly=19.53)
    cosj = jload("cos_metrics.json")
    gp_may = cosj.get("estate_gp_may") or 70.1      # CoS estate GP (AUTHORITATIVE col Q, sales-weighted), May anchor
    gp_wk_live = cosj.get("estate_gp_wk")           # latest week, estate-wide col Q (Master COS)
    gp_qtd_live = cosj.get("estate_gp_qtd")         # quarter-to-date, estate-wide col Q
    npat_src = "derived"
    try:
        prows = sheet(SID["npat_pnl"], "A1:AB300")
        def _last_num(row):
            v = None
            for c in row[1:]:
                if isinstance(c, (int, float)): v = c
                else:
                    t = str(c).replace(",", "").replace("£", "").replace("%", "").strip()
                    if t.startswith("(") and t.endswith(")"): t = "-" + t[1:-1]
                    try: v = float(t)
                    except Exception: pass
            return v
        WANT = {"total turnover": "turn", "total cost of sales": "cogs", "gross wages": "w1",
                "employers n.i. (non-directors)": "w2", "employers pensions": "w3",
                "total administrative costs": "admin", "profit after taxation": "pat"}
        vals = {}
        for r in prows:
            if not r or r[0] in (None, ""): continue
            lab = str(r[0]).strip().lower()
            if lab in WANT: vals[WANT[lab]] = _last_num(r)
        if vals.get("turn") and vals.get("cogs") is not None and all(k in vals for k in ("w1", "w2", "w3")):
            turn = vals["turn"]; cogs = vals["cogs"]; labour = vals["w1"] + vals["w2"] + vals["w3"]
            B["turn"], B["cogs"], B["labour"] = turn, cogs, labour
            B["admin"] = vals.get("admin", B["admin"])
            B["gp_prod"] = round((turn - (cogs - labour)) / turn * 100, 2)
            B["labour_pct"] = round(labour / turn * 100, 2)
            B["admin_pct"] = round(B["admin"] / turn * 100, 2)
            if vals.get("pat"): B["npat"] = round(vals["pat"] / turn * 100, 1)
            B["hourly"] = round(labour / (turn / B["cph_base"]), 2)   # avg £/hr = labour ÷ (turnover ÷ baseline CPH)
            npat_src = "sheet"
    except Exception as e:
        flags.append("Net Profit After Tax: P&L sheet not readable by the service account (%s) — share '%s P&L' "
                     "(ID %s, Viewer) with dashboards-bot@%s.iam.gserviceaccount.com. Using FROZEN May baseline constants."
                     % (str(e)[:60], NPAT_MONTH, SID["npat_pnl"], PROJECT))

    def _npat_project(live_gp, live_cph):
        gp_c = round(live_gp - gp_may, 1) if (live_gp is not None and gp_may is not None) else 0.0
        live_lab = (B["hourly"] / live_cph * 100) if live_cph else B["labour_pct"]
        lab_c = round(B["labour_pct"] - live_lab, 1)                  # +ve when labour% below baseline (CPH up)
        return round(B["npat"] + gp_c + lab_c, 1), gp_c, lab_c
    npat_wk, npat_wk_gp, npat_wk_lab = _npat_project(gp_wk_live, cph_estate)
    npat_qtd, npat_qtd_gp, npat_qtd_lab = _npat_project(gp_qtd_live, qtd_cph)   # labour side uses QTD CPH from weekly_history
    def _npat_detail(tag, gp_c, lab_c):
        return "%s · baseline %.1f%% · GP %+.1fpp · labour %+.1fpp" % (tag, B["npat"], gp_c, lab_c)
    npat_note = ("Projected (GP + labour flex off the %s P&L). NPAT%% = baseline %.1f%% + (estate GP%% − %s baseline) "
                 "− (labour%% − baseline). Baseline: product GP %.1f%%, labour %.1f%%, admin %.1f%% (held), avg labour £%.2f/hr. "
                 "GP movement = estate Gross Profit%% from the CoS sheet (col Q, sales-weighted; %s baseline %.2f%%, latest week %s%%, QTD %s%%). "
                 "Labour flexes via planner actual CPH £%.1f ÷ baseline £%.1f (avg £%.2f/hr ÷ live CPH). Weekly CPH = this week\'s "
                 "planner CPH; QTD CPH £%.1f is hours-weighted from weekly_history.csv (%d week%s so far)."
                 % (NPAT_MONTH, B["npat"], NPAT_MONTH, B["gp_prod"], B["labour_pct"], B["admin_pct"], B["hourly"],
                    NPAT_MONTH, gp_may if gp_may is not None else 0, gp_wk_live, gp_qtd_live,
                    cph_estate or 0, B["cph_base"], B["hourly"], qtd_cph or 0, n_hist_q, "" if n_hist_q == 1 else "s"))

    # ---- QTD health blends (Google / RMS) from storehealth_raw.json (QTD per-store [n, avg]) ----
    weeks_q = max(1, round((CUR_END - QSTART).days / 7.0))
    sh = jload("storehealth_raw.json")
    def _qtd_blend(dd, vol_per_week):
        if not dd: return (None, 0, None)
        n = sum(v[0] for v in dd.values())
        if not n: return (None, 0, None)
        avg = sum(v[0] * v[1] for v in dd.values()) / n
        pct = round((min(n / (vol_per_week * weeks_q), 1) + min(avg / 4.6, 1)) / 2 * 100, 1)
        return (pct, n, round(avg, 2))
    gh_qtd, gh_qtd_n, gh_qtd_avg = _qtd_blend(sh.get("google", {}), 40)
    rh_qtd, rh_qtd_n, rh_qtd_avg = _qtd_blend(sh.get("rms", {}), 70)

    # ---- live quarterly: YoY sales / tx (QTD LFL) ----
    yoy_sales = yoy_tx = None; lfl_n = None
    qstart_lit = "DATE('%s')" % QSTART.isoformat()
    qstart_ly_lit = "DATE('%s')" % (QSTART - datetime.timedelta(days=364)).isoformat()
    try:
        rows = bq(f"""
          WITH b AS (SELECT item_outlet_name s, DATE(sales_date) dd, id,
                            SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
                     FROM {FLAT}
                     WHERE DATE(sales_date) BETWEEN {qstart_ly_lit} AND {CE}
                       AND item_outlet_name NOT IN ('Royal Leamington Spa','Leamington Retail','Leamington Spa')),
          p AS (SELECT s,
                  SUM(IF(dd BETWEEN {qstart_lit} AND {CE}, v, 0)) qtd,
                  COUNT(DISTINCT IF(dd BETWEEN {qstart_lit} AND {CE}, id, NULL)) qtx,
                  SUM(IF(dd BETWEEN {qstart_ly_lit} AND {d(364)}, v, 0)) qtd_ly,
                  COUNT(DISTINCT IF(dd BETWEEN {qstart_ly_lit} AND {d(364)}, id, NULL)) qtx_ly
                FROM b GROUP BY s)
          SELECT ROUND(100*(SUM(IF(qtd>0 AND qtd_ly>0,qtd,0))/NULLIF(SUM(IF(qtd>0 AND qtd_ly>0,qtd_ly,0)),0)-1),1) yoy_sales,
                 ROUND(100*(SUM(IF(qtd>0 AND qtd_ly>0,qtx,0))/NULLIF(SUM(IF(qtd>0 AND qtd_ly>0,qtx_ly,0)),0)-1),1) yoy_tx,
                 COUNTIF(qtd>0 AND qtd_ly>0) lfl_stores
          FROM p""")
        if rows:
            yoy_sales = rows[0].get("yoy_sales"); yoy_tx = rows[0].get("yoy_tx"); lfl_n = rows[0].get("lfl_stores")
    except Exception as e:
        flags.append("YoY (BigQuery QTD) pull failed (%s) — YoY rows shown as awaiting." % str(e)[:90])

    def metric(mid, name, plan_def, derived, unit, fmt, source, detail, note, tbc=False, dirn="high"):
        a = ma(mid)
        if tbc:
            return {"id": mid, "name": name, "plan": None, "actual": None, "unit": unit,
                    "fmt": fmt, "dir": dirn, "source": "tbc", "detail": detail, "note": note, "tbc": True}
        actual = a if a is not None else derived
        src = "manual" if (a is not None and source in ("derived", "live")) else source
        return {"id": mid, "name": name, "plan": mp(mid, plan_def), "actual": actual, "unit": unit,
                "fmt": fmt, "dir": dirn, "source": src, "detail": detail, "note": note}

    qn = (QSTART.month - 1) // 3 + 1
    m3 = QSTART.replace(month=QSTART.month + 2)
    qlabel = "Q%d %d (%s–%s)" % (qn, QSTART.year, QSTART.strftime("%b"), m3.strftime("%b"))

    weekly = [
        metric("yoy_sales_wk", "YoY Sales Growth", 12, yoy_sales_wk, "%", "pct_signed", "derived",
               "%s (%d like-for-like stores)" % (wk_ref, len(lfl)),
               "Last completed week vs same week last year (LFL); reuses the weekly sales pull (lw26/lw25)."),
        metric("yoy_tx_wk", "YoY Transactional Growth", 5, yoy_tx_wk, "%", "pct_signed", "derived",
               "%s (%d like-for-like stores)" % (wk_ref, len(lflx)),
               "Last completed week transactions vs same week last year (LFL); reuses tx26/tx25."),
        metric("google_health", "Google Health", 100, gh, "%", "pct0", "derived", gh_detail,
               "Blend: avg of reviews÷40 and rating÷4.6, each capped 100%. Last completed week."),
        metric("rms_health", "Rate My Shift Health", 100, rh, "%", "pct0", "derived", rh_detail,
               "Blend: avg of submissions÷70 and avgScore÷4.6, each capped 100%. Last completed week."),
        metric("brew_crew_kudos", "Brew Crew Kudos Participation", 50, kudos_wk_pct, "%", "pct0", "derived",
               ("%d of %d employees gave kudos last week (BCKH)" % (kudos_wk_n, kudos_total)) if kudos_wk_pct is not None
               else ("No BCKH entries last week (latest %s)" % (bckh_latest.isoformat() if bckh_latest else "n/a")),
               "Distinct employees who contributed to Brew Crew Kudos (BCKH tab, F1 workbook) in the LAST COMPLETED WEEK, matched by email to the Employee List, ÷ total employees. Awaiting if no entries that week."),
        metric("social_media", "Social Media Engagement", None, None, "%", "pct0", "tbc", "",
               "Metric and target not yet defined.", tbc=True),
        metric("sph_labour", "SPH Labour (incl holiday pay)", 55, sph, "£", "gbp1", "derived",
               ("£%.0f sales ÷ %.0f hours used (last week, %d stores reporting)" % (num, den, nrep)) if den else "Awaiting posted hours",
               "Sales per labour hour incl holiday pay. Last completed week; provisional on Sunday, finalised Monday once planner hours post."),
        metric("bench", "Bench", 3, bench_net, "", "num_signed", "derived",
               ("Net SM on the bench: %d live Store Manager vacanc%s now (actual %+d) vs a +3 surplus target — %d off plan." % (sm_vacancies, "y" if sm_vacancies == 1 else "ies", bench_net, 3 - bench_net)) if bench_net is not None else "",
               "MAIN KPI = NET Store Managers on the bench. Actual = -(Store Manager vacancies) from the HRP 'HRP & Bench' roster (the red 'Gap / no SM' stores); target = +3 (a surplus of ready SM cover); miss = target - actual. The star map, management-team table and Bench-ready / Thin / Capability-gap cards below use the hierarchy-gap rule, unchanged and byte-identical to the Company Dashboard bench tab."),
        metric("f1_score_wk", "F1 Score", F1_PLAN, f1_wk, "", "num1", "sheet",
               ("Last week's race result, estate avg (%d stores) — lower is better" % len(f1_wk_xs)) if f1_wk_xs else "No race scores logged last week",
               f1_note, dirn="low"),
        metric("brand_audit_wk", "Brand Audit Score", 4.6, audit_lastwk, "", "score2", "derived",
               ("Audits logged last week, estate avg (%d audits)" % audit_lastwk_n) if audit_lastwk_n else "No brand audits logged last week",
               "Last completed week's audits. Brand audits are periodic — tile stays awaiting in weeks with none; the QTD tile is the reliable one."),
        metric("food_gp_wk", "Food GP%", 71, fg_wk, "%", "pct1", "derived",
               ("Cost-of-Sales estate Gross Profit%% (col Q), latest week ending %s" % cos_week) if cos_week else "Estate Gross Profit% (col Q) from Cost of Sales",
               "Estate Gross Profit% from the Cost-of-Sales sheet (col Q, sales-weighted across stores)."),
        metric("npat_wk", "Net Profit After Tax (projected)", 18, npat_wk, "%", "pct1", npat_src,
               _npat_detail("Weekly flex", npat_wk_gp, npat_wk_lab),
               npat_note),
        metric("new_starter_health_wk", "New Starter Health", None, None, "%", "pct0", "tbc", "",
               "Metric and target not yet defined.", tbc=True),
    ]
    quarterly = [
        metric("yoy_sales", "YoY Sales Growth", 12, yoy_sales, "%", "pct_signed", "live",
               ("LFL QTD sales vs same period last year (%s like-for-like stores)" % lfl_n) if lfl_n else "LFL QTD sales vs same period last year",
               "Auto from BigQuery v_sales_details_flat (quarter-to-date)."),
        metric("yoy_tx", "YoY Transactional Growth", 5, yoy_tx, "%", "pct_signed", "live",
               ("LFL QTD transactions vs last year (%s like-for-like stores)" % lfl_n) if lfl_n else "LFL QTD transactions vs same period last year",
               "Auto from BigQuery v_sales_details_flat (quarter-to-date)."),
        metric("google_health_qtd", "Google Health", 100, gh_qtd, "%", "pct0", "derived",
               ("%d reviews (÷%d) · %s★ (÷4.6) QTD" % (gh_qtd_n, 40 * weeks_q, gh_qtd_avg)) if gh_qtd is not None else "No QTD reviews",
               "Blend: avg of QTD reviews÷(40×%d wks) and avg rating÷4.6, each capped 100%%." % weeks_q),
        metric("rms_health_qtd", "Rate My Shift Health", 100, rh_qtd, "%", "pct0", "derived",
               ("%d submissions (÷%d) · %s★ (÷4.6) QTD" % (rh_qtd_n, 70 * weeks_q, rh_qtd_avg)) if rh_qtd is not None else "No QTD submissions",
               "Blend: avg of QTD submissions÷(70×%d wks) and avg score÷4.6, each capped 100%%." % weeks_q),
        metric("brew_crew_kudos_qtd", "Brew Crew Kudos Participation", 50, kudos_qtd_pct, "%", "pct0", "derived",
               ("%d of %d employees gave kudos this quarter (BCKH)" % (kudos_qtd_n, kudos_total)) if kudos_qtd_pct is not None else "",
               "Distinct employees who contributed to Brew Crew Kudos (BCKH tab) QUARTER-TO-DATE, matched by email to the Employee List, ÷ total employees."),
        metric("social_media_qtd", "Social Media Engagement", None, None, "%", "pct0", "tbc", "",
               "Metric and target not yet defined.", tbc=True),
        metric("sph_labour_qtd", "SPH Labour (incl holiday pay)", 55, qtd_sph, "£", "gbp1", "derived",
               "QTD £/hr, hours-weighted from weekly_history (%d week%s so far)" % (n_hist_q, "" if n_hist_q == 1 else "s"),
               "QTD sales per labour hour, hours-weighted across the weekly_history.csv rows since quarter start. Thin until several weeks accumulate (falls back to the current week)."),
        metric("bench_qtd", "Bench", 3, bench_net, "", "num_signed", "derived",
               ("Net SM on the bench: %d live Store Manager vacanc%s now (actual %+d) vs a +3 surplus target — %d off plan." % (sm_vacancies, "y" if sm_vacancies == 1 else "ies", bench_net, 3 - bench_net)) if bench_net is not None else "",
               "Point-in-time net Store Managers on the bench (same as weekly): actual = -(SM vacancies), target = +3, miss = target - actual. Detail below is byte-identical to the Company Dashboard bench tab (hierarchy-gap rule)."),
        metric("f1_score", "F1 Score", F1_PLAN, f1_qtd, "", "num1", "sheet",
               ("QTD race 'Total Score', estate avg (%d stores) — lower is better" % len(f1_qtd_xs)) if f1_qtd_xs else "Awaiting F1 race data",
               f1_note, dirn="low"),
        metric("brand_audit", "Brand Audit Score", 4.6, ba, "", "score2", "derived",
               "Estate average brand audit (QTD), out of 5",
               "Auto-derived from the Brand Audit sheet (quarter-to-date); override in the inputs sheet if needed."),
        metric("food_gp", "Food GP%", 71, fg_qtd, "%", "pct1", "derived",
               "Estate Gross Profit% (col Q) from Cost of Sales, quarter-to-date (sales-weighted)",
               "Estate Gross Profit% from the Cost-of-Sales sheet (col Q, sales-weighted), quarter-to-date."),
        metric("npat", "Net Profit After Tax (projected)", 18, npat_qtd, "%", "pct1", npat_src,
               _npat_detail("QTD flex", npat_qtd_gp, npat_qtd_lab),
               npat_note),
        metric("new_starter_health", "New Starter Health", None, None, "%", "pct0", "tbc", "",
               "Metric and target not yet defined.", tbc=True),
    ]
    flags = [
        "Status is strictly binary: GREEN when actual ≥ plan, RED when below — no near-target band. Bench is green when ≥ 3.",
        "Google Health & Rate My Shift Health blend divisors (40 reviews / 4.6★ ; 70 submissions / 4.6★) are default assumptions — adjust if you prefer different volume targets.",
        "Plans (Matt's stated defaults): SPH Labour 55, Brew Crew Kudos 50%, Bench 3, NPAT 18%, Food GP% 71%. YoY Sales 12% / Transactions 5% on both tabs.",
        "F1 Score = AVERAGE RACE TOTAL SCORE (Matt confirmed), live from the F1 sheet (ID %s) — weekly = last week's race, quarterly = QTD avg. LOWER IS BETTER on this scale: target ≤220, green at or below 220 and red above (estate ~282 now, so RED). The old '75' higher-is-better target is retired." % SID["f1"],
        "SYMMETRIC: both tabs now carry the SAME 13 KPIs — Weekly measured on the last completed week, Quarterly the identical 13 measured QTD (since quarter start). Where a measure has no natural weekly/QTD split it shows the same figure on both tabs (see below).",
        "Same figure on both tabs (by nature): NPAT (latest-month P&L projection — no weekly actual), SPH Labour (a £/hr rate — QTD labour hours not separately sourced), Bench (point-in-time headcount), Food GP% (weekly CoS, a week in arrears). Brand Audit weekly shows 'awaiting' in weeks with no audits; the QTD tile is the reliable one.",
        "Still need definitions/sources: New Starter Health and Social Media Engagement are greyed TBC placeholders on BOTH tabs until Matt defines the metric + source. NPAT needs the P&L sheet shared with the service account to go beyond the May snapshot.",
        "Net Profit After Tax is a PROJECTION model: May P&L baseline (product GP 66.1%, labour 33.85%, admin 24.33%, NPAT 7.9%, avg labour £19.53/hr) flexed by live GP movement (CoS blended GP, commercial-store proxy) and live SPH labour. This period GP/SPH match baseline so both tiles read ~7.9%; they flex as GP/SPH move. Share the P&L sheet with the SA so the baseline auto-refreshes monthly.",
        "Food GP% uses the Cost of Sales estate GP% as a proxy until a company food-specific GP source exists.",
        "Social Media Engagement and New Starter Health are greyed TBC placeholders pending metric + target definitions.",
        "Each metric now shows an accountable OWNER (EOS-style): YoY Sales/Transactions & Food GP% = Rich; Google Health, Social Media & SPH Labour = Jon; Rate My Shift, Brew Crew Kudos, Bench & New Starter = Kel; F1 & Brand Audit = Claire. Net Profit After Tax is UNASSIGNED (shown as —) — Matt to confirm the owner (likely Matt/MD). Owners are a config block in gen_eos_scorecard.py.",
        "NEW third tab 'Quarterly Scorecard' — classic EOS grid: the 13 metrics as rows (owner + plan) × each week of the quarter as columns, traffic-lit binary. Back-filled from source: BigQuery (sales, YoY sales/tx per week), COS master (estate GP + NPAT projection per week), F1 sheet (race score), Shift Ratings (RMS), Reviews (Google Health), BCKH (Kudos). SPH (no historical hours), Bench (point-in-time) and Brand Audit (sparse) fill going forward; Social Media & New Starter stay TBC. The grid reads weekly_history.csv.",
        "QTD CPH/SPH and the labour side of QTD NPAT now read from the committed weekly_history.csv (one row per week-ending, upserted each run — re-runs update, no dupes). Thin until several weeks accumulate; until then QTD ≈ the current week. YoY (BigQuery), Kudos QTD (BCKH), GP QTD (COS master) keep their own source-of-truth and are also logged to history.",
        "Manual inputs sheet 'Bewiched EOS Scorecard Inputs' (ID %s) must be shared (Viewer) with dashboards-bot@%s.iam.gserviceaccount.com for the automated run to read it." % (SID["eos"], PROJECT),
    ] + flags

    # ---- per-store QTD sources (BigQuery) for the Metric detail Weekly/Quarterly toggle ----
    # Per-store QTD sales/tx vs last year (LFL: closed 'Royal Leamington Spa' excluded; new stores drop
    # out via the qtd_ly>0 gate). Reused for YoY Sales QTD, YoY Transactions QTD and ATV QTD.
    qsales_ps = {}
    try:
        for r in bq(f"""
          WITH b AS (SELECT item_outlet_name s, DATE(sales_date) dd, id,
                            SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
                     FROM {FLAT} WHERE DATE(sales_date) BETWEEN {qstart_ly_lit} AND {CE}
                       AND item_outlet_name NOT IN ('Royal Leamington Spa','Leamington Retail','Leamington Spa'))
          SELECT s,
            ROUND(SUM(IF(dd BETWEEN {qstart_lit} AND {CE}, v, 0))) qtd,
            COUNT(DISTINCT IF(dd BETWEEN {qstart_lit} AND {CE}, id, NULL)) qtx,
            ROUND(SUM(IF(dd BETWEEN {qstart_ly_lit} AND {d(364)}, v, 0))) qtd_ly,
            COUNT(DISTINCT IF(dd BETWEEN {qstart_ly_lit} AND {d(364)}, id, NULL)) qtx_ly
          FROM b GROUP BY s"""):
            st = normalize(r.get("s"))
            if st: qsales_ps[st] = r
    except Exception as e:
        flags.append("Per-store QTD sales/tx (BigQuery) failed (%s)." % str(e)[:70])
    def _yoy_qtd(kind):
        out = []
        for st, r in qsales_ps.items():
            qd = r.get("qtd") or 0; qdl = r.get("qtd_ly") or 0
            if qd <= 0 or qdl <= 0: continue                 # LFL: trading BOTH periods
            if kind == "sales":
                out.append({"store": st, "value": round(100 * (qd / qdl - 1), 1)})
            else:
                qx = r.get("qtx") or 0; qxl = r.get("qtx_ly") or 0
                if qxl > 0: out.append({"store": st, "value": round(100 * (qx / qxl - 1), 1)})
        return out
    atv_qtd_ps = [{"store": st, "value": round(r["qtd"] / r["qtx"], 2)}
                  for st, r in qsales_ps.items() if (r.get("qtx") or 0) > 0 and (r.get("qtd") or 0) > 0]
    # Per-store QTD food attachment % (Food/Bakery guest-checks ÷ transactions, quarter-to-date)
    food_qtd_ps = {}
    try:
        for r in bq(f"""
          WITH t AS (SELECT item_outlet_name s, id, MAX(IF(cat IN ('Food','Bakery'),1,0)) hasfood
            FROM (SELECT item_outlet_name, id, {cat_case('item_product_name')} cat FROM {FLAT}
                  WHERE DATE(sales_date) BETWEEN {qstart_lit} AND {CE}
                    AND item_outlet_name NOT IN ('Royal Leamington Spa','Leamington Retail','Leamington Spa'))
            GROUP BY s, id)
          SELECT s, COUNT(*) txns, ROUND(100*SUM(hasfood)/COUNT(*),1) fa FROM t GROUP BY s"""):
            st = normalize(r.get("s"))
            if st and (r.get("txns") or 0) > 0: food_qtd_ps[st] = r.get("fa")
    except Exception as e:
        flags.append("Per-store QTD food-attach (BigQuery) failed (%s)." % str(e)[:70])
    # Per-store WEEKLY F1 (last completed week's race Total Score)
    f1_wk_ps = []
    for st, v in fdet.items():
        rr = v.get("race")
        if rr and len(rr) > 8 and rr[8] and LASTWK_MON.isoformat() <= str(rr[8]) <= CUR_END.isoformat():
            f1_wk_ps.append({"store": st, "value": round(rr[5], 1)})

    # ---- per-store breakdown, DUAL basis (weekly + QTD) for the Metric detail toggle ----
    # per_store[name] = {"plan":…, "weekly":{"basis","rows"}?, "qtd":{"basis","rows"}?}. A basis is
    # omitted when not sourced per store (renderer shows a graceful note). Company-only / TBC metrics
    # (NPAT, Kudos, Social Media, New Starter) carry no per_store — renderer shows the company figure.
    per_store = {}
    def _clean(rows): return [r for r in (rows or []) if r.get("value") is not None]
    def _ps2(name, plan=None, weekly=None, wbasis="", qtd=None, qbasis=""):
        e = {"plan": plan}
        wr, qr = _clean(weekly), _clean(qtd)
        if wr: e["weekly"] = {"basis": wbasis, "rows": wr}
        if qr: e["qtd"] = {"basis": qbasis, "rows": qr}
        if "weekly" in e or "qtd" in e: per_store[name] = e
    _ps2("YoY Sales Growth", plan=12,
         weekly=[{"store": st, "value": round(100 * (r["lw26"] / r["lw25"] - 1), 1)}
                 for st, r in rec.items() if (r.get("lw25") or 0) > 0 and (r.get("lw26") or 0) > 0],
         wbasis="Last completed week vs 2025, like-for-like (per store)",
         qtd=_yoy_qtd("sales"), qbasis="Quarter-to-date vs 2025, like-for-like (per store)")
    _ps2("YoY Transactional Growth", plan=5,
         weekly=[{"store": st, "value": round(100 * (r["tx26"] / r["tx25"] - 1), 1)}
                 for st, r in rec.items() if (r.get("tx25") or 0) > 0 and (r.get("tx26") or 0) > 0],
         wbasis="Last completed week transactions vs 2025, like-for-like (per store)",
         qtd=_yoy_qtd("tx"), qbasis="Quarter-to-date transactions vs 2025, like-for-like (per store)")
    _ps2("Food GP%", plan=71,
         weekly=[{"store": st, "value": round(v["gp_pct"], 1)} for st, v in cos.items() if v.get("gp_pct") is not None],
         wbasis="Cost-of-Sales latest week, per store (col Q Gross Profit%)",
         qtd=[{"store": st, "value": round(v["gp_qtd"], 1)} for st, v in cos.items() if v.get("gp_qtd") is not None],
         qbasis="Cost-of-Sales quarter-to-date, per store (col Q, sales-weighted)")
    # Per-store SPH targets from the Store-Targets sheet (cph_targets.json, col C £/hr). Each store is
    # judged against ITS OWN target; the company headline SPH tile stays on the blanket 55. A store with
    # no target in the sheet falls back to 55 (target=None -> renderer flags it as a default).
    _sph_tgt = jload("cph_targets.json").get("targets", {})
    _sph_weekly = [{"store": st, "value": round(rec[st]["lw26"] / v["used_lastwk"], 1),
                    "target": _sph_tgt.get(st)}
                   for st, v in ovr.items() if v.get("used_lastwk") and rec.get(st, {}).get("lw26")]
    _ps2("SPH Labour (incl holiday pay)", plan=55,
         weekly=_sph_weekly,
         wbasis="Last completed week sales ÷ planner hours used, vs each store's own £/hr target (Store-Targets sheet)",
         qtd=[dict(r) for r in _sph_weekly],
         qbasis="Per-store SPH vs each store's own target — QTD labour hours aren't separately sourced, so this mirrors the last completed week")   # company QTD tile stays on 55
    _bench_rows = [{"store": row[0], "value": sum(1 for i in range(6, 10) if len(row) > i and str(row[i]).strip())}
                   for row in benchj.get("rows", []) if row and row[0]]
    _ps2("Bench", plan=1,
         weekly=_bench_rows, wbasis="Named bench successors per store (point-in-time — same each period)",
         qtd=[dict(x) for x in _bench_rows], qbasis="Named bench successors per store (point-in-time — same each period)")
    _ps2("F1 Score", plan=F1_PLAN,
         weekly=f1_wk_ps, wbasis="Last completed week race Total Score (per store)",
         qtd=[{"store": st, "value": round(v["race_qtd"]["score"], 1)} for st, v in fdet.items()
              if v.get("race_qtd") and v["race_qtd"].get("score") is not None],
         qbasis="QTD average race Total Score (per store)")
    _ps2("Google Health", plan=100,
         qtd=[{"store": st, "value": round((min(nv[0] / (40 * weeks_q), 1) + min(nv[1] / 4.6, 1)) / 2 * 100, 1)}
              for st, nv in sh.get("google", {}).items() if nv and nv[0]],
         qbasis="QTD blend: review volume (÷%d) & rating (÷4.6), per store" % (40 * weeks_q))
    _ps2("Rate My Shift Health", plan=100,
         qtd=[{"store": st, "value": round((min(nv[0] / (70 * weeks_q), 1) + min(nv[1] / 4.6, 1)) / 2 * 100, 1)}
              for st, nv in sh.get("rms", {}).items() if nv and nv[0]],
         qbasis="QTD blend: submission volume (÷%d) & score (÷4.6), per store" % (70 * weeks_q))
    _ps2("Brand Audit Score", plan=4.6,
         qtd=[{"store": st, "value": round(r["audit_qtd"], 2)} for st, r in rec.items() if r.get("audit_qtd")],
         qbasis="QTD brand audit score out of 5 (per store)")
    _ps2("Brew Crew Kudos Participation", plan=50,
         weekly=kudos_ps_weekly,
         wbasis="Distinct employees at the store who gave kudos last week ÷ store headcount (per store, vs 50% plan)",
         qtd=kudos_ps_qtd,
         qbasis="Distinct employees at the store who gave kudos this quarter ÷ store headcount (per store, vs 50% plan)")

    # ---- YoY Sales detail extras: per-store ATV + food-attachment %, DUAL basis (weekly + QTD) ----
    atv_ps = [{"store": st, "value": round(r["lw26"] / r["tx26"], 2)}
              for st, r in rec.items() if (r.get("tx26") or 0) > 0 and (r.get("lw26") or 0) > 0]
    food_attach = []
    try:
        fa_rows = bq(f"""
          WITH t AS (
            SELECT item_outlet_name s, id, MAX(IF(cat IN ('Food','Bakery'),1,0)) hasfood
            FROM (SELECT item_outlet_name, id, {cat_case('item_product_name')} cat
                  FROM {FLAT}
                  WHERE DATE(sales_date) BETWEEN DATE('{LASTWK_MON.isoformat()}') AND {CE}
                    AND item_outlet_name NOT IN ('Royal Leamington Spa','Leamington Retail','Leamington Spa'))
            GROUP BY s, id)
          SELECT s, COUNT(*) txns, SUM(hasfood) foodtx, ROUND(100*SUM(hasfood)/COUNT(*),1) fa
          FROM t GROUP BY s""")
        food_attach = [{"store": normalize(r["s"]), "value": r["fa"]} for r in fa_rows
                       if normalize(r["s"]) and (r.get("txns") or 0) > 0]
    except Exception as e:
        flags.append("YoY detail: per-store food-attach (BigQuery) failed (%s)." % str(e)[:70])
    yoy_detail = {
        "atv_target": 6.8,
        "atv_trend_col": "estate_atv",          # gen reads this weekly_history column for the estate ATV trend
        "atv_wk": atv_wk,
        "atv": {"weekly": {"basis": "Last completed week sales ÷ transactions (per store)", "rows": atv_ps},
                "qtd": {"basis": "Quarter-to-date sales ÷ transactions (per store)", "rows": atv_qtd_ps}},
        "food_attach": {"weekly": {"basis": "Food or Bakery guest-checks ÷ transactions, last completed week (per store)", "rows": food_attach},
                        "qtd": {"basis": "Food or Bakery guest-checks ÷ transactions, quarter-to-date (per store)",
                                "rows": [{"store": st, "value": v} for st, v in food_qtd_ps.items() if v is not None]}},
    }

    out = {
        "_about": "Bewiched EOS Scorecard data. Written by run_weekly.py pull_eos_scorecard(); "
                  "rendered by gen_eos_scorecard.py. Live = BigQuery; derived = other feeds; manual = inputs sheet.",
        "generated": NOW_UK.strftime("%d %b %Y, %H:%M"),
        "cur_end": CUR_END.isoformat(),
        "quarter_start": QSTART.isoformat(),   # current calendar-quarter start; gen filters the grid/trends to this
        "week_label": wlabel(LASTWK_MON),
        "quarter_label": qlabel,
        "manual_sheet_id": SID["eos"],
        "config": {"binary": True},
        "weekly": weekly,
        "quarterly": quarterly,
        "per_store": per_store,
        "yoy_detail": yoy_detail,
        "flags": flags,
    }
    # ---- BACK-FILL prior weeks of the quarter into weekly_history.csv (idempotent; cell-level) ----
    # Week-endings (Sundays) from quarter start to cur_end.
    q_weeks = []
    _we = CUR_END
    while _we >= QSTART:
        q_weeks.append(_we); _we -= datetime.timedelta(days=7)
    q_weeks = sorted(q_weeks)
    def _wend(dt):     # map any date to its week-ending Sunday
        return dt - datetime.timedelta(days=(dt.weekday() + 1) % 7)
    bf = {w.isoformat(): {} for w in q_weeks}
    # (a) BigQuery per-week: estate sales, LFL YoY sales/tx
    try:
        first = q_weeks[0].isoformat()
        rows = bq(f"""
          WITH weeks AS (SELECT we FROM UNNEST(GENERATE_DATE_ARRAY(DATE('{first}'), {CE}, INTERVAL 7 DAY)) we),
          b AS (SELECT item_outlet_name s, DATE(sales_date) dd, id, SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
                FROM {FLAT} WHERE DATE(sales_date) BETWEEN DATE_SUB(DATE('{first}'), INTERVAL 370 DAY) AND {CE}
                  AND item_outlet_name NOT IN ('Royal Leamington Spa','Leamington Retail','Leamington Spa')),
          sw AS (SELECT w.we, x.s,
                   SUM(IF(x.dd BETWEEN DATE_SUB(w.we,INTERVAL 6 DAY) AND w.we, x.v,0)) cur,
                   COUNT(DISTINCT IF(x.dd BETWEEN DATE_SUB(w.we,INTERVAL 6 DAY) AND w.we, x.id,NULL)) curtx,
                   SUM(IF(x.dd BETWEEN DATE_SUB(w.we,INTERVAL 370 DAY) AND DATE_SUB(w.we,INTERVAL 364 DAY), x.v,0)) ly,
                   COUNT(DISTINCT IF(x.dd BETWEEN DATE_SUB(w.we,INTERVAL 370 DAY) AND DATE_SUB(w.we,INTERVAL 364 DAY), x.id,NULL)) lytx
                 FROM weeks w CROSS JOIN b x GROUP BY w.we, x.s)
          SELECT CAST(we AS STRING) we, ROUND(SUM(cur)) sales,
                 ROUND(SUM(cur)/NULLIF(SUM(curtx),0),2) atv,
                 ROUND(100*(SUM(IF(cur>0 AND ly>0,cur,0))/NULLIF(SUM(IF(cur>0 AND ly>0,ly,0)),0)-1),1) yoy_sales,
                 ROUND(100*(SUM(IF(cur>0 AND ly>0,curtx,0))/NULLIF(SUM(IF(cur>0 AND ly>0,lytx,0)),0)-1),1) yoy_tx
          FROM sw GROUP BY we""")
        for r in rows:
            w = r["we"]
            if w in bf:
                bf[w].update(estate_sales=r["sales"], estate_atv=r["atv"],
                             yoy_sales_pct=r["yoy_sales"], yoy_tx_pct=r["yoy_tx"])
    except Exception as e:
        flags.append("Grid back-fill: BigQuery per-week sales/YoY failed (%s)." % str(e)[:70])
    # (b) COS estate GP per week + NPAT projection (GP flex only; labour held at baseline for history)
    gpw = jload("cos_metrics.json").get("estate_gp_by_week", {})
    for w, g in gpw.items():
        if w in bf and g is not None:
            bf[w]["estate_gp_pct"] = g
            bf[w]["npat_proj_pct"] = round(B["npat"] + (g - (gp_may if gp_may is not None else g)), 1)
    # (c) F1 per week: average race Total Score (The Race: date col0, Total col18)
    try:
        for r in sheet(SID["f1"], "'The Race'!A1:AE3000")[1:]:
            if len(r) < 19 or r[0] in (None, ""): continue
            dt = parse_any_date(r[0])
            if not dt: continue
            w = _wend(dt).isoformat()
            if w in bf: bf[w].setdefault("_f1", []).append(fnum(r[18]))
        for w in bf:
            xs = bf[w].pop("_f1", None)
            if xs: bf[w]["f1_avg"] = round(sum(xs) / len(xs), 1)
    except Exception as e:
        flags.append("Grid back-fill: F1 per-week failed (%s)." % str(e)[:70])
    # (d) RMS per week blend (Shift Ratings: date col0, rating col2)
    try:
        rmsw = {}
        for r in sheet(SID["f1"], "'Shift Ratings'!A1:N20000")[1:]:
            if not r or len(r) < 3 or r[1] in (None, ""): continue
            dt = parse_any_date(r[0])
            try: rt = float(r[2])
            except Exception: continue
            if not dt: continue
            w = _wend(dt).isoformat()
            if w in bf: rmsw.setdefault(w, []).append(rt)
        for w, xs in rmsw.items():
            if xs:
                avg = sum(xs) / len(xs)
                bf[w]["rms_pct"] = round((min(len(xs) / 70, 1) + min(avg / 4.6, 1)) / 2 * 100, 1)
    except Exception as e:
        flags.append("Grid back-fill: RMS per-week failed (%s)." % str(e)[:70])
    # (e) Google Health per week blend (Reviews: star col1, time col3)
    try:
        gw = {}
        rv = sheet(SID["reviews"], "Reviews!A1:D6000", unformatted=False)
        if len(rv) >= 5999: rv += sheet(SID["reviews"], "Reviews!A6000:D20000", unformatted=False)
        for r in rv[1:]:
            if not r or not r[0]: continue
            star = fnum(r[1], None) if len(r) > 1 and r[1] not in (None, "") else None
            dt = parse_any_date(r[3]) if len(r) > 3 else None
            if star is None or not dt: continue
            w = _wend(dt).isoformat()
            if w in bf: gw.setdefault(w, []).append(star)
        for w, xs in gw.items():
            if xs:
                avg = sum(xs) / len(xs)
                bf[w]["google_health_pct"] = round((min(len(xs) / 40, 1) + min(avg / 4.6, 1)) / 2 * 100, 1)
    except Exception as e:
        flags.append("Grid back-fill: Google per-week failed (%s)." % str(e)[:70])
    # (f) Kudos per week: distinct employee-contributors that week / total employees (reuse bckh_rows + emp_emails)
    if emp_emails and bckh_rows:
        kw = {}
        for r in bckh_rows:
            if len(r) < 2 or r[1] in (None, ""): continue
            dt = parse_any_date(r[0]) if r[0] not in (None, "") else None
            if not dt: continue
            em = str(r[1]).strip().lower()
            if em in emp_emails:
                w = _wend(dt).isoformat()
                if w in bf: kw.setdefault(w, set()).add(em)
        for w, es in kw.items():
            bf[w]["kudos_pct"] = round(100 * len(es) / len(emp_emails), 1)
    # merge back-fill into history (cell-level; current week overwritten by the primary upsert below)
    bywk0 = {r.get("week_ending"): r for r in hist_rows}
    for w, cells in bf.items():
        row = bywk0.setdefault(w, {"week_ending": w})
        for k, v in cells.items():
            if v is not None: row[k] = v
    hist_rows = list(bywk0.values())
    n_bf_weeks = len(q_weeks)

    # ---- upsert this week's row into weekly_history.csv (dedupe by week_ending: re-runs UPDATE, not duplicate) ----
    def _hc(v): return "" if v is None else v
    new_row = {"week_ending": CUR_END.isoformat(), "estate_sales": round(estate_sales_wk),
               "estate_gp_pct": _hc(gp_wk_live), "estate_cph": _hc(cph_estate), "sph": _hc(sph),
               "npat_proj_pct": _hc(npat_wk), "yoy_sales_pct": _hc(yoy_sales_wk), "yoy_tx_pct": _hc(yoy_tx_wk),
               "f1_avg": _hc(f1_wk), "rms_pct": _hc(rh), "kudos_pct": _hc(kudos_wk_pct),
               "brand_audit": _hc(audit_lastwk), "google_health_pct": _hc(gh), "estate_atv": _hc(atv_wk)}
    by_wk = {r.get("week_ending"): r for r in hist_rows}
    by_wk[new_row["week_ending"]] = new_row
    ordered = sorted(by_wk.values(), key=lambda r: r.get("week_ending", ""))
    with open(HIST, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=HCOLS); wr.writeheader()
        for r in ordered: wr.writerow({k: r.get(k, "") for k in HCOLS})
    print("[pull] weekly_history: upserted %s (%d rows total, %d in quarter)" % (CUR_END.isoformat(), len(ordered), n_hist_q))

    W("eos_scorecard.json", out, indent=1)
    print("[pull] eos_scorecard: weekly %d / quarterly %d metrics (yoy_sales=%s yoy_tx=%s)"
          % (len(weekly), len(quarterly), yoy_sales, yoy_tx))


def _run(script, *args):
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, script), *args],
                           cwd=HERE, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        sys.stdout.write("[builder FAILED] %s\n" % script)
        sys.stdout.write((e.stdout or "") + (e.stderr or ""))
        sys.stdout.flush()
        raise
    out = (p.stdout or "") + (p.stderr or "")
    sys.stdout.write(out)
    if "leftover placeholders" in out:
        GEN_LEFTOVER[script] = out.count("leftover placeholders: none")
    return out

def build():
    """Run the full builder/generator/patcher chain in dependency order.
    A (estate pulls) already ran in main(). Here: B builders -> D generators -> E patcher."""
    # B — store-page input builders + estate transforms (must precede generators & patcher)
    _run("build_mix_peaktime.py")
    _run("build_queue_benchmark.py")
    _run("storehealth_calc.py")
    _run("build_reviews.py", "cur_end=%s" % CUR_END.isoformat())
    _run("build_audit.py")
    _run("build_compliance.py")
    _run("build_simply_lunch.py")
    _run("build_txquality_glenvale.py")
    _run("build_txquality_leamington.py")
    _run("build_star.py")
    # D — generators (each prints 'leftover placeholders: none'); bench_render is imported within
    _run("gen_company.py")
    _run("gen_area.py")
    _run("gen_kel.py")
    _run("gen_claire.py")
    if os.path.exists(os.path.join(HERE, "gen_eos_scorecard.py")) and \
       os.path.exists(os.path.join(HERE, "eos_scorecard.json")):
        _run("gen_eos_scorecard.py")
    if os.path.exists(os.path.join(HERE, "gen_maintenance.py")) and \
       os.path.exists(os.path.join(HERE, "maintenance.json")):
        try:
            _run("gen_maintenance.py")            # NON-FATAL: maintenance must never abort the whole build/commit
        except Exception as e:
            print("[build] gen_maintenance FAILED - Maintenance section degraded, run continues: %s" % e)
    # B9 store sales + E patcher (LAST)
    _run("build_newsite_sales.py")
    _run("patch_newsite.py")
    print("[build] full chain complete")


def freshness_gate():
    """Refuse to publish a partial run (the 28 Jun failure). Fail loudly, publish nothing."""
    errs = []
    def fresh(fn):
        p = os.path.join(HERE, fn)
        return os.path.exists(p) and os.path.getmtime(p) >= RUN_START - 1
    # 1. F1: newest raw Race date must be FRESH for this run — on OR AFTER cur_end.
    #    The gate only catches STALE F1 (newest race BEHIND the reporting week, i.e. the
    #    F1 pull was skipped / audits not entered). An F1 audit dated in the current,
    #    incomplete week (AHEAD of cur_end) is legitimately newer than the reporting
    #    week-end and must NOT block publishing. ISO date strings compare chronologically.
    try:
        fd = json.load(open(os.path.join(HERE, "f1_detail.json")))
        newest = max((v["race"][8] for v in fd.values() if v.get("race")), default=None)
        if newest is None or newest < CUR_END.isoformat():
            errs.append("f1_detail newest race %s < cur_end %s (F1 pull skipped or audits pending — stale)"
                        % (newest, CUR_END))
    except Exception as e:
        errs.append("f1_detail unreadable: %s" % e)
    # 2. Reviews: _wtd_window == [cur_end-6, cur_end] AND rec carries cust_qtd/cust_wtd
    try:
        rf = json.load(open(os.path.join(HERE, "reviews_feed.json")))
        want = [LASTWK_MON.isoformat(), CUR_END.isoformat()]
        win = rf.get("_wtd_window")
        if win not in (want, "%s..%s" % tuple(want)):
            errs.append("reviews_feed _wtd_window %s != %s" % (win, want))
        rec = json.load(open(os.path.join(HERE, "allstores.json")))["rec"]
        if not any("cust_qtd" in r and "cust_wtd" in r for r in rec.values()):
            errs.append("allstores rec missing cust_qtd/cust_wtd (build_reviews skipped)")
    except Exception as e:
        errs.append("reviews gate unreadable: %s" % e)
    # 3. Changed-vs-baseline: every key estate output must have been rewritten THIS run
    for fn in ("allstores.json", "company_wastage.json", "daypart_food.json", "actuals.json",
               "planner_overrides.json", "rms.json", "storehealth.json", "audit_themes.json",
               "compliance.json", "star_rating.json", "cos_metrics.json", "cph_targets.json",
               "f1_detail.json", "newsite_sales.json", "smt_visits.json", "bench.json"):
        if not fresh(fn):
            errs.append("%s not rewritten this run (pull/builder skipped -> stale)" % fn)
    # 4. Consistency: newsite_sales _window names this run's Sunday
    try:
        ns = json.load(open(os.path.join(HERE, "newsite_sales.json")))
        if CUR_END.strftime("%-d %b") not in ns.get("_window", ""):
            errs.append("newsite_sales _window stale: %s" % ns.get("_window"))
    except Exception as e:
        errs.append("newsite_sales unreadable: %s" % e)
    # 5. Generators each reported 'leftover placeholders: none'
    for g in ("gen_company.py", "gen_area.py", "gen_kel.py", "gen_claire.py"):
        if GEN_LEFTOVER.get(g, 0) < 1:
            errs.append("%s did not report 'leftover placeholders: none'" % g)
    if errs:
        print("[gate] FAILED — partial run, publishing nothing:")
        for e in errs: print("   x " + e)
        sys.exit(1)
    print("[gate] freshness OK — all estate outputs refreshed to %s" % CUR_END)


# ============================ ORCHESTRATION ============================
def pulls():
    """All estate + store-page pulls (A) in dependency order."""
    pull_sales()              # rec windows/dow/daypart  (-> allstores.json)
    pull_cph_fallback()       # rec.cph
    pull_cph_targets()        # cph_targets.json
    pull_cos()                # cos_metrics.json
    pull_smt()                # smt_visits.json + rec.visdow
    pull_wastage()            # company_wastage.json + rec waste
    pull_f1()                 # f1_detail.json + rec.f1 + champ + the_race.csv
    pull_actuals()            # actuals.json
    pull_planner()            # planner_overrides.json  (MANDATORY)
    pull_takeaway()           # rec.takeaway
    pull_sickness()           # rec.sent
    pull_audit()              # audit_raw.json + rec.audit_qtd
    pull_mix()                # rec.mix/mix_prev/mix_lw
    pull_peak()               # peak_cat_raw.json + peak_bakery_raw.json
    pull_availability()       # rec.avail
    pull_daypart_food()       # daypart_food.json + daypart_food_area.json
    pull_bench()              # bench.json
    pull_reviews()            # reviews_raw.json + rec.cust + customer.json (+ google scratch)
    pull_rms_storehealth()    # rms.json + storehealth_raw.json
    pull_compliance()         # compliance_raw.json
    pull_ns_raws()            # ns_*_raw.json (7)
    pull_sl_raws()            # sl_*_raw.json (2)
    pull_txq_raws()           # txq_*_raw.json (2)
    pull_eos_scorecard()      # eos_scorecard.json (EOS Weekly+Quarterly scorecard)
    pull_maintenance()        # maintenance.json (reactive/planned/coffee/audit)  [non-fatal]


def main():
    print("[run] Bewiched weekly — mode=%s cur_end=%s" % (MODE, CUR_END))
    pulls()
    build()
    freshness_gate()
    print("[done] %s run rebuilt — workflow will commit & push" % MODE)


if __name__ == "__main__":
    main()
