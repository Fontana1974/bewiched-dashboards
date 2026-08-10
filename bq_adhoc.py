#!/usr/bin/env python3
"""One-off BigQuery pull for the back-to-school sales & food-usage forecast.
Runs in GitHub Actions with the dashboards SA (GCP_SA_JSON). Prints JSON blocks."""
import os, json, datetime as dt
from google.oauth2 import service_account
from google.cloud import bigquery

PROJECT="bewiched-coffee-368116"; DATASET="bewiched_coffee"; LOCATION="europe-west2"
FLAT=f"`{PROJECT}.{DATASET}.v_sales_details_flat`"
creds=service_account.Credentials.from_service_account_info(
    json.loads(os.environ["GCP_SA_JSON"]), scopes=["https://www.googleapis.com/auth/bigquery"])
client=bigquery.Client(project=PROJECT, credentials=creds)
def bq(sql): return [dict(r) for r in client.query(sql, location=LOCATION).result()]

# item categoriser (copied from run_weekly.py) + product-name cleaner
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
CLEAN = (r"REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE("
         r"item_product_name,r'^[23]?[*]? ',''),r' TA$',''),"
         r"r'(?i)bacon bap meal deal.*','Bacon Bap'),r'(?i)sausage bap meal deal.*','Sausage Bap')")

# recent 8-week YoY windows (to Sun 2026-08-09) and the -364 aligned 2025 window
r26_end=dt.date(2026,8,9); r26_start=r26_end-dt.timedelta(days=55)
r25_end=r26_end-dt.timedelta(days=364); r25_start=r26_start-dt.timedelta(days=364)
R26S,R26E=r26_start.isoformat(),r26_end.isoformat(); R25S,R25E=r25_start.isoformat(),r25_end.isoformat()

# 2025 school-calendar weeks (aligned to the 2026 target weeks)
PK=("2025-08-25","2025-08-31")   # last holiday week (incl 2025 Aug bank hol Mon 25 Aug)
BK=("2025-09-01","2025-09-07")   # first week back
ST=("2025-09-08","2025-09-14")   # first FULL settled week back

q1=f"""
SELECT item_outlet_name AS store,
  ROUND(SUM(IF(d BETWEEN '{PK[0]}' AND '{PK[1]}', v,0)),2) sales_peak25,
  ROUND(SUM(IF(d BETWEEN '{BK[0]}' AND '{BK[1]}', v,0)),2) sales_back25,
  ROUND(SUM(IF(d BETWEEN '{ST[0]}' AND '{ST[1]}', v,0)),2) sales_settled25,
  ROUND(SUM(IF(d BETWEEN '{R25S}' AND '{R25E}', v,0)),2) sales_recent25,
  ROUND(SUM(IF(d BETWEEN '{R26S}' AND '{R26E}', v,0)),2) sales_recent26,
  COUNT(DISTINCT IF(d BETWEEN '{PK[0]}' AND '{PK[1]}', id, NULL)) tx_peak25,
  COUNT(DISTINCT IF(d BETWEEN '{BK[0]}' AND '{BK[1]}', id, NULL)) tx_back25,
  COUNT(DISTINCT IF(d BETWEEN '{ST[0]}' AND '{ST[1]}', id, NULL)) tx_settled25
FROM (SELECT item_outlet_name, id, DATE(sales_date) d,
             SAFE_CAST(item_line_total_after_discount AS FLOAT64) v
      FROM {FLAT}
      WHERE DATE(sales_date) BETWEEN '{R25S}' AND '{ST[1]}'
         OR DATE(sales_date) BETWEEN '{R26S}' AND '{R26E}')
GROUP BY store ORDER BY store"""

q2=f"""
SELECT item_outlet_name AS store,
  ROUND(SUM(IF(d BETWEEN '{PK[0]}' AND '{PK[1]}', q,0))) food_peak25,
  ROUND(SUM(IF(d BETWEEN '{BK[0]}' AND '{BK[1]}', q,0))) food_back25,
  ROUND(SUM(IF(d BETWEEN '{ST[0]}' AND '{ST[1]}', q,0))) food_settled25
FROM (SELECT item_outlet_name, DATE(sales_date) d, SAFE_CAST(item_quantity AS FLOAT64) q
      FROM {FLAT}
      WHERE DATE(sales_date) BETWEEN '{PK[0]}' AND '{ST[1]}'
        AND {cat_case('item_product_name')} IN ('Food','Bakery'))
GROUP BY store ORDER BY store"""

