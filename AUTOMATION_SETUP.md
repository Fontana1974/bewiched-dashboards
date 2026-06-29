# Bewiched dashboards — moving the weekly run to true automation

Goal: the Monday refresh runs **by itself** (GitHub Actions cron) with no agent and no
desktop. The agent (Cowork) is then only used to *change* dashboards, not to run them.

## How it will work
- A committed script, `run_weekly.py`, pulls BigQuery + Google Sheets **directly via a
  Google service account** (no Zapier → no column scrambling, no row caps, full reads),
  rebuilds all 11 dashboards with the existing builders, runs a freshness gate.
- **GitHub Actions** runs it on a cron and pushes the result. The built-in `GITHUB_TOKEN`
  does the push, so **the only secret you add is the Google service account.**
- Every per-run constant (week dates, hours, forecast) is **derived from the run date +
  the data** — nothing hand-bumped, which kills most of the recurring breakage.

## What only YOU can set up (≈20 min, one-time)

### 1. Create a Google service account
1. Go to https://console.cloud.google.com → project **bewiched-coffee-368116**.
2. IAM & Admin → **Service Accounts** → **Create service account**.
   - Name: `dashboards-bot`. Create.
3. Grant it two roles (IAM & Admin → IAM → grant on this account):
   - **BigQuery Job User**
   - **BigQuery Data Viewer**
4. Open the new account → **Keys** → Add key → **Create new key → JSON** → download it.
   Note the account email, e.g. `dashboards-bot@bewiched-coffee-368116.iam.gserviceaccount.com`.

### 2. Share every source Sheet with that email (Viewer)
Open each of these and Share → paste the service-account email → **Viewer**:
- Store Targets / CPH, the 3 Area Planners (Jon/Rich/Ian), Master Populator,
  the F1 workbook, Sickness/RTW, Brand Audit, Reviews, Availability tracker, SMT visits.
(They're all listed by ID in `run_weekly.py` → `SID`.)

### 3. Add the key as a GitHub secret
GitHub repo **Fontana1974/bewiched-dashboards** → Settings → Secrets and variables →
Actions → **New repository secret**:
- Name: `GCP_SA_JSON`
- Value: paste the **entire contents** of the downloaded JSON key file.

### 4. (timing) Decide the run time
Coaches post "hours used" through Monday morning. Cron is in **UTC**:
- 10:00 UK (BST) = `0 9 * * 1` · 10:30 UK = `30 9 * * 1`.
Set it later than 9am if you want hours complete on the first pass.

## What I (the agent) do once the above exists
- Finish porting the remaining pulls in `run_weekly.py` (sales/planner/actuals are done;
  the rest are stubbed with the spec) and **test the whole run end-to-end** against the
  real service account.
- Uncomment the `schedule:` cron in `.github/workflows/weekly.yml`.
- Disable the old Cowork "weekly-area-dashboard-refresh" task so there's one source of truth.

## Future dashboard changes (unchanged for you)
Just ask me in Cowork — "add a GP% column", "new tab for store X", "we opened a new site".
I edit the committed code (`build_*.py` for data, `TEMPLATE_*.html` + `gen_*.py` /
`patch_newsite.py` for layout), test it (dry-run or a manual Actions run), commit. The
next scheduled run uses it automatically — or we trigger one immediately from the Actions
tab. Everything's in git, so any change is reviewable and one-click revertible.

## Note on the workflow file
GitHub blocks tokens without the `workflow` scope from pushing `.github/workflows/*`.
So the workflow is shipped here as `automation/weekly.yml.txt`. To activate it, either:
- **Web UI (easiest):** GitHub → Add file → Create new file → name it
  `.github/workflows/weekly.yml` → paste the contents of `automation/weekly.yml.txt` → commit. OR
- create a PAT **with the `workflow` scope** and the agent can push it directly.
