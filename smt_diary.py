#!/usr/bin/env python3
"""smt_diary.py — maintain the "Weekly SMT Visit Diary" Google Sheet.

Two idempotent jobs, safe to run weekly on a cron:

  1. Rebuild the Master roll-up ARRAY FORMULA so it references the ACTUAL weekly tabs
     (the real Monday-date naming, e.g. '29th June') in chronological order. This repairs
     the prior 'WC ...' mismatch so every existing + future week feeds Master. The per-week
     element structure is taken verbatim from the sheet's current formula (only the tab name
     is swapped), so the Master layout stays identical to before.

  2. Ensure the upcoming WEEKS_AHEAD weeks (including the current week) each have a tab:
     duplicate the latest week's tab (keeps the Table format + day-of-week dropdowns via the
     Sheets duplicateSheet copy), rename to the Monday-date convention, clear the coach day
     cells + Slack Feedback for population, and set the Date column to that week's Monday.

Auth: service account (GCP_SA_JSON) with the spreadsheets WRITE scope. The sheet must be
shared to the service account as Editor.

Env:
  GCP_SA_JSON  - service-account JSON (GitHub Actions secret).
  DRY_RUN      - 'true'/'1' -> probe write access + print the plan, make NO structural changes.
"""
import os, re, json, sys, datetime

