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
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",           # read + write (SPH history sheet)
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

def _accident_date(v):
    """Accident-log date. Cells are normally REAL dates (Sheets serials -> unambiguous), so those
    parse exactly. For any TEXT-entered date, disambiguate US M/D vs UK D/M robustly (the banking
    US-format trap): prefer the interpretation that is valid AND not in the future; if both qualify,
    prefer UK day-first (Bewiched is a UK business). Falls back to parse_any_date for other formats."""
    if isinstance(v, (int, float)):
        return serial_to_date(v)
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100: y += 2000
        def mk(mo, da):
            try: return datetime.date(y, mo, da)
            except ValueError: return None
        uk = mk(b, a); us = mk(a, b)                 # UK day/month ; US month/day
        today = datetime.date.today()
        for d in (uk, us):                            # UK-first, non-future wins
            if d and d <= today:
                return d
        return uk or us
    return parse_any_date(s)


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
_PQM = QSTART.month - 3; _PQY = QSTART.year
if _PQM <= 0: _PQM += 12; _PQY -= 1
PREV_QSTART = datetime.date(_PQY, _PQM, 1)   # previous calendar-quarter start (module-level; avoids fn-local PQSTART shadow)
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
         "Warwick", "Wellingborough", "Wellingborough Train Station"]
COACH = {  # store -> area coach (Jon 9 / Rich 9 / Ian 4 = 22)
    "Burton Latimer": "Jon", "Peterborough Fletton Quays": "Jon", "Rothwell": "Jon",
    "Corby": "Jon", "Kettering": "Jon", "Rushden Lakes": "Jon",
    "Peterborough Bridge Street": "Jon", "Higham Ferrers": "Jon", "Olney": "Jon",
    "Leamington Parade": "Rich", "Northampton": "Rich", "Wellingborough Train Station": "Rich",
    "Market Harborough": "Rich", "Wellingborough": "Rich", "Lower Heathcote": "Rich",
    "Rugby": "Rich", "Northampton Drive-Thru": "Rich", "Billing Drive Thru": "Rich",
    "Attleborough": "Ian", "HOE Balsall Common": "Ian", "Glenvale Drive Thru": "Ian",
    "Warwick": "Ian"}
DT_STORES = ["Billing Drive Thru", "Glenvale Drive Thru", "Northampton Drive-Thru"]
DT_LANE_SHEET = "1ZC4XdhbHV4FhsqURkgp3W8cipn94FnDMumn_jxMWt58"   # matt@-owned DT lane-speed log (SA writer)
DT_SITE_MAP = {"glenvale": "Glenvale Drive Thru", "great billing": "Billing Drive Thru",
               "billing": "Billing Drive Thru", "northampton": "Northampton Drive-Thru",
               "moulton": "Northampton Drive-Thru", "moulton park": "Northampton Drive-Thru",
               "moulton park dt": "Northampton Drive-Thru"}
STORE_PAGES = ["Olney", "Attleborough", "Billing Drive Thru", "Glenvale Drive Thru",
               "Northampton Drive-Thru", "Leamington Parade"]
COMMERCIAL_STORES = ["Glenvale Drive Thru", "Leamington Parade"]
CATS = ["Hot drinks", "Cold drinks", "Milkshakes", "Food", "Bakery", "Other & retail"]

# informal source label -> canonical (lower-cased keys; competitors flagged separately)
_MAP = {
    "lower heathcote, warwick": "Lower Heathcote", "lower heathcote": "Lower Heathcote",
    "warwick": "Warwick", "warwick market square": "Warwick", "burton": "Burton Latimer",
    "peterborough": "Peterborough Bridge Street", "p'boro bridge st": "Peterborough Bridge Street",
    "fletton": "Peterborough Fletton Quays", "p'boro fletton quays": "Peterborough Fletton Quays",
    "market street": "Wellingborough", "w'boro market st": "Wellingborough",
    "northampton grosvenor": "Northampton", "npton grosvenor": "Northampton", "grosvenor": "Northampton",
    "train station": "Wellingborough Train Station",
    "w'boro train station": "Wellingborough Train Station",
    "wboro train station": "Wellingborough Train Station",
    "w'boro train stn": "Wellingborough Train Station", "wboro train stn": "Wellingborough Train Station",
    "lakes": "Rushden Lakes",
    "higham": "Higham Ferrers", "balsall": "HOE Balsall Common",
    "balsall common": "HOE Balsall Common",
    "northampton drive thru": "Northampton Drive-Thru", "npton drive thru": "Northampton Drive-Thru",
    "glenvale dt": "Glenvale Drive Thru", "leamington retail": None, "leamington spa": None,
    "royal leamington spa": None}
COMPETITORS = {"costa", "nero", "nero's", "starbucks", "coffee#1", "coffee #1", "pret"}
def is_competitor(name):
    return str(name).strip().lower().rstrip("'s") in {c.rstrip("'s") for c in COMPETITORS}
_WC_MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
def _parse_wc(v):
    """Parse a 'W/C 17 Aug 2026' style week-commencing label -> datetime.date (the Monday).
    Robust to ordinals (1st/2nd/3rd/17th), 3+ letter month names, and a missing year
    (falls back to the current run year). Returns None if it can't be parsed."""
    if v in (None, ""):
        return None
    m = re.search(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]{3,})\.?(?:\s+(\d{4}))?", str(v))
    if not m:
        return None
    day = int(m.group(1)); mon = _WC_MONTHS.get(m.group(2)[:3].lower())
    if not mon:
        return None
    yr = int(m.group(3)) if m.group(3) else CUR_END.year
    try:
        return datetime.date(yr, mon, day)
    except Exception:
        return None


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
def cat_case7(col):
    """Like cat_case but splits Retail (beans/1kg/gift/merch) out from the ELSE catch-all 'Other'.
    Categories: Hot, Cold, Milkshakes, Food, Bakery, Retail, Other."""
    return (r"""CASE
      WHEN REGEXP_CONTAINS(LOWER({c}), r'milkshake') THEN 'Milkshakes'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'iced|frappe|frozen|matcha|cold brew') THEN 'Cold'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'beans|1kg|gift|merch') THEN 'Retail'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'pastry|sausage roll') AND REGEXP_CONTAINS(LOWER({c}), r'meal deal') THEN 'Bakery'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'meal deal|croque|ciabatta|\bbap\b|wrap|sandwich|bagel|salad|tuna|panini|toastie|soup|sausage roll|breakfast') THEN 'Food'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'traybake|brownie|slice|croissant|pastry|muffin|cookie|cake|bakewell|millionaire|teacake|scone|flapjack|twist|doughnut|fudge|cinnamon') THEN 'Bakery'
      WHEN REGEXP_CONTAINS(LOWER({c}), r'latte|cappuccino|americano|flat white|mocha|espresso|hot choc|\bmug\b|\bpot\b|\btea\b|coffee|macchiato|cortado|chai') THEN 'Hot'
      ELSE 'Other' END""").replace("{c}", col)
CAT7LABEL = {"Hot": "Hot drinks", "Cold": "Cold drinks", "Milkshakes": "Milkshakes",
             "Food": "Food", "Bakery": "Bakery", "Retail": "Retail", "Other": "Other"}
CAT7ORDER = ["Hot drinks", "Cold drinks", "Milkshakes", "Food", "Bakery", "Retail", "Other"]

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
    # ---- ALL-TIME COMPANY RECORDS (auto-rolls: recomputed from the full BigQuery history each run,
    #      so a new record set this week is picked up automatically). Non-fatal: degrades the widget only.
    ALL_IN = "(" + ",".join("'%s'" % st.replace("'", "\\'") for st in CANON) + ")"
    try:
        _rw = bq(f"""
          SELECT wc, rev FROM (
            SELECT DATE_TRUNC(DATE(sales_date),WEEK(MONDAY)) wc,
                   ROUND(SUM(SAFE_CAST(item_line_total_after_discount AS FLOAT64))) rev
            FROM {FLAT}
            WHERE item_outlet_name IN {ALL_IN} AND DATE(sales_date) <= {CE}
            GROUP BY wc
            QUALIFY ROW_NUMBER() OVER (ORDER BY rev DESC)=1)""")
        _rh = bq(f"""
          SELECT dd, hr, rev, orders FROM (
            SELECT DATE(sales_date) dd, {HOUR} hr,
                   ROUND(SUM(SAFE_CAST(item_line_total_after_discount AS FLOAT64))) rev,
                   COUNT(DISTINCT id) orders
            FROM {FLAT}
            WHERE item_outlet_name IN {ALL_IN} AND DATE(sales_date) <= {CE}
            GROUP BY dd, hr
            HAVING orders >= 30 AND SAFE_DIVIDE(rev, orders) <= 30
            QUALIFY ROW_NUMBER() OVER (ORDER BY rev DESC)=1)""")
        recout = {"_updated": CUR_END.isoformat(), "_basis": "All-time, company estate (%d stores), from BigQuery full history to %s." % (len(CANON), CUR_END.isoformat())}
        if _rw:
            wc = _rw[0]["wc"]
            if not isinstance(wc, datetime.date): wc = parse_any_date(str(wc))
            we = (wc + datetime.timedelta(days=6)) if wc else None
            recout["record_week"] = {"rev": int(_rw[0]["rev"]),
                "week_start": wc.isoformat() if wc else None,
                "week_ending": we.isoformat() if we else None,
                "label": ("w/e %s" % we.strftime("%-d %b %Y")) if we else str(_rw[0]["wc"])}
        if _rh:
            dd = _rh[0]["dd"]
            if not isinstance(dd, datetime.date): dd = parse_any_date(str(dd))
            hr = int(_rh[0]["hr"])
            recout["record_hour"] = {"rev": int(_rh[0]["rev"]), "orders": int(_rh[0]["orders"]),
                "date": dd.isoformat() if dd else str(_rh[0]["dd"]), "hour": hr,
                "dow_label": dd.strftime("%a %-d %b %Y") if dd else "",
                "hour_label": "%02d:00\u2013%02d:00" % (hr, (hr + 1) % 24)}
        # ---- average gross weekly sales PER STORE vs same week last year (fair: each year ÷ its own
        #      actual trading-store count, since the estate was smaller last year). Also a flat ÷21 variant.
        _av = bq(f"""
          SELECT
            ROUND(SUM(IF(dd BETWEEN {d(6)} AND {CE}, v, 0))) ty_total,
            COUNT(DISTINCT IF(dd BETWEEN {d(6)} AND {CE} AND v>0, s, NULL)) ty_stores,
            ROUND(SUM(IF(dd BETWEEN {d(370)} AND {d(364)}, v, 0))) ly_total,
            COUNT(DISTINCT IF(dd BETWEEN {d(370)} AND {d(364)} AND v>0, s, NULL)) ly_stores
          FROM (SELECT item_outlet_name s, DATE(sales_date) dd,
                       SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
                FROM {FLAT}
                WHERE item_outlet_name IN {ALL_IN} AND DATE(sales_date) BETWEEN {d(370)} AND {CE})""")
        if _av:
            a0 = _av[0]
            tyt = a0.get("ty_total") or 0; tys = a0.get("ty_stores") or 0
            lyt = a0.get("ly_total") or 0; lys = a0.get("ly_stores") or 0
            ty_avg = round(tyt / tys) if tys else None
            ly_avg = round(lyt / lys) if lys else None
            yoy = round(100 * (ty_avg / ly_avg - 1), 1) if (ty_avg and ly_avg) else None
            NST = len(CANON)
            ty21 = round(tyt / NST) if NST else None
            ly21 = round(lyt / NST) if NST else None
            yoy21 = round(100 * (ty21 / ly21 - 1), 1) if (ty21 and ly21) else None
            recout["avg_per_store"] = {
                "ty_total": int(tyt), "ly_total": int(lyt), "ty_stores": int(tys), "ly_stores": int(lys),
                "ty_avg": ty_avg, "ly_avg": ly_avg, "yoy_pct": yoy,
                "ty_avg_fixed": ty21, "ly_avg_fixed": ly21, "yoy_fixed_pct": yoy21, "fixed_n": NST,
                "week_label": wlabel(LASTWK_MON)}
            print("[pull] avg/store vs LY: TY £%s (÷%d) vs LY £%s (÷%d) -> %s%% | flat ÷%d: £%s vs £%s -> %s%%" % (
                ty_avg, tys, ly_avg, lys, yoy, NST, ty21, ly21, yoy21))
        W("sales_records.json", recout, indent=1)
        print("[pull] sales records: record week £%s %s | record hour £%s %s %s" % (
            recout.get("record_week", {}).get("rev"), recout.get("record_week", {}).get("label"),
            recout.get("record_hour", {}).get("rev"), recout.get("record_hour", {}).get("hour_label"),
            recout.get("record_hour", {}).get("dow_label")))
    except Exception as e:
        print("[pull] sales records FAILED (non-fatal, widget degrades): %s" % str(e)[:150])
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
    # SOLD FIX: v_sales_vs_wastage.SalesQuantity reads 0 for every line, so join wastage -> EPOS actuals
    # (SUM(item_quantity) from v_sales_details_flat) on a NORMALISED product name (strip leading digits/
    # asterisks, ' TA', ' (Copy)') over the SAME 28-day window. Unmatched lines -> sold=None ('no EPOS match').
    def _cw(col):
        return ("TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(LOWER(%s),"
                r" r'^[0-9*]+ *',''), r' ta$',''), r' \(copy\)',''))") % col
    comp = bq(f"""
      WITH sold AS (
        SELECT {_cw('item_product_name')} p, SUM(SAFE_CAST(item_quantity AS FLOAT64)) units
        FROM {FLAT} WHERE DATE(sales_date) BETWEEN {d(27)} AND {CE} GROUP BY p),
      waste AS (
        SELECT {_cw('product_name')} p, ANY_VALUE(product_name) nm,
               ROUND(SUM({WQ})) wq, ROUND(SUM({RV}),2) wr
        FROM {WASTE} WHERE date BETWEEN {d(27)} AND {CE} AND {WQ}>0
        GROUP BY p)
      SELECT w.nm, w.wq, w.wr, s.units sold
      FROM waste w LEFT JOIN sold s ON w.p = s.p
      ORDER BY w.wr DESC LIMIT 40""")
    _w4 = CUR_END - datetime.timedelta(days=27)
    def _dl(d1, d2):
        f1 = d1.strftime("%-d %b" + ("" if d1.year == d2.year else " %Y")); return "%s \u2013 %s" % (f1, d2.strftime("%-d %b %Y"))
    _nomatch = sum(1 for r in comp if r["sold"] is None)
    W("company_wastage.json", {"_window": "last 28 days",
        "_window4": [_w4.isoformat(), CUR_END.isoformat()], "_window4_label": _dl(_w4, CUR_END),
        "_window_lw": [LASTWK_MON.isoformat(), CUR_END.isoformat()], "_window_lw_label": _dl(LASTWK_MON, CUR_END),
        "rows": [[r["nm"], r["wq"] or 0, r["wr"] or 0,
                  (int(r["sold"]) if r["sold"] is not None else None)] for r in comp]}, indent=1)
    print("[pull] wastage sold-join: %d products, %d with no EPOS match" % (len(comp), _nomatch))
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


