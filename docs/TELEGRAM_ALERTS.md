# Telegram alerts and the scheduled holdings scan

Issue #21. The **StockWatch scan** GitHub Actions job analyses your holdings every 15 minutes on
weekdays and sends new alerts to Telegram. The scan runs even when Telegram isn't set up. Every run
writes a summary of what actually happened, and turns red when you need to act.

The repository is public, so its Actions logs are too. The job's log and summary show **counts and
statuses only**: no tickers, share counts, costs, bot token or chat ID. Alert text goes only to
Telegram (or ntfy/email if you set them).

## Set up Telegram (owner only, privately)

Never paste the token, chat ID or holdings into an issue, a pull request, a commit or a chat.

1. **Create the bot.** In Telegram, open **@BotFather** → `/newbot` → choose a name and a username
   ending in `bot`. BotFather replies with a token like `123456789:AAH…`. That token is a password.
2. **Find your chat ID.** Open your new bot and send it any message (e.g. `hi`). Then, in your own
   browser, open `https://api.telegram.org/bot<TOKEN>/getUpdates` with your token in place of
   `<TOKEN>`. Your chat ID is the number after `"chat":{"id":`. A personal chat ID is a positive number.
   A group's starts with `-`.
3. **Add three repository secrets.** In GitHub: repo → **Settings → Secrets and variables → Actions →
   New repository secret**:
   - `TELEGRAM_BOT_TOKEN`: the token from step 1
   - `TELEGRAM_CHAT_ID`: the number from step 2
   - `STOCKWATCH_PORTFOLIO`: your holdings YAML, or set `STOCKWATCH_SHEET_URL` to use the Google Sheet:
     ```yaml
     holdings:
       - {ticker: AAPL, tier: 1, shares: 40, cost_basis: 165}
       - {ticker: NVDA, tier: 2, shares: 0}      # shares 0 = watchlist
     ```
4. **Check, then test.** **Actions → StockWatch scan → Run workflow**, and pick a mode:
   1. `telegram-check`: confirms both secrets are present and well formed. It sends nothing.
   2. `telegram-test-send` with `SEND` typed in the confirm box: sends one fixed message ("StockWatch
      test message … No holdings are included."). Check it arrives on your phone.
   3. `holdings-dry-run`: runs the real scan and reports how many alerts it *would* send. It sends
      nothing and doesn't touch the alert history.

After that the schedule runs `holdings-scan` on its own.

## Run modes

| Mode | Sends? | When |
|---|---|---|
| `holdings-scan` | yes, new alerts | every scheduled run; manual live run |
| `holdings-dry-run` | no | **default for "Run workflow"** |
| `telegram-check` | no (no network call) | after adding or changing the secrets |
| `telegram-test-send` | one fixed test message, only with `SEND` | to prove delivery works |
| `market-scan` | the S&P 500 setups | the daily 12:50 UTC job; manual runs no longer start it alongside the holdings scan |

## What a run's colour means

**Red (needs you):**
- only the example list was found (`portfolio.example.yaml` isn't your portfolio), the holdings are empty or unreadable, or the Google Sheet couldn't be read
- the scanner crashed, or no ticker could be analysed
- Telegram is half configured (token without chat ID, or the reverse) or malformed
- a Telegram send failed or was rate-limited
- new alerts were found but no channel is configured

**Green with a warning:**
- some tickers couldn't be analysed
- prices are older than the last session (a market holiday can cause this)
- no channel is configured and there was nothing to send
- no holding has a share count

**Green, no warnings:** every check passed. The summary says how many tickers were analysed, the
latest daily price bar, how many live quotes came back, how many new alerts there were, and how each
was delivered.

**A green run doesn't prove fresh data or a delivered message on its own.** Read the summary's
"Latest daily bar", "Live quotes" and "Delivery" rows. "Delivery: telegram: sent" means Telegram
accepted the message.

**Undelivered alerts are retried.** The alert history (which stops the same alert repeating within
`alert_cooldown_hours`) is saved only when a run succeeds. So when a send fails, or alerts arrive
before Telegram is set up, the next run finds them again and tries again. If Telegram asks the job to
wait 10 seconds or less it waits once. A longer wait is reported as rate-limited and the run goes red.
Each message holds up to 15 alerts, most urgent first, within Telegram's 4,096-character limit.
The rest are counted ("+N more").

## Schedule: Friday 23 October 2026

GitHub's scheduled runs are **best effort**: they can start several minutes late, and are sometimes
skipped when GitHub is busy. The crons are in UTC. New York is on EDT (UTC−4) until 1 November,
and Riyadh is UTC+3, so Riyadh is 7 hours ahead of New York.

| | UTC | New York (EDT) | Riyadh |
|---|---|---|---|
| Holdings scan, every 15 min | Fri 08:00 – Sat 01:45 | Fri 04:00 – 21:45 | Fri 11:00 – Sat 04:45 |
| US regular session | 13:30 – 20:00 | 09:30 – 16:00 | 16:30 – 23:00 |
| S&P 500 scan | 12:50 | 08:50 | 15:50 |

From 1 November (EST, UTC−5), the same UTC times are an hour earlier in New York, so the scans run
3:00am – 8:45pm New York (11:00 – 04:45 Riyadh, unchanged).

## Verify that the scan actually ran

Open **Actions → StockWatch scan** → the run → **Summary**. A run that really scanned shows:
- **Holdings source:** `STOCKWATCH_PORTFOLIO secret` or `Google Sheet`, never `example file`
- **Analysed:** `N of N`, matching the number of tickers you hold
- **Latest daily bar:** today's or the previous trading day's date
- **New alerts:** a count
- **Delivery:** `telegram: sent`, or `nothing new to send`

The old job could finish green after skipping everything. That can't happen now: there's no skip
step, and the scan step itself reports.

Locally: `STOCKWATCH_DEMO=1 STOCKWATCH_PORTFOLIO="$(cat portfolio.yaml)" python -m stockwatch.ci_scan --mode holdings-dry-run`.
