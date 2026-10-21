# StockWatch

Keeps scanning your holdings and watchlist and flags **opportunities** (add / buy) and **risks** (trim / review / exit).
Every stock gets a **fundamental** and a **technical** score. The two are weighted by tier and checked against each other.

> Personal decision-support tool, not financial advice. Free Yahoo data can be delayed or incomplete.

## Quick start

```bash
pip install -r requirements.txt
cp portfolio.example.yaml portfolio.yaml        # edit with your positions

python -m stockwatch.scanner                    # continuous scanning (every 15 min by default)
streamlit run dashboard.py                      # dashboard at http://localhost:8501
```

Try it without network access: `python -m stockwatch.scanner --once --demo` and `STOCKWATCH_DEMO=1 streamlit run dashboard.py`.
The demo uses synthetic prices, so the numbers don't mean anything.

## Tiers

| | Tier 1 (core) | Tier 2 (tactical) |
|---|---|---|
| Score weighting | 65% fundamental / 35% technical | 40% fundamental / 60% technical |
| Hard stop vs cost | -25% | -12% |
| ATR trailing stop | 4× ATR | 2.5× ATR |
| Max portfolio weight | 15% | 7% |

You can change all of these in `portfolio.yaml`. Set `shares: 0` to put a ticker on the watchlist: it is scanned for entries only, with no stop or position alerts.

## What gets evaluated

**Technical** (`stockwatch/technical.py`): 50/200-day trend, golden and death crosses, losing or reclaiming the 200-day, RSI, MACD crossovers, Bollinger pullbacks, 52-week highs and drawdowns, volume surges, ATR trailing stop.

**Fundamental** (`stockwatch/fundamental.py`): four pillars.
- **Valuation:** forward P/E, PEG, analyst target upside, consensus
- **Growth:** revenue and earnings growth
- **Quality:** operating margin, ROE, free cash flow
- **Balance sheet:** debt/equity, current ratio

Missing data is skipped, not penalized.

**Combined rules** (`stockwatch/engine.py`), where the two sides check each other:
- Strong fundamentals + a technical entry trigger (oversold in an uptrend, pullback to the lower band, reclaiming the 200-day) → **quality entry: add / buy zone**.
- Weak fundamentals + a technical breakdown → **thesis breakdown**.
- Good fundamentals in a downtrend → possible **value trap**: wait for the trend to turn.
- Weak fundamentals with an overbought price → **momentum without support**.
- Trailing-stop hit on a strong stock still above its 200-day → downgraded to a **pullback** warning.
- Tier 1 stock with a fundamental score under 45 → **core fundamentals weak**.

**Relative strength** (`stockwatch/relative.py`): 1- and 3-month performance against SPY and the stock's sector ETF (XLK, XLV, ...).
Leading the market is a plus. Lagging SPY or the sector by more than 15% is flagged.
The dashboard also shows the market as RISK-ON / CAUTION / RISK-OFF, based on SPY's trend.

**Catalysts** (`stockwatch/catalysts.py`):
- **Earnings:** a warning 7 days before a report, and a note at 14 days.
- **Analyst moves:** upgrades, downgrades and Buy initiations from the last 10 days.
- **News:** headlines from the last 72 hours are checked for keywords. "Offering", "fraud" and "delisting" count as serious; "beats" and "raises guidance" count as positive. This is keyword matching, so treat it as a prompt to read the headline, not as sentiment analysis.

**Deep research** (`stockwatch/deepdive.py`). This adds information and low-urgency signals but doesn't change the scores.
- **Earnings track record:** the last 4 quarters' EPS against estimates, the current beat streak, and how the stock moved on each report day. The free data has no report dates, so the report day is estimated as the heaviest-volume session after each quarter closed. Also shows the revenue and margin trend over the last 5 quarters.
- **Smart money:** insider buying and selling over 90 days (open-market trades only), insider and institutional ownership, short interest as a % of float, days to cover, and the change since last month.
- **Valuation in context:**
  - P/E compared with the stock's own year-end history and with its industry leaders.
  - A fair-value range from three methods: analyst targets, own-history P/E and peer P/E. Methods that land implausibly far from the price are dropped, which usually means a stock split distorted the EPS history.
  - Nearest support and resistance, taken from swing highs and lows over the last year.

**Technical shifts** (`stockwatch/engine.py`): the technical score is compared with a week earlier. A swing of 20+ points raises its own alert whether or not the fundamentals changed. Fundamentals update quarterly and price action daily, so a breakdown or turn doesn't wait for both to agree.

