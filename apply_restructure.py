#!/usr/bin/env python3
"""One-shot: apply the Sales · Commercial · Operations · People & Customer layout (+ PAT card,
+ reworked Grow star) to the two published store pages WITHOUT re-running the weekly data refresh,
so every live figure is preserved. The full weekly patch() carries the same restructure for future
runs. Structure-only and idempotent."""
import patch_newsite as P
TARGETS=[('Glenvale_Forecast.html','Glenvale Drive Thru','Ian'),
         ('Leamington_Parade_Forecast.html','Leamington Parade','Rich')]
def apply(fn,store,coach):
    h=open(fn,encoding='utf-8').read()
    h=P.inject_star(h,store)          # re-render the Grow star with the new pillars (4.6 target kept)
    h=P.inject_compliance(h,store)    # full Operations & compliance panel (pre-restructure home)
    h=P.inject_simply_lunch(h,store)
    h=P.inject_reviews(h,store)
    h=P.relocate_coaching(h)
    h=P.inject_sales_tab(h,store)     # rebuild the sales-only STORESALES body
    h=P.restructure_tabs(h,store)     # -> Sales / Commercial / Operations / People & Customer
    h=P.inject_audit(h,store)         # Operations: brand audit
    h=P.inject_compliance(h,store)    # Operations: remote audit / compliance / coaching / RTW
    h=P.inject_pat_card(h,store)      # Commercial: PAT KPI card
    h=P.inject_cos_cards(h,store)     # Commercial: Holding-stock % + GP% cards
    h=P.inject_txquality(h,store)     # Commercial: transaction quality + PAT tracker
    h=P.simplify_mix_table(h)
    h=P.merge_mix_capture(h)          # merge mix + capture into one table
    open(fn,'w',encoding='utf-8').write(h)
    print("restructured",fn)
if __name__=='__main__':
    for t in TARGETS: apply(*t)
