# Smallcap Sheet on your Windows PC

Nothing is scheduled by installing the Python code or merging the PR. Set this up
on your PC after merge. It does not need an app restart and does not run on GitHub Actions.

1. In the repo folder, create a virtual environment (`py -m venv .venv`), then run
   `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
2. Enable **Google Sheets API** in a Google Cloud project. Create a service account
   and a JSON key. Keep the key outside the repo (for example in your Windows user
   folder). Share your existing Sheet with the service account's `client_email`
   as **Editor**. No public edit access or Drive API is needed.
3. In Windows **Edit environment variables for your account**, add
   `GOOGLE_APPLICATION_CREDENTIALS` with the full key-file path and
   `STOCKWATCH_SMALLCAP_SHEET_URL` with your private Sheet link. Alternatively,
   `GOOGLE_SERVICE_ACCOUNT_JSON` can hold the complete key JSON (it takes priority).
   Never paste these values into GitHub, commit them, or send the key in chat.
   Reopen PowerShell and Task Scheduler after setting them so they see the variables.
4. From PowerShell in the repo, run `& .\scripts\install_smallcap_task.ps1`.
   This creates **StockWatch Smallcap** for your current Windows account. It runs
   `.venv\Scripts\python.exe -m stockwatch.smallcap --db "…\StockWatch\smallcap.db"`
   from the repo, using a database under `%LOCALAPPDATA%`, separate from the app.
   Optional script arguments: `-Python 'full path to python.exe'` and
   `-Database 'full path to smallcap.db'`. Keep that database between runs: it holds
   the weekly list, fundamentals cache, hourly comparisons, events and pending writes.

The task wakes hourly on the PC's local clock. Python does work only on weekdays
from **04:00 inclusive to 20:00 exclusive in New York**, automatically allowing
for daylight saving. Outside those hours it prints a skip message. Holidays are
not modelled. Your PC must be awake, online and logged into that Windows account.
Missed hours are not replayed. Overlapping task instances are ignored.

For a manual check during session hours, run:

```powershell
.venv\Scripts\python.exe -m stockwatch.smallcap --db "$env:LOCALAPPDATA\StockWatch\smallcap.db"
```

Missing link or key prints a reason and exits successfully before any scan. An
invalid key also exits cleanly. Network, permission or delivery errors return 1;
check the manual command and Task Scheduler's **Last Run Result**. The first run
can take time; no more than 40 fundamentals are requested per scan.

The job creates **Shortlist** and **Log** if needed. Shortlist is replaced each
run, including clearing old rows when the list shrinks. Log keeps its header and
appends entry/exit events; an empty event batch adds nothing. The screening core
establishes a baseline on its first run, so it may initially log no entries.
Unknown data remains `unknown`. Values are written as plain values, not formulas.

A delivery is saved locally before its event baseline advances. A failed write is
retried next hour before another scan. Log reserves a row before writing, so a
retry after a timeout writes those same cells. **Use one task/database and let only
this job write Log**; don't insert/delete Log rows while a delivery is pending.
Do not switch the target Sheet while a delivery is pending. Shortlist may briefly
be empty if clearing succeeds but its update fails; the retry restores it.

Disable the task in Task Scheduler to stop it, or run
`Unregister-ScheduledTask -TaskName 'StockWatch Smallcap' -Confirm:$false`.
Revoking/deleting the service-account key also removes its access. Keep the
private database if you want to resume with the same cache and event history.

For synthetic CSV output only, use `--demo --out smallcap_out`; this never writes
the Sheet and uses separate demo state. `--out` on a live run also exports CSVs.
Keep exports private and outside the repo.
