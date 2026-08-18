#!/usr/bin/env python3
"""TEMPORARY ad-hoc: list v_sales_details_flat columns to check for a discount/gross field.
(Repurposed bq-adhoc harness; restored to the SMT script immediately after this run.)"""
import os, json
from google.oauth2 import service_account
from google.cloud import bigquery

def main():
    sa = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        sa, scopes=["https://www.googleapis.com/auth/bigquery",
                    "https://www.googleapis.com/auth/cloud-platform"])
    client = bigquery.Client(project="bewiched-coffee-368116", credentials=creds)
    q = ("SELECT column_name, data_type FROM "
         "`bewiched-coffee-368116.bewiched_coffee.INFORMATION_SCHEMA.COLUMNS` "
         "WHERE table_name='v_sales_details_flat' ORDER BY ordinal_position")
    cols = list(client.query(q).result())
    print("[schema] v_sales_details_flat has %d columns" % len(cols))
    for r in cols:
        print("COL", r.column_name, r.data_type)
    hits = [r.column_name for r in cols if any(k in r.column_name.lower()
            for k in ("discount", "gross", "before", "full_price", "list_price", "rrp", "line_total"))]
    print("[schema] discount/gross candidates:", hits)

if __name__ == "__main__":
    main()