SMT_ID = "1IGL3sLWSI7k1vuXEMFBWplgk3uS4tTUU1-MtGYDk-bQ"
WEEKS_AHEAD = 4                       # keep this many weeks present (incl. the current week)
WRITE_SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def _svc():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    sa = json.loads(os.environ["GCP_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(sa, scopes=WRITE_SCOPE)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _ord(n):
    return "%d%s" % (n, "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def tab_name(monday):                 # date -> '29th June'
    return "%s %s" % (_ord(monday.day), MONTHS[monday.month - 1])


def col_letter(i):                    # 0 -> A, 1 -> B, ...
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_tab_date(title, today):
    """Parse a weekly-tab title (e.g. '29th June' or 'WC 12th May') -> a date near today (year inferred)."""
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)", title.strip())
    if not m:
        return None
    day = int(m.group(1)); mon = m.group(2).lower()[:3]
    mi = next((i + 1 for i, nm in enumerate(MONTHS) if nm.lower().startswith(mon)), None)
    if not mi:
        return None
    best = None
    for yr in (today.year - 1, today.year, today.year + 1):
        try:
            d = datetime.date(yr, mi, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best if (best and abs((best - today).days) <= 220) else None


def monday_of(d):
    return d - datetime.timedelta(days=d.weekday())


def build_element_template(cur_formula):
    """Derive the per-week FILTER(...) element verbatim from the current Master formula,
    returning a function tab_name -> element string. Falls back to the known structure."""
    try:
        inner = cur_formula.strip()
        if inner.startswith("={") and inner.endswith("}"):
            inner = inner[2:-1]
        first = inner.split(";")[0].strip()
        m = re.search(r"'([^']+)'!", first)
        if first.upper().startswith("FILTER(") and m:
            old = m.group(1)
            return lambda t: first.replace("'%s'" % old, "'%s'" % t)
    except Exception:
        pass
    return (lambda t: "FILTER({'%s'!A2:F1000,IFERROR(ARRAYFORMULA('%s'!A2:A1000/0)),'%s'!G2:L1000}, LEN('%s'!A2:A1000))"
            % (t, t, t, t))


def main():
    svc = _svc()
    ss = svc.spreadsheets()
    today = datetime.date.today()
    print("[smt] run %s  DRY_RUN=%s" % (today.isoformat(), DRY_RUN))

    # ---- write-access probe (harmless: write + clear a scratch cell well outside any spill) ----
    try:
        ss.values().update(spreadsheetId=SMT_ID, range="Master!Z999",
                           valueInputOption="RAW", body={"values": [["probe"]]}).execute()
        ss.values().clear(spreadsheetId=SMT_ID, range="Master!Z999", body={}).execute()
        print("[smt] write-access OK (service account can edit)")
    except Exception as e:
        print("[smt] WRITE ACCESS DENIED - the sheet is not shared to the service account as Editor.")
        print("[smt]   error: %s" % str(e)[:200])
        sys.exit(2)

    meta = ss.get(spreadsheetId=SMT_ID, fields="sheets.properties(sheetId,title,index)").execute()
    props = [s["properties"] for s in meta["sheets"]]
    titles = [p["title"] for p in props]
    master = next((p for p in props if p["title"].strip().lower() == "master"), None)
    print("[smt] tabs present (%d): %s" % (len(titles), " | ".join(titles)))

    weekly = {}
    for p in props:
        if p["title"].strip().lower() == "master":
            continue
        d = parse_tab_date(p["title"], today)
        if d:
            weekly[p["title"]] = {"date": d, "sheetId": p["sheetId"]}
    if not weekly:
        print("[smt] no weekly tabs recognised - aborting")
        sys.exit(1)

    latest = max(weekly, key=lambda t: weekly[t]["date"])
    latest_gid = weekly[latest]["sheetId"]
    print("[smt] latest existing week: '%s' (%s) -> template/source" % (latest, weekly[latest]["date"]))

    header = ss.values().get(spreadsheetId=SMT_ID, range="'%s'!1:1" % latest).execute().get("values", [[]])
    header = header[0] if header else []
    def colidx(name):
        for i, h in enumerate(header):
            if str(h).strip().lower() == name.lower():
                return i
        return None
    store_c, slack_c = colidx("Store Name"), colidx("Slack Feedback")
    nov_c, date_c = colidx("Number Of Visits"), colidx("Date")
    coach_cols = list(range(store_c + 1, slack_c)) if (store_c is not None and slack_c is not None) else []
    colA = ss.values().get(spreadsheetId=SMT_ID, range="'%s'!A2:A" % latest).execute().get("values", [])
    n_stores = 0
    for r in colA:
        if r and str(r[0]).strip():
            n_stores += 1
        else:
            break
    last_row = 1 + n_stores
    nov_is_formula = False
    if nov_c is not None:
        cell = ss.values().get(spreadsheetId=SMT_ID, range="'%s'!%s2" % (latest, col_letter(nov_c)),
                               valueRenderOption="FORMULA").execute().get("values", [[""]])
        nov_is_formula = bool(cell and cell[0] and str(cell[0][0]).startswith("="))
    print("[smt] columns: store=%s coach=%s slack=%s nov=%s(formula=%s) date=%s | %d store rows"
          % (col_letter(store_c) if store_c is not None else "?",
             ",".join(col_letter(c) for c in coach_cols) or "?",
             col_letter(slack_c) if slack_c is not None else "?",
             col_letter(nov_c) if nov_c is not None else "?", nov_is_formula,
             col_letter(date_c) if date_c is not None else "?", n_stores))

    cur = ss.values().get(spreadsheetId=SMT_ID, range="Master!A2", valueRenderOption="FORMULA").execute().get("values", [[""]])
    cur_formula = cur[0][0] if (cur and cur[0]) else ""
    make_elem = build_element_template(cur_formula)

    cur_mon = monday_of(today)
    targets = [cur_mon + datetime.timedelta(weeks=k) for k in range(WEEKS_AHEAD)]
    existing_dates = {v["date"] for v in weekly.values()}
    to_create = [(m, tab_name(m)) for m in targets if m not in existing_dates]
    print("[smt] target weeks: %s" % ", ".join("%s(%s)" % (tab_name(m), "exists" if m in existing_dates else "CREATE") for m in targets))

    if DRY_RUN:
        planned = sorted(list(weekly) + [nm for _, nm in to_create],
                         key=lambda t: parse_tab_date(t, today) or today)
        print("[smt][dry] would create tabs: %s" % (", ".join(nm for _, nm in to_create) or "none"))
        print("[smt][dry] would rebuild Master over %d weeks: %s" % (len(planned), " | ".join(planned)))
        print("[smt][dry] current Master!A2 (first 300): %s" % cur_formula[:300])
        return

    created = []
    master_index = master["index"] if master else len(props)
    for mon, name in to_create:
        resp = ss.batchUpdate(spreadsheetId=SMT_ID, body={"requests": [
            {"duplicateSheet": {"sourceSheetId": latest_gid,
                                "insertSheetIndex": master_index,
                                "newSheetName": name}}]}).execute()
        new_gid = resp["replies"][0]["duplicateSheet"]["properties"]["sheetId"]
        master_index += 1
        clear_cols = list(coach_cols)
        if slack_c is not None:
            clear_cols.append(slack_c)
        if nov_c is not None and not nov_is_formula:
            clear_cols.append(nov_c)
        ranges = ["'%s'!%s2:%s%d" % (name, col_letter(c), col_letter(c), last_row) for c in clear_cols]
        if ranges:
            ss.values().batchClear(spreadsheetId=SMT_ID, body={"ranges": ranges}).execute()
        if date_c is not None:
            vals = [[mon.isoformat()] for _ in range(n_stores)]
            ss.values().update(spreadsheetId=SMT_ID,
                               range="'%s'!%s2:%s%d" % (name, col_letter(date_c), col_letter(date_c), last_row),
                               valueInputOption="USER_ENTERED", body={"values": vals}).execute()
        created.append(name)
        weekly[name] = {"date": mon, "sheetId": new_gid}
        print("[smt] created tab '%s' (Date=%s, days cleared)" % (name, mon.isoformat()))

    order = sorted(weekly, key=lambda t: weekly[t]["date"])
    new_formula = "={" + ";".join(make_elem(t) for t in order) + "}"
    if cur_formula.replace(" ", "") == new_formula.replace(" ", ""):
        print("[smt] Master formula already current (%d weeks)" % len(order))
    else:
        ss.values().update(spreadsheetId=SMT_ID, range="Master!A2",
                           valueInputOption="USER_ENTERED", body={"values": [[new_formula]]}).execute()
        print("[smt] Master formula rebuilt over %d weeks: %s" % (len(order), " | ".join(order)))

    print("[smt] DONE. created=%s" % (created or "none"))


if __name__ == "__main__":
    main()
