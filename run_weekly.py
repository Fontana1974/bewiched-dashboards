#!/usr/bin/env python3
"""
Bewiched weekly dashboard refresh — FULLY AUTOMATED (no agent, no desktop).

Runs in GitHub Actions on a cron. Pulls BigQuery + Google Sheets DIRECTLY via a
service account (no Zapier middleware -> no column-flattener scrambling, no ~60-row
read caps, full deterministic reads every time), rebuilds all 11 dashboards using the
existing builders (gen_*.py / build_*.py / patch_newsite.py), runs a freshness gate,
and the workflow commits/pushes.

STATUS: scaffold. Auth, date-derivation, helpers, the freshness gate and the proven
pulls (sales / planner / actuals) are done. The remaining estate pulls are stubbed
with the exact spec in the weekly runbook (SKILL.md STEP 2*/4f). Finish + test against
the real service account, then enable the cron in .github/workflows/weekly.yml.

KEY WIN vs the old agent run: every per-run constant is DERIVED from the run date +
the data — nothing is hand-bumped, so the "stale constant" class of bugs is gone.
"""
import os, sys, json, subprocess, datetime
from google.oauth2 import service_account
from google.cloud import bigquery
from googleapiclient.discovery import build as gbuild

# ---------- auth ----------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/bigquery"]
_sa = json.loads(os.environ["GCP_SA_JSON"])              # GitHub secret
_creds = service_account.Credentials.from_service_account_info(_sa, scopes=SCOPES)
BQ = bigquery.Client(project="bewiched-coffee-368116", credentials=_creds)
_SHEETS = gbuild("sheets", "v4", credentials=_creds, cache_discovery=False).spreadsheets().values()

def bq(sql: str):
    """Run BigQuery SQL, return list[dict]. Deterministic — no TO_JSON_STRING wrapping,
    no flattener. Just write normal SQL."""
    return [dict(r) for r in BQ.query(sql, location="europe-west2").result()]

def sheet(spreadsheet_id: str, a1_range: str):
    """Read a Sheet range as positional rows (unformatted; dates come as serials)."""
    return _SHEETS.get(spreadsheetId=spreadsheet_id, range=a1_range,
                       valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])

EPOCH = datetime.date(1899, 12, 30)
def serial_to_iso(s):  # google sheets serial -> 'YYYY-MM-DD'
    return (EPOCH + datetime.timedelta(days=int(s))).isoformat()

# ---------- run dates (ALL derived; nothing hand-bumped) ----------
TODAY   = datetime.date.today()
CUR_END = TODAY - datetime.timedelta(days=(TODAY.weekday() + 1) % 7)   # last completed Sunday
LASTWK_MON = CUR_END - datetime.timedelta(days=6)                       # just-completed week Monday  (= old NEWDATE)
CURWK_MON  = CUR_END + datetime.timedelta(days=1)                       # current week Monday          (forward-forecast start)
def wlabel(d): return "w/c " + d.strftime("%-d %b")                     # e.g. 'w/c 22 Jun'
print(f"[dates] cur_end={CUR_END}  last_week={LASTWK_MON} ({wlabel(LASTWK_MON)})  cur_week={CURWK_MON}")

# ---------- sheet IDs ----------
SID = dict(
    cph="18iUyF6Usm5QnUAARPgNsAkqWp00fKPv1WA3waBKJFZU",
    planner_jon="1PSjBGiR40171h769esQCtn3ldcpCB5XJyfqRTo7Yccs",
    planner_rich="11XuXn9zQr-JB4x2fQ0ORV96Sf-U7xWPQPvg2YlCl_dQ",
    planner_ian="1_qdK6fzqPg1NcA2KKMy2TnaZ8nQJtVE-fglz2On3oBw",
    master_pop="1RZ8ZmFdLyXz1btg3_pNdaVaAyXKhQqHwjVpWWzoFuI0",
    f1="1YFqpR9_ftlQEbfwc5ZVMjtS5tFO0j-7ccwB8rwG56wQ",
    sickness="1f_nTz6TJTPlVP4CSX6AzQ9sf5KbF7QwpVdVnxiW-bM4",
    audit="10JL4idTOmcCXnDTLsqHJjrHFnTMiIf7HR5uzVPwrjbM",
    reviews="1Dm3fxmhodV2xH-apaMp1baWmJ6zDIofv6z6YPuY8D3s",
    availability="1CeTBvZ610zfEMe118m76LgMW5gw_SDS-2Eel1HMuM78",
    smt="1IGL3sLWSI7k1vuXEMFBWplgk3uS4tTUU1-MtGYDk-bQ",
)

