# Telegram decision-change alerts and the scheduled scan

Issue #21. The **StockWatch scan** GitHub Actions job analyses every tracked stock every 15 minutes on
weekdays. Telegram gets a message when a stock's **call changes**, for example WAIT → BUY ON DIP or HOLD
→ SELL SOME. The scan runs even when Telegram isn't set up. Every run writes a summary of what actually
happened, and turns red when you need to act.

The repository is public, so its Actions logs are too. The job's log and summary show **counts and
statuses only**: no tickers, share counts, costs, bot token or chat ID. Message text goes only to Telegram.

## Which stocks, and what triggers a message

**The tracked fleet** is your holdings list: every row of the `STOCKWATCH_PORTFOLIO` secret (or the
Google Sheet), both held stocks (shares > 0) and watchlist stocks (shares 0). Add a row to start tracking a
stock; delete it to stop. The S&P 500 discovery scan isn't part of it and **never messages Telegram** unless
you set the repository variable `STOCKWATCH_SP500_PUSH` to `true` (**Settings → Secrets and variables → Actions
→ Variables**); then its daily 12:50 UTC run sends up to five S&P buy setups. Without it, that daily run is
skipped.

**What counts as a call** is the one the dashboard shows: the verdict reconciled with the trade plan
(`transitions.effective_stance`, which the dashboard's list now also uses). Calls fall into classes, and a
message is sent only when a stock moves between them:

| Class | Calls | Applies to |
|---|---|---|
| BUY | BUY NOW, BUY ON BREAKOUT (need the BUY SETUP verdict) | watchlist |
| DIP | BUY ON DIP: a conditional limit order in the zone below the price, which the plan can give without BUY SETUP | watchlist |
| ADD | BUY MORE | held |
| WAIT | WAIT (not a buy yet) | both |
| HOLD | HOLD | held |
| TRIM | SELL SOME (incl. trim / protect) | held |
| SELL | SELL (reduce / exit) | held |
| PASS | PASS (no trade) | watchlist |

Moving within a class (e.g. BUY NOW → BUY ON BREAKOUT) or a verdict change that doesn't change the call (STRONG
HOLD → HOLD) sends nothing. Individual signals (a golden cross, an RSI reading) no longer send messages from
the scheduled job. A watchlist stock is never told to "sell": the dashboard's rule turns that into PASS.

**Rules:**
- **First sight is a baseline.** The first time a stock is read (or after the memory expires) its current
  call is recorded and nothing is sent, so you don't get a burst of "BUY" messages.
- **Confirmed on two valid readings in a row.** A new call has to be seen on two valid readings in a row
  (usually two consecutive runs, about 15 to 30 minutes) before it's sent. A one-run flip, or a flip back,
  sends nothing. A run without a valid reading for that stock (outage, stale prices) in between neither
  confirms nor cancels the pending change.
- **No data, no change.** When a stock can't be read properly (analysis error, no trade plan, prices
  older than the last session, or verdict and plan disagreeing) its recorded call stays as it was. An
  outage is never read as HOLD or SELL.
- **Buying or selling the whole position re-baselines.** When a stock moves between watchlist and held,
  its new call is recorded without a message.
- **Delivered, then remembered.** A change is recorded only after Telegram accepts the message. A failed
  send stays pending and is retried on the next run (the run goes red meanwhile). If a send succeeds but
  the run dies before saving, the same message can arrive twice; it never silently disappears.
- **No per-signal cooldown.** A real change of call is always sent, however recently another alert was.

**Each message** shows:
- the ticker, held or watchlist, and the previous → new call
- the price with when it **traded**: a regular-session or pre-market / after-hours trade time in New York
  time, or "last daily bar" with its date. Last night's after-hours price seen before today's open, or a
  quote without a valid trade time, falls back to the daily bar; the time a quote was fetched is never
  shown as its trade time.
