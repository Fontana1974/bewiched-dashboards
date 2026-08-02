import json, os
# Reads storehealth_raw.json (written by run_weekly.py from the F1 'Shift Ratings' tab + Google
# reviews QTD, ALREADY canonical-keyed) -> storehealth.json. No Zapier, no hand-pasted dicts.
# Falls back to the last committed hand-pasted snapshot only if the raw file is absent (legacy run).
targets={"Northampton Drive-Thru":49,"Kettering":24,"Burton Latimer":10,"Rothwell":12,"Northampton":15,"Wellingborough":18,"Wellingborough Train Station":10,"Rushden Lakes":49,"Peterborough Fletton Quays":15,"Higham Ferrers":10,"Peterborough Bridge Street":18,"Lower Heathcote":8,"Leamington Parade":15,"Market Harborough":24,"Rugby":25,"Corby":25,"Glenvale Drive Thru":49,"HOE Balsall Common":15,"Billing Drive Thru":49,"Attleborough":15,"Olney":10}
OLNEY_DEFAULT=True
stores=["Attleborough","Billing Drive Thru","Burton Latimer","Corby","Glenvale Drive Thru","HOE Balsall Common","Higham Ferrers","Kettering","Leamington Parade","Lower Heathcote","Market Harborough","Northampton","Northampton Drive-Thru","Olney","Peterborough Bridge Street","Peterborough Fletton Quays","Rothwell","Rugby","Rushden Lakes","Wellingborough","Wellingborough Train Station"]

if os.path.exists("storehealth_raw.json"):
    RAW=json.load(open("storehealth_raw.json"))
    # raw values are [n, avg] lists, canonical-keyed
    g_canon={k:tuple(v) for k,v in (RAW.get("google") or {}).items()}
    rms_canon={k:tuple(v) for k,v in (RAW.get("rms") or {}).items()}
    _UPDATED=RAW.get("_updated","")
else:   # legacy fallback (last hand-pasted snapshot) — only used if run_weekly didn't write the raw
    g_canon={"Wellingborough Train Station":(98,4.969),"Burton Latimer":(16,4.938),"Corby":(10,4.8),"Glenvale Drive Thru":(34,4.676),"Billing Drive Thru":(14,5.0),"Olney":(2,5.0),"Attleborough":(1,5.0)}
    rms_canon={"Corby":(60,3.533),"Glenvale Drive Thru":(51,3.294),"Northampton":(28,4.679),"Kettering":(24,4.583),"HOE Balsall Common":(36,4.917),"Northampton Drive-Thru":(41,4.146),"Peterborough Fletton Quays":(15,4.333),"Rugby":(62,4.919),"Market Harborough":(14,4.286),"Rothwell":(16,4.25),"Wellingborough":(11,4.636),"Rushden Lakes":(19,3.368),"Peterborough Bridge Street":(19,4.789),"Leamington Parade":(120,4.692),"Lower Heathcote":(18,4.222),"Burton Latimer":(18,4.889),"Wellingborough Train Station":(13,1.846),"Higham Ferrers":(8,4.625),"Billing Drive Thru":(22,4.818),"Olney":(3,5.0),"Attleborough":(32,4.688)}
    _UPDATED=""
def grag(h):
    return 'green' if h>=3.32 else 'red'
def rrag(a):
    return 'green' if a>=4.5 else ('amber' if a>=4.0 else 'red')
out={"_basis":"Quarter-to-date. NOT last week.","_updated":_UPDATED or "2026-06-16",
     "_google_formula":"google_health = avg_star*0.5 + min(reviews/quarterly_target,1)*2.5 ; green>=3.32 ; ZERO reviews in period => 0.0 (red)",
     "_rms_formula":"rms_avg = quarterly mean shift rating (1-5); green>=4.5 amber>=4.0 red<4.0",
     "_google_feed_note":"No reviews in the period => Google Health forced to 0.0 (red), per rule - no rating credit without reviews.",
     "targets":targets,"stores":{}}
print("%-28s | %-22s | %-22s"%("STORE","GOOGLE (n/target avg -> h RAG)","RMS (n avg -> RAG)"))
for s in stores:
    rec={}
    if s in g_canon and (g_canon[s][0] or 0) > 0:
        n,avg=g_canon[s]; tgt=targets.get(s)
        vol=min(n/tgt,1.0); h=round(avg*0.5+vol*2.5,2)
        rec["g_n"]=n; rec["g_avg"]=avg; rec["g_target"]=tgt; rec["g_health"]=h; rec["g_rag"]=grag(h); rec["g_stale"]=False
        gtxt="%d/%d %.2f* -> %.2f %s"%(n,tgt,avg,h,grag(h))
    else:
        # RULE (Matt): NO reviews in the period -> Google Health is a hard 0.0 (red). No residual
        # rating credit, since with zero reviews there is no rating to reward. Flows to EOS + Star Card.
        rec["g_n"]=0; rec["g_avg"]=None; rec["g_target"]=targets.get(s); rec["g_health"]=0.0; rec["g_rag"]="red"; rec["g_stale"]=False
        gtxt="0 reviews -> 0.00 red"
    if s in rms_canon:
        n,avg=rms_canon[s]; rec["r_n"]=n; rec["r_avg"]=round(avg,2); rec["r_rag"]=rrag(avg)
        rtxt="%d %.2f -> %s"%(n,avg,rrag(avg))
    else:
        rec["r_n"]=None; rec["r_avg"]=None; rec["r_rag"]="na"; rtxt="no data"
    out["stores"][s]=rec
    print("%-28s | %-22s | %-22s"%(s+("*" if s=="Olney" else ""),gtxt,rtxt))
json.dump(out,open('storehealth.json','w'),indent=1)
print("\n* Olney target defaulted to 10 (no target provided) - CONFIRM")
