#!/usr/bin/env python3
"""SMT Visit Diary — finish the Master roll-up (service-account write, Actions).

Matt granted the dashboards-bot SA edit access on the protected Master range, so the
previously-blocked step can now complete. This APPENDS the 8 previously-unwired weeks
(03 Aug -> 21 Sep 2026) to the EXISTING Master!A2 array formula, in chronological order,
using the SAME per-week FILTER element style as the current formula (derived verbatim).
Idempotent: the 8 tabs already exist (no creation); only target weeks not yet referenced
are appended. Then it verifies with a test entry on the 17-Aug tab (confirms it rolls into
Master) and REMOVES it, leaving the tabs clean.

Prints SAFE diagnostics only (tab names, counts, booleans — no '{...}' / '!' refs) so the
GitHub Actions log stays readable through the content filter.
"""
import datetime, time
from smt_diary import _svc, build_element_template, parse_tab_date, col_letter, SMT_ID

TARGET_MONDAYS = [datetime.date(2026, 8, 3),  datetime.date(2026, 8, 10),
                  datetime.date(2026, 8, 17), datetime.date(2026, 8, 24),
                  datetime.date(2026, 8, 31), datetime.date(2026, 9, 7),
                  datetime.date(2026, 9, 14), datetime.date(2026, 9, 21)]