**SEC filings** (`stockwatch/sec.py`), from SEC EDGAR's free API:
- **Filings list:** recent filings with links, and 8-K items translated into plain English.
- **Alerts:**
  - serious 8-K events: bankruptcy, delisting notice, restated financials, auditor change, impairment
  - offering registrations (S-1, S-3, 424B), which mean possible dilution
  - late-filing notices
  - activist 13D stakes
  - share-count growth over the last year (dilution), or a falling share count (buybacks)

SEC asks automated tools to identify themselves, so set `SEC_USER_AGENT` to your name and email (e.g. `"Jane Doe jane@example.com"`) in the Streamlit secrets and as a GitHub Actions secret.

**S&P 500 opportunity scan** (`stockwatch/market.py`, the **S&P 500** view or `python -m stockwatch.market`):
- **Stage 1** screens all ~500 constituents on price action using one bulk download, looking for a golden cross, reclaiming the 200-day, a pullback in an uptrend, a volume surge or a 52-week-high breakout.
- **Stage 2** runs the full fundamental and technical evaluation on the strongest 25 and ranks the buy setups.
- **The list of members** refreshes daily from a maintained list, with a bundled copy as a fallback.
- **Notifications:** with notifications configured, the GitHub job runs the scan every weekday before the open and pushes the top setups.

**Trade plan** (`stockwatch/tradeplan.py`): a rule-based plan for every stock, on its details page and as a one-line summary on each card.
- **Stance:**
  - for new entries: buy now / buy on a pullback / buy the breakout / wait for confirmation / no trade
  - for positions you hold: add / hold / trim / reduce or exit
  - A buy stance requires the engine's BUY SETUP verdict, so the plan never contradicts the verdict.
- **Entry zone and trigger:** the zone comes from the nearest support or moving average; breakouts use the pivot; otherwise the plan waits for a close above the 200-day.
- **Stop:** just below support when that's sensible, otherwise 2x ATR (Tier 2) or 3x ATR (Tier 1) below the entry.
- **Targets:**
  - Target 1 is the nearest of resistance, the 52-week high, fair value or the analyst target that pays at least 1.5x the risk (capped at 5x).
  - Target 2 is the next level up, or a measured move.
  - Reward-to-risk is shown for each.
- **Outlook and horizon:** bullish, neutral or bearish, with the level that proves the view wrong. Tier 1 plans are position trades (3–12 months); Tier 2 plans are swing trades (2–8 weeks).
- **When to sell:** the stop; take a third at Target 1 and move the stop to break-even; trail the rest under the 20-day (Tier 2) or 50-day (Tier 1) average; thesis-break exits; a time stop.
- **Position size:** shares chosen so that hitting the stop loses `risk_per_trade_pct` of the portfolio (default 1%, adjustable on the page), capped by the tier's maximum position size.
- **Warnings:** earnings within a week, or a big pre-market or after-hours move.

The levels are mechanical, from price structure and volatility. They're a consistent starting point, not a forecast.

The plan is then refined (`tradeplan.refine`) with three checks.

**1. Older scenarios** (`stockwatch/analogs.py`):
- **Matching:** finds past days in the stock's own 5-year history with the same trend state, a similar RSI and the same position relative to the 52-week high.
- **Replay:** applies the plan's stop and target distances forward from each matching day, counting nearby days as one episode.
- **Results:** how often the target came first, how often the stop came first, and the median days to the target.
- **Effect on the plan:**
  - The median days set the timeframe and the time stop.
  - A new entry where fewer than 40% of 10+ similar setups worked becomes "wait for confirmation".

**2. Earnings setup** (`stockwatch/street.py`). A favourable / mixed / unfavourable verdict scored from:
- the beat rate
- the direction of estimate revisions
- the average report-day reaction
- the run-up into the report against the market
- the valuation premium to peers

Options-implied moves are compared with the stock's usual reaction. Within a week of the report:
- **Unfavourable setup:** no new buying, and a Tier 2 position is flagged for trimming.
- **Favourable setup:** a half position before the report is reasonable.

**3. Where the company is heading:**
- **Street view:** buy/hold/sell counts and their change over 3 months, price targets, and EPS and revenue growth expected this year and next.
- **Estimate revisions:** the change over 30 and 90 days, plus how many analysts raised vs cut estimates this month.
- **Scenarios:** 3, 6 and 12-month bear / base / bull ranges with the probability of being higher. They use options-implied volatility (historical volatility as a fallback), and the base case blends the median target with a market-average return.
- **Effect on the plan:** these feed the bullish / neutral / bearish call. A negative street that is cutting estimates blocks new entries.

**Today's news** opens each details page, with each headline tagged positive, negative or neutral.