- why: the verdict change and the top two reasons
- the levels from the existing trade plan: entry zone and trigger for BUY / ADD / DIP (DIP says it's a conditional limit order, not a buy at the current price); the watch zone, marked
  "not an active buy", for WAIT; stop and target for HOLD; for TRIM, trim at the current price (the plan has no separate trim zone) with the stop; reduce /
  exit with the stop for SELL. A level the plan doesn't have reads "unavailable"; nothing is made up.
- "Don't rush" when the dashboard would say REASSESS (a sell call on a stock that's bouncing)
- "Model levels from StockWatch's rules, not orders or predictions."

The call, price, levels, warnings and disclaimer are always sent whole. Only the "why" is shortened (each
reason to 200 characters, marked …) to fit Telegram's 4,096-character limit. A message that wouldn't fit
even then isn't sent at all; it stays pending and the run goes red. Nothing is ever cut off silently.

## The alert memory, and why it's encrypted

To know what changed, the job remembers each stock's last call between runs. It keeps that in the Actions
cache, and **anyone who can open a pull request on a public repository can read its caches**. So:
- **What's kept:** only the encrypted file `data/alert_state.bin`, holding each ticker's last call and any
  change awaiting confirmation. No share counts, costs, prices or message text.
- **The scan's own database is never cached.** It holds positions and costs, and is thrown away after each
  run.
- **Encryption:** Fernet (AES with an integrity check), keyed from the `STOCKWATCH_STATE_KEY` repository
  secret. Without the key the file reveals only its size. A tampered or wrong-key file is refused; the run
  goes red and starts a new baseline.
- **Without the key, alerts are off.** A live run with no `STOCKWATCH_STATE_KEY` still scans and reports,
  but sends nothing, stores nothing, and goes red.
- **Expiry:** GitHub drops caches unused for 7 days. After a long pause, the first run re-baselines and
  says so.

## Set up (owner only, privately)

Never paste the token, chat ID, key or holdings into an issue, a pull request, a commit or a chat.

1. **Create the bot.** In Telegram, open **@BotFather** → `/newbot` → choose a name and a username
   ending in `bot`. BotFather replies with a token like `123456789:AAH…`. That token is a password.
2. **Find your chat ID.** Open your new bot and send it any message (e.g. `hi`). Then, in your own
   browser, open `https://api.telegram.org/bot<TOKEN>/getUpdates` with your token in place of `<TOKEN>`.
   Your chat ID is the number after `"chat":{"id":`.
3. **Make an alert-memory key:** any random text of 32 characters or more, for example from your password
   manager's generator. Keep a copy there; changing it later just re-baselines.
4. **Add the repository secrets.** In GitHub: repo → **Settings → Secrets and variables → Actions → New
   repository secret**:
   - `TELEGRAM_BOT_TOKEN`: the token from step 1
   - `TELEGRAM_CHAT_ID`: the number from step 2
   - `STOCKWATCH_STATE_KEY`: the key from step 3
   - `STOCKWATCH_PORTFOLIO`: your holdings YAML, or set `STOCKWATCH_SHEET_URL` to use the Google Sheet:
     ```yaml
     holdings:
       - {ticker: AAPL, tier: 1, shares: 40, cost_basis: 165}
       - {ticker: NVDA, tier: 2, shares: 0}      # shares 0 = watchlist
     ```
5. **Delete the old caches.** Earlier versions of this job cached `data/stockwatch.db`, which holds
   positions and costs. Open **Actions → Caches** (left sidebar, under Management) and delete every entry
   whose key starts with `stockwatch-db-`. This version never creates them.
6. **Check, then test.** **Actions → StockWatch scan → Run workflow**, and pick a mode:
   1. `telegram-check`: confirms both Telegram secrets are present and well formed. It sends nothing.
   2. `telegram-test-send` with `SEND` typed in the confirm box: sends one fixed message ("StockWatch
      test message … No holdings are included."). Check it arrives on your phone.
   3. `holdings-dry-run`: runs the real scan and reports how many changes it *would* send. It sends
      nothing and saves nothing.

After that, the schedule runs `holdings-scan` on its own. Its first run records the baseline.

## Run modes

| Mode | Sends? | Saves memory? | When |
|---|---|---|---|
| `holdings-scan` | confirmed changes | yes | every scheduled run; manual live run |
| `holdings-dry-run` | no | no | **default for "Run workflow"**; demo data allowed (labelled synthetic) |
| `telegram-check` | no (no network call) | no | after adding or changing the secrets |
| `telegram-test-send` | one fixed test message, only with `SEND` | no | to prove delivery works |
| `market-scan` | no, unless `STOCKWATCH_SP500_PUSH` is `true` | no | prints the S&P 500 setups to the log; manual runs no longer start it alongside the holdings scan |

## What a run's colour means

**Red (needs you):**
- only the example list was found (`portfolio.example.yaml` isn't your portfolio), the holdings are empty or unreadable, or the Google Sheet couldn't be read
- the demo data provider is selected for a live scan (`STOCKWATCH_DEMO`, or `data_provider: demo`): it never analyses or alerts on synthetic prices
- the scanner crashed, or no ticker could be analysed
- Telegram is half configured (token without chat ID, or the reverse) or malformed
- `STOCKWATCH_STATE_KEY` is missing or too short, or the saved memory can't be decrypted
- a Telegram send failed or was rate-limited, or a change was confirmed with Telegram not configured

**Green with a warning:**
- some tickers couldn't be analysed, or have prices older than the last session (a market holiday can cause this); those stocks' calls aren't compared this run
- no saved memory (first run or expired): a baseline was recorded
- Telegram isn't configured and there was nothing to send

ntfy and email aren't used by the scheduled scan; a run never counts them as delivery.

**A green run doesn't prove fresh data or a delivered message on its own.** Read the summary's "Latest
daily bar", "Live quotes", "Decision changes" and "Delivery" rows. "telegram: 1 sent" means Telegram
accepted the message.

## Schedule: Friday 23 October 2026

GitHub's scheduled runs are **best effort**: they can start several minutes late, and are sometimes
skipped when GitHub is busy. The crons are in UTC. New York is on EDT (UTC−4) until 1 November,
and Riyadh is UTC+3, so Riyadh is 7 hours ahead of New York.

| | UTC | New York (EDT) | Riyadh |
|---|---|---|---|
| Scan, every 15 min | Fri 08:00 – Sat 01:45 | Fri 04:00 – 21:45 | Fri 11:00 – Sat 04:45 |
| US regular session | 13:30 – 20:00 | 09:30 – 16:00 | 16:30 – 23:00 |
| S&P 500 scan (only with `STOCKWATCH_SP500_PUSH`) | 12:50 | 08:50 | 15:50 |

From 1 November (EST, UTC−5), the same UTC times are an hour earlier in New York, so the scans run
3:00am – 8:45pm New York (11:00 – 04:45 Riyadh, unchanged). With the two-run confirmation, a change is
sent about 15 to 30 minutes after it first appears.

## Verify that the scan actually ran

Open **Actions → StockWatch scan** → the run → **Summary**. A run that really scanned shows:
- **Holdings source:** `STOCKWATCH_PORTFOLIO secret` or `Google Sheet`, never `example file`
- **Market data:** `Yahoo`, never `SYNTHETIC`
- **Analysed:** `N of N`, matching the number of stocks you track
- **Latest daily bar:** today's or the previous trading day's date
- **Alert memory:** `restored (N stocks)`
- **Decision changes** and **Delivery:** e.g. `1 confirmed …` and `telegram: 1 sent, 0 failed`

Locally: `STOCKWATCH_DEMO=1 STOCKWATCH_STATE_KEY=<32+ chars> STOCKWATCH_PORTFOLIO="$(cat portfolio.yaml)" python -m stockwatch.ci_scan --mode holdings-dry-run`.