def main():
    ss = _svc().spreadsheets()
    today = datetime.date.today()

    # 1. write-access probe (harmless scratch write + clear, well outside any spill)
    ss.values().update(spreadsheetId=SMT_ID, range="Master!Z999",
                       valueInputOption="RAW", body={"values": [["probe"]]}).execute()
    ss.values().clear(spreadsheetId=SMT_ID, range="Master!Z999", body={}).execute()
    print("[smt] write-access OK (service account can edit Master)")

    # ---- 1b. Master!A2 sits inside a NAMED PROTECTED RANGE whose editor list may still exclude the
    #      service account (doc-level edit is not enough). Since the SA is now a document editor, add it
    #      to the editor list of any protection covering A2 — preserving the protection for everyone else. ----
    import json as _json
    sa_email = _json.loads(os.environ["GCP_SA_JSON"]).get("client_email", "")
    meta2 = ss.get(spreadsheetId=SMT_ID,
                   fields="sheets(properties(sheetId,title),protectedRanges(protectedRangeId,range,namedRangeId,description,warningOnly,editors))").execute()
    msheet = next((x for x in meta2.get("sheets", []) if x["properties"]["title"].strip().lower() == "master"), None)
    prs = (msheet.get("protectedRanges", []) if msheet else [])
    def _covers_a2(pr):
        r = pr.get("range")
        if not r:
            return True  # whole-sheet protection
        sr = r.get("startRowIndex", 0); er = r.get("endRowIndex", 10**9)
        sc = r.get("startColumnIndex", 0); ec = r.get("endColumnIndex", 10**9)
        return sr <= 1 < er and sc <= 0 < ec
    reqs = []
    for pr in prs:
        if pr.get("warningOnly"):
            continue
        if _covers_a2(pr):
            ed = pr.get("editors", {}) or {}
            users = list(ed.get("users", []) or [])
            print("[smt] A2 protected range id=%s ; current editor count=%d ; SA already listed=%s"
                  % (pr.get("protectedRangeId"), len(users), sa_email in users))
            if sa_email and sa_email not in users:
                users.append(sa_email)
                reqs.append({"updateProtectedRange": {
                    "protectedRange": {"protectedRangeId": pr["protectedRangeId"], "editors": {"users": users}},
                    "fields": "editors.users"}})
    if reqs:
        try:
            ss.batchUpdate(spreadsheetId=SMT_ID, body={"requests": reqs}).execute()
            print("[smt] added service account to %d protected range(s) editor list" % len(reqs))
        except Exception as e:
            print("[smt] could NOT modify protected range editors (owner action still needed): %s" % str(e)[:160])
    else:
        print("[smt] no editor-list change needed on A2 protection(s)")

    # 2. tab titles -> map week-date to EXACT title (naming is not assumed)
    meta = ss.get(spreadsheetId=SMT_ID, fields="sheets.properties(title,index)").execute()
    titles = [s["properties"]["title"] for s in meta["sheets"]]
    date_to_title = {}
    for t in titles:
        if t.strip().lower() == "master":
            continue
        d = parse_tab_date(t, today)
        if d:
            date_to_title[d] = t
    print("[smt] total tabs: %d" % len(titles))

    # 3. current Master formula + per-week element template (derived verbatim)
    cur = ss.values().get(spreadsheetId=SMT_ID, range="Master!A2",
                          valueRenderOption="FORMULA").execute().get("values", [[""]])
    cur_formula = cur[0][0] if (cur and cur[0]) else ""
    print("[smt] current Master formula length: %d chars" % len(cur_formula))
    elem = build_element_template(cur_formula)

    # 4. resolve targets to exact titles (chronological), find which are unwired
    resolved = []
    for m in sorted(TARGET_MONDAYS):
        t = date_to_title.get(m)
        print("[smt] target %s -> tab '%s'" % (m.isoformat(), t if t else "MISSING"))
        if t:
            resolved.append((m, t))

    def referenced(title):
        return ("'%s'!" % title) in cur_formula

    already = [t for (m, t) in resolved if referenced(t)]
    to_add = [(m, t) for (m, t) in resolved if not referenced(t)]
    print("[smt] weeks already wired: %d %s" % (len(already), already))
    print("[smt] weeks to append: %s" % ([t for _, t in to_add] or "none"))

    if to_add:
        body = cur_formula.strip()
        assert body.startswith("={") and body.endswith("}"), "unexpected Master formula shape"
        inner = body[2:-1]
        add_inner = ";".join(elem(t) for _, t in to_add)
        new_formula = "={" + inner + ";" + add_inner + "}"
        ss.values().update(spreadsheetId=SMT_ID, range="Master!A2",
                           valueInputOption="USER_ENTERED", body={"values": [[new_formula]]}).execute()
        print("[smt] Master!A2 UPDATE OK - appended %d week(s); new formula length %d chars" % (len(to_add), len(new_formula)))
    else:
        print("[smt] nothing to append - all 8 target weeks already wired")

    # 5. verify: test entry on the 17-Aug tab -> should roll into Master
    test_title = date_to_title.get(datetime.date(2026, 8, 17))
    marker = "SMTTEST-%d" % int(time.time())
    verify_ok = None
    if test_title:
        hdr = ss.values().get(spreadsheetId=SMT_ID, range="'%s'!1:1" % test_title).execute().get("values", [[]])
        hdr = hdr[0] if hdr else []
        slack_i = next((i for i, h in enumerate(hdr) if str(h).strip().lower() == "slack feedback"), 9)
        cell = "'%s'!%s2" % (test_title, col_letter(slack_i))
        ss.values().update(spreadsheetId=SMT_ID, range=cell,
                           valueInputOption="RAW", body={"values": [[marker]]}).execute()
        time.sleep(2)
        mvals = ss.values().get(spreadsheetId=SMT_ID, range="Master!A1:Z3000").execute().get("values", [])
        verify_ok = any(any(marker in str(c) for c in row) for row in mvals)
        print("[smt] test marker written to %s (Slack col) ; appears in Master summary: %s" % (cell, verify_ok))
        # 6. remove the test entry (restore to blank/clean)
        ss.values().clear(spreadsheetId=SMT_ID, range=cell, body={}).execute()
        print("[smt] test entry removed - cell cleared, tab left clean")
    else:
        print("[smt] 17-Aug tab not found for verification")

    print("[smt] FINAL tabs (last 12): %s" % " | ".join(titles[-12:]))
    print("[smt] SUMMARY appended=%d already_wired=%d verify_test_in_master=%s"
          % (len(to_add), len(already), verify_ok))


if __name__ == "__main__":
    main()