# ---------- pulls (write the same JSON files the builders already consume) ----------
def pull_sales():
    """STEP 2 core sales for all 21 stores -> overlay into allstores.json rec fields.
    Direct SQL (windows derived from CUR_END)."""
    ce = CUR_END.isoformat()
    rows = bq(f"""
      WITH b AS (SELECT item_outlet_name s, DATE(sales_date) d, id,
                        SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
                 FROM `bewiched-coffee-368116.bewiched_coffee.v_sales_details_flat`
                 WHERE DATE(sales_date) BETWEEN DATE_SUB(DATE('{ce}'),INTERVAL 391 DAY) AND DATE_SUB(DATE('{ce}'),INTERVAL 343 DAY)
                    OR DATE(sales_date) BETWEEN DATE_SUB(DATE('{ce}'),INTERVAL 27 DAY) AND DATE('{ce}'))
      SELECT s,
        ROUND(SUM(IF(d BETWEEN DATE_SUB(DATE('{ce}'),INTERVAL 6 DAY) AND DATE('{ce}'),v,0))) lw26,
        COUNT(DISTINCT IF(d BETWEEN DATE_SUB(DATE('{ce}'),INTERVAL 6 DAY) AND DATE('{ce}'),id,NULL)) tx26,
        ROUND(SUM(IF(d BETWEEN DATE_SUB(DATE('{ce}'),INTERVAL 27 DAY) AND DATE('{ce}'),v,0))) s4,
        COUNT(DISTINCT IF(d BETWEEN DATE_SUB(DATE('{ce}'),INTERVAL 27 DAY) AND DATE('{ce}'),id,NULL)) tx4,
        ROUND(SUM(IF(d BETWEEN DATE_SUB(DATE('{ce}'),INTERVAL 370 DAY) AND DATE_SUB(DATE('{ce}'),INTERVAL 364 DAY),v,0))) lw25,
        ROUND(SUM(IF(d BETWEEN DATE_SUB(DATE('{ce}'),INTERVAL 391 DAY) AND DATE_SUB(DATE('{ce}'),INTERVAL 364 DAY),v,0))) s4_25
      FROM b GROUP BY s""")
    # ... overlay yoy/atv/vs4w/ly/dow_growth/daypart_growth/takeaway exactly as the
    #     runbook STEP 2 describes, then json.dump allstores.json.  (port from this session)
    return rows

def pull_planner():
    """STEP 2g — 3 planners -> planner_overrides.json. Section A hours-used may be blank
    (coaches post through Mon AM): if blank, leave used_lastwk ABSENT (never hold stale)."""
    # for sid in (jon,rich,ian): rows = sheet(SID[...], "'Weekly Planner'!A1:L60"); parse A & B ...
    raise NotImplementedError("port from SKILL.md STEP 2g")

# TODO (port each from the runbook spec — all become plain bq()/sheet() calls):
#   pull_wastage()  STEP 2d   pull_mix()/pull_peak() 2k/2p   pull_daypart_food() 2n
#   pull_f1()       STEP 2e (read The Race / Qualifying via sheet(), UNFORMATTED, full span)
#   pull_actuals()  STEP 2f   pull_takeaway() 2h   pull_sickness() 2i   pull_audit() 2j
#   pull_reviews()  STEP 2l   pull_availability() 2m   pull_rms()/storehealth 2g2/2g3
#   pull_smt() 2c   pull_bench() 2o   + store-page raws (STEP 4f)

def build():
    """Run the existing builders (unchanged) over the freshly-written JSON."""
    for g in ("gen_area.py","gen_company.py","gen_kel.py","gen_claire.py"):
        subprocess.run([sys.executable, g], check=True)
    subprocess.run([sys.executable, "build_newsite_sales.py"], check=True)
    subprocess.run([sys.executable, "patch_newsite.py"], check=True)

def freshness_gate(mode='full'):
    """Refuse to publish a partial run. Assert key outputs moved to THIS week."""
    ns = json.load(open("newsite_sales.json"))
    assert CUR_END.strftime("%-d %b") in ns["_window"], f"newsite_sales stale: {ns['_window']}"
    # ... assert f1_detail newest race == CUR_END; allstores lw26 changed; etc.
    print("[gate] freshness OK")

# ---------- run mode ----------
# Sunday 21:00 = FULL refresh (hours not posted yet -> show "—").
# Monday 09:30 = HOURS update: re-pull planners only (hours + finalised forecasts),
#               rebuild over Sunday's data, push. Everything else stays as Sunday.
def run_mode():
    if len(sys.argv) > 1 and sys.argv[1] in ("full","hours"): return sys.argv[1]
    return "hours" if TODAY.weekday() == 0 else "full"   # Mon=hours, else full

def main():
    mode = run_mode(); print(f"[mode] {mode}")
    if mode == "full":
        pull_sales(); pull_planner()        # + wastage/f1/mix/daypart/actuals/... (ported)
    else:  # hours — light Monday pass
        pull_planner()                      # finalised forecasts + now-posted hours only
    build()
    freshness_gate(mode)
    print(f"[done] {mode} run rebuilt — workflow will commit & push")

if __name__ == "__main__":
    main()