q3=f"""
SELECT item, cat,
  ROUND(SUM(IF(d BETWEEN '{PK[0]}' AND '{PK[1]}', q,0))) q_peak,
  ROUND(SUM(IF(d BETWEEN '{BK[0]}' AND '{BK[1]}', q,0))) q_back,
  ROUND(SUM(IF(d BETWEEN '{ST[0]}' AND '{ST[1]}', q,0))) q_settled
FROM (SELECT {CLEAN} item, {cat_case('item_product_name')} cat, DATE(sales_date) d,
             SAFE_CAST(item_quantity AS FLOAT64) q
      FROM {FLAT} WHERE DATE(sales_date) BETWEEN '{PK[0]}' AND '{ST[1]}')
WHERE cat IN ('Food','Bakery')
GROUP BY item, cat ORDER BY q_peak DESC LIMIT 45"""

print("META", json.dumps({"peak":PK,"back":BK,"settled":ST,
      "recent26":[R26S,R26E],"recent25":[R25S,R25E]}))
print("===Q1==="); print(json.dumps(bq(q1)))
print("===Q2==="); print(json.dumps(bq(q2)))
print("===Q3==="); print(json.dumps(bq(q3)))
# ---- day-of-week weekday(Mon-Thu) vs weekend(Fri-Sun): HOLIDAY (11-31 Aug 2025) vs TERM (8-28 Sep 2025) ----
HOL=("2025-08-11","2025-08-31"); TRM=("2025-09-08","2025-09-28")  # 3 clean Mon-Sun weeks each
q4=f"""
SELECT store,
  ROUND(SUM(IF(period='hol' AND wknd, v,0))) hol_wknd_s,
  ROUND(SUM(IF(period='hol' AND NOT wknd, v,0))) hol_wkday_s,
  ROUND(SUM(IF(period='term' AND wknd, v,0))) term_wknd_s,
  ROUND(SUM(IF(period='term' AND NOT wknd, v,0))) term_wkday_s,
  ROUND(SUM(IF(period='hol' AND wknd, fq,0))) hol_wknd_f,
  ROUND(SUM(IF(period='hol' AND NOT wknd, fq,0))) hol_wkday_f,
  ROUND(SUM(IF(period='term' AND wknd, fq,0))) term_wknd_f,
  ROUND(SUM(IF(period='term' AND NOT wknd, fq,0))) term_wkday_f
FROM (SELECT item_outlet_name store,
        SAFE_CAST(item_line_total_after_discount AS FLOAT64) v,
        IF({cat_case('item_product_name')} IN ('Food','Bakery'), SAFE_CAST(item_quantity AS FLOAT64), 0) fq,
        EXTRACT(DAYOFWEEK FROM DATE(sales_date)) IN (6,7,1) wknd,
        IF(DATE(sales_date) BETWEEN '{HOL[0]}' AND '{HOL[1]}','hol',
           IF(DATE(sales_date) BETWEEN '{TRM[0]}' AND '{TRM[1]}','term',NULL)) period
      FROM {FLAT} WHERE DATE(sales_date) BETWEEN '{HOL[0]}' AND '{TRM[1]}')
WHERE period IS NOT NULL GROUP BY store ORDER BY store"""

q5=f"""
SELECT dow,
  ROUND(SUM(IF(period='hol', v,0))/3) hol_avg,
  ROUND(SUM(IF(period='term', v,0))/3) term_avg
FROM (SELECT EXTRACT(DAYOFWEEK FROM DATE(sales_date)) dow,
        SAFE_CAST(item_line_total_after_discount AS FLOAT64) v,
        IF(DATE(sales_date) BETWEEN '{HOL[0]}' AND '{HOL[1]}','hol',
           IF(DATE(sales_date) BETWEEN '{TRM[0]}' AND '{TRM[1]}','term',NULL)) period
      FROM {FLAT} WHERE DATE(sales_date) BETWEEN '{HOL[0]}' AND '{TRM[1]}')
WHERE period IS NOT NULL GROUP BY dow ORDER BY dow"""
print("===Q4==="); print(json.dumps(bq(q4)))
print("===Q5==="); print(json.dumps(bq(q5)))
print("===END===")