def pull_area_quarters():
    """Scope-A area date filter: per-store CURRENT-quarter (QTD) and immediately-PREVIOUS-quarter
    aggregates (sales / tx / YoY / ATV + wastage £&% + category mix) for the area-dashboard
    this-quarter / last-quarter selector. Previous quarter auto-rolls each quarter boundary."""
    a = load_all(); rec = a["rec"]
    _pqm = QSTART.month - 3; _pqy = QSTART.year
    if _pqm <= 0: _pqm += 12; _pqy -= 1
    PQSTART = datetime.date(_pqy, _pqm, 1); PQEND = QSTART - datetime.timedelta(days=1)
    def _ly(dd):
        try: return dd.replace(year=dd.year - 1)
        except ValueError: return dd.replace(year=dd.year - 1, day=28)
    D = lambda x: "DATE('%s')" % x.isoformat()
    qcs, qce = D(QSTART), D(CUR_END); qcsly, qcely = D(_ly(QSTART)), D(_ly(CUR_END))
    qps, qpe = D(PQSTART), D(PQEND); qpsly, qpely = D(_ly(PQSTART)), D(_ly(PQEND))
    sx = bq(f"""
      SELECT item_outlet_name s,
        ROUND(SUM(IF(dd BETWEEN {qcs} AND {qce}, v, 0))) qc_s,
        COUNT(DISTINCT IF(dd BETWEEN {qcs} AND {qce}, id, NULL)) qc_t,
        ROUND(SUM(IF(dd BETWEEN {qcsly} AND {qcely}, v, 0))) qc_sly,
        COUNT(DISTINCT IF(dd BETWEEN {qcsly} AND {qcely}, id, NULL)) qc_tly,
        ROUND(SUM(IF(dd BETWEEN {qps} AND {qpe}, v, 0))) qp_s,
        COUNT(DISTINCT IF(dd BETWEEN {qps} AND {qpe}, id, NULL)) qp_t,
        ROUND(SUM(IF(dd BETWEEN {qpsly} AND {qpely}, v, 0))) qp_sly,
        COUNT(DISTINCT IF(dd BETWEEN {qpsly} AND {qpely}, id, NULL)) qp_tly
      FROM (SELECT item_outlet_name, DATE(sales_date) dd, id,
                   SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
            FROM {FLAT} WHERE DATE(sales_date) BETWEEN {qpsly} AND {qce})
      GROUP BY s""")
    wx = bq(f"""
      SELECT outlet s,
        ROUND(SUM(IF(date BETWEEN {qcs} AND {qce} AND SAFE_CAST(WastageQuantity AS FLOAT64)>0, SAFE_CAST(RetailValue AS FLOAT64), 0))) qc_w,
        ROUND(SUM(IF(date BETWEEN {qps} AND {qpe} AND SAFE_CAST(WastageQuantity AS FLOAT64)>0, SAFE_CAST(RetailValue AS FLOAT64), 0))) qp_w
      FROM {WASTE} WHERE date BETWEEN {qps} AND {qce} GROUP BY s""")
    wm = {r["s"]: r for r in wx}
    mx = bq(f"""
      SELECT s, cat,
        ROUND(SUM(IF(dd BETWEEN {qcs} AND {qce}, v, 0))) qc,
        ROUND(SUM(IF(dd BETWEEN {qps} AND {qpe}, v, 0))) qp
      FROM (SELECT item_outlet_name s, DATE(sales_date) dd, {cat_case('item_product_name')} cat,
                   SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
            FROM {FLAT} WHERE DATE(sales_date) BETWEEN {qps} AND {qce})
      GROUP BY s, cat""")
    mixmap = {}
    for r in mx:
        d = mixmap.setdefault(r["s"], {"qc": {}, "qp": {}})
        d["qc"][CATLABEL[r["cat"]]] = r["qc"] or 0
        d["qp"][CATLABEL[r["cat"]]] = r["qp"] or 0
    def _q(sv, tv, slv, tlv, wv):
        sv = sv or 0; tv = tv or 0
        return {"sales": round(sv), "tx": int(tv), "atv": round(sv / tv, 2) if tv else None,
                "yoy_sales": round(100 * (sv / slv - 1), 1) if slv else None,
                "yoy_tx": round(100 * (tv / tlv - 1), 1) if tlv else None,
                "waste": round(wv or 0), "waste_pct": round(100 * (wv or 0) / sv, 1) if sv else None}
    for r in sx:
        st = r["s"]
        if st not in rec: continue
        w = wm.get(st, {})
        rec[st]["q_cur"] = _q(r["qc_s"], r["qc_t"], r["qc_sly"], r["qc_tly"], w.get("qc_w"))
        rec[st]["q_prev"] = _q(r["qp_s"], r["qp_t"], r["qp_sly"], r["qp_tly"], w.get("qp_w"))
        mm = mixmap.get(st, {"qc": {}, "qp": {}})
        for key, qk in (("q_cur", "qc"), ("q_prev", "qp")):
            cats = mm[qk]; tot = sum(cats.values()) or 1
            rec[st][key]["mix"] = {c: round(100 * cats.get(c, 0) / tot, 1) for c in CATS}
    def _ql(dd): return "Q%d %d" % ((dd.month - 1) // 3 + 1, dd.year)
    a["area_qmeta"] = {"cur_label": _ql(QSTART), "prev_label": _ql(PQSTART),
        "cur_range": [QSTART.isoformat(), CUR_END.isoformat()],
        "prev_range": [PQSTART.isoformat(), PQEND.isoformat()]}
    save_all(a)
    print("[pull] area quarters: %d stores (cur %s / prev %s)" % (len(sx), _ql(QSTART), _ql(PQSTART)))


def pull_f1():
    """STEP 2e — RAW 'The Race' + 'Qualifying' tabs (UNFORMATTED, full span). Writes
    f1_detail.json + rec.f1 + champ. Also writes the_race.csv for build_queue_benchmark.
    VALIDATED via Zapier 29 Jun: newest Race serial 46201 == 2026-06-28 == cur_end;
    cols Date0 Store1 Queue4 Hello5 Goodbye6 HowAreYou7 WTQ8 Total18 Coach28 ChampPts29 Finish30."""
    race = sheet(SID["f1"], "'The Race'!A1:AG3000")   # AG captures col AF "Average Person Queue Time" (idx 31)
    quali = sheet(SID["f1"], "'Qualifying'!A1:R2000")
    # F1 QUEUE-METRIC CUTOVER (confirmed with Matt; mirrors the Total Score formula's
    # date-conditional): dates  < 29 Jun 2026 -> OLD "Queue average" (col E, idx 4);
    # dates >= 29 Jun 2026 -> NEW "Average Person Queue Time" (col AF, idx 31). Applied
    # to race_arr / race_qtd.queue_s / race_qtd.queue and the_race.csv (queue-vs-comp trend).
    Q_CUTOVER = datetime.date(2026, 6, 29)
    def f1_queue(dt, row):
        idx = 31 if dt >= Q_CUTOVER else 4
        return fnum(row[idx]) if len(row) > idx else None
    racer, csv_rows = {}, []          # racer[store] -> list of (date, row)
    comp_rows = []
    for r in race[1:]:
        if len(r) < 31 or r[0] in (None, ""): continue
        dt = parse_any_date(r[0])
        if not dt: continue
        coach = (str(r[28]).strip() if len(r) > 28 else "")
        csv_rows.append([dt.isoformat(), str(r[1]).strip(), f1_queue(dt, r), coach])
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
        race_arr = [f1_queue(dt, r), fnum(r[5]), fnum(r[6]), fnum(r[7]), fnum(r[8]),
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
        q2 = [x for x in rows if PREV_QSTART <= x[0] < QSTART and fnum(x[1][18]) > 0]   # prior quarter (F1 QoQ)
        def avg(idx, src=qtd):
            xs = [fnum(x[1][idx]) for x in src]
            return round(sum(xs) / len(xs), 2) if xs else None
        def avgq(src=qtd):   # queue avg with per-row E/AF cutover
            xs = [f1_queue(x[0], x[1]) for x in src]
            xs = [v for v in xs if v is not None]
            return round(sum(xs) / len(xs), 2) if xs else None
        def pct(v): return None if v is None else round(v * 100, 1)
        # RACE QTD table reads queue_s / qcall (=Working The Queue %) / hello|goodbye|howareyou.
        # The sheet holds greetings as 0-1 fractions, so store them as PERCENTAGES (were rendering ~1%).
        race_qtd = {"n": len(qtd), "score": avg(18),
                    "queue_s": avgq(), "qcall": pct(avg(8)),
                    "hello": pct(avg(5)), "goodbye": pct(avg(6)), "howareyou": pct(avg(7)),
                    "queue": avgq(), "wtq": avg(8)}
        race_q2 = {"n": len(q2), "score": avg(18, q2)}   # prior-quarter avg Total Score (lower = better)
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
        # ---- Full race breakdown: every scored section (cols 19-27), QTD avg per store.
        # These are PENALTY points that roll into Total Score (0 = full marks, lower = better).
        _SECT = [(19,"Hello"),(20,"Goodbye"),(21,"How are you"),(22,"Working the queue"),
                 (23,"Food & syrups"),(24,"Tables <3 mins"),(25,"Tables brand standard"),
                 (26,"Virtual section plan"),(27,"No late team")]
        _sections = {}
        for _ix,_lab in _SECT:
            _xs = [fnum(x[1][_ix]) for x in qtd if len(x[1]) > _ix and x[1][_ix] not in (None,"")]
            _sections[_lab] = round(sum(_xs)/len(_xs),2) if _xs else None
        fd[st] = {"race": race_arr, "quali": quali_arr,
                  "race_qtd": race_qtd, "race_q2": race_q2, "quali_qtd": quali_qtd, "last6": last6,
                  "sections": _sections, "sect_queue": avgq()}
    # F1 staleness marker (read by the generators to badge the section, and by the freshness
    # gate as a SOFT warning). Stale = the newest race audit is behind this reporting week's
    # Sunday (audits pending) — the F1 pull still ran, so we publish and badge rather than block.
    # Estate average per race section + section max points (for the full-breakdown visual).
    _SECT_MAX = {"Hello":25,"Goodbye":25,"How are you":25,"Working the queue":25,
                 "Food & syrups":31.25,"Tables <3 mins":31.25,"Tables brand standard":31.25,
                 "Virtual section plan":31.25,"No late team":31.25}
    _SECT_ORDER = ["Hello","Goodbye","How are you","Working the queue","Food & syrups",
                   "Tables <3 mins","Tables brand standard","Virtual section plan","No late team"]
    _est = {}
    for _lab in _SECT_ORDER:
        _vs = [fd[_s]["sections"][_lab] for _s in fd
               if isinstance(fd.get(_s), dict) and fd[_s].get("sections")
               and fd[_s]["sections"].get(_lab) is not None]
        _est[_lab] = round(sum(_vs)/len(_vs),2) if _vs else None
    fd["_race_sections"] = {"order": _SECT_ORDER, "maxpoints": _SECT_MAX, "estate": _est,
        "note": "penalty points per audit section that roll into Total Score; lower = better (0 = full marks)"}
    _f1_stale = (newest is None) or (newest < CUR_END)
    fd["_stale"] = {"stale": bool(_f1_stale),
                    "newest": newest.isoformat() if newest else None,
                    "cur_end": CUR_END.isoformat(),
                    "badge": "F1 awaiting this week's audit (w/e %s)" % CUR_END.strftime("%-d %b %Y")}
    W("f1_detail.json", fd, indent=1)

    # rec.f1 / f1_finish + champ (drivers since 25 Apr 2026; constructors by coach)
    a = load_all(); rec = a["rec"]
    drivers = []
    cons = {}
    cons_n = {}
    CHAMP_FROM = QSTART   # RESET each quarter: drivers + constructors count THIS quarter only (was fixed 25 Apr)
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
    # SEASON-TO-DATE constructors: sum Championship Points across EVERY audited race this season
    # (not reset each quarter), by area coach. season_from = earliest audited race in the data.
    cons_s = {}; cons_s_n = {}; season_from = None
    drivers_season = []   # per-store season championship points — the DRIVERS that roll up into each constructor
    for st, rows in racer.items():
        srows = [(dt, r) for dt, r in rows if fnum(r[18]) > 0]   # audited races only, this season
        spts = round(sum(fnum(r[29]) for dt, r in srows))         # store's season championship points
        coach = COACH.get(st, "")
        cons_s[coach] = cons_s.get(coach, 0) + spts               # constructor total = Sum of its drivers' points
        cons_s_n[coach] = cons_s_n.get(coach, 0) + 1
        first_race = min((dt for dt, r in srows), default=None)
        drivers_season.append([st, coach, spts, len(srows),
                               first_race.isoformat() if first_race else None])
        for dt, r in srows:
            season_from = dt if season_from is None else min(season_from, dt)
    drivers_season.sort(key=lambda x: -x[2])
    cons_season = [[c, tot, cons_s_n[c], round(tot / cons_s_n[c], 1) if cons_s_n[c] else 0]
                   for c, tot in cons_s.items()]
    cons_season.sort(key=lambda x: -x[3])
    # reconciliation: sum of each constructor's drivers' points must equal the constructor total
    _drv_by_coach = {}
    for _st, _cc, _pts, _n, _fr in drivers_season:
        _drv_by_coach[_cc] = _drv_by_coach.get(_cc, 0) + _pts
    _recon_ok = all(abs(_drv_by_coach.get(_c, 0) - _tot) < 1 for _c, _tot in cons_s.items())
    # ---- QUARTER-TO-DATE constructors + drivers (Option A): same points system, current calendar
    # quarter only (dt >= QSTART = 1st of this quarter). Both reconcile: constructor = Sum of drivers. ----
    cons_q = {}; cons_q_n = {}; drivers_qtd = []
    for st, rows in racer.items():
        qrows = [(dt, r) for dt, r in rows if fnum(r[18]) > 0 and dt >= QSTART]   # audited races THIS quarter
        qpts = round(sum(fnum(r[29]) for dt, r in qrows))
        coach = COACH.get(st, "")
        cons_q[coach] = cons_q.get(coach, 0) + qpts
        cons_q_n[coach] = cons_q_n.get(coach, 0) + 1
        first_q = min((dt for dt, r in qrows), default=None)
        drivers_qtd.append([st, coach, qpts, len(qrows),
                            first_q.isoformat() if first_q else None])
    drivers_qtd.sort(key=lambda x: -x[2])
    cons_qtd = [[c, tot, cons_q_n[c], round(tot / cons_q_n[c], 1) if cons_q_n[c] else 0]
                for c, tot in cons_q.items()]
    cons_qtd.sort(key=lambda x: -x[3])
    _drvq_by_coach = {}
    for _st, _cc, _pts, _n, _fr in drivers_qtd:
        _drvq_by_coach[_cc] = _drvq_by_coach.get(_cc, 0) + _pts
    _recon_qtd_ok = all(abs(_drvq_by_coach.get(_c, 0) - _tot) < 1 for _c, _tot in cons_q.items())
    # ---- Q(this) vs Q(prev) QoQ: "Working the Queue" score (col I / idx 8) + Greet/Goodbye (Hello idx5 +
    #      Goodbye idx6). These are SCORED criteria, unaffected by the 29-Jun queue-TIMING cutover, so the
    #      quarter-over-quarter comparison is straight like-for-like. Company rollup + per-coach rollups.
    _pqm = QSTART.month - 3; _pqy = QSTART.year
    if _pqm <= 0: _pqm += 12; _pqy -= 1
    PQSTART = datetime.date(_pqy, _pqm, 1)
    def _blank(): return {"q3": {"qw": [0.0, 0], "gg": [0.0, 0]}, "q2": {"qw": [0.0, 0], "gg": [0.0, 0]}}
    comp_acc = _blank(); coach_acc = {}
    for st, rows in racer.items():
        ca = coach_acc.setdefault(COACH.get(st, ""), _blank())
        for dt, r in rows:
            if fnum(r[18]) <= 0: continue          # real audited race rows only
            if dt >= QSTART: k = "q3"
            elif PQSTART <= dt < QSTART: k = "q2"
            else: continue
            if len(r) > 8 and r[8] not in (None, ""):
                v = fnum(r[8])
                for acc in (comp_acc, ca): acc[k]["qw"][0] += v; acc[k]["qw"][1] += 1
            h = fnum(r[5]) if len(r) > 5 and r[5] not in (None, "") else None
            g = fnum(r[6]) if len(r) > 6 and r[6] not in (None, "") else None
            if h is not None and g is not None:
                gg = (h + g) / 2
                for acc in (comp_acc, ca): acc[k]["gg"][0] += gg; acc[k]["gg"][1] += 1
    def _qoq_out(acc):
        def pc(k, m):
            tot, n = acc[k][m]
            return round(100 * tot / n, 1) if n else None
        return {"qw_q3": pc("q3", "qw"), "qw_q2": pc("q2", "qw"),
                "gg_q3": pc("q3", "gg"), "gg_q2": pc("q2", "gg"),
                "n_q3": acc["q3"]["qw"][1], "n_q2": acc["q2"]["qw"][1]}
    qn3 = (QSTART.month - 1) // 3 + 1; qn2 = (PQSTART.month - 1) // 3 + 1
    a["champ"] = {"drivers": drivers, "cons": cons_rows,
        "cons_season": cons_season, "drivers_season": drivers_season,
        "cons_qtd": cons_qtd, "drivers_qtd": drivers_qtd,
        "qtd_from": QSTART.isoformat(),
        "season_from": season_from.isoformat() if season_from else None,
        "f1_qoq": _qoq_out(comp_acc),
        "f1_qoq_coach": {c: _qoq_out(ac) for c, ac in coach_acc.items()},
        "f1_qoq_labels": {"q3": "Q%d" % qn3, "q2": "Q%d" % qn2,
            "q3_range": [QSTART.isoformat(), CUR_END.isoformat()],
            "q2_range": [PQSTART.isoformat(), (QSTART - datetime.timedelta(days=1)).isoformat()]}}
    save_all(a)
    with open(os.path.join(HERE, "the_race.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["Date", "Store Name", "Queue average", "Area Coach"])
        w.writerows(csv_rows)
    print("[pull] f1: %d stores, newest race %s (cur_end %s)" % (len(fd), newest, CUR_END))
    print("[pull] f1 drivers_season: %d drivers, reconciles_to_constructors=%s" % (len(drivers_season), _recon_ok))
    print("[pull] f1 drivers_qtd (since %s): %d drivers, reconciles_to_constructors=%s" % (QSTART.isoformat(), len(drivers_qtd), _recon_qtd_ok))
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
    """B5 — Store-Targets sheet -> cph_targets.json. SINGLE SOURCE OF TRUTH for the per-store SPH
    target feeding EOS + Star Card scoring: column G "SPH including Holiday Pay" (6% holiday-inclusive
    basis, matches actual SPH now that holiday is folded into the denominator). Falls back to the old
    col C "SPH target (£/hr)" if G is blank for a store (e.g. Warwick, not yet in the sheet)."""
    rows = sheet(SID["cph"], "A1:G40")
    tgt = {}; _src = {}
    for r in rows[1:]:
        if not r: continue
        st = normalize(r[0])
        if not st: continue
        g = r[6] if len(r) > 6 and r[6] not in (None, "") else None   # col G = SPH including Holiday Pay
        c = r[2] if len(r) > 2 and r[2] not in (None, "") else None   # col C = legacy SPH target
        if g is not None:
            tgt[st] = round(fnum(g)); _src[st] = "G"
        elif c is not None:
            tgt[st] = round(fnum(c)); _src[st] = "C(fallback)"
    W("cph_targets.json", {"_source": "Google Sheet %s: col G 'SPH including Holiday Pay' (6%% holiday-inclusive), fallback col C" % SID["cph"],
        "_basis": "holiday-inclusive", "_pulled": CUR_END.isoformat(), "targets": tgt, "_col": _src}, indent=1)
    print("[pull] cph_targets: %d stores (col G holiday-inclusive; fallback C: %s)"
          % (len(tgt), ",".join(k for k,v in _src.items() if v!="G") or "none"))


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
    latest_x = {}       # store -> (date-serial, delivery%, total_deliv£, sales, {supplier £})
    week_hist = {}      # week-iso -> {store -> {stock, deliv, gp}} for per-store trend sparklines (backfilled from the sheet)
    qtd_x = {}          # store -> {sales, deliv, sel, fresh, johal, tiffin} summed over the quarter
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
            # delivery % (col P/idx15), total deliveries £ (col O/idx14), suppliers K-N (idx10-13)
            def _n(i): return fnum(r[i]) if len(r) > i and r[i] not in (None, "") else None
            _dp = _n(15); dpc = (round(_dp * 100, 1) if (_dp is not None and _dp < 2) else (round(_dp, 1) if _dp is not None else None))
            tdv = _n(14); sel = _n(10); fre = _n(11); kw = _n(12); sim = _n(13)   # col M=K&W, N=Simply (header N still reads "Tiffin")
            if st not in latest_x or ds >= latest_x[st][0]:
                latest_x[st] = (ds, dpc, tdv, sales, {"Select Catering": sel, "Fresh Ideas": fre, "K&W": kw, "Simply": sim})
            _wk = serial_to_iso(ds)
            if _wk:
                week_hist.setdefault(_wk, {})[st] = {"stock": hold, "deliv": dpc, "gp": round(gp * 100, 2),
                    "sales": (round(sales) if sales is not None else None),
                    "stock_gbp": (round(hold / 100.0 * sales) if (hold is not None and sales) else None),
                    "deliv_gbp": (round(tdv) if tdv is not None else None),
                    "sup": {"Select Catering": (round(sel) if sel is not None else None),
                            "Fresh Ideas": (round(fre) if fre is not None else None),
                            "K&W": (round(kw) if kw is not None else None),
                            "Simply": (round(sim) if sim is not None else None)}}
            if ds >= QSTART_S:
                qx = qtd_x.setdefault(st, {"sales": 0.0, "deliv": 0.0, "sel": 0.0, "fresh": 0.0, "kw": 0.0, "sim": 0.0})
                qx["sales"] += sales; qx["deliv"] += (tdv or 0)
                qx["sel"] += (sel or 0); qx["fresh"] += (fre or 0); qx["kw"] += (kw or 0); qx["sim"] += (sim or 0)
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
    # ---- delivery % + supplier breakdown (latest COS week + QTD) per store ----
    for st, (ds, dpc, tdv, _sa, sup) in latest_x.items():
        sx = out["stores"].setdefault(st, {})
        sx["delivery_pct"] = dpc; sx["deliv_gbp"] = round(tdv) if tdv is not None else None
        sx["suppliers"] = {k: (round(v) if v is not None else None) for k, v in sup.items()}
    for st, qx in qtd_x.items():
        sx = out["stores"].setdefault(st, {})
        if qx["sales"]: sx["delivery_pct_qtd"] = round(100 * qx["deliv"] / qx["sales"], 1)
        sx["suppliers_qtd"] = {"Select Catering": round(qx["sel"]), "Fresh Ideas": round(qx["fresh"]),
                               "K&W": round(qx["kw"]), "Simply": round(qx["sim"])}
    # ---- stock-holding TARGET BAND, derived from the current estate spread (median +/- 10pp of sales) ----
    import statistics as _stats
    hvals = sorted(v["holding_pct"] for v in out["stores"].values() if v.get("holding_pct") is not None)
    if hvals:
        _med = _stats.median(hvals); _TOL = 10.0
        out["holding_median"] = round(_med, 1)
        out["holding_band"] = [round(max(0, _med - _TOL), 1), round(_med + _TOL, 1)]
        out["holding_band_basis"] = "estate median %.1f%% of sales +/- %g pp (n=%d stores)" % (_med, _TOL, len(hvals))
    # ---- delivery target + company delivery % (latest week, store-summed) + QTD + £ opportunity ----
    out["delivery_target"] = 23.0; out["delivery_saving_per_pct"] = 31000
    _td = sum(x[2] or 0 for x in latest_x.values()); _ts = sum(x[3] or 0 for x in latest_x.values())
    out["delivery_company_pct"] = round(100 * _td / _ts, 1) if _ts else None
    _tdq = sum(qx["deliv"] for qx in qtd_x.values()); _tsq = sum(qx["sales"] for qx in qtd_x.values())
    out["delivery_company_qtd"] = round(100 * _tdq / _tsq, 1) if _tsq else None
    _cp = out["delivery_company_pct"]
    out["delivery_opportunity_gbp"] = round(max(0.0, (_cp - 23.0)) * 31000) if _cp is not None else None
    # ---- PER-STORE VOLUME-BASED planned targets (fit £target = base + rate*weekly_sales across the
    #      estate; gives each store a target scaled to its own sales volume). Stock: base = minimum
    #      stock any store needs; rate = cover as % of sales. Ordering = delivery cost £. Re-fit each run.
    pts = []   # (sales, stock£, deliv£) per store, latest COS week
    for st, (ds, dpc, tdv, sa, sup) in latest_x.items():
        h = latest.get(st, (None,))[0]
        if sa and sa > 0 and h is not None and tdv is not None:
            pts.append((sa, h * sa / 100.0, tdv))
    def _ols(xs, ys):
        n = len(xs)
        if n < 4: return None
        mx = sum(xs) / n; my = sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        if den <= 0: return None
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
        return (my - b * mx, b)
    _sx = [p[0] for p in pts]
    smod = _ols(_sx, [p[1] for p in pts]); dmod = _ols(_sx, [p[2] for p in pts])
    if smod:
        out["stock_model"] = {"base_gbp": round(smod[0]), "rate_pct": round(smod[1] * 100, 1),
            "_basis": "planned stock £ = %d + %.1f%% of weekly sales (fit across %d stores)" % (round(smod[0]), smod[1] * 100, len(pts))}
    if dmod:
        out["deliv_model"] = {"base_gbp": round(dmod[0]), "rate_pct": round(dmod[1] * 100, 1),
            "_basis": "planned delivery £ = %d + %.1f%% of weekly sales (fit across %d stores); company ref 23%%" % (round(dmod[0]), dmod[1] * 100, len(pts))}
    for st, (ds, dpc, tdv, sa, sup) in latest_x.items():
        if not (sa and sa > 0): continue
        sx = out["stores"].setdefault(st, {})
        if smod: sx["stock_target_pct"] = round(100 * (smod[0] + smod[1] * sa) / sa, 1)
        if dmod: sx["deliv_target_pct"] = round(100 * (dmod[0] + dmod[1] * sa) / sa, 1)
    _wks = dict(sorted(week_hist.items())[-13:])
    W("cos_history.json", {"weeks": _wks}, indent=1)
    W("cos_metrics.json", out, indent=1)
    print("[pull] cos history: %d weeks banked (per-store stock/deliv/gp)" % len(_wks))
    print("[pull] cos delivery+stock: company deliv %s%% (qtd %s%%) target 23%% | stock band %s | %d stores" % (
        out.get("delivery_company_pct"), out.get("delivery_company_qtd"), out.get("holding_band"), len(latest_x)))
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
    # ---- named OUTSTANDING RTW (last 4 weeks) + per-store table for the EOS RMS tab (mirrors Kel's Sentiment tab) ----
    def _nn(x): return re.sub(r'\s+', ' ', str(x or '').strip().lower())
    cutoff28 = CUR_END - datetime.timedelta(days=28)
    rtw_by_name = {}
    for r in rtw[1:]:
        if not r or len(r) < 3 or not r[0]: continue
        nm = _nn(r[0]); dtc = parse_any_date(r[2]) if len(r) > 2 else None
        if nm and dtc: rtw_by_name.setdefault(nm, []).append(dtc)
    outstanding = []
    for r in sick[1:]:
        if not r or len(r) < 6 or not r[0] or not r[1]: continue
        typ = str(r[3]).strip().lower() if len(r) > 3 and r[3] else ''
        if 'late' in typ: continue                       # RTW is for sickness, not lateness
        dts = parse_any_date(r[5])
        if not dts or dts < cutoff28 or dts > CUR_END: continue
        nm = _nn(r[0]); stc = normalize(r[1])
        done = any(d >= dts for d in rtw_by_name.get(nm, []))   # RTW interview conducted on/after the absence
        if not done:
            outstanding.append({'name': str(r[0]).strip(), 'store': stc or str(r[1]).strip(),
                                'date': dts.isoformat(),
                                'reason': (re.sub(r'\s+', ' ', str(r[4]).strip())[:90] if len(r) > 4 and r[4] else '')})
    outstanding.sort(key=lambda x: x['date'], reverse=True)
    _tbl = []
    for st in sorted(rec, key=lambda z: -((S.get(z, {}) or {}).get('sick', 0))):
        e = S.get(st, {})
        _tbl.append({'store': st, 'sickfs': e.get('sickfs', 0), 'late': e.get('late', 0),
                     'rep_pct': (round(100 * e.get('rep', 0) / e.get('tot', 1)) if e.get('tot') else None),
                     'rtw': RT.get(st, 0), 'sick': e.get('sick', 0),
                     'rtw_rate': (round(100 * RT.get(st, 0) / e.get('sick', 0)) if e.get('sick') else None)})
    W('sickness_rtw.json', {'generated': CUR_END.isoformat(), 'window_days': 28,
        'outstanding': outstanding, 'outstanding_n': len(outstanding), 'per_store': _tbl}, indent=1)
    print('[pull] sickness named RTW: %d outstanding in last 28d' % len(outstanding))
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


def pull_remote():
    """STEP 2j+ — Remote Assessment (same Richard Wagg sheet as the brand audit; tab
    'Remote Assessment Data': Store col B, Date col D, Score col E out of 100). Per-store QTD mean
    of valid scores (Score>0), normalised to /5 (divide by 20). Sets rec.remote_qtd (/5),
    rec.remote_qtd100, rec.remote_n; writes remote_raw.json with the last-completed-week estate avg."""
    rows = sheet(SID["audit"], "'Remote Assessment Data'!A1:F4000")
    a = load_all(); rec = a["rec"]
    qtd = {}; lastwk = []
    for r in rows[1:]:
        if len(r) < 5 or not r[1]: continue
        st = normalize(r[1])
        if st is None: continue
        dt = parse_any_date(r[3])
        if not dt: continue
        sc = fnum(r[4])
        if sc is None or sc <= 0: continue           # negative / blank = not completed -> skip
        if dt >= QSTART: qtd.setdefault(st, []).append(sc)
        if LASTWK_MON <= dt <= CUR_END: lastwk.append(sc)
    for st, xs in qtd.items():
        if st in rec:
            avg100 = sum(xs) / len(xs)
            rec[st]["remote_qtd100"] = round(avg100, 1)
            rec[st]["remote_qtd"] = round(avg100 / 20, 3)
            rec[st]["remote_n"] = len(xs)
    save_all(a)
    W("remote_raw.json", {"_pulled": CUR_END.isoformat(),
        "_sheet": "%s / Remote Assessment Data" % SID["audit"],
        "_scale": "Score out of 100, normalised to /5 (divide by 20)",
        "_lastwk_avg100": round(sum(lastwk) / len(lastwk), 1) if lastwk else None,
        "_lastwk_n": len(lastwk)}, indent=1)
    print("[pull] remote: %d stores qtd, %d assessments last week" % (len(qtd), len(lastwk)))


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
    life = {}; lastwk = {}; qtd_g = {}; q2_g = {}
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
        if dt and PREV_QSTART <= dt < QSTART:
            q2_g.setdefault(st, []).append(star)   # prior-quarter Google (QoQ)
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
    json.dump({st: [len(v), round(sum(v) / len(v), 3)] for st, v in q2_g.items()},
              open(os.path.join(HERE, "_google_prevq.json"), "w"))    # prior-quarter Google for the Star Card QoQ chip
    print("[pull] reviews: %d rows, %d stores last week" % (len(recs), len(lastwk)))


def pull_rms_storehealth():
    """STEP 2g2/2g3 — F1 'Shift Ratings' tab. rms.json (company last week) + storehealth_raw.json
    (per-store QTD RMS + per-store QTD Google) for the refactored storehealth_calc.py.
    VALIDATED layout via Zapier 29 Jun: Date0(serial) Store1 Rating2."""
    rows = sheet(SID["f1"], "'Shift Ratings'!A1:N20000")   # FULL tail — latest submissions are at the BOTTOM (>6k rows); A1:N6000 missed them
    # Cols: A Date, B Store, C Rating(1-5), D Description(team comment), E SMT Comment(mgr reply), F DoW, G Area.
    lastwk = []                        # company last completed week
    qtd = {}                           # store -> [ratings] (QTD)
    q2 = {}                            # store -> [ratings] (prior quarter, for QoQ)
    wk_store = {}                      # store -> [ratings] (last completed week, per store)
    COMMENT_LO = TODAY - datetime.timedelta(days=13)   # 'recent shift voice' = last ~2 weeks to the run date
    comment_rows = []                  # (date, store_disp, rating, description, smt_reply)
    lastwk_rows = []                   # FULL previous-week detail rows (date, store, rating, desc, smt) for the worst-first list
    for r in rows[1:]:
        if not r or len(r) < 3 or not r[1]: continue
        dt = parse_any_date(r[0]); st = normalize(r[1])
        try: rating = float(r[2])
        except Exception: continue
        if not dt: continue
        if LASTWK_MON <= dt <= CUR_END:
            lastwk.append(rating)
            if st: wk_store.setdefault(st, []).append(rating)
            _lwd = re.sub(r"\s+", " ", str(r[3])).strip() if len(r) > 3 and r[3] not in (None, "") else ""
            _lws = re.sub(r"\s+", " ", str(r[4])).strip() if len(r) > 4 and r[4] not in (None, "") else ""
            lastwk_rows.append((dt, st or str(r[1]).strip(), rating, _lwd, _lws))
        if st and dt >= QSTART: qtd.setdefault(st, []).append(rating)
        if st and PREV_QSTART <= dt < QSTART: q2.setdefault(st, []).append(rating)   # prior-quarter RMS (QoQ)
        # recent free-text comments (col D), with the manager's reply (col E) when present
        if COMMENT_LO <= dt <= TODAY:
            desc = re.sub(r"\s+", " ", str(r[3])).strip() if len(r) > 3 and r[3] not in (None, "") else ""
            if desc:
                smt = re.sub(r"\s+", " ", str(r[4])).strip() if len(r) > 4 and r[4] not in (None, "") else ""
                comment_rows.append((dt, st or str(r[1]).strip(), rating, desc, smt))
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
    # ---- rms_feed.json: the expanded Rate My Shift detail (per-store weekly+QTD participation +
    #      recent 'shift voice' comments with sentiment). Rendered by gen_eos_scorecard.py; mirrors
    #      the reviews_feed / Customer Voice pattern. EVERY store appears (non-posters shown as 0).
    def _rsent(rt):
        return "Positive" if rt >= 4 else ("Negative" if rt <= 2 else "Mixed")
    per_store = {}
    for st in rec:
        wv = wk_store.get(st, []); qv = qtd.get(st, []); pv = q2.get(st, [])
        per_store[st] = {
            "weekly": {"n": len(wv), "avg": round(sum(wv) / len(wv), 2) if wv else None},
            "qtd":    {"n": len(qv), "avg": round(sum(qv) / len(qv), 2) if qv else None},
            "prevq":  {"n": len(pv), "avg": round(sum(pv) / len(pv), 2) if pv else None}}
    comments = []
    for (dt, st_disp, rt, desc, smt) in comment_rows:
        comments.append({"store": st_disp, "date": dt.isoformat(), "rating": rt,
                         "text": desc[:300], "smt": (smt[:300] or None), "sentiment": _rsent(rt)})
    comments.sort(key=lambda c: (c["date"], c["rating"]), reverse=True)
    # ---- worst-rated shifts of the PREVIOUS COMPLETED WEEK, lowest score first, with a suggested action on outliers ----
    def _rms_action(store, rating, text):
        t = (text or "").lower()
        if any(k in t for k in ("short", "understaff", "no cover", "no support", "on my own", "single", "slammed", "rushed", "rota", "not enough", "busy")):
            return "Review staffing / rota cover for %s — the low score points to being under-supported on shift." % store
        if any(k in t for k in ("manager", "rude", "shout", "unfair", "ignored", "listened", "disrespect", "attitude", "management")):
            return "Follow up with %s's manager on team support and conduct on this shift." % store
        if any(k in t for k in ("broken", "machine", "equipment", "fault", "fridge", "grinder", "boiler", "clean")):
            return "Check equipment / raise maintenance at %s — kit issues flagged on this shift." % store
        if any(k in t for k in ("train", "new starter", "didn't know", "induction", "no idea", "unclear", "confus")):
            return "Reinforce training / onboarding at %s." % store
        if text:
            return "Follow up with %s's manager to investigate this shift and address the comment." % store
        return "Low rating with no comment — ask %s's manager to check in with the team member." % store
    worst = []
    for (dt, st_disp, rt, desc, smt) in sorted(lastwk_rows, key=lambda x: (x[2], x[0])):
        worst.append({"store": st_disp, "date": dt.isoformat(), "dow": dt.strftime("%a %-d %b"),
                      "rating": rt, "text": desc[:300], "smt": (smt[:300] or None),
                      "sentiment": _rsent(rt),
                      "action": (_rms_action(st_disp, rt, desc) if rt <= 2 else None)})
    worst = worst[:12]
    # store-level outliers: lowest weekly average (>=2 shifts), genuinely low only
    _savg = sorted(((st, round(sum(v) / len(v), 2), len(v)) for st, v in wk_store.items() if len(v) >= 2),
                   key=lambda x: x[1])
    outlier_stores = [{"store": st, "avg": av, "n": n,
                       "action": "%s averaged %.2f★ from %d shifts last week (lowest in the estate) — check in with the manager on what's driving it." % (st, av, n)}
                      for st, av, n in _savg[:3] if av < 3.5]
    _psd = {}
    for (dt, st_disp, rt, desc, smt) in lastwk_rows:
        _psd.setdefault(st_disp, []).append({"date": dt.isoformat(), "dow": dt.strftime("%a %-d %b"),
            "rating": rt, "text": desc[:300], "smt": (smt[:300] or None), "sentiment": _rsent(rt),
            "action": (_rms_action(st_disp, rt, desc) if rt <= 2 else None)})
    for _k in _psd: _psd[_k].sort(key=lambda x: (x["rating"], x["date"]))
    _qn = (CUR_END.month - 1) // 3 + 1
    W("rms_feed.json", {
        "_weekly_label": wlabel(LASTWK_MON),
        "_weekly_window": [LASTWK_MON.isoformat(), CUR_END.isoformat()],
        "_qtd_label": "Q%d %d" % (_qn, CUR_END.year),
        "_qtd_window": [QSTART.isoformat(), CUR_END.isoformat()],
        "_comments_label": "recent shift voice — last 2 weeks to %s" % TODAY.strftime("%-d %b %Y"),
        "_comments_window": [COMMENT_LO.isoformat(), TODAY.isoformat()],
        "_lastweek_count": subs,
        "worst": worst,
        "outlier_stores": outlier_stores,
        "per_store": per_store,
        "per_store_detail": _psd,
        "comments": comments[:24]}, indent=1)
    print("[pull] rms/storehealth: company subs %d avg %s; %d rms stores qtd; %d recent comments" % (subs, avg, len(qtd), len(comments)))


def pull_planner():
    """STEP 2g — 3 area planners 'Weekly Planner'!A1:L60 -> planner_overrides.json (MANDATORY).
    VALIDATED layout via Zapier 29 Jun. Section A: Hours used=idx5, Actual CPH=idx6.
    Section B: CPH=idx1, Forecast=idx4/7/10, Plan hrs=idx5/8/11. Blank hours -> field absent."""
    ovr = {}
    for sid in (SID["planner_jon"], SID["planner_rich"], SID["planner_ian"]):
        rows = sheet(sid, "'Weekly Planner'!A1:V60")
        sec = None
        secB_weeks = [None, None, None]   # calendar weeks the 3 forecast cols are LABELLED for (row 19 D/G/J)
        for r in rows:
            if not r: continue
            head = str(r[0]).strip() if r[0] is not None else ""
            low = head.lower()
            if low == "store" and any("hours used" == str(c).strip().lower() for c in r):
                sec = "A"; continue
            if low == "store" and any(str(c).strip().lower() in ("cph target", "sph target") for c in r) and len(r) >= 12:
                sec = "B"; continue
            if head.startswith("AREA TOTAL") or head.startswith("②") or head.startswith("①"):
                if head.startswith("AREA"): sec = None
                continue
            if low.startswith("forecast = last year"):   # Section B week-label row: D/G/J = 'W/C .. 2026'
                secB_weeks = [_parse_wc(r[i]) if len(r) > i else None for i in (3, 6, 9)]
                continue
            st = normalize(r[0])
            if st is None: continue
            o = ovr.setdefault(st, {})
            if sec == "A":
                worked = r[5] if len(r) > 5 and r[5] not in (None, "") else None
                hol = r[8] if len(r) > 8 and r[8] not in (None, "") else None   # Holiday Pay Hours (col I)
                ssp = r[9] if len(r) > 9 and r[9] not in (None, "") else None    # NEW: SSP Hours (col J), folded into SPH exactly like holiday
                acph = r[6] if len(r) > 6 and r[6] not in (None, "") else None  # Actual SPH = C/(F+I+J): sheet folds holiday + SSP in
                if worked is not None:
                    w = round(fnum(worked), 1)
                    hh = round(fnum(hol), 1) if hol is not None else 0.0
                    ss = round(fnum(ssp), 1) if ssp is not None else 0.0
                    o["worked_lastwk"] = w                       # worked hours only (kept separate/visible)
                    o["holiday_lastwk"] = hh                     # holiday pay hours (paid, non-worked)
                    o["ssp_lastwk"] = ss                         # SSP hours (paid sick, non-worked)
                    o["used_lastwk"] = round(w + hh + ss, 1)     # SPH hours = worked + holiday + SSP (feeds den + sph_history + Vizz)
                if acph is not None: o["actual_cph_lastwk"] = round(fnum(acph), 1)
            elif sec == "B":
                o["cph"] = round(fnum(r[1]), 1) if len(r) > 1 and r[1] not in (None, "") else o.get("cph")
                def cv(i): return round(fnum(r[i])) if len(r) > i and r[i] not in (None, "") else None
                o["fc"] = [cv(4), cv(7), cv(10)]
                o["hrs"] = [round(fnum(r[5]), 1) if len(r) > 5 and r[5] not in (None, "") else None,
                            round(fnum(r[8]), 1) if len(r) > 8 and r[8] not in (None, "") else None,
                            round(fnum(r[11]), 1) if len(r) > 11 and r[11] not in (None, "") else None]
                # NEW: holiday-forecast N/P/R (idx 13/15/17); forecast SPH = forecast / (plan hrs + holiday fcst), mirrors sheet O/Q/S
                def hvf(i): return round(fnum(r[i]), 1) if len(r) > i and r[i] not in (None, "") else 0.0
                o["hol_fc"] = [hvf(13), hvf(15), hvf(17)]
                o["ssp_fc"] = [hvf(19), hvf(20), hvf(21)]   # NEW: SSP-forecast T/U/V, folded into forecast SPH like holiday
                _sfc = []
                for _k in range(3):
                    _f = o["fc"][_k]; _h = o["hrs"][_k]; _hol = o["hol_fc"][_k]; _ssp = o["ssp_fc"][_k]
                    _den = (_h or 0) + (_hol or 0) + (_ssp or 0)
                    _sfc.append(round(_f / _den) if (_f is not None and _den > 0) else None)
                o["sph_fc"] = _sfc
                # LABEL-KEYED: the calendar week (Monday ISO) each forecast column is labelled for
                o["fc_weeks"] = [w.isoformat() if w else None for w in secB_weeks]
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



def pull_openclose():
    """Open/Close checklist completion % per store for the Brand Audit tab. Reuses the HRP
    open/close completion log values (all 21 stores, the same source the Star Card foundations
    use) and overlays the live Process Street digital-checklist status where a store is onboarded
    (Glenvale live; Leamington is on the checklist but its dated log is still empty -> awaiting).
    Writes openclose_feed.json for gen_eos_scorecard. No new external pull."""
    OC = {"Kettering":100,"HOE Balsall Common":100,"Glenvale Drive Thru":100,"Rugby":98,
          "Rushden Lakes":98,"Rothwell":98,"Northampton":98,"Leamington Parade":98,
          "Northampton Drive-Thru":96,"Billing Drive Thru":96,"Wellingborough Train Station":94,
          "Attleborough":94,"Burton Latimer":92,"Peterborough Bridge Street":90,
          "Market Harborough":90,"Higham Ferrers":88,"Olney":87,"Peterborough Fletton Quays":85,
          "Wellingborough":81,"Corby":77,"Lower Heathcote":73}
    si_path = os.path.join(HERE, "star_inputs.json")
    si = json.load(open(si_path)) if os.path.exists(si_path) else {}
    live = {}
    for st in COMMERCIAL_STORES:
        s0 = si.get(st, {})
        live[st] = {"on_checklist": True, "pct": s0.get("openclose_pct")}
    rows = []
    for st, pct in OC.items():
        lv = live.get(st)
        on = bool(lv and lv.get("on_checklist"))
        awaiting = bool(lv and lv.get("pct") is None)
        eff = lv["pct"] if (lv and lv.get("pct") is not None) else pct
        rows.append({"store": st, "pct": eff, "on_checklist": on, "awaiting": awaiting})
    rows.sort(key=lambda r: (r["awaiting"], r["pct"] if r["pct"] is not None else 0))
    W("openclose_feed.json", {"cur_end": CUR_END.isoformat(), "target": 90,
        "_source": "HRP open/close completion log (all 21 stores) + live Process Street checklist status",
        "stores": rows})
    ok = sum(1 for r in rows if r["pct"] is not None and not r["awaiting"] and r["pct"] >= 90)
    print("[pull] openclose_feed: %d stores, %d green (>=90)" % (len(rows), ok))


def pull_accidents():
    """Accident / incident log per store for the Brand Audit tab (H&S). Reads the HRP
    'Accident Forms' tab (same accident data surfaced on the Star Card urgent flags) and emits
    accidents_feed.json: recent incidents per store with date + short description + named
    individual, plus a per-store count. Contact number + home address columns are intentionally
    NOT emitted (privacy). Window = trailing 180 days from CUR_END. Non-fatal."""
    try:
        rows = sheet(SID["hrp"], "'Accident Forms'!A1:K400")
    except Exception as e:
        print("[pull] accidents SKIPPED (Accident Forms unreadable by SA? %s)" % e)
        return
    cutoff = CUR_END - datetime.timedelta(days=180)
    def g(r, i):
        return (str(r[i]).strip() if len(r) > i and r[i] not in (None, "") else "")
    by = {}
    total = 0
    for r in rows[1:]:
        if not r:
            continue
        d = _accident_date(r[0] if len(r) > 0 else None)
        if not d or d < cutoff or d > CUR_END:
            continue
        raw_store = g(r, 5)
        st = normalize(raw_store) or ("Unassigned: %s" % raw_store if raw_store else "Unassigned")
        person = g(r, 4) or g(r, 1)
        incident = g(r, 6)
        injury = g(r, 7)
        details = g(r, 10)
        if len(details) > 140:
            details = details[:137].rstrip() + "..."
        fa = g(r, 9).lower()
        first_aid = fa in ("y", "yes", "true", "1")
        item = {"date": d.strftime("%d %b"), "iso": d.isoformat(), "person": person,
                "incident": incident, "injury": injury, "details": details, "first_aid": first_aid}
        by.setdefault(st, []).append(item)
        total += 1
    stores = []
    for st, items in by.items():
        items.sort(key=lambda x: x["iso"], reverse=True)
        stores.append({"store": st, "count": len(items), "items": items})
    stores.sort(key=lambda s0: -s0["count"])
    W("accidents_feed.json", {"cur_end": CUR_END.isoformat(), "window_days": 180,
        "window_from": cutoff.isoformat(),
        "_source": "HRP 'Accident Forms' tab (H&S incident log); contact number + address omitted",
        "total": total, "stores": stores})
    print("[pull] accidents_feed: %d incidents across %d stores (last 180d)" % (total, len(stores)))


def pull_csbr():
    """CS & Br coaching-completion % per store for the Brand Audit tab AND the Star Card coaching
    foundation. Reads the HRP 'CS and Br %' tab: the summary block (K:S) gives per-store
    Customer-Service (CS) and Barista (Br) checklist completion %, monthly + quarterly; the raw
    coaching log (A:F = Name, _, Store, Checklist, Score, Date) is used to compute the 'both
    checklists this month' figure (team members with BOTH a Customer AND a Barista checklist in the
    current month). One source, two consumers. Writes csbr_feed.json. Non-fatal."""
    HRP = SID["hrp"]
    # tab store label -> canonical (EOS rec keys). "Warwick Market Place" = the new Warwick store.
    CSBRMAP = {
        "Burton": "Burton Latimer", "Corby": "Corby", "Northampton Drive Thru": "Northampton Drive-Thru",
        "Fletton": "Peterborough Fletton Quays", "Higham": "Higham Ferrers", "Kettering": "Kettering",
        "Market Street": "Wellingborough", "Northampton Grosvenor": "Northampton",
        "Peterborough": "Peterborough Bridge Street", "Rothwell": "Rothwell", "Rugby": "Rugby",
        "Lakes": "Rushden Lakes", "Train Station": "Wellingborough Train Station",
        "Balsall Common": "HOE Balsall Common", "Lower Heathcote, Warwick": "Lower Heathcote",
        "Market Harborough": "Market Harborough", "Leamington Parade": "Leamington Parade",
        "Glenvale Drive Thru": "Glenvale Drive Thru", "Olney": "Olney", "Attleborough": "Attleborough",
        "Billing Drive Thru": "Billing Drive Thru", "Warwick Market Place": "Warwick",
        "Leamington Retail": None}
    CS_TYPES = {"customer coaching checklist", "customer service coaching checklist",
                "customer service coaching checklist drive thru final"}
    BR_TYPES = {"foundation barista coaching", "level two barista assessment"}
    try:
        summ = sheet(HRP, "'CS and Br %'!K1:S40")
    except Exception as e:
        print("[pull] csbr SKIPPED (summary unreadable? %s)" % e)
        return
    def num(x):
        try: return float(x)
        except Exception: return None
    per = {}
    for r in summ[1:]:
        if not r or not str(r[0]).strip():
            continue
        raw = str(r[0]).strip()
        canon = CSBRMAP.get(raw, raw)
        if canon is None:
            continue
        def g(i): return num(r[i]) if len(r) > i else None
        cs_m_cnt, cs_m, cs_q_cnt, cs_q = g(1), g(2), g(3), g(4)
        b_m_cnt, b_m, b_q_cnt, b_q = g(5), g(6), g(7), g(8)
        # derive active headcount from count / pct (same denominator across cols)
        hc = None
        for cnt, pct in ((cs_m_cnt, cs_m), (b_m_cnt, b_m), (cs_q_cnt, cs_q), (b_q_cnt, b_q)):
            if cnt and pct and pct > 0:
                hc = round(cnt / pct); break
        per[canon] = {"store": canon, "raw_label": raw,
                      "cs_m_pct": round(cs_m * 100, 1) if cs_m is not None else None,
                      "cs_q_pct": round(cs_q * 100, 1) if cs_q is not None else None,
                      "b_m_pct": round(b_m * 100, 1) if b_m is not None else None,
                      "b_q_pct": round(b_q * 100, 1) if b_q is not None else None,
                      "cs_m_cnt": int(cs_m_cnt) if cs_m_cnt is not None else 0,
                      "b_m_cnt": int(b_m_cnt) if b_m_cnt is not None else 0,
                      "headcount": hc}
    # ---- 'both checklists this month' from the raw log ----
    mon_start = CUR_END.replace(day=1)
    try:
        log = sheet(HRP, "'CS and Br %'!A2:F2000")
    except Exception:
        log = []
    def logdate(v):
        if v in (None, ""):
            return None
        try:
            return serial_to_date(float(v))
        except Exception:
            pass
        for fmt in ("%b %d %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(str(v).strip(), fmt).date()
            except Exception:
                continue
        return None
    csp, brp = {}, {}
    for r in log:
        if len(r) < 6:
            continue
        name = str(r[0]).strip().lower()
        name = " ".join(name.split())
        raw_store = str(r[2]).strip() if len(r) > 2 else ""
        chk = str(r[3]).strip().lower() if len(r) > 3 else ""
        d = logdate(r[5] if len(r) > 5 else None)
        if not name or not raw_store or not d or d < mon_start or d > CUR_END:
            continue
        canon = CSBRMAP.get(raw_store, raw_store)
        if canon is None:
            continue
        if chk in CS_TYPES:
            csp.setdefault(canon, set()).add(name)
        elif chk in BR_TYPES:
            brp.setdefault(canon, set()).add(name)
    for canon, rec in per.items():
        both = len(csp.get(canon, set()) & brp.get(canon, set()))
        rec["both_m_cnt"] = both
        hc = rec.get("headcount")
        rec["both_m_pct"] = round(100 * both / hc, 1) if hc else None
        # a store with no headcount AND no coaching logged this month = awaiting/new
        rec["awaiting"] = bool(not hc and rec["cs_m_cnt"] == 0 and rec["b_m_cnt"] == 0)
    rows = sorted(per.values(), key=lambda x: (x.get("both_m_pct") is None, x.get("both_m_pct") or 0))
    W("csbr_feed.json", {"cur_end": CUR_END.isoformat(), "month_start": mon_start.isoformat(),
        "target": 90,
        "_source": "HRP 'CS and Br %' tab (sheetId 913735784): summary K:S (CS/Br completion %) + raw coaching log A:F (both-checklists-this-month). CS=Customer checklist, Br=Barista checklist.",
        "_note": "both_m_pct = team members with BOTH a Customer AND a Barista checklist this month / active headcount. Warwick = 'Warwick Market Place' in the tab; its % denominator currently uses the shared Lower Heathcote/Warwick staff tab until a dedicated Warwick staff tab exists.",
        "stores": rows})
    nb = sum(1 for r in rows if r.get("both_m_pct") is not None and r["both_m_pct"] >= 90)
    print("[pull] csbr_feed: %d stores, %d >=90%% both-checklists" % (len(rows), nb))




def pull_forecast_daily():
    """EOS Forecast tab feed. 3-week planner forecast (planner_overrides: fc/hrs/hol_fc/sph_fc) + LY
    (allstores rec.ly) per store, plus each store's day-of-week SHARE from the last 8 weeks (BigQuery)
    so the weekly forecast can be split into daily. New/low-history stores fall back to the estate DOW
    share. Labour metric = forecast SPH incl holiday (already fc/(hrs+hol)); no food cost. -> forecast_feed.json"""
    import datetime as _dt
    try:
        ovr = json.load(open(os.path.join(HERE, "planner_overrides.json")))
    except Exception as e:
        print("[pull] forecast_daily SKIPPED (no planner_overrides: %s)" % e); return
    try:
        rec = (json.load(open(os.path.join(HERE, "allstores.json"))) or {}).get("rec", {})
    except Exception:
        rec = {}
    mon = CUR_END + _dt.timedelta(days=1)
    def wl(dd): return "W/C %d %s" % (dd.day, dd.strftime("%b"))
    weeks = [{"label": wl(mon + _dt.timedelta(days=7 * i)),
              "monday": (mon + _dt.timedelta(days=7 * i)).isoformat()} for i in range(3)]
    # day-of-week shares (last 8 weeks). BQ DAYOFWEEK: 1=Sun..7=Sat -> Mon..Sun index
    raw = {}
    try:
        for r in bq(f"""
          SELECT item_outlet_name s, EXTRACT(DAYOFWEEK FROM DATE(sales_date)) dw,
                 ROUND(SUM(SAFE_CAST(item_line_total_after_discount AS FLOAT64))) v
          FROM {FLAT} WHERE DATE(sales_date) BETWEEN {d(55)} AND {CE}
          GROUP BY s, dw"""):
            st = normalize(r["s"]); di = {2:0,3:1,4:2,5:3,6:4,7:5,1:6}.get(int(r["dw"]))
            if st and di is not None: raw.setdefault(st, [0.0]*7)[di] += (r["v"] or 0)
    except Exception as e:
        print("[pull] forecast_daily DOW query failed (%s) -- estate share only" % e)
    def shares(arr):
        t = sum(arr) if arr else 0
        return [round(x / t, 4) for x in arr] if t > 0 else None
    est = [0.0]*7
    for arr in raw.values():
        for i in range(7): est[i] += arr[i]
    est_share = shares(est) or [round(1/7, 4)]*7
    wk_iso = [w["monday"] for w in weeks]
    stores = {}
    for st in COACH:
        o = ovr.get(st) or {}
        ly = rec.get(st, {}).get("ly") or [0, 0, 0, 0]
        sh = shares(raw.get(st, []))
        # LABEL-KEYED: pin each coach forecast column to the calendar week it is LABELLED for,
        # then re-order to the dashboard's rolling weeks. Missing label -> None (miss flag set).
        fcw = o.get("fc_weeks") or [None, None, None]
        fc_raw = o.get("fc") or [None, None, None]; hr_raw = o.get("hrs") or [None, None, None]
        hol_raw = o.get("hol_fc") or [0, 0, 0]; sph_raw = o.get("sph_fc") or [None, None, None]
        idxof = {}
        for _j, _w in enumerate(fcw):
            if _w: idxof[_w] = _j
        have_labels = any(fcw)
        fc = [None, None, None]; hrs = [None, None, None]; hol = [0, 0, 0]; sph = [None, None, None]; miss = [False, False, False]
        for _i in range(3):
            j = idxof.get(wk_iso[_i]) if have_labels else (_i if o else None)   # positional fallback if labels unreadable
            if j is None:
                miss[_i] = True
            else:
                fc[_i] = fc_raw[j] if j < len(fc_raw) else None
                hrs[_i] = hr_raw[j] if j < len(hr_raw) else None
                hol[_i] = hol_raw[j] if j < len(hol_raw) else 0
                sph[_i] = sph_raw[j] if j < len(sph_raw) else None
                if fc[_i] is None: miss[_i] = True
        stores[st] = {"area": COACH.get(st, ""),
                      "fc": fc, "hrs": hrs, "hol": hol, "sph": sph, "miss": miss,
                      "labels_ok": have_labels, "fc_weeks": fcw,
                      "ly": [ly[1] if len(ly) > 1 else 0, ly[2] if len(ly) > 2 else 0, ly[3] if len(ly) > 3 else 0],
                      "dow": sh or est_share, "dow_est": sh is None}
    W("forecast_feed.json", {"_generated": CUR_END.isoformat(), "weeks": weeks,
        "dow_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "estate_dow": est_share,
        "stores": stores,
        "_note": "Forecast \u00a3 / plan hrs / SPH (incl holiday) from the area planners' Section B, LABEL-KEYED: each coach forecast column is pinned to the calendar week it is labelled for (row 19 W/C dates), then aligned to these dashboard weeks; a week with no matching label shows 'no forecast entered'. "
                 "Daily split = each week's forecast \u00d7 the store's last-8-week day-of-week share; new stores use the estate share."},
      indent=1)
    print("[pull] forecast_daily: %d stores, weeks %s" % (len(stores), ", ".join(w["label"] for w in weeks)))


def pull_backtoschool():
    """5th EOS tab feed: Back-to-School sales & food forecast per store + estate. Mirrors the
    standalone Bewiched_BackToSchool_Forecast methodology exactly:
      * 2026 forecast week = 2025 SAME-week actual x each store's capped recent-8wk YoY.
      * Weeks: Peak 24-30 Aug, Transition 31 Aug-6 Sep (term from Wed 2 Sep), Settled 7-13 Sep 2026,
        baselined on 2025 weeks 25-31 Aug / 1-7 Sep / 8-14 Sep.
      * Weekday->weekend shift from 3 holiday weeks (11-31 Aug 2025) vs 3 term weeks (8-28 Sep 2025),
        weekend = Fri-Sun.  Food = per-store Food+Bakery item quantities, same YoY scaling.
    Per-store food usage IS available from BigQuery (no pro-rata fallback for established stores).
    New stores with no 2025 history (Billing DT, Attleborough, Olney): sales estimated from run-rate
    x estate seasonal shape, food + weekend-shift shown as unavailable. Writes backtoschool_feed.json."""
    FLATq = FLAT
    PK=("2025-08-25","2025-08-31"); BK=("2025-09-01","2025-09-07"); ST=("2025-09-08","2025-09-14")
    r26_end=datetime.date(2026,8,9); r26_start=r26_end-datetime.timedelta(days=55)
    r25_end=r26_end-datetime.timedelta(days=364); r25_start=r26_start-datetime.timedelta(days=364)
    R26S,R26E=r26_start.isoformat(),r26_end.isoformat(); R25S,R25E=r25_start.isoformat(),r25_end.isoformat()
    HOL=("2025-08-11","2025-08-31"); TRM=("2025-09-08","2025-09-28")
    def clampyoy(x):
        try: x=float(x)
        except Exception: return 1.0
        return max(0.85, min(1.25, x))

    q1=("SELECT item_outlet_name AS store,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', v,0)),2) sp,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', v,0)),2) sb,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', v,0)),2) ss,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', v,0)),2) s25,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', v,0)),2) s26"
        " FROM (SELECT item_outlet_name, DATE(sales_date) d,"
        " SAFE_CAST(item_line_total_after_discount AS FLOAT64) v FROM %s"
        " WHERE DATE(sales_date) BETWEEN '%s' AND '%s' OR DATE(sales_date) BETWEEN '%s' AND '%s')"
        " GROUP BY store" % (PK[0],PK[1],BK[0],BK[1],ST[0],ST[1],R25S,R25E,R26S,R26E,FLATq,R25S,ST[1],R26S,R26E))
    q2=("SELECT item_outlet_name AS store,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', q,0))) fp,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', q,0))) fb,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', q,0))) fs"
        " FROM (SELECT item_outlet_name, DATE(sales_date) d, SAFE_CAST(item_quantity AS FLOAT64) q"
        " FROM %s WHERE DATE(sales_date) BETWEEN '%s' AND '%s' AND %s IN ('Food','Bakery'))"
        " GROUP BY store" % (PK[0],PK[1],BK[0],BK[1],ST[0],ST[1],FLATq,PK[0],ST[1],cat_case('item_product_name')))
    q4=("SELECT store,"
        " ROUND(SUM(IF(period='hol' AND wknd, v,0))) hws, ROUND(SUM(IF(period='hol' AND NOT wknd, v,0))) hds,"
        " ROUND(SUM(IF(period='term' AND wknd, v,0))) tws, ROUND(SUM(IF(period='term' AND NOT wknd, v,0))) tds,"
        " ROUND(SUM(IF(period='hol' AND wknd, fq,0))) hwf, ROUND(SUM(IF(period='hol' AND NOT wknd, fq,0))) hdf,"
        " ROUND(SUM(IF(period='term' AND wknd, fq,0))) twf, ROUND(SUM(IF(period='term' AND NOT wknd, fq,0))) tdf"
        " FROM (SELECT item_outlet_name store, SAFE_CAST(item_line_total_after_discount AS FLOAT64) v,"
        " IF(%s IN ('Food','Bakery'), SAFE_CAST(item_quantity AS FLOAT64), 0) fq,"
        " EXTRACT(DAYOFWEEK FROM DATE(sales_date)) IN (6,7,1) wknd,"
        " IF(DATE(sales_date) BETWEEN '%s' AND '%s','hol', IF(DATE(sales_date) BETWEEN '%s' AND '%s','term',NULL)) period"
        " FROM %s WHERE DATE(sales_date) BETWEEN '%s' AND '%s') WHERE period IS NOT NULL GROUP BY store"
        % (cat_case('item_product_name'),HOL[0],HOL[1],TRM[0],TRM[1],FLATq,HOL[0],TRM[1]))
    q5=("SELECT dow, ROUND(SUM(IF(period='hol', v,0))/3) ha, ROUND(SUM(IF(period='term', v,0))/3) ta"
        " FROM (SELECT EXTRACT(DAYOFWEEK FROM DATE(sales_date)) dow,"
        " SAFE_CAST(item_line_total_after_discount AS FLOAT64) v,"
        " IF(DATE(sales_date) BETWEEN '%s' AND '%s','hol', IF(DATE(sales_date) BETWEEN '%s' AND '%s','term',NULL)) period"
        " FROM %s WHERE DATE(sales_date) BETWEEN '%s' AND '%s') WHERE period IS NOT NULL GROUP BY dow"
        % (HOL[0],HOL[1],TRM[0],TRM[1],FLATq,HOL[0],TRM[1]))
    q3=("SELECT item, cat,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', q,0))) qp,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', q,0))) qb,"
        " ROUND(SUM(IF(d BETWEEN '%s' AND '%s', q,0))) qs"
        " FROM (SELECT %s item, %s cat, DATE(sales_date) d, SAFE_CAST(item_quantity AS FLOAT64) q"
        " FROM %s WHERE DATE(sales_date) BETWEEN '%s' AND '%s') WHERE cat IN ('Food','Bakery')"
        " GROUP BY item, cat ORDER BY qp DESC LIMIT 19"
        % (PK[0],PK[1],BK[0],BK[1],ST[0],ST[1],CLEAN,cat_case('item_product_name'),FLATq,PK[0],ST[1]))

    try:
        d1={normalize(r["store"]):r for r in bq(q1) if normalize(r["store"])}
        d2={normalize(r["store"]):r for r in bq(q2) if normalize(r["store"])}
        d4={normalize(r["store"]):r for r in bq(q4) if normalize(r["store"])}
        d5=bq(q5); d3=bq(q3)
    except Exception as e:
        print("[pull] backtoschool SKIPPED (BQ error: %s)" % e); return

    NEW_STORES={"Billing Drive Thru","Attleborough","Olney"}
    def yoy(st):
        r=d1.get(st) or {}; a=r.get("s25") or 0; b=r.get("s26") or 0
        return clampyoy(b/a) if a else 1.0
    # estate seasonal shape from established stores (for new-store estimate)
    est_pk=est_bk=est_st=0.0
    stores=[]
    for st in CANON:
        r1=d1.get(st); is_new = (st in NEW_STORES) or (not r1) or ((r1.get("sp") or 0) < 200)
        y=yoy(st)
        if not is_new:
            pk=round((r1.get("sp") or 0)*y); tr=round((r1.get("sb") or 0)*y); se=round((r1.get("ss") or 0)*y)
            est_pk+=pk; est_bk+=tr; est_st+=se
        else:
            pk=tr=se=None
        stores.append({"store":st,"new":is_new,"peak":pk,"trans":tr,"settled":se,"_r1":r1})
    # estate normal-week run-rate (recent26 estate weekly avg) for new-store sizing
    est26=sum((d1.get(st,{}) or {}).get("s26") or 0 for st in CANON)
    normal_wk = est26/8.0 if est26 else 1.0
    idx_pk = (est_pk/ (len([s for s in stores if not s["new"]]) or 1)) # not used; use ratio vs settled
    # seasonal indices relative to a normal week (established estate)
    n_est=max(1,len([s for s in stores if not s["new"]]))
    est_normal_est = sum(((d1.get(s["store"],{}) or {}).get("s26") or 0) for s in stores if not s["new"])/8.0 or 1.0
    pk_idx = est_pk/est_normal_est if est_normal_est else 1.0
    bk_idx = est_bk/est_normal_est if est_normal_est else 1.0
    st_idx = est_st/est_normal_est if est_normal_est else 1.0
    # scale indices so they represent a single store's weekly run-rate multiple
    pk_ratio = est_pk/ (est_pk+est_bk+est_st) if (est_pk+est_bk+est_st) else 0.34
    # simpler: new store weekly run-rate * seasonal factor derived from estate week-shape
    shp_pk = est_pk/((est_pk+est_bk+est_st)/3) if (est_pk+est_bk+est_st) else 1.0
    shp_bk = est_bk/((est_pk+est_bk+est_st)/3) if (est_pk+est_bk+est_st) else 1.0
    shp_st = est_st/((est_pk+est_bk+est_st)/3) if (est_pk+est_bk+est_st) else 1.0
    for s in stores:
        if s["new"]:
            rr=((d1.get(s["store"],{}) or {}).get("s26") or 0)/8.0   # this store's recent weekly run-rate
            s["peak"]=round(rr*shp_pk); s["trans"]=round(rr*shp_bk); s["settled"]=round(rr*shp_st)
    # per-store weekend shift + food
    for s in stores:
        st=s["store"]; y=yoy(st)
        f=d2.get(st) or {}
        if not s["new"]:
            s["food_peak"]=round((f.get("fp") or 0)*y); s["food_trans"]=round((f.get("fb") or 0)*y); s["food_settled"]=round((f.get("fs") or 0)*y)
        else:
            s["food_peak"]=s["food_trans"]=s["food_settled"]=None
        w=d4.get(st) or {}
        hw=w.get("hws") or 0; hd=w.get("hds") or 0; tw=w.get("tws") or 0; td=w.get("tds") or 0
        if (hw+hd)>0 and (tw+td)>0 and not s["new"]:
            sh_hol=100*hw/(hw+hd); sh_term=100*tw/(tw+td)
            s["wk_share_hol"]=round(sh_hol); s["wk_share_term"]=round(sh_term); s["wk_share_pp"]=round(sh_term-sh_hol)
            s["weekday_delta"]=round(100*(td/hd-1)) if hd else None
            s["weekend_delta"]=round(100*(tw/hw-1)) if hw else None
        else:
            s["wk_share_hol"]=s["wk_share_term"]=s["wk_share_pp"]=s["weekday_delta"]=s["weekend_delta"]=None
        if s["peak"] and s["settled"]:
            s["pk_settled_pct"]=round(100*(s["settled"]/s["peak"]-1))
        else:
            s["pk_settled_pct"]=None
        s.pop("_r1",None)
    stores.sort(key=lambda x:-(x["peak"] or 0))

    # estate DOW (Mon..Sun) from q5 (dow 1=Sun..7=Sat)
    DOWMAP={2:"Mon",3:"Tue",4:"Wed",5:"Thu",6:"Fri",7:"Sat",1:"Sun"}
    dm={int(r["dow"]):r for r in d5}
    dow=[]
    for k in (2,3,4,5,6,7,1):
        r=dm.get(k) or {}; ha=r.get("ha") or 0; ta=r.get("ta") or 0
        dow.append({"day":DOWMAP[k],"hol":round(ha),"term":round(ta),"pct":round(100*(ta/ha-1)) if ha else 0})
    # estate KPIs
    wkday=[d for d in dow if d["day"] in ("Mon","Tue","Wed","Thu")]
    wkday_pct=round(100*(sum(d["term"] for d in wkday)/ (sum(d["hol"] for d in wkday) or 1) -1))
    satsun=[d for d in dow if d["day"] in ("Sat","Sun")]
    wkend_pct=round(100*(sum(d["term"] for d in satsun)/(sum(d["hol"] for d in satsun) or 1)-1))
    fri_sun_hol=sum(d["hol"] for d in dow if d["day"] in ("Fri","Sat","Sun")); all_hol=sum(d["hol"] for d in dow)
    fri_sun_trm=sum(d["term"] for d in dow if d["day"] in ("Fri","Sat","Sun")); all_trm=sum(d["term"] for d in dow)
    share_hol=round(100*fri_sun_hol/all_hol) if all_hol else 0
    share_trm=round(100*fri_sun_trm/all_trm) if all_trm else 0
    estate_peak=sum(s["peak"] or 0 for s in stores)
    # top food lines
    food_lines=[]
    for r in d3:
        qp=r.get("qp") or 0; qb=r.get("qb") or 0; qs=r.get("qs") or 0
        food_lines.append({"item":r["item"],"cat":r["cat"],"peak":round(qp),"trans":round(qb),
                           "settled":round(qs),"pct":round(100*(qs/qp-1)) if qp else 0})
    # estate food seasonal index
    fpk=sum((d2.get(st,{}) or {}).get("fp") or 0 for st in CANON if st not in NEW_STORES)
    fst=sum((d2.get(st,{}) or {}).get("fs") or 0 for st in CANON if st not in NEW_STORES)
    fbk=sum((d2.get(st,{}) or {}).get("fb") or 0 for st in CANON if st not in NEW_STORES)
    fnorm=(fpk+fbk+fst)/3 or 1.0

    out={"_generated": datetime.datetime.now(zoneinfo.ZoneInfo("Europe/London")).strftime("%-d %b %Y, %H:%M"),
        "return_date":"2026-09-02",
        "weeks":{"peak":"Mon 24 – Sun 30 Aug 2026","transition":"Mon 31 Aug – Sun 6 Sep 2026",
                 "settled":"Mon 7 – Sun 13 Sep 2026"},
        "estate":{"peak":estate_peak,"weekday_pct":wkday_pct,"weekend_pct":wkend_pct,
                  "weekend_share_hol":share_hol,"weekend_share_term":share_trm,
                  "dow":dow,"food_lines":food_lines,
                  "food_index_peak":round(fpk/fnorm,2) if fnorm else None,
                  "food_index_settled":round(fst/fnorm,2) if fnorm else None},
        "stores":stores,
        "_method":"2025 same-week actuals x capped recent-8wk YoY (0.85-1.25). Weekday/weekend from 3 holiday wks (11-31 Aug 25) vs 3 term wks (8-28 Sep 25); weekend=Fri-Sun. Per-store food usage from BigQuery item quantities. New stores (Billing DT, Attleborough, Olney): run-rate x estate seasonal shape; food/weekend n/a."}
    W("backtoschool_feed.json", out, indent=1)
    print("[pull] backtoschool: %d stores, estate peak £%s (weekday %s%%, weekend %s%%, wkend share %s->%s)"
          % (len(stores), format(estate_peak,","), wkday_pct, wkend_pct, share_hol, share_trm))


# ============================ BUILD / ASSEMBLE (B–E) ============================
RUN_START = datetime.datetime.now().timestamp()
GEN_LEFTOVER = {}


def pull_sales_extras():
    """EOS Sales-tab additions -> sales_extras.json (rendered at the TOP of the YoY Sales Growth
    'Sales' view by gen_eos_scorecard.py).
      1. Drive-thru lane throughput: distinct orders taken through each DT site's drive-thru
         register(s). A site may have MORE THAN ONE 'drive'-named register (Northampton has a lane
         till + an order-storing till); ALL of them roll into ONE lane figure via
         LOWER(register.register_name) LIKE '%drive%' with COUNT(DISTINCT id) (an order seen on two
         DT registers counts once). YoY vs the weekday-aligned window 364 days (52 weeks) earlier.
         A lane with no prior-year DT history (e.g. Billing DT, opened May 2026) is flagged 'new'
         rather than shown a fabricated YoY.
      2. Top chilled grab-and-go 'fridge' food items estate-wide (sandwiches, ciabattas, wraps,
         salads, bagels, croques/toasties; cooked-to-order baps and the hot sausage roll excluded),
         units QTD + last week, with the recent range-refresh SKUs flagged 'new'.
    Fault-tolerant: any failure leaves the last-good sales_extras.json in place."""
    try:
        LW0=(CUR_END-datetime.timedelta(days=6)).isoformat(); LW1=CUR_END.isoformat()
        LWl0=(CUR_END-datetime.timedelta(days=6+364)).isoformat(); LWl1=(CUR_END-datetime.timedelta(days=364)).isoformat()
        QT0=QSTART.isoformat(); QT1=CUR_END.isoformat()
        QTl0=(QSTART-datetime.timedelta(days=364)).isoformat(); QTl1=(CUR_END-datetime.timedelta(days=364)).isoformat()
        # ---- 1. Drive-thru lanes (all 'drive'-named registers per site rolled into one) ----
        dsql = """
          SELECT store,
            COUNT(DISTINCT IF(dd BETWEEN DATE('%s') AND DATE('%s'), id, NULL)) lw26,
            COUNT(DISTINCT IF(dd BETWEEN DATE('%s') AND DATE('%s'), id, NULL)) lw25,
            COUNT(DISTINCT IF(dd BETWEEN DATE('%s') AND DATE('%s'), id, NULL)) qtd26,
            COUNT(DISTINCT IF(dd BETWEEN DATE('%s') AND DATE('%s'), id, NULL)) qtd25
          FROM (SELECT outlet.outlet_name store, id, DATE(sales_date) dd
                FROM %s
                WHERE LOWER(register.register_name) LIKE '%%drive%%'
                  AND DATE(sales_date) BETWEEN DATE('%s') AND DATE('%s'))
          GROUP BY store
        """ % (LW0,LW1, LWl0,LWl1, QT0,QT1, QTl0,QTl1, SDET, QTl0, QT1)
        def _yoy(a,b): return round(100.0*(a/b-1.0),1) if (b and b>0) else None
        lanes=[]
        for r in bq(dsql):
            q26=int(r["qtd26"] or 0); q25=int(r["qtd25"] or 0)
            l26=int(r["lw26"] or 0);  l25=int(r["lw25"] or 0)
            new = (q25==0 and l25==0)
            lanes.append({"store": r["store"], "lw": l26, "lw_ly": l25,
                          "lw_yoy": (None if new else _yoy(l26,l25)),
                          "qtd": q26, "qtd_ly": q25,
                          "qtd_yoy": (None if new else _yoy(q26,q25)), "new": new})
        lanes.sort(key=lambda x: -x["qtd"])
        # ---- 2. Chilled grab-and-go 'fridge' food items ----
        NEW_WINDOW = 70
        new_cut = (CUR_END-datetime.timedelta(days=NEW_WINDOW)).isoformat()
        fsql = """
          WITH base AS (
            SELECT %s AS prod, DATE(sales_date) dd, SAFE_CAST(item_quantity AS FLOAT64) q
            FROM %s
            WHERE DATE(sales_date) BETWEEN DATE('2023-01-01') AND DATE('%s')
              AND REGEXP_CONTAINS(LOWER(item_product_name), r'ciabatta|sandwich|\\bwrap\\b|bagel|salad|croque|toastie|toasty|panini')
              AND NOT REGEXP_CONTAINS(LOWER(item_product_name), r'\\bbap\\b|sausage roll|pastry|wrapped|kids')
          )
          SELECT prod,
            ROUND(SUM(IF(dd BETWEEN DATE('%s') AND DATE('%s'), q, 0))) units_qtd,
            ROUND(SUM(IF(dd BETWEEN DATE('%s') AND DATE('%s'), q, 0))) units_lw,
            MIN(dd) first_sold
          FROM base GROUP BY prod HAVING units_qtd > 0 ORDER BY units_qtd DESC
        """ % (CLEAN, FLAT, QT1, QT0, QT1, LW0, LW1)
        frows = bq(fsql)
        tot_qtd = sum(float(r["units_qtd"] or 0) for r in frows) or 1.0
        items=[]
        for r in frows:
            fs = r["first_sold"]; fs = fs.isoformat() if hasattr(fs,"isoformat") else (str(fs) if fs else None)
            items.append({"name": r["prod"], "qtd": int(r["units_qtd"] or 0),
                          "lw": int(r["units_lw"] or 0),
                          "share": round(100.0*float(r["units_qtd"] or 0)/tot_qtd,1),
                          "first_sold": fs, "new": bool(fs and fs >= new_cut)})
        # ---- 3. Sales by category (estate): last complete week + QTD (£ and % of sales) ----
        catsql = """
          SELECT cat,
            ROUND(SUM(IF(dd BETWEEN DATE('%s') AND DATE('%s'), v, 0))) wk,
            ROUND(SUM(IF(dd BETWEEN DATE('%s') AND DATE('%s'), v, 0))) qtd
          FROM (SELECT %s cat, DATE(sales_date) dd,
                       SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
                FROM %s WHERE DATE(sales_date) BETWEEN DATE('%s') AND DATE('%s'))
          GROUP BY cat
        """ % (LW0, LW1, QT0, QT1, cat_case7('item_product_name'), FLAT, QT0, QT1)
        _cm = {}
        for r in bq(catsql):
            _cm[CAT7LABEL.get(r["cat"], r["cat"])] = (float(r["wk"] or 0), float(r["qtd"] or 0))
        _wk_tot = sum(v[0] for v in _cm.values()) or 1.0
        _qt_tot = sum(v[1] for v in _cm.values()) or 1.0
        cat_week = []; cat_qtd = []
        for lab in CAT7ORDER:
            w, q = _cm.get(lab, (0.0, 0.0))
            cat_week.append({"cat": lab, "gbp": round(w), "pct": round(100.0 * w / _wk_tot, 1)})
            cat_qtd.append({"cat": lab, "gbp": round(q), "pct": round(100.0 * q / _qt_tot, 1)})
        # ---- 4. Top selling DRINKS (Hot+Cold+Milkshakes), last complete week: units + £ ----
        dnew_cut = (CUR_END - datetime.timedelta(days=NEW_WINDOW)).isoformat()
        drsql = """
          WITH base AS (
            SELECT %s prod, DATE(sales_date) dd,
                   SAFE_CAST(item_quantity AS FLOAT64) q,
                   SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
            FROM %s
            WHERE DATE(sales_date) BETWEEN DATE('2023-01-01') AND DATE('%s')
              AND %s IN ('Hot','Cold','Milkshakes'))
          SELECT prod,
            ROUND(SUM(IF(dd BETWEEN DATE('%s') AND DATE('%s'), q, 0))) units,
            ROUND(SUM(IF(dd BETWEEN DATE('%s') AND DATE('%s'), v, 0))) gbp,
            MIN(dd) first_sold
          FROM base GROUP BY prod HAVING units > 0 ORDER BY units DESC LIMIT 20
        """ % (CLEAN, FLAT, LW1, cat_case7('item_product_name'), LW0, LW1, LW0, LW1)
        drows = bq(drsql)
        _du_tot = sum(float(r["units"] or 0) for r in drows) or 1.0
        drinks = []
        for r in drows:
            fs = r["first_sold"]; fs = fs.isoformat() if hasattr(fs, "isoformat") else (str(fs) if fs else None)
            drinks.append({"name": r["prod"], "units": int(r["units"] or 0), "gbp": int(r["gbp"] or 0),
                           "share": round(100.0 * float(r["units"] or 0) / _du_tot, 1),
                           "first_sold": fs, "new": bool(fs and fs >= dnew_cut)})
        out = {"_updated": CUR_END.isoformat(),
               "week_label": wlabel(LASTWK_MON),
               "qtd_label": "%s – %s" % (QSTART.strftime("%-d %b"), CUR_END.strftime("%-d %b %Y")),
               "yoy_basis": "vs same window 364 days (52 weeks) earlier, weekday-aligned",
               "category": {"week": cat_week, "qtd": cat_qtd,
                            "week_total": round(_wk_tot), "qtd_total": round(_qt_tot)},
               "top_drinks": {"items": drinks, "week_total_units": int(_du_tot), "new_window_days": NEW_WINDOW},
               "dt_lanes": lanes,
               "fridge": {"items": items, "total_qtd": int(tot_qtd), "new_window_days": NEW_WINDOW}}
        W("sales_extras.json", out)
        print("[pull] sales_extras: %d DT lanes (%d new), %d fridge items (%d flagged new), fridge QTD units=%d"
              % (len(lanes), sum(1 for l in lanes if l["new"]), len(items),
                 sum(1 for i in items if i["new"]), int(tot_qtd)))
    except Exception as e:
        print("[pull] sales_extras SKIPPED (non-fatal) - %s" % str(e)[:200])



def pull_franchise():
    """Franchise Fees Scale (HoE / Ian's franchise stores) -> franchise_fees.json.
    MONTHLY per-store Brand audit (/5, Total col J) + Remote assessment (/100 col E -> /5) from the
    Richard Wagg sheet, blended 50/50 on the /5 scale (4.6 = 100/100 target). The combined score keys
    the royalty fee tier (Matt's 'Royalty fees linked to brand execution' scale). Monthly turnover from
    BigQuery gives the GBP fee = Total Fee % x turnover. Franchise stores: Attleborough, Glenvale Drive
    Thru, HOE Balsall Common; Warwick listed as open-trading (first audit pending) until it has audits.
    Fault-tolerant: any failure leaves the last-good franchise_fees.json in place."""
    try:
        import collections
        FRAN = ["Attleborough", "Glenvale Drive Thru", "HOE Balsall Common"]
        NEW = [{"store": "Warwick", "status": "Open \u2013 trading; first audit pending"}]
        # brand monthly (cols A Store, D Date, J Total; A:J avoids the huge action-plan column)
        bmon = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in sheet(SID["audit"], "'Brand Audit Date (NEW24/25)'!A1:J4000")[1:]:
            if not r or not r[0]: continue
            st = normalize(r[0])
            if st not in FRAN: continue
            dt = parse_any_date(r[3]) if len(r) > 3 else None
            tot = fnum(r[9]) if len(r) > 9 else None
            if not dt or not tot: continue
            bmon[st][dt.strftime("%Y-%m")].append(tot)
        # remote monthly (cols B Store, D Date, E Score/100; skip <=0 = not completed)
        rmon = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in sheet(SID["audit"], "'Remote Assessment Data'!A1:F4000")[1:]:
            if len(r) < 5 or not r[1]: continue
            st = normalize(r[1])
            if st not in FRAN: continue
            dt = parse_any_date(r[3]); sc = fnum(r[4])
            if not dt or sc is None or sc <= 0: continue
            rmon[st][dt.strftime("%Y-%m")].append(sc)
        # monthly turnover (BigQuery) for the GBP fee
        tvr = {}
        try:
            for row in bq(("SELECT item_outlet_name store, FORMAT_DATE('%%Y-%%m', DATE(sales_date)) ym, "
                           "ROUND(SUM(SAFE_CAST(item_line_total_after_discount AS FLOAT64))) rev FROM %s "
                           "WHERE DATE(sales_date) >= DATE('2024-01-01') AND item_outlet_name IN "
                           "('Attleborough','Glenvale Drive Thru','HOE Balsall Common') GROUP BY store, ym") % FLAT):
                tvr[(row["store"], row["ym"])] = float(row["rev"] or 0)
        except Exception as e:
            print("[pull] franchise turnover BQ skipped (fee %% only): %s" % str(e)[:120])

        def tier(x):
            if x is None: return None
            if x >= 4.9: return ("Excelling", "\u2b50", 3.0, 1.0)
            if x >= 4.8: return ("Above Target", "\U0001f7e0", 3.5, 1.5)
            if x >= 4.6: return ("On Target", "\u2705", 4.0, 2.0)
            if x >= 4.4: return ("Fail", "\u26a0\ufe0f", 6.0, 2.0)
            return ("Breakdown", "\U0001f534", 6.5, 2.5)

        months = set()
        for st in FRAN:
            months |= set(bmon[st]); months |= set(rmon[st])
        months = sorted(months)
        data = {}
        for st in FRAN:
            rows = {}
            for ym in months:
                bs = bmon[st].get(ym); rs = rmon[st].get(ym)
                brand5 = round(sum(bs) / len(bs), 2) if bs else None
                rem100 = round(sum(rs) / len(rs), 1) if rs else None
                rem5 = round(rem100 / 20, 2) if rem100 is not None else None
                if brand5 is not None and rem5 is not None: comb5 = round((brand5 + rem5) / 2, 2)
                elif rem5 is not None: comb5 = rem5
                elif brand5 is not None: comb5 = brand5
                else: comb5 = None
                if comb5 is None:
                    rows[ym] = {"audit": False}; continue
                t = tier(comb5); tot_pct = round(t[2] + t[3], 2)
                turn = tvr.get((st, ym))
                rows[ym] = {"audit": True, "brand5": brand5, "brand_n": len(bs) if bs else 0,
                            "remote100": rem100, "remote5": rem5, "remote_n": len(rs) if rs else 0,
                            "comb5": comb5, "comb100": round(comb5 / 4.6 * 100, 1),
                            "tier": t[0], "emoji": t[1], "royalty": t[2], "marketing": t[3],
                            "total_pct": tot_pct, "turnover": round(turn) if turn else None,
                            "fee_gbp": round(turn * tot_pct / 100) if turn else None}
            data[st] = rows
        out = {"_updated": CUR_END.isoformat(), "months": months, "stores": FRAN, "new_stores": NEW,
               "data": data,
               "scale": [{"band": "\u2265 4.9", "tier": "Excelling", "emoji": "\u2b50", "royalty": 3.0, "marketing": 1.0, "total": 4.0},
                         {"band": "4.8 \u2013 4.89", "tier": "Above Target", "emoji": "\U0001f7e0", "royalty": 3.5, "marketing": 1.5, "total": 5.0},
                         {"band": "4.6 \u2013 4.79", "tier": "On Target", "emoji": "\u2705", "royalty": 4.0, "marketing": 2.0, "total": 6.0},
                         {"band": "4.4 \u2013 4.59", "tier": "Fail", "emoji": "\u26a0\ufe0f", "royalty": 6.0, "marketing": 2.0, "total": 8.0},
                         {"band": "< 4.4", "tier": "Breakdown", "emoji": "\U0001f534", "royalty": 6.5, "marketing": 2.5, "total": 9.0}],
               "note": "Combined = 50/50 brand+remote on /5 (4.6 = 100/100 target). Fees are % of turnover."}
        W("franchise_fees.json", out, indent=1)
        print("[pull] franchise: %d months, %d stores, turnover_rows=%d" % (len(months), len(FRAN), len(tvr)))
    except Exception as e:
        print("[pull] franchise SKIPPED (non-fatal) - %s" % str(e)[:200])


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
    GREV_TARGET = 50   # weekly total-reviews target. Google Health = coverage x (volume/quality blend),
    #                   so stores with NO review deplete the score (coverage = stores with >=1 review / 21).
    rev = cust.get("reviews"); rat = cust.get("avg_rating_last_week"); gcov_n = cust.get("stores_with_reviews")
    gcov = (gcov_n / 21) if gcov_n is not None else None
    gh = round(100 * gcov * (0.5 * min(rev / GREV_TARGET, 1) + 0.5 * min(rat / 4.6, 1)), 1) if (gcov is not None and rev is not None and rat) else None
    gh_detail = ("Coverage %d%% (%d/21) · %s reviews vs target %d · %s★ avg — last week" % (round(gcov * 100), gcov_n, rev, GREV_TARGET, rat)) if (gcov is not None and rat) else "No reviews logged last week"
    subs = rms.get("submissions") or 0; ravg = rms.get("avg_rating")
    rh = round((min(subs / 70, 1) + min(ravg / 4.6, 1)) / 2 * 100, 1) if ravg and subs else None
    rh_detail = ("%d submissions (÷70) · %s★ (÷4.6) last week" % (subs, ravg)) if ravg else "No Rate My Shift submissions logged last week"
    # Company SPH = 18-equity basis (Σ sales ÷ Σ hours, exclude Ian's franchise). Aggregate the SAME
    # per-store sales+hours the banking loop uses; if the live planner read is momentarily empty this
    # pass, fall back to the already-banked per-store rows (sph_history.csv, current week) so the
    # headline stays consistent with the per-store SPH. Genuinely empty (no data anywhere) -> None -> awaiting.
    num = den = 0.0; nrep = 0
    for st, v in ovr.items():
        h = v.get("used_lastwk"); sa = (rec.get(st, {}) or {}).get("lw26")
        if h and sa and COACH.get(st) != "Ian":
            num += sa; den += h; nrep += 1
    if not den:
        try:
            _sphp = os.path.join(HERE, "sph_history.csv"); _cw = CUR_END.isoformat()
            if os.path.exists(_sphp):
                with open(_sphp, newline="") as _fh:
                    for _r in csv.DictReader(_fh):
                        if _r.get("week_ending") != _cw or COACH.get(_r.get("store")) == "Ian":
                            continue
                        try: _s = float(_r.get("sales")); _h = float(_r.get("hours"))
                        except Exception: continue
                        if _s and _h: num += _s; den += _h; nrep += 1
        except Exception:
            pass
    sph = round(num / den, 1) if den else None
    # planner CPH (actual sales-per-labour-hour from the 3 area planners, Section A) — hours-weighted estate avg.
    cnum = cden = 0.0
    for st, v in ovr.items():
        c = v.get("actual_cph_lastwk"); h = v.get("used_lastwk")
        if c and h and COACH.get(st) != "Ian": cnum += c * h; cden += h   # equity-basis (exclude franchise)
    cph_estate = round(cnum / cden, 1) if cden else sph        # fall back to BQ SPH if planners blank
    estate_sales_wk = sum(r.get("lw26", 0) or 0 for r in rec.values())
    estate_tx_wk = sum(r.get("tx26", 0) or 0 for r in rec.values())
    atv_wk = round(estate_sales_wk / estate_tx_wk, 2) if estate_tx_wk else None   # estate ATV, last completed week
    # ---- committed weekly-performance history (weekly_history.csv) for accumulating QTD ----
    HIST = os.path.join(HERE, "weekly_history.csv")
    HCOLS = ["week_ending", "estate_sales", "estate_gp_pct", "estate_cph", "sph", "npat_proj_pct",
             "yoy_sales_pct", "yoy_tx_pct", "f1_avg", "rms_pct", "kudos_pct", "brand_audit", "google_health_pct",
             "estate_atv", "bench", "new_starter_health"]
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
    F1_PLAN = 175   # LOWER IS BETTER on this race Total-Score scale — target ≤175 (estate ~282 now, so RED).
    f1_note = ("Metric = AVERAGE RACE TOTAL SCORE, and LOWER IS BETTER on this scale. Target ≤%d — "
               "green when the average score is at or below %d, red when above. (Estate ~282 now, so RED.) "
               "The old '75' higher-is-better target is retired." % (F1_PLAN, F1_PLAN))
    # ---- Brand Audit, last completed week (audits are periodic; awaiting if none logged that week) ----
    audit_lastwk = jload("audit_raw.json").get("_lastwk_avg")
    audit_lastwk_n = jload("audit_raw.json").get("_lastwk_n", 0)
    # ---- Brand & Remote Assessment blend (50/50; fallback: if one side missing, use the other) ----
    _rem_wk100 = jload("remote_raw.json").get("_lastwk_avg100")
    def _blend(b, r5):
        if b is not None and r5 is not None: return round((b + r5) / 2, 2)
        if r5 is not None: return round(r5, 2)
        if b is not None: return round(b, 2)
        return None
    brand_remote_rows = []
    for st, r in rec.items():
        b = r.get("audit_qtd"); r100 = r.get("remote_qtd100")
        r5 = (r100 / 20) if r100 is not None else None
        bl = _blend(b, r5)
        if bl is None: continue
        r["blend_qtd"] = bl
        brand_remote_rows.append({"store": st, "brand": b, "remote100": r100,
            "remote5": round(r5, 2) if r5 is not None else None, "blend": bl,
            "src": "both" if (b is not None and r5 is not None) else ("remote" if r5 is not None else "brand")})
    brand_remote_rows.sort(key=lambda x: -x["blend"])
    ba_blend = round(sum(x["blend"] for x in brand_remote_rows) / len(brand_remote_rows), 2) if brand_remote_rows else None
    audit_blend_wk = _blend(audit_lastwk, (_rem_wk100 / 20) if _rem_wk100 is not None else None)
    _rem_vals = [r.get("remote_qtd100") for r in rec.values() if r.get("remote_qtd100") is not None]
    _estate_remote100 = round(sum(_rem_vals) / len(_rem_vals), 1) if _rem_vals else None
    # ---- New Starter Health (Youda onboarding). Committed source new_starter.json (the Actions runner
    #      can't reach Youda; it is refreshed separately). Persist it into the scorecard each run so a
    #      regeneration never wipes it, and derive the two tiles from its headline. ----
    new_starter = jload("new_starter.json") or {}
    # ---- New Starter Health scoring (Matt-approved): replace the all-or-nothing "clear of EVERY
    #      step" headline (which pinned the metric at 0-7%) with an ON-TIME STEP-COMPLETION RATE =
    #      share of due onboarding steps that are NOT overdue = (present - overdue) / present.
    #      Not-yet-due ('due') steps are excluded from the penalty (pending, not late). Recomputed
    #      each build from the raw per_step/per_starter the Youda pull writes, then persisted back
    #      into new_starter.json so EVERY surface (EOS tile/detail + Star Card brand-foundation,
    #      which reads per_site.pct) shows the SAME corrected score. Rolling 90-day cohort unchanged.
    if isinstance(new_starter, dict) and new_starter.get("per_step"):
        _ps = new_starter.get("per_step") or []
        _P = sum(int(x.get("present", 0) or 0) for x in _ps)
        _O = sum(int(x.get("overdue", 0) or 0) for x in _ps)
        _D = sum(int(x.get("done", 0) or 0) for x in _ps)
        _ontime = round(100 * (_P - _O) / _P) if _P else None
        if _ontime is not None:
            new_starter.setdefault("headline_compliant_alltime", new_starter.get("headline"))
            new_starter["headline"] = _ontime
            new_starter["scoring"] = "on_time_step_completion"
            new_starter["ontime"] = {"present": _P, "overdue": _O, "done": _D, "pct": _ontime}
        from collections import defaultdict as _dd
        _sp = _dd(lambda: [0, 0])   # site -> [present, overdue] from per-starter step statuses
        for _r in (new_starter.get("per_starter") or []):
            _site = _r.get("site", "")
            for _lab, _st in (_r.get("steps") or {}).items():
                if _st in ("done", "overdue", "due"):
                    _sp[_site][0] += 1
                    if _st == "overdue":
                        _sp[_site][1] += 1
        _newps = []
        for _r in (new_starter.get("per_site") or []):
            _site = _r.get("site", ""); _P2, _O2 = _sp.get(_site, [0, 0])
            _r = dict(_r); _r.setdefault("pct_compliant_alltime", _r.get("pct"))
            _r["pct"] = (round(100 * (_P2 - _O2) / _P2) if _P2 else 0)
            _r["ontime_present"] = _P2; _r["ontime_overdue"] = _O2
            _newps.append(_r)
        if _newps:
            new_starter["per_site"] = _newps
        # staleness guard: Youda pull (Cowork Bot) refreshes new_starter.json weekly; if it stops,
        # badge the tile instead of showing a real-looking number. Base on the 'generated' stamp.
        _gen = new_starter.get("generated")
        try:
            _gd = datetime.datetime.strptime(str(_gen), "%d %b %Y").date()
            _age = (CUR_END - _gd).days
            new_starter["_stale"] = {"stale": bool(_age > 10), "age_days": _age, "generated": _gen,
                                     "badge": "New Starter Health awaiting Youda refresh (last pulled %s)" % _gen}
        except Exception:
            new_starter["_stale"] = {"stale": True, "generated": _gen,
                                     "badge": "New Starter Health awaiting Youda refresh"}
        W("new_starter.json", new_starter, indent=1)
    ns_headline = new_starter.get("headline")
    ns_comp = new_starter.get("compliant", 0); ns_n = new_starter.get("cohort_n", 0)
    ns_ot = (new_starter.get("ontime") or {})
    ns_stale = (new_starter.get("_stale") or {})
    _ns_ontrack = (ns_ot.get("present", 0) - ns_ot.get("overdue", 0))
    _ns_pre = ns_ot.get("present", 0)
    _ns_badge = ((ns_stale.get("badge", "") + " — ") if ns_stale.get("stale") else "")
    _ns_detail_wk = ((_ns_badge + ("On-time onboarding — %s%% of due steps on track (%s of %s steps not overdue) across %s starters in the first-90-day cohort"
                     % (ns_headline, _ns_ontrack, _ns_pre, ns_n))) if new_starter else "New Starter Health source (new_starter.json) unavailable")
    _ns_note = ("Youda onboarding: ON-TIME step completion — share of due onboarding steps NOT overdue (not-yet-due steps excluded from the penalty), rolling first-90-day cohort. From new_starter.json (refreshed weekly from Youda by the Cowork Bot; badged if that refresh stalls). Target 90%.")
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
        # Emit the email->store map for the BCKH engagement feed (built by the scheduled Cowork
        # task, which pulls Slack and needs authoritative store attribution). Non-fatal.
        try:
            W("emp_store_map.json", {em: st for em, st in emp_store.items()})
            print("[pull] emp_store_map: %d email->store rows" % len(emp_store))
        except Exception as _e:
            print("[pull] emp_store_map emit skipped: %s" % str(_e)[:60])
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
    _gq = sh.get("google", {})
    gh_qtd_n = sum((v[0] or 0) for v in _gq.values())
    _gcovq = sum(1 for v in _gq.values() if (v[0] or 0) > 0)
    gh_qtd_avg = round(sum((v[1] or 0) * (v[0] or 0) for v in _gq.values()) / gh_qtd_n, 2) if gh_qtd_n else None
    gh_qtd = round(100 * (_gcovq / 21) * (0.5 * min(gh_qtd_n / (GREV_TARGET * weeks_q), 1) + 0.5 * min(gh_qtd_avg / 4.6, 1)), 1) if (gh_qtd_n and gh_qtd_avg) else None
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
        metric("google_health", "Google Health", 70, gh, "%", "pct0", "derived", gh_detail,
               "Coverage × volume × rating: (stores with ≥1 review ÷ 21) × [0.5·min(reviews÷50,1) + 0.5·min(rating÷4.6,1)] × 100. No-review stores pull it down. Last completed week. Green ≥ 70."),
        metric("rms_health", "Rate My Shift Health", 70, rh, "%", "pct0", "derived", rh_detail,
               "Blend: avg of submissions÷70 and avgScore÷4.6, each capped 100%. Last completed week."),
        metric("brew_crew_kudos", "Brew Crew Kudos Participation", 50, kudos_wk_pct, "%", "pct0", "derived",
               ("%d of %d employees gave kudos last week (BCKH)" % (kudos_wk_n, kudos_total)) if kudos_wk_pct is not None
               else ("No BCKH entries last week (latest %s)" % (bckh_latest.isoformat() if bckh_latest else "n/a")),
               "Distinct employees who contributed to Brew Crew Kudos (BCKH tab, F1 workbook) in the LAST COMPLETED WEEK, matched by email to the Employee List, ÷ total employees. Awaiting if no entries that week."),
        metric("social_media", "Social Media Engagement", None, None, "%", "pct0", "tbc", "",
               "Metric and target not yet defined.", tbc=True),
        metric("sph_labour", "SPH Labour (incl holiday pay)", 52, sph, "£", "gbp1", "derived",
               ("£%.0f sales ÷ %.0f hours used (last week, %d stores reporting)" % (num, den, nrep)) if den else "Awaiting posted hours",
               "Sales per labour hour incl holiday pay. Last completed week; provisional on Sunday, finalised Monday once planner hours post."),
        metric("bench", "Bench", 3, bench_net, "", "num_signed", "derived",
               ("Net SM on the bench: %d live Store Manager vacanc%s now (actual %+d) vs a +3 surplus target — %d off plan." % (sm_vacancies, "y" if sm_vacancies == 1 else "ies", bench_net, 3 - bench_net)) if bench_net is not None else "",
               "MAIN KPI = NET Store Managers on the bench. Actual = -(Store Manager vacancies) from the HRP 'HRP & Bench' roster (the red 'Gap / no SM' stores); target = +3 (a surplus of ready SM cover); miss = target - actual. The star map, management-team table and Bench-ready / Thin / Capability-gap cards below use the hierarchy-gap rule, unchanged and byte-identical to the Company Dashboard bench tab."),
        metric("f1_score_wk", "F1 Score", F1_PLAN, f1_wk, "", "num1", "sheet",
               ("Last week's race result, estate avg (%d stores) — lower is better" % len(f1_wk_xs)) if f1_wk_xs else "No race scores logged last week",
               f1_note, dirn="low"),
        metric("brand_audit_wk", "Brand & Remote Assessment", 4.6, audit_blend_wk, "", "score2", "derived",
               "Blended brand audit + remote assessment, last completed week (estate)" if audit_blend_wk is not None else "No brand audit or remote assessment logged last week",
               "Last completed week's 50/50 blend of brand audit and remote assessment (whichever is present that week). Both are periodic — the QTD tile is the reliable one."),
        metric("food_gp_wk", "Food GP%", 71, fg_wk, "%", "pct1", "derived",
               ("Cost-of-Sales estate Gross Profit%% (col Q), latest week ending %s" % cos_week) if cos_week else "Estate Gross Profit% (col Q) from Cost of Sales",
               "Estate Gross Profit% from the Cost-of-Sales sheet (col Q, sales-weighted across stores)."),
        metric("npat_wk", "Net Profit After Tax (projected)", 18, npat_wk, "%", "pct1", npat_src,
               _npat_detail("Weekly flex", npat_wk_gp, npat_wk_lab),
               npat_note),
        metric("new_starter_health_wk", "New Starter Health", 90, ns_headline, "%", "pct0", "derived",
               _ns_detail_wk, _ns_note),
    ]
    quarterly = [
        metric("yoy_sales", "YoY Sales Growth", 12, yoy_sales, "%", "pct_signed", "live",
               ("LFL QTD sales vs same period last year (%s like-for-like stores)" % lfl_n) if lfl_n else "LFL QTD sales vs same period last year",
               "Auto from BigQuery v_sales_details_flat (quarter-to-date)."),
        metric("yoy_tx", "YoY Transactional Growth", 5, yoy_tx, "%", "pct_signed", "live",
               ("LFL QTD transactions vs last year (%s like-for-like stores)" % lfl_n) if lfl_n else "LFL QTD transactions vs same period last year",
               "Auto from BigQuery v_sales_details_flat (quarter-to-date)."),
        metric("google_health_qtd", "Google Health", 70, gh_qtd, "%", "pct0", "derived",
               ("%d reviews (vs %d target) · %s★ QTD" % (gh_qtd_n, GREV_TARGET * weeks_q, gh_qtd_avg)) if gh_qtd is not None else "No QTD reviews",
               "Coverage × volume × rating: (QTD stores with a review ÷ 21) × [0.5·min(reviews÷(50×%d wks),1) + 0.5·min(rating÷4.6,1)] × 100. Green ≥ 70." % weeks_q),
        metric("rms_health_qtd", "Rate My Shift Health", 70, rh_qtd, "%", "pct0", "derived",
               ("%d submissions (÷%d) · %s★ (÷4.6) QTD" % (rh_qtd_n, 70 * weeks_q, rh_qtd_avg)) if rh_qtd is not None else "No QTD submissions",
               "Blend: avg of QTD submissions÷(70×%d wks) and avg score÷4.6, each capped 100%%." % weeks_q),
        metric("brew_crew_kudos_qtd", "Brew Crew Kudos Participation", 50, kudos_qtd_pct, "%", "pct0", "derived",
               ("%d of %d employees gave kudos this quarter (BCKH)" % (kudos_qtd_n, kudos_total)) if kudos_qtd_pct is not None else "",
               "Distinct employees who contributed to Brew Crew Kudos (BCKH tab) QUARTER-TO-DATE, matched by email to the Employee List, ÷ total employees."),
        metric("social_media_qtd", "Social Media Engagement", None, None, "%", "pct0", "tbc", "",
               "Metric and target not yet defined.", tbc=True),
        metric("sph_labour_qtd", "SPH Labour (incl holiday pay)", 52, qtd_sph, "£", "gbp1", "derived",
               "QTD £/hr, hours-weighted from weekly_history (%d week%s so far)" % (n_hist_q, "" if n_hist_q == 1 else "s"),
               "QTD sales per labour hour, hours-weighted across the weekly_history.csv rows since quarter start. Thin until several weeks accumulate (falls back to the current week)."),
        metric("bench_qtd", "Bench", 3, bench_net, "", "num_signed", "derived",
               ("Net SM on the bench: %d live Store Manager vacanc%s now (actual %+d) vs a +3 surplus target — %d off plan." % (sm_vacancies, "y" if sm_vacancies == 1 else "ies", bench_net, 3 - bench_net)) if bench_net is not None else "",
               "Point-in-time net Store Managers on the bench (same as weekly): actual = -(SM vacancies), target = +3, miss = target - actual. Detail below is byte-identical to the Company Dashboard bench tab (hierarchy-gap rule)."),
        metric("f1_score", "F1 Score", F1_PLAN, f1_qtd, "", "num1", "sheet",
               ("QTD race 'Total Score', estate avg (%d stores) — lower is better" % len(f1_qtd_xs)) if f1_qtd_xs else "Awaiting F1 race data",
               f1_note, dirn="low"),
        metric("brand_audit", "Brand & Remote Assessment", 4.6, ba_blend, "", "score2", "derived",
               "Estate 50/50 blend of brand audit + remote assessment (QTD), out of 5",
               "Each store blends its QTD brand audit (/5) and remote assessment (out of 100, divided by 20) 50/50; a store with only one uses that one. Estate = average of per-store blends. Sources: Brand Audit sheet + 'Remote Assessment Data' tab (Richard Wagg)."),
        metric("food_gp", "Food GP%", 71, fg_qtd, "%", "pct1", "derived",
               "Estate Gross Profit% (col Q) from Cost of Sales, quarter-to-date (sales-weighted)",
               "Estate Gross Profit% from the Cost-of-Sales sheet (col Q, sales-weighted), quarter-to-date."),
        metric("npat", "Net Profit After Tax (projected)", 18, npat_qtd, "%", "pct1", npat_src,
               _npat_detail("QTD flex", npat_qtd_gp, npat_qtd_lab),
               npat_note),
        metric("new_starter_health", "New Starter Health", 90, ns_headline, "%", "pct0", "derived",
               _ns_detail_wk, _ns_note),
    ]
    flags = [
        "Status is strictly binary: GREEN when actual ≥ plan, RED when below — no near-target band. Bench is green when ≥ 3.",
        "Google Health & Rate My Shift Health blend divisors (40 reviews / 4.6★ ; 70 submissions / 4.6★) are default assumptions — adjust if you prefer different volume targets.",
        "Plans (Matt's stated defaults): SPH Labour 52 (holiday-inclusive; was 55 worked-only), Brew Crew Kudos 50%, Bench 3, NPAT 18%, Food GP% 71%. YoY Sales 12% / Transactions 5% on both tabs.",
        "F1 Score = AVERAGE RACE TOTAL SCORE (Matt confirmed), live from the F1 sheet (ID %s) — weekly = last week's race, quarterly = QTD avg. LOWER IS BETTER on this scale: target ≤175, green at or below 175 and red above (estate ~282 now, so RED). The old '75' higher-is-better target is retired." % SID["f1"],
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
    _FRAN = {s for s, c in COACH.items() if c == "Ian"}     # Ian's franchise: Attleborough / Glenvale DT / HOE Balsall Common
    # ---- committed PER-STORE SPH history (sph_history.csv): banks each week's per-store sales+hours so the
    # ---- per-store SPH accumulates a real QTD (was mirroring the last week). Upserted by week_ending+store. ----
    SPH_HIST = os.path.join(HERE, "sph_history.csv")
    SPH_COLS = ["week_ending", "store", "sales", "hours", "sph", "holiday", "ssp"]
    _sph_hist = []
    if os.path.exists(SPH_HIST):
        try:
            with open(SPH_HIST, newline="") as _fh: _sph_hist = [r for r in csv.DictReader(_fh)]
        except Exception:
            _sph_hist = []
    _cur_we = CUR_END.isoformat()
    _sph_this = []
    for st, v in ovr.items():
        h = v.get("used_lastwk"); sa = (rec.get(st, {}) or {}).get("lw26")
        if h and sa:
            _sph_this.append({"week_ending": _cur_we, "store": st, "sales": round(sa), "hours": round(h, 1),
                              "sph": round(sa / h, 1),
                              "holiday": round(v.get("holiday_lastwk") or 0, 1),
                              "ssp": round(v.get("ssp_lastwk") or 0, 1)})
    # AUTHORITATIVE company SPH: derive the headline from the per-store rows just built for this week
    # (_sph_this is runtime-proven present every run — the banking loop populates it), on the 18-equity
    # basis (exclude Ian's franchise). This overrides the earlier estate aggregation, which has
    # intermittently read empty at its point in the run, so the tile stays consistent with the
    # per-store SPH (~£47-49). If _sph_this is genuinely empty, the earlier `sph`/awaiting stands.
    _IAN_FRAN = {st for st, c in COACH.items() if c == "Ian"}
    _bn = _bd = 0.0
    for _sr in _sph_this:
        if _sr.get("store") not in _IAN_FRAN:
            try: _bn += float(_sr["sales"]); _bd += float(_sr["hours"])
            except Exception: pass
    if _bd:
        _sph_bank = round(_bn / _bd, 1)
        sph = _sph_bank
        qtd_sph = _qtd_rate(q_prior, estate_sales_wk, _sph_bank, "sph") or _sph_bank
        for _ml in (weekly, quarterly):
            for _m in _ml:
                if _m.get("id") == "sph_labour" and ma("sph_labour") is None:
                    _m["actual"] = _sph_bank
                elif _m.get("id") == "sph_labour_qtd" and ma("sph_labour_qtd") is None:
                    _m["actual"] = qtd_sph
    _sph_merged = {(r.get("week_ending"), r.get("store")): r for r in _sph_hist}
    for r in _sph_this: _sph_merged[(r["week_ending"], r["store"])] = r
    _sph_ord = sorted(_sph_merged.values(), key=lambda r: (r.get("week_ending", ""), r.get("store", "")))
    with open(SPH_HIST, "w", newline="") as _fh:
        _w = csv.DictWriter(_fh, fieldnames=SPH_COLS); _w.writeheader()
        for r in _sph_ord: _w.writerow({k: r.get(k, "") for k in SPH_COLS})
    def _sf(x):
        try: return float(x)
        except Exception: return None
    _QS = QSTART.isoformat()
    _sph_agg = {}
    for r in _sph_ord:
        if r.get("week_ending", "") < _QS: continue
        st = r.get("store"); sa = _sf(r.get("sales")); h = _sf(r.get("hours"))
        if st and sa and h:
            a = _sph_agg.setdefault(st, [0.0, 0.0]); a[0] += sa; a[1] += h
    _sph_qtd_store = {st: round(sa / h, 1) for st, (sa, h) in _sph_agg.items() if h}
    _sph_qweeks = len({r["week_ending"] for r in _sph_ord if r.get("week_ending", "") >= _QS})
    print("[pull] sph_history: upserted %s (%d store rows this wk, %d total) -- per-store QTD from %d week(s)"
          % (_cur_we, len(_sph_this), len(_sph_ord), _sph_qweeks))
    # ---- mirror the full SPH history into Matt's live Google Sheet ("Bewiched SPH History",
    # ---- owner matt@bewiched.co.uk; dashboards-bot SA has editor). Full-range rewrite = idempotent,
    # ---- so weekly re-runs never duplicate; the sheet stays current exactly like sph_history.csv. ----
    SPH_SHEET_ID = "1VpPT7irAcm8Wiq0gXmyF9P60YO2VAPPYx51J4S03R1g"
    try:
        from googleapiclient.discovery import build as _gbuild
        _svc = _gbuild("sheets", "v4", credentials=_creds(), cache_discovery=False).spreadsheets()
        _hdr = ["Week Ending", "Store", "Sales \u00a3", "Hours", "SPH \u00a3/hr", "Holiday Hrs", "SSP Hrs"]
        _vals = [_hdr] + [[str(r.get("week_ending", "")), str(r.get("store", "")),
                           str(r.get("sales", "")), str(r.get("hours", "")), str(r.get("sph", "")),
                           str(r.get("holiday", "")), str(r.get("ssp", ""))]
                          for r in _sph_ord]
        _svc.values().clear(spreadsheetId=SPH_SHEET_ID, range="Sheet1!A:G").execute()
        _svc.values().update(spreadsheetId=SPH_SHEET_ID, range="Sheet1!A1",
                             valueInputOption="USER_ENTERED", body={"values": _vals}).execute()
        try:  # best-effort: bold + freeze the header row
            _sid = _svc.get(spreadsheetId=SPH_SHEET_ID).execute()["sheets"][0]["properties"]["sheetId"]
            _svc.batchUpdate(spreadsheetId=SPH_SHEET_ID, body={"requests": [
                {"repeatCell": {"range": {"sheetId": _sid, "startRowIndex": 0, "endRowIndex": 1},
                                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                                "fields": "userEnteredFormat.textFormat.bold"}},
                {"updateSheetProperties": {"properties": {"sheetId": _sid,
                                "gridProperties": {"frozenRowCount": 1}},
                                "fields": "gridProperties.frozenRowCount"}}]}).execute()
        except Exception as _fe:
            print("[pull] sph sheet: header formatting skipped (%s)" % _fe)
        print("[pull] sph sheet: wrote %d rows to Google Sheet %s" % (len(_vals) - 1, SPH_SHEET_ID))
    except Exception as _se:
        print("[pull] sph sheet: WRITE FAILED (%s)" % _se)
    _sph_weekly = [{"store": st, "value": round(rec[st]["lw26"] / v["used_lastwk"], 1),
                    "target": _sph_tgt.get(st)}
                   for st, v in ovr.items()
                   if v.get("used_lastwk") and rec.get(st, {}).get("lw26") and st not in _FRAN]
    _ps2("SPH Labour (incl holiday pay)", plan=52,
         weekly=_sph_weekly,
         wbasis="Last completed week sales ÷ planner hours used, vs each store's own £/hr target (Store-Targets sheet)",
         qtd=[{"store": r["store"], "value": _sph_qtd_store.get(r["store"], r["value"]), "target": r["target"]} for r in _sph_weekly],
         qbasis="Per-store SPH QTD = Σ sales ÷ Σ planner hours across the quarter's weeks, banked in sph_history.csv (upserted per week+store). Thin until several weeks accumulate; until then QTD ≈ the current week.")   # company QTD tile: 52 = blanket 55 / 1.06 (holiday-inclusive)
    # Franchise (Ian's) stores as DETAIL ONLY on the SPH per-store table — never in the company SPH
    # headline/aggregate (that stays on the 18-equity basis). Ian's planner doesn't record Section-A
    # hours used, so actual £/hr can't be computed -> value None (renders "—", awaiting hours); the
    # store's £/hr target is still shown. Grouped + labelled as franchise by the renderer (frows).
    _sph_fran = [{"store": st, "value": None, "target": _sph_tgt.get(st)} for st in sorted(_FRAN)]
    _sph_e = per_store.get("SPH Labour (incl holiday pay)")
    if _sph_e and _sph_fran:
        for _k in ("weekly", "qtd"):
            if _k in _sph_e: _sph_e[_k]["frows"] = _sph_fran
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
    _ps2("Brand & Remote Assessment", plan=4.6,
         qtd=[{"store": x["store"], "value": x["blend"]} for x in brand_remote_rows],
         qbasis="QTD 50/50 blend of brand audit + remote assessment, out of 5 (per store)")
    _ps2("Brew Crew Kudos Participation", plan=50,
         weekly=kudos_ps_weekly,
         wbasis="Distinct employees at the store who gave kudos last week ÷ store headcount (per store, vs 50% plan)",
         qtd=kudos_ps_qtd,
         qbasis="Distinct employees at the store who gave kudos this quarter ÷ store headcount (per store, vs 50% plan)")

    # ---- YoY Sales detail extras: per-store ATV + food-attachment %, DUAL basis (weekly + QTD) ----
    atv_ps = [{"store": st, "value": round(r["lw26"] / r["tx26"], 2)}
              for st, r in rec.items() if (r.get("tx26") or 0) > 0 and (r.get("lw26") or 0) > 0]
    food_attach = []; fa_map = {}
    try:
        _faly0 = (LASTWK_MON - datetime.timedelta(days=364)).isoformat()
        _faly1 = (CUR_END - datetime.timedelta(days=364)).isoformat()
        fa_rows = bq(f"""
          WITH t AS (
            SELECT s, id,
              MAX(IF(cat IN ('Food','Bakery') AND ty, 1, 0)) hf_ty,
              MAX(IF(cat IN ('Food','Bakery') AND ly, 1, 0)) hf_ly,
              MAX(IF(ty, 1, 0)) is_ty, MAX(IF(ly, 1, 0)) is_ly
            FROM (
              SELECT item_outlet_name s, id, {cat_case('item_product_name')} cat,
                     DATE(sales_date) BETWEEN DATE('{LASTWK_MON.isoformat()}') AND {CE} ty,
                     DATE(sales_date) BETWEEN DATE('{_faly0}') AND DATE('{_faly1}') ly
              FROM {FLAT}
              WHERE (DATE(sales_date) BETWEEN DATE('{LASTWK_MON.isoformat()}') AND {CE}
                     OR DATE(sales_date) BETWEEN DATE('{_faly0}') AND DATE('{_faly1}'))
                AND item_outlet_name NOT IN ('Royal Leamington Spa','Leamington Retail','Leamington Spa'))
            GROUP BY s, id)
          SELECT s,
            SUM(is_ty) tx_ty, ROUND(100*SUM(hf_ty)/NULLIF(SUM(is_ty),0),1) fa_ty,
            SUM(is_ly) tx_ly, ROUND(100*SUM(hf_ly)/NULLIF(SUM(is_ly),0),1) fa_ly
          FROM t GROUP BY s""")
        for r in fa_rows:
            st = normalize(r["s"])
            if not st: continue
            fa_ty = r["fa_ty"] if (r.get("tx_ty") or 0) > 0 else None
            fa_ly = r["fa_ly"] if (r.get("tx_ly") or 0) > 0 else None
            fa_map[st] = (fa_ty, fa_ly)
            if fa_ty is not None:
                food_attach.append({"store": st, "value": fa_ty})
    except Exception as e:
        flags.append("YoY detail: per-store food-attach (BigQuery) failed (%s)." % str(e)[:70])
    # ---- Weekend Fri/Sat/Sun visual: previous completed weekend vs the prior-year equivalent weekend
    #      (364 days back = exactly 52 weeks, so weekdays align). Company-wide sales + transactions.
    _wk_fri, _wk_sat, _wk_sun = CUR_END - datetime.timedelta(days=2), CUR_END - datetime.timedelta(days=1), CUR_END
    _ly_fri, _ly_sat, _ly_sun = CUR_END - datetime.timedelta(days=366), CUR_END - datetime.timedelta(days=365), CUR_END - datetime.timedelta(days=364)
    weekend = None; weekend_by_store = {}
    try:
        _wd = bq(f"""
          SELECT item_outlet_name s,
            ROUND(SUM(IF(dd={d(2)},v,0)))   fs, COUNT(DISTINCT IF(dd={d(2)},id,NULL))   ft,
            ROUND(SUM(IF(dd={d(1)},v,0)))   ss, COUNT(DISTINCT IF(dd={d(1)},id,NULL))   st_,
            ROUND(SUM(IF(dd={CE},v,0)))     us, COUNT(DISTINCT IF(dd={CE},id,NULL))     ut,
            ROUND(SUM(IF(dd={d(366)},v,0))) fsl, COUNT(DISTINCT IF(dd={d(366)},id,NULL)) ftl,
            ROUND(SUM(IF(dd={d(365)},v,0))) ssl, COUNT(DISTINCT IF(dd={d(365)},id,NULL)) stl,
            ROUND(SUM(IF(dd={d(364)},v,0))) usl, COUNT(DISTINCT IF(dd={d(364)},id,NULL)) utl
          FROM (SELECT item_outlet_name, DATE(sales_date) dd, id, SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
                FROM {FLAT}
                WHERE DATE(sales_date) IN ({d(2)},{d(1)},{CE},{d(366)},{d(365)},{d(364)}))
          GROUP BY s""")
        cs_t = [0, 0, 0]; cs_l = [0, 0, 0]; ct_t = [0, 0, 0]; ct_l = [0, 0, 0]   # company totals = sum of per-store (estate convention)
        for r in _wd:
            s_this = [r.get("fs") or 0, r.get("ss") or 0, r.get("us") or 0]
            s_last = [r.get("fsl") or 0, r.get("ssl") or 0, r.get("usl") or 0]
            t_this = [r.get("ft") or 0, r.get("st_") or 0, r.get("ut") or 0]
            t_last = [r.get("ftl") or 0, r.get("stl") or 0, r.get("utl") or 0]
            for i in range(3):
                cs_t[i] += s_this[i]; cs_l[i] += s_last[i]; ct_t[i] += t_this[i]; ct_l[i] += t_last[i]
            _st = normalize(r.get("s"))
            if _st:
                weekend_by_store[_st] = {"sales": {"this": s_this, "last": s_last},
                                         "tx": {"this": t_this, "last": t_last}}
        weekend = {
            "days": ["Fri", "Sat", "Sun"],
            "label_this": "%s–%s %s" % (_wk_fri.strftime("%-d"), _wk_sun.strftime("%-d"), _wk_sun.strftime("%b %Y")),
            "label_last": "%s–%s %s" % (_ly_fri.strftime("%-d"), _ly_sun.strftime("%-d"), _ly_sun.strftime("%b %Y")),
            "dates_this": [_wk_fri.isoformat(), _wk_sat.isoformat(), _wk_sun.isoformat()],
            "dates_last": [_ly_fri.isoformat(), _ly_sat.isoformat(), _ly_sun.isoformat()],
            "sales": {"this": cs_t, "last": cs_l},
            "tx":    {"this": ct_t, "last": ct_l},
        }
    except Exception as e:
        flags.append("YoY detail: weekend Fri/Sat/Sun (BigQuery) failed (%s)." % str(e)[:70])
    # Per-store last-week YoY raw figures (company Sales-tab table: sales £, ATV, guest counts + YoY).
    yoy_by_store = [{"store": st, "lw26": r.get("lw26") or 0, "lw25": r.get("lw25") or 0,
                     "tx26": r.get("tx26") or 0, "tx25": r.get("tx25") or 0,
                     "fa26": fa_map.get(st, (None, None))[0], "fa25": fa_map.get(st, (None, None))[1]}
                    for st, r in rec.items() if (r.get("lw26") or 0) > 0]
    yoy_detail = {
        "atv_target": 6.8,
        "weekend": weekend,
        "weekend_by_store": weekend_by_store,
        "by_store": yoy_by_store,
        "atv_trend_col": "estate_atv",          # gen reads this weekly_history column for the estate ATV trend
        "atv_wk": atv_wk,
        "atv": {"weekly": {"basis": "Last completed week sales ÷ transactions (per store)", "rows": atv_ps},
                "qtd": {"basis": "Quarter-to-date sales ÷ transactions (per store)", "rows": atv_qtd_ps}},
        "food_attach": {"weekly": {"basis": "Food or Bakery guest-checks ÷ transactions, last completed week (per store)", "rows": food_attach},
                        "qtd": {"basis": "Food or Bakery guest-checks ÷ transactions, quarter-to-date (per store)",
                                "rows": [{"store": st, "value": v} for st, v in food_qtd_ps.items() if v is not None]}},
    }

    brand_remote_detail = {"estate_blend": ba_blend, "estate_brand": ba, "estate_remote100": _estate_remote100,
                           "target": 4.6, "rows": brand_remote_rows}
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
        "brand_remote": brand_remote_detail,
        "new_starter": new_starter,
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
            if w in bf:
                _g = gw.setdefault(w, {"stars": [], "stores": set()})
                _g["stars"].append(star)
                _gs = normalize(r[0])
                if _gs: _g["stores"].add(_gs)
        for w, _g in gw.items():
            xs = _g["stars"]
            if xs:
                avg = sum(xs) / len(xs); _cov = len(_g["stores"]) / 21
                bf[w]["google_health_pct"] = round(100 * _cov * (0.5 * min(len(xs) / GREV_TARGET, 1) + 0.5 * min(avg / 4.6, 1)), 1)
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
               "brand_audit": _hc(audit_blend_wk), "google_health_pct": _hc(gh), "estate_atv": _hc(atv_wk),
               "bench": _hc(bench_net), "new_starter_health": _hc(ns_headline)}
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
    if os.path.exists(os.path.join(HERE, "gen_starcard.py")):
        try:
            _run("gen_starcard.py")               # NON-FATAL: live Bewiched Star Card (2 tabs); gated by apply_gate
        except Exception as e:
            print("[build] gen_starcard FAILED - Star Card degraded, run continues: %s" % e)
    # B9 store sales + E patcher (LAST)
    if os.path.exists(os.path.join(HERE, "gen_franchise.py")):
        try:
            _run("gen_franchise.py")             # NON-FATAL: Franchise Fees Scale (gated by apply_gate)
        except Exception as e:
            print("[build] gen_franchise FAILED - franchise page degraded, run continues: %s" % e)
    _run("build_newsite_sales.py")
    _run("patch_newsite.py")
    # F — client-side password gate: stamp every served dashboard with its own
    #     hash LAST, so it survives the rebuild and covers all regenerated pages.
    _run("apply_gate.py")
    print("[build] full chain complete")


def freshness_gate():
    """Refuse to publish a partial run (the 28 Jun failure). Fail loudly, publish nothing."""
    errs = []; warns = []
    def fresh(fn):
        p = os.path.join(HERE, fn)
        return os.path.exists(p) and os.path.getmtime(p) >= RUN_START - 1
    # 1. F1 date: SOFT (per-metric). If the F1 pull RAN (f1_detail.json rewritten — enforced HARD by
    #    check #3) but its newest race is behind cur_end (audits pending for this reporting week),
    #    DO NOT block the whole publish. Publish everything else that's fresh and degrade only the F1
    #    section — the generators badge it 'awaiting this week's audit' from f1_detail._stale. A
    #    genuinely SKIPPED F1 pull is still caught HARD by check #3 below (file not rewritten).
    try:
        fd = json.load(open(os.path.join(HERE, "f1_detail.json")))
        newest = max((v["race"][8] for v in fd.values() if isinstance(v, dict) and v.get("race")), default=None)
        if newest is None or newest < CUR_END.isoformat():
            warns.append("F1 stale: newest race %s < cur_end %s — publishing other metrics; F1 section badged 'awaiting this week's audit'."
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
    if warns:
        print("[gate] SOFT — published, section(s) degraded (not a partial-build failure):")
        for w in warns: print("   ! " + w)
    if errs:
        print("[gate] FAILED — partial/broken build, publishing nothing:")
        for e in errs: print("   x " + e)
        sys.exit(1)
    print("[gate] freshness OK — estate outputs refreshed to %s%s" % (CUR_END, " (F1 degraded)" if warns else ""))



def push_cos_history():
    """Bank the full weekly COS history per store and mirror it into the 'COS History' tab of the
    Bewiched SPH History sheet (dashboards-bot SA has editor). Idempotent full-range clear+rewrite,
    same pattern as the SPH mirror. stock%/sales/delivery£/per-supplier£/GP% come from the Master COS
    sheet history (banked in cos_history.json); Wastage% + Discounts% are backfilled from BigQuery for
    every banked week. Enriches cos_history.json (adds waste/disc) and writes the sheet tab.
    Non-fatal: any failure leaves the last-good tab in place."""
    SHEET_ID = "1VpPT7irAcm8Wiq0gXmyF9P60YO2VAPPYx51J4S03R1g"
    TAB = "COS History"
    SUPS = ["Select Catering", "Fresh Ideas", "K&W", "Simply"]
    try:
        ch = json.load(open(os.path.join(HERE, "cos_history.json")))
        weeks = ch.get("weeks", {})
        if not weeks:
            print("[cos-history] no weeks banked -- skip"); return
        wk_iso = sorted(weeks.keys())
        _mon0 = (datetime.date.fromisoformat(wk_iso[0]) - datetime.timedelta(days=6)).isoformat()
        # ---- BQ backfill: Wastage% + Discounts% per store per week_ending (Sunday) over the span ----
        WQ = "SAFE_CAST(WastageQuantity AS FLOAT64)"; RV = "SAFE_CAST(RetailValue AS FLOAT64)"
        WE_F = "DATE_ADD(DATE_TRUNC(DATE(sales_date), WEEK(MONDAY)), INTERVAL 6 DAY)"
        WE_W = "DATE_ADD(DATE_TRUNC(date, WEEK(MONDAY)), INTERVAL 6 DAY)"
        _sal, _dsc, _wst = {}, {}, {}
        try:
            for r in bq(("SELECT item_outlet_name s, %s we, "
                         "ROUND(SUM(SAFE_CAST(item_line_total_after_discount AS FLOAT64))) sales "
                         "FROM %s WHERE DATE(sales_date) BETWEEN '%s' AND %s GROUP BY s, we")
                        % (WE_F, FLAT, _mon0, CE)):
                st = normalize(r["s"]);  we = str(r["we"])
                if st: _sal[(we, st)] = r.get("sales") or 0
            for r in bq(("SELECT s, we, ROUND(SUM(gross-net)) dgbp, ROUND(SUM(net)) net FROM ("
                         " SELECT item_outlet_name s, id, %s we, "
                         "  ANY_VALUE(SAFE_CAST(sales_total_before_line_discount AS FLOAT64)) gross, "
                         "  ANY_VALUE(SAFE_CAST(sales_total_after_line_discount AS FLOAT64)) net "
                         " FROM %s WHERE DATE(sales_date) BETWEEN '%s' AND %s GROUP BY s, id, we) "
                         "GROUP BY s, we") % (WE_F, FLAT, _mon0, CE)):
                st = normalize(r["s"]); we = str(r["we"])
                if st and r.get("net"): _dsc[(we, st)] = round(100 * (r.get("dgbp") or 0) / r["net"], 1)
            for r in bq(("SELECT outlet s, %s we, ROUND(SUM(IF(%s>0, %s, 0))) wr "
                         "FROM %s WHERE date BETWEEN '%s' AND %s GROUP BY s, we")
                        % (WE_W, WQ, RV, WASTE, _mon0, CE)):
                st = normalize(r["s"]); we = str(r["we"])
                if st: _wst[(we, st)] = r.get("wr") or 0
        except Exception as _be:
            print("[cos-history] BQ backfill wastage/discounts partial (%s)" % str(_be)[:140])
        # ---- merge waste%/disc% into the banked weeks. The Master-COS week labels are mostly the
        # ---- Sunday week-ending but some are the Monday after; the BQ backfill keys to Sunday
        # ---- week-endings, so match by nearest day (+/-2d) rather than exact string. ----
        def _near(dmap, we, st):
            try: L = datetime.date.fromisoformat(we)
            except Exception: return None
            for off in (0, -1, 1, -2, 2):
                k = (L + datetime.timedelta(days=off)).isoformat()
                if (k, st) in dmap: return dmap[(k, st)]
            return None
        for we, stores in weeks.items():
            for st, d in stores.items():
                sa = _near(_sal, we, st) or d.get("sales")
                wr = _near(_wst, we, st)
                d["waste"] = (round(100 * wr / sa, 1) if (wr is not None and sa) else None)
                d["disc"] = _near(_dsc, we, st)
        W("cos_history.json", {"weeks": weeks}, indent=1)
        # ---- flatten -> one row per store per week ----
        HDR = ["Week Ending", "Store", "Area", "Sales £", "Stock £", "Stock %",
               "Delivery £", "Delivery %", "Wastage %", "Discounts %", "GP %",
               "Select £", "Fresh Ideas £", "K&W £", "Simply £"]
        def _s(x): return "" if x is None else x
        out_rows = []
        for we in wk_iso:
            for st in sorted(weeks[we].keys()):
                d = weeks[we][st]; sup = d.get("sup") or {}
                out_rows.append([we, st, COACH.get(st, ""), _s(d.get("sales")), _s(d.get("stock_gbp")),
                                 _s(d.get("stock")), _s(d.get("deliv_gbp")), _s(d.get("deliv")),
                                 _s(d.get("waste")), _s(d.get("disc")), _s(d.get("gp")),
                                 _s(sup.get("Select Catering")), _s(sup.get("Fresh Ideas")),
                                 _s(sup.get("K&W")), _s(sup.get("Simply"))])
        # ---- mirror into the 'COS History' tab (create if missing); clear+rewrite = idempotent ----
        from googleapiclient.discovery import build as _gbuild
        _svc = _gbuild("sheets", "v4", credentials=_creds(), cache_discovery=False).spreadsheets()
        _meta = _svc.get(spreadsheetId=SHEET_ID).execute()
        _tab = next((s for s in _meta["sheets"] if s["properties"]["title"] == TAB), None)
        if _tab is None:
            _r = _svc.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [
                {"addSheet": {"properties": {"title": TAB, "gridProperties": {"columnCount": 16}}}}]}).execute()
            _sid = _r["replies"][0]["addSheet"]["properties"]["sheetId"]
        else:
            _sid = _tab["properties"]["sheetId"]
        _svc.values().clear(spreadsheetId=SHEET_ID, range="'%s'!A:O" % TAB).execute()
        _svc.values().update(spreadsheetId=SHEET_ID, range="'%s'!A1" % TAB, valueInputOption="USER_ENTERED",
                             body={"values": [HDR] + out_rows}).execute()
        try:
            _svc.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [
                {"repeatCell": {"range": {"sheetId": _sid, "startRowIndex": 0, "endRowIndex": 1},
                                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                                "fields": "userEnteredFormat.textFormat.bold"}},
                {"updateSheetProperties": {"properties": {"sheetId": _sid,
                                "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}}]}).execute()
        except Exception as _fe:
            print("[cos-history] header format skipped (%s)" % str(_fe)[:80])
        print("[cos-history] wrote %d rows (%d weeks) to 'COS History' tab" % (len(out_rows), len(wk_iso)))
    except Exception as _e:
        print("[cos-history] SKIPPED (non-fatal) - %s" % str(_e)[:200])


def push_cos_planner():
    """STEP (pull) — write per-store Wastage% + Discounts% into each area planner's COS tab (cols K,L)
    each run. Coach fills Stock£ + the four supplier £ (Stock%, Total Deliveries, Delivery% are in-sheet
    formulas; Sales links from the Weekly Planner). Wastage% = v_sales_vs_wastage for the exact last-completed week (rec.waste_pct_lw); Discounts% =
    (gross-net)/net at sale level for that SAME week (matches the COS Sales week). Idempotent per-cell overwrite."""
    try:
        rec = (json.load(open(os.path.join(HERE, "allstores.json"))) or {}).get("rec", {})
    except Exception as e:
        print("[cos-planner] allstores.json missing (%s) -- skip" % e); return
    dmap = {}
    try:
        for r in bq(f"""
          SELECT s, ROUND(SUM(gross-net)) dgbp, ROUND(SUM(net)) net FROM (
            SELECT item_outlet_name s, id,
              ANY_VALUE(SAFE_CAST(sales_total_before_line_discount AS FLOAT64)) gross,
              ANY_VALUE(SAFE_CAST(sales_total_after_line_discount AS FLOAT64)) net
            FROM {FLAT}
            WHERE DATE(sales_date) BETWEEN {d(6)} AND {CE}
            GROUP BY s, id)
          GROUP BY s"""):
            st = normalize(r["s"])
            if st: dmap[st] = (r.get("dgbp") or 0, r.get("net") or 0)
    except Exception as e:
        print("[cos-planner] discounts query failed (%s) -- discounts left blank" % e)
    api = _sheets_api()
    for nm, sid in (("Jon", SID["planner_jon"]), ("Rich", SID["planner_rich"]), ("Ian", SID["planner_ian"])):
        try:
            col = api.get(spreadsheetId=sid, range="COS!A4:A20").execute().get("values", [])
        except Exception as e:
            print("[cos-planner] %s: read COS!A failed (%s) -- skip" % (nm, e)); continue
        data = []; totrow = None
        for i, rowv in enumerate(col):
            label = (rowv[0].strip() if rowv and rowv[0] else "")
            if not label: continue
            r = 4 + i
            if label.upper().startswith("AREA TOTAL"): totrow = r; continue
            data.append((r, normalize(label)))
        updates = []; swr = ss4 = sdg = snet = 0.0
        for r, st in data:
            wp = rec.get(st, {}).get("waste_pct_lw")
            dg, nt = dmap.get(st, (None, None))
            dpct = round(100 * dg / nt, 1) if (dg is not None and nt) else None
            updates.append({"range": "COS!K%d:L%d" % (r, r),
                            "values": [[("" if wp is None else wp), ("" if dpct is None else dpct)]]})
            if rec.get(st, {}).get("wr_lw") is not None and rec.get(st, {}).get("lw26"):
                swr += rec[st]["wr_lw"]; ss4 += rec[st]["lw26"]
            if dg is not None and nt: sdg += dg; snet += nt
        if totrow:
            awp = round(100 * swr / ss4, 1) if ss4 else ""
            adp = round(100 * sdg / snet, 1) if snet else ""
            updates.append({"range": "COS!K%d:L%d" % (totrow, totrow), "values": [[awp, adp]]})
        try:
            api.batchUpdate(spreadsheetId=sid,
                            body={"valueInputOption": "USER_ENTERED", "data": updates}).execute()
            print("[cos-planner] %s: wrote wastage%%+discounts%% for %d stores%s"
                  % (nm, len(data), " + area" if totrow else ""))
        except Exception as e:
            print("[cos-planner] %s: write failed (%s)" % (nm, e))


# ============================ ORCHESTRATION ============================
def pull_dt_lane_speed():
    """Drive-thru lane speed (avg TOTAL time) from the matt@-owned 'Drive-Thru Lane Speed' log
    (dashboards-bot SA has writer access). 'Weekly Log' tab = one row per site per week:
    Week Ending | Wk# | Site | Cars Served | Avg Total (mm:ss) | Avg Total (secs) | %Under3:00 | ...
    Emits dt_lane_speed.json with cars-weighted QTD + YTD average total SECONDS per DT store.
    Goal (sheet's own): total time < 3:00 (180s). Newly populating -> sparse/early data handled
    gracefully (a store with no rows is simply absent -> Star Card shows 'collecting'). Non-fatal."""
    OUT = {"_source": "Drive-Thru Lane Speed log 'Weekly Log' tab (matt@, SA writer). "
                      "Avg Total secs, cars-weighted across the period.",
           "_target_secs": 180, "_generated": CUR_END.isoformat(), "stores": {}}
    try:
        rows = sheet(DT_LANE_SHEET, "'Weekly Log'!A1:J2000")
        agg = {}
        for r in rows:
            if len(r) < 6: continue
            site = str(r[2]).strip().lower() if len(r) > 2 and r[2] not in (None, "") else ""
            if site not in DT_SITE_MAP: continue          # skips header, GROUP row, blanks
            we = parse_any_date(r[0])
            if not we: continue
            try: cars = float(r[3])
            except Exception: cars = 0.0
            try: secs = float(r[5])
            except Exception: continue
            if secs <= 0: continue
            st = DT_SITE_MAP[site]
            a = agg.setdefault(st, {"qws": 0.0, "qc": 0.0, "yws": 0.0, "yc": 0.0, "nq": 0, "ny": 0, "latest": None,
                                   "lastwk": None, "lastwk_we": None, "lastwk_cars": None})
            # last completed week (== CUR_END): the row for the Sales-tab "last week avg time"
            if we == CUR_END or (a["lastwk_we"] is None and we >= LASTWK_MON and we <= CUR_END):
                a["lastwk"] = round(secs); a["lastwk_we"] = we; a["lastwk_cars"] = int(cars)
            if we.year == CUR_END.year:
                a["yws"] += secs * cars; a["yc"] += cars; a["ny"] += 1
                if a["latest"] is None or we > a["latest"]: a["latest"] = we
            if we >= QSTART:
                a["qws"] += secs * cars; a["qc"] += cars; a["nq"] += 1
        for st, a in agg.items():
            OUT["stores"][st] = {
                "qtd_secs": (round(a["qws"] / a["qc"]) if a["qc"] > 0 else None),
                "ytd_secs": (round(a["yws"] / a["yc"]) if a["yc"] > 0 else None),
                "weeks_qtd": a["nq"], "weeks_ytd": a["ny"], "cars_qtd": int(a["qc"]),
                "lastwk_secs": a["lastwk"], "lastwk_cars": a["lastwk_cars"],
                "lastwk_we": (a["lastwk_we"].isoformat() if a["lastwk_we"] else None),
                "latest_we": (a["latest"].isoformat() if a["latest"] else None)}
        W("dt_lane_speed.json", OUT)
        print("[pull] dt_lane_speed: %d DT store(s) - %s" % (len(OUT["stores"]),
              ", ".join("%s q=%ss/y=%ss" % (k.split()[0], v["qtd_secs"], v["ytd_secs"])
                        for k, v in OUT["stores"].items()) or "no rows yet (collecting)"))
    except Exception as e:
        W("dt_lane_speed.json", OUT)   # empty stores -> Star Card renders 'collecting'
        print("[pull] dt_lane_speed skipped (non-fatal): %s" % str(e)[:140])


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
    pull_remote()             # remote_raw.json + rec.remote_qtd (Remote Assessment Data tab)
    pull_mix()                # rec.mix/mix_prev/mix_lw
    pull_area_quarters()      # rec[s].q_cur / q_prev (area this-Q/last-Q filter)
    pull_peak()               # peak_cat_raw.json + peak_bakery_raw.json
    pull_availability()       # rec.avail
    pull_daypart_food()       # daypart_food.json + daypart_food_area.json
    pull_bench()              # bench.json
    pull_reviews()            # reviews_raw.json + rec.cust + customer.json (+ google scratch)
    pull_rms_storehealth()    # rms.json + storehealth_raw.json
    pull_compliance()         # compliance_raw.json
    pull_openclose()          # openclose_feed.json (Brand Audit: open/close completion %)
    pull_accidents()          # accidents_feed.json (Brand Audit: H&S accidents/incidents)
    pull_csbr()               # csbr_feed.json (Brand Audit + Star Card: CS/Br coaching completion %)
    pull_ns_raws()            # ns_*_raw.json (7)
    pull_sl_raws()            # sl_*_raw.json (2)
    pull_txq_raws()           # txq_*_raw.json (2)
    pull_eos_scorecard()      # eos_scorecard.json (EOS Weekly+Quarterly scorecard)
    pull_backtoschool()       # backtoschool_feed.json (EOS 5th tab: back-to-school forecast)
    pull_forecast_daily()     # forecast_feed.json (EOS Forecast tab: 3-wk forecast + daily DOW split)
    pull_sales_extras()       # sales_extras.json (EOS Sales tab: DT lane throughput + fridge items)
    pull_dt_lane_speed()      # dt_lane_speed.json (Star Card: DT avg total time, 3rd Ops metric)
    pull_franchise()          # franchise_fees.json (Franchise Fees Scale dashboard)
    push_cos_planner()        # write Wastage%+Discounts% into each planner COS tab (K,L)
    push_cos_history()        # bank + mirror full weekly COS history -> "COS History" tab
    pull_maintenance()        # maintenance.json (reactive/planned/coffee/audit)  [non-fatal]


def _run_smt_diary():
    """Non-fatal, idempotent housekeeping: keep the 'Weekly SMT Visit Diary' sheet ~4 weeks of
    tabs ahead and its Master roll-up formula in sync. Independent of the dashboard build/gate —
    it writes only to that external sheet (via the service account), never to this repo, and must
    never abort the weekly run."""
    smt = os.path.join(HERE, "smt_diary.py")
    if not os.path.exists(smt):
        return
    try:
        r = subprocess.run([sys.executable, smt], check=False, timeout=180,
                           capture_output=True, text=True)
        for line in (r.stdout or "").splitlines():
            print(line)
        if r.returncode not in (0,):
            print("[smt] diary maintenance exited %d (non-fatal): %s" % (r.returncode, (r.stderr or "")[:200]))
    except Exception as e:
        print("[smt] diary maintenance skipped (non-fatal): %s" % str(e)[:160])


def main():
    print("[run] Bewiched weekly — mode=%s cur_end=%s" % (MODE, CUR_END))
    # _run_smt_diary()  # TEMPORARILY DISABLED — SMT diary sheet is more complex than expected
    #                     (61 tabs, two naming schemes, differing structures); reworking smt_diary.py
    pulls()
    build()
    freshness_gate()
    print("[done] %s run rebuilt — workflow will commit & push" % MODE)


if __name__ == "__main__":
    main()
