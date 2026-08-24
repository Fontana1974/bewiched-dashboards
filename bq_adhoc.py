#!/usr/bin/env python3
"""TEMP outlet discovery: find the new Warwick store's exact item_outlet_name + whether sales flow.
(Repurposed bq-adhoc harness; restored to the SMT script right after.)"""
import os, json
from google.oauth2 import service_account
from google.cloud import bigquery

def main():
    sa = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        sa, scopes=["https://www.googleapis.com/auth/bigquery",
                    "https://www.googleapis.com/auth/cloud-platform"])
    c = bigquery.Client(project="bewiched-coffee-368116", credentials=creds)
    FLAT = "`bewiched-coffee-368116.bewiched_coffee.v_sales_details_flat`"
    print("=== outlets matching warwick/market square/square/leam ===")
    q1 = ("SELECT item_outlet_name s, COUNT(*) n, MIN(DATE(sales_date)) first, MAX(DATE(sales_date)) last "
          "FROM %s WHERE LOWER(item_outlet_name) LIKE '%%warwick%%' OR LOWER(item_outlet_name) LIKE '%%market square%%' "
          "OR LOWER(item_outlet_name) LIKE '%%square%%' OR LOWER(item_outlet_name) LIKE '%%leam%%' "
          "GROUP BY s ORDER BY last DESC" % FLAT)
    for r in c.query(q1).result():
        print("OUT | %-32s | rows=%-7d first=%s last=%s" % (r.s, r.n, r.first, r.last))
    print("=== outlets first-sold in the last 120 days (new stores) ===")
    q2 = ("SELECT item_outlet_name s, COUNT(*) n, MIN(DATE(sales_date)) first, MAX(DATE(sales_date)) last "
          "FROM %s GROUP BY s HAVING MIN(DATE(sales_date)) >= DATE_SUB(CURRENT_DATE(), INTERVAL 120 DAY) "
          "ORDER BY first DESC" % FLAT)
    n = 0
    for r in c.query(q2).result():
        print("NEW | %-32s | rows=%-7d first=%s last=%s" % (r.s, r.n, r.first, r.last)); n += 1
    if n == 0:
        print("NEW | (none in last 120 days)")

if __name__ == "__main__":
    main()
