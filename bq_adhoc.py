#!/usr/bin/env python3
"""READ-ONLY investigation for the EOS Sales-tab additions:
  Q1 drive-thru register/lane detection (what identifies a DT lane, which outlets)
  Q2 per-DT-lane transaction counts LW + QTD, this year vs -364 last year (YoY)
  Q3 top FOOD-category items (units) QTD + LW estate
  Q4 the named NEW SKUs (egg mayo / ham&cheese ciabatta / chicken cheese bbq toasty) + first-sold date
Prints JSON blocks."""
import os, json
from google.oauth2 import service_account
from google.cloud import bigquery
PROJECT="bewiched-coffee-368116"; DATASET="bewiched_coffee"; LOC="europe-west2"
FLAT=f"`{PROJECT}.{DATASET}.v_sales_details_flat`"
SDET=f"`{PROJECT}.{DATASET}.v_sales_details`"
creds=service_account.Credentials.from_service_account_info(
    json.loads(os.environ["GCP_SA_JSON"]), scopes=["https://www.googleapis.com/auth/bigquery"])
cl=bigquery.Client(project=PROJECT, credentials=creds)
def bq(sql): return [dict(r) for r in cl.query(sql, location=LOC).result()]
# periods aligned to EOS cur_end 2026-08-09
LW=("2026-08-03","2026-08-09"); LW25=("2025-08-04","2025-08-10")
QT=("2026-07-01","2026-08-09"); QT25=("2025-07-02","2025-08-10")
CAT=r"""CASE
  WHEN REGEXP_CONTAINS(LOWER({c}), r'milkshake') THEN 'Milkshakes'
  WHEN REGEXP_CONTAINS(LOWER({c}), r'iced|frappe|frozen|matcha|cold brew') THEN 'Cold'
  WHEN REGEXP_CONTAINS(LOWER({c}), r'beans|1kg|gift|merch') THEN 'Other&retail'
  WHEN REGEXP_CONTAINS(LOWER({c}), r'pastry|sausage roll') AND REGEXP_CONTAINS(LOWER({c}), r'meal deal') THEN 'Bakery'
  WHEN REGEXP_CONTAINS(LOWER({c}), r'meal deal|croque|ciabatta|\bbap\b|wrap|sandwich|bagel|salad|tuna|panini|toastie|toasty|soup|sausage roll|breakfast') THEN 'Food'
  WHEN REGEXP_CONTAINS(LOWER({c}), r'traybake|brownie|slice|croissant|pastry|muffin|cookie|cake|bakewell|millionaire|teacake|scone|flapjack|twist|doughnut|fudge|cinnamon') THEN 'Bakery'
  WHEN REGEXP_CONTAINS(LOWER({c}), r'latte|cappuccino|americano|flat white|mocha|espresso|hot choc|\bmug\b|\bpot\b|\btea\b|coffee|macchiato|cortado|chai') THEN 'Hot'
  ELSE 'Other&retail' END""".replace("{c}","item_product_name")

print("===Q1 DT registers (QTD)===")
print(json.dumps(bq(f"""
SELECT outlet.outlet_name store, register.register_name reg, COUNT(DISTINCT id) orders
FROM {SDET}
WHERE DATE(sales_date) BETWEEN '{QT[0]}' AND '{QT[1]}' AND LOWER(register.register_name) LIKE '%drive%'
GROUP BY store, reg ORDER BY orders DESC""")))

print("===Q2 per-DT-lane transactions LW/QTD YoY===")
print(json.dumps(bq(f"""
SELECT store,
  COUNT(DISTINCT IF(d BETWEEN '{LW[0]}' AND '{LW[1]}', id, NULL)) lw26,
  COUNT(DISTINCT IF(d BETWEEN '{LW25[0]}' AND '{LW25[1]}', id, NULL)) lw25,
  COUNT(DISTINCT IF(d BETWEEN '{QT[0]}' AND '{QT[1]}', id, NULL)) qtd26,
  COUNT(DISTINCT IF(d BETWEEN '{QT25[0]}' AND '{QT25[1]}', id, NULL)) qtd25
FROM (SELECT outlet.outlet_name store, id, DATE(sales_date) d
      FROM {SDET}
      WHERE LOWER(register.register_name) LIKE '%drive%'
        AND (DATE(sales_date) BETWEEN '{QT25[0]}' AND '{QT25[1]}' OR DATE(sales_date) BETWEEN '{QT[0]}' AND '{QT[1]}'))
GROUP BY store ORDER BY qtd26 DESC""")))

print("===Q3 top FOOD items units QTD/LW===")
print(json.dumps(bq(f"""
SELECT item_product_name item,
  ROUND(SUM(IF(d BETWEEN '{QT[0]}' AND '{QT[1]}', q,0))) units_qtd,
  ROUND(SUM(IF(d BETWEEN '{LW[0]}' AND '{LW[1]}', q,0))) units_lw
FROM (SELECT item_product_name, DATE(sales_date) d, SAFE_CAST(item_quantity AS FLOAT64) q, {CAT} cat
      FROM {FLAT} WHERE DATE(sales_date) BETWEEN '{QT[0]}' AND '{QT[1]}')
WHERE cat='Food'
GROUP BY item ORDER BY units_qtd DESC LIMIT 30""")))

print("===Q4 NEW SKUs + first-sold===")
print(json.dumps(bq(f"""
SELECT item_product_name item, MIN(d) first_sold,
  ROUND(SUM(IF(d BETWEEN '{QT[0]}' AND '{QT[1]}', q,0))) units_qtd,
  ROUND(SUM(IF(d BETWEEN '{LW[0]}' AND '{LW[1]}', q,0))) units_lw
FROM (SELECT item_product_name, DATE(sales_date) d, SAFE_CAST(item_quantity AS FLOAT64) q
      FROM {FLAT} WHERE DATE(sales_date) BETWEEN '2026-04-01' AND '{QT[1]}')
WHERE REGEXP_CONTAINS(LOWER(item_product_name), r'egg.*mayo|double egg|ham.*chee.*ciabatta|chicken.*chee.*bbq|bbq.*toast|chicken.*bbq')
GROUP BY item ORDER BY units_qtd DESC LIMIT 25""")))
print("===END===")
