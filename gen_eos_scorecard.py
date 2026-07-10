#!/usr/bin/env python3
# Bewiched EOS Weekly & Quarterly Scorecard generator.
# Reads eos_scorecard.json -> writes EOS_Scorecard.html, matching the Bewiched dashboards stack.
# Two tabs (Weekly / Quarterly); each metric = an EOS traffic-light widget (plan vs actual).
# STRICTLY BINARY status: GREEN actual>=plan | RED below. No near-target band.
# Greyed tiles: TBC (not yet defined) and AWAITING DATA (defined but no actual yet) — never red.
import json, datetime as dt, os, html

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "eos_scorecard.json")))
GEN = D.get("generated") or dt.datetime.now().strftime("%d %b %Y, %H:%M")

# ---- OWNERS: one accountable name per metric (EOS-style), keyed by metric NAME — same on both tabs.
# Edit here to reassign. "" / missing => shown as "—" (unassigned).
OWNERS = {
    "YoY Sales Growth": "Rich",
    "YoY Transactional Growth": "Rich",
    "Google Health": "Jon",
    "Rate My Shift Health": "Kel",
    "Brew Crew Kudos Participation": "Kel",
    "Social Media Engagement": "Jon",
    "SPH Labour (incl holiday pay)": "Jon",
    "Bench": "Kel",
    "F1 Score": "Claire",
    "Brand & Remote Assessment": "Claire",
    "Food GP%": "Rich",
    "New Starter Health": "Kel",
    "Net Profit After Tax (projected)": "",   # unassigned — Matt to confirm (likely Matt/MD)
}

PLACEHOLDER_FULL_CONTENT = True