**Briefings** (`stockwatch/briefing.py`):
- **Each stock** gets a plain-English summary: why it has its verdict, what changed since the last scan, and what to watch next (earnings, key levels, the 200-day trigger, fair value, stops).
- **The Radar tab** opens with a portfolio-level mission brief.

**Live tracking:** while the market is trading (4:00am-8:00pm New York, weekdays), a background tracker in the app re-runs the full analysis every 2 minutes (technicals on today's live bar, verdicts, plans, alerts) and refreshes prices every minute in between (`STOCKWATCH_SWEEP_SECONDS` / `STOCKWATCH_QUOTE_SECONDS` to change). The page picks up new results within 30 seconds, pops up new important alerts, and marks cards whose verdict just changed ("NEW · was HOLD"). The same tracker runs the S&P 500 opportunity scan every 30 minutes while the market trades (`STOCKWATCH_MARKET_SECONDS`), on its own thread so the 2-minute tracking isn't held up; it doesn't rescan after a restart if the last scan is recent. Buy setups that weren't in the previous scan are marked NEW SETUP, logged, and popped up on screen. It runs while the app is awake; for alerts when nobody has it open, use the GitHub Actions notifications.

**Live prices:** while the market is trading (pre-market, regular hours, after-hours), prices refresh every 2 minutes while the page is open, and on page load when they're over 3 minutes old. During regular hours cards show the live price and today's change, marked LIVE. Outside regular hours they show the latest pre-market or after-hours trade. Scores, verdicts and plans still update on a sweep. It comes from Yahoo's quote, falling back to 1-minute and then 5-minute bars that include extended hours. **Log → System diagnostics** shows, for each stock, the session, the price, which source answered, and any problem.
Cards show `PRE` or `AH` next to the regular close, and the header shows the current session.
A move of 3% or more outside regular hours raises a signal; 5% or more on a stock you hold raises an alert (often an earnings reaction).
Scores and indicators still use regular-session prices.

**Position checks:** stop-loss vs cost, halfway-to-stop warning, target price reached, concentration.

**Verdicts:** `OPPORTUNITY - ADD`, `STRONG HOLD`, `HOLD`, `TRIM / REVIEW`, `RISK - REVIEW`.
Watchlist verdicts: `BUY SETUP`, `WATCH`, `AVOID`.

## Dashboard

Dark "mission control" theme, designed for phones first. Tap any stock (a card, a ticker in the brief, an S&P scan result) to open its details page. The views are:
- **Radar:** one card per stock, most urgent first. Filter by risk, opportunity, held or watchlist.
- **Details:** chart, every signal, readouts, SEC filings, analyst moves and news for one stock.
- **S&P 500:** the opportunity scan.
- **⚡ Turbo:** a quick decision on any ticker, without adding it to your list.
  - **The call:** BUY / WAIT FOR PULLBACK / WAIT FOR TRIGGER / PASS, with a confidence level and a one-line plan.
  - **How it's trading today:** the change, VWAP, volume compared with normal for the time of day, and how stretched the price is above its 20-day average in ATRs.
  - **Checks against the live price:**
    - Up 5%+ today and 2+ ATRs above the 20-day average: "don't chase", with a pullback zone and a stop below it.
    - Already past the entry zone: wait.
    - Already below the stop: pass.
  - **Speed:** a quick read appears first; the analyst, SEC and earnings-setup data then refine it.
- **Log:** the alert history.
- **Fleet:** add tickers (several at once, separated by commas) with a tier and share count, or remove them.
  Each new ticker shows a **company overview**: what the company does, its size and location, and a report card.
  The report card grades Valuation, Growth, Profitability, Balance sheet, Momentum, Earnings delivery and Smart money from A to F, with the evidence for each grade, then lists strengths and concerns.
  The same overview is available for any stock on the Target tab.

Fleet changes are saved in the app's database. On Streamlit Cloud that database is wiped on reboot or redeploy, so the Fleet tab shows YAML you can paste into the `STOCKWATCH_PORTFOLIO` secret to keep your changes.

## Alerts

Signals of severity 2 or higher are saved to `data/stockwatch.db` and sent out. The same alert for the same ticker won't repeat within `alert_cooldown_hours`.
Alerts always print to the console. Set these environment variables to also send them as a phone push (ntfy), by Telegram, or by email:

```bash
export NTFY_TOPIC=stockwatch-your-secret-topic
export TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=you@gmail.com SMTP_PASSWORD=app-password ALERT_EMAIL_TO=you@gmail.com
```

To scan 24/7, run the scanner as a service (systemd, `tmux`, or a small cloud VM). Or run `--once` from cron.

## Second data source: Finnhub (recommended on Streamlit Cloud)

Yahoo blocks its quote, analyst and ownership data for apps on Streamlit Cloud's shared servers. Prices and technicals still work, and fundamentals fall back to SEC filings, but analyst ratings, price targets, insider trades, the earnings calendar and news can come back empty.

Add a free Finnhub key to fill those gaps:
1. Sign up at finnhub.io (free) and copy your API key from the dashboard.
2. Add it as `FINNHUB_API_KEY = "..."` in the Streamlit secrets, and as a GitHub Actions secret if you use notifications.

Finnhub is used only when Yahoo doesn't return the data. It provides:
- analyst recommendation trends and price targets (if your plan includes them)
- earnings history and the next earnings date
- insider transactions
- key ratios
- company news

Requests are spaced to stay under the free plan's 60 a minute, and results are cached for hours. Short interest and institutional ownership need a paid plan on most providers. **Log → System diagnostics** shows whether the fallback is on.

## Ticker list in a Google Sheet

Keep your tickers in a Google Sheet so the dashboard and the notification job always read the same list.
The first tab needs a header row with `Ticker`, `Tier`, `Shares`, and optionally `Avg cost`, `Target price` and `Notes`.
A Shares value of 0 or blank puts the stock on the watchlist.

1. In the sheet, click **Share** and set General access to **Anyone with the link → Viewer**. The app reads the sheet without signing in, so the link works like a password: anyone who has it can see the list.
2. Add the sheet's link as `STOCKWATCH_SHEET_URL`:
   - in Streamlit (**Settings → Secrets**): `STOCKWATCH_SHEET_URL = "https://docs.google.com/spreadsheets/d/.../edit"`
   - in GitHub (**Settings → Secrets and variables → Actions**): a secret with the same name and value
3. Edit the sheet from anywhere, including the Google Sheets app on your phone. The dashboard picks up changes within a minute (or tap **Reload sheet now** on the Fleet tab), and new tickers get a company overview.

If the sheet can't be read, the app falls back to `STOCKWATCH_PORTFOLIO` (or `portfolio.yaml`) and shows a warning.
A "Publish to web → CSV" link also works instead of link sharing.

## Use it from your phone

You don't need a computer that stays on. This setup uses two free services:

### 1. Push notifications (ntfy + GitHub Actions)
The dashboard only scans while it's open. For alerts while your phone is in your pocket, a GitHub Actions job scans every 15 minutes on weekdays from 4am to 8pm New York time (pre-market through after-hours) and sends one grouped push per sweep.

1. Install the free **ntfy** app (iOS or Android). Tap **+** and subscribe to a topic name that's hard to guess, e.g. `stockwatch-<random letters>`. Anyone who knows the name can read the alerts, so treat it like a password.
2. In GitHub, open the repo → **Settings → Secrets and variables → Actions → New repository secret**. Add:
   - `NTFY_TOPIC`: the topic name from step 1
   - `STOCKWATCH_PORTFOLIO`: your holdings YAML (the same text as in the Streamlit secret)
3. Optional: under the **Variables** tab, add `DASHBOARD_URL` with your Streamlit app link, so tapping a notification opens the dashboard.
4. Test it: **Actions → StockWatch scan → Run workflow**. The schedule runs on its own after that.

Push priority follows severity. Urgent risks (stop hit, thesis breakdown) arrive as high-priority notifications; opportunities arrive as normal ones. The job does nothing until `NTFY_TOPIC` (or Telegram) is set.

**Things to know:**
- **Use the Google Sheet for your ticker list** (see above). The job reads the same sheet as the dashboard, so additions are scanned for notifications too. Without a sheet, the job reads only the `STOCKWATCH_PORTFOLIO` secret, and tickers added in the dashboard aren't scanned.
- **Don't also set `NTFY_TOPIC` in Streamlit,** or you'll get duplicate pushes when you sweep from the app.
- **GitHub pauses scheduled jobs after 60 days with no repo activity.** Re-enable it from the Actions tab.

Telegram works the same way: set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` instead of (or as well as) `NTFY_TOPIC`.

### 2. Dashboard on your phone (Streamlit Community Cloud)
1. Sign in at **share.streamlit.io** with GitHub. Click **Create app** and pick this repo, the branch, and `dashboard.py`.
2. Under **Advanced settings → Secrets**, add your portfolio:
   ```toml
   STOCKWATCH_PORTFOLIO = """
   holdings:
     - {ticker: AAPL, tier: 1, shares: 40, cost_basis: 165}
   """
   ```
3. Open the app URL on your phone. In your browser's share menu, choose **Add to Home Screen** to get an app icon. Tap **Scan now**, or turn on auto-scan.

## Tests

```bash
python -m pytest -q
```
