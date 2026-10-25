# Paper trading

A fake account (start $50,000) trades the rules in `stockwatch/decision.py` on a short list of stocks, only in the New York regular session. It never places a real order and changes no card, score, call or alert. The **◈ Paper** tab shows it.

## How it runs
- The tracker thread (`live.py`) calls `paper_live.tick` about every 20 seconds. It reads the latest scans and live prices already in the store, so it fetches nothing itself.
- Stocks come from the **Test list** tab of your paper-trading Google Sheet (columns `Ticker`, `Paper`; `yes` turns a row on; up to 20). Add a row to add a stock. A stock the app is not tracking yet is shown as skipped with the reason, so keep the test list inside your holdings list.
- Buys follow the entry gates, no opening wait for now (owner's choice, so the test sees the open; set `STOCKWATCH_PAPER_BLACKOUT_MIN=60` to bring back the first-hour wait), an earnings block and a limit price. Sells follow the owner's intraday rule: a dip is only an alert until 3:45 pm, then half is sold; a close below the floor sells all.
- At the first target, a strong trend (momentum strong or building, chart sound) is not sold: the trade is "stretched". The stop trails up under the chart floor and never goes below the entry. It sells everything when the trend has turned for 30 minutes, or a third at 3 times the first risk. A mixed or weak trend at the target sells a third, as before. Each stretched trade records what selling all at the target would have made, and the Report shows the difference. To switch it off, set `stretch=False` in `decision.Config`.
- The book is kept in the app's database and pushed to the Sheet (Trades, Blocked buys, Daily report tabs) after each change and after 4:05 pm. A rebooted app reads the saved book back.
- The report says "Too few trades to judge" until 30 trades have closed.

## One-time setup
1. In the Sheet: Extensions, Apps Script. Paste `docs/paper_sheet_script.gs`. Project Settings, Script properties, add `TOKEN` with a password you choose.
2. Deploy, New deployment, Web app. Run as: Me. Who has access: Anyone. Copy the web app link.
3. Share the Test list tab as General access: Anyone with the link, Viewer. Copy that tab's link (it must carry `gid=`).
4. In Streamlit Cloud secrets add:
   - `STOCKWATCH_PAPER_LIST_URL` the Test list tab link
   - `STOCKWATCH_PAPER_WEBHOOK` the web app link
   - `STOCKWATCH_PAPER_TOKEN` the same password
5. Reboot the app. Never commit these values; the repo is public.

Without the list link nothing trades. Without the webhook the book lives in the app only, and the tab says so.

## Limits
- Fills use the latest price the tracker holds, so they are approximate.
- The app only trades while it is awake and tracking.
- Rules here apply to paper trading only, not to the live cards.
