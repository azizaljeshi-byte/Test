# StockWatch: project handoff

This summarises the whole project so far, for picking it up in a new conversation. It describes the state as of
commit `b232d30` on branch `claude/stock-dashboard-alerts-rr9r83` (also the repo's default branch): 28 commits,
about 8,000 lines of Python, 128 passing tests. The README has the user-facing setup guide; this file covers what's
built, why, and what to watch out for.

## 1. What it is

A personal stock dashboard that keeps scanning a tiered portfolio and watchlist and flags **opportunities** (add, buy)
and **risks** (trim, review, exit). Every stock gets a fundamental score and a technical score, and the two are checked
against each other. On top of that, every stock gets a plain-English briefing and a rule-based trade plan.

- **Owner's setup:** about 15 holdings plus about 34 watchlist names (49 tickers in total), kept in a Google Sheet.
- **Where it runs:** on Streamlit Community Cloud, used mainly from a phone.
- **Phone alerts:** sent through ntfy by a GitHub Actions job.
- **Style:** a dark "mission control" theme, made warmer and more human on request.

## 2. Features (each one a user request, in the order added)

1. **Tiered portfolio.**
   - Tier 1 is core holdings: fundamentals weigh 65%, stop at -25%, maximum 15% of the portfolio.
   - Tier 2 is tactical holdings: technicals weigh 60%, stop at -12%, maximum 7%.
   - `shares: 0` means the stock is watchlist-only.
2. **Technical analysis.**
   - Indicators: 50/200-day trend and crosses, RSI, MACD, Bollinger bands, 52-week high/low, volume surges, and an ATR trailing stop.
   - Relative strength against SPY and against the stock's sector ETF.
   - A "technical shift" alert when the technical score swings 20+ points in a week, whatever the fundamentals do.
   - The score is a smooth curve with no hard 0 floor, and the Details page shows a per-factor breakdown ("Why the technical score is N").
3. **Fundamental analysis.**
   - Four pillars: valuation, growth, quality and balance sheet.
   - **Missing data counts as unknown, never as bad.** With fewer than 3 measures, fundamentals are "unavailable": the composite uses technicals only and no fundamental alerts fire.
4. **Combined rules.** Quality entry (strong fundamentals plus an entry trigger), thesis breakdown, value-trap watch, momentum without support.
5. **Catalysts.**
   - The next earnings date: a warning at 7 days and a note at 14.
   - Analyst upgrades and downgrades.
   - News headline keywords. "Offering" counts only as a share sale, not a product offering.
6. **Deep research.**
   - **Earnings track record:** beats and misses, plus the report-day move. The report day is estimated as the heaviest-volume day after each quarter closes.
   - **Smart money:** insider buys and sells (open-market trades only), ownership and short interest.
   - **Valuation in context:**
     - P/E compared with the stock's own history (split-distorted history is dropped) and with peers
     - a fair-value range from analyst targets, own-history P/E and peer P/E
     - support and resistance from swing highs and lows
7. **SEC EDGAR (free, no key).**
   - **Filings:** a list of recent filings, with 8-K items translated into plain English.
   - **Alerts:** serious 8-K items, offering registrations (dilution), late filings and activist 13D stakes.
   - **Share count:** the change over a year, with common split ratios recognised so splits aren't reported as dilution.
   - **Fallbacks:** fundamentals computed from XBRL company facts (trailing twelve months as YTD + last fiscal year - prior YTD) when Yahoo refuses, and the next earnings date estimated from the results 8-K a year earlier.
8. **Street view and outlook (3-12 months).**
   - Consensus and its change over 3 months, price targets, expected EPS and revenue growth, and estimate revisions. Revision direction never contradicts its own evidence.
   - Options-implied moves.
   - Bear/base/bull ranges at 3, 6 and 12 months with the chance of being higher. The base case blends the median target 50/50 with a market-average return.
   - An earnings setup verdict (favourable / mixed / unfavourable) with its reasons.
9. **Trade plan** (`tradeplan.py`).
   - **Stance:**
     - new entries: buy now / buy on pullback / buy the breakout / wait for confirmation / no trade
     - holdings: add / hold / trim / trim-protect / reduce-exit
     - Buy stances require the engine's BUY SETUP verdict.
   - **Levels:** an entry zone and trigger; a structural or ATR stop; Target 1 (the nearest level paying at least 1.5x the risk, capped at 5x) and Target 2; reward-to-risk.
   - **Selling:** exit rules (stop, a third at Target 1, then trail, thesis exits, a time stop) and position sizing from a per-trade risk budget.
   - **Refined by** (`refine`):
     - **Older scenarios** (`analogs.py`): similar past setups in the stock's own history are replayed with the plan's stop and target, giving a hit rate, a timeframe and the time stop.
     - **The earnings setup.**
     - **The forward view.**
   - **Reconciled by** `reconcile`: a trailing-stop hit on a stock whose bigger picture is bullish becomes TRIM / PROTECT, not exit.
10. **Briefings.** Per stock: why the verdict, what changed since the last scan, what to watch next. Plus a portfolio "mission brief", a company overview and an A-F report card.
11. **S&P 500 scan** (`market.py`).
    - **Universe:** constituents refreshed daily from a maintained list, with a bundled copy in `stockwatch/universe/sp500.csv` that includes CIKs.
    - **Stage 1:** a technical screen of every member from one bulk download.
    - **Stage 2:** a light full evaluation of the top 25.
    - **Live:** runs automatically every 30 minutes; new setups are marked NEW SETUP and logged.
12. **Turbo** (`turbo.py`). A quick decision on any ticker without tracking it:
    - **The call:** BUY / WAIT FOR PULLBACK / WAIT FOR TRIGGER / PASS, with confidence.
    - **Today's momentum:** move, VWAP, relative volume for the time of day, and extension in ATRs.
    - **Live-price checks:** don't chase, ran past the zone, below the stop.
13. **Live tracking** (`live.py`). While the market trades (4:00am-8:00pm New York, weekdays):
    - **Analysis:** a background thread re-runs the full analysis every 2 minutes.
    - **Prices:** refreshed every 1 minute, all tickers in one bulk download.
    - **S&P scan:** every 30 minutes, on its own thread.
    - **The page:** polls a watermark every 30 seconds, reloads when results land, shows toasts for new alerts, and marks changed verdicts "NEW · was X".
14. **Prices.**
    - **Source:** live and extended-hours prices come from Yahoo minute bars (pre/post-market included).
    - **Session:** decided by the New York clock, not Yahoo's `marketState`, which lags.
    - **On the cards:** PRE / AH, or "AH (last night)", outside regular hours; LIVE with the time during regular hours.
15. **Notifications.**
    - **Channel:** ntfy pushes (and optionally Telegram or email).
    - **Schedule:** a GitHub Actions job every 15 minutes from 4am to 8pm New York, plus a daily S&P scan push at 12:50 UTC.
    - **Skipped:** the job does nothing until `NTFY_TOPIC` or Telegram is set.
16. **Ticker list from a Google Sheet.**
    - **Source:** the "StockWatch Holdings" sheet in the owner's Drive, link-shared as Viewer. Columns: Ticker, Tier, Shares, Avg cost, Target price, Notes.
    - **Readers:** both the app and the GitHub job read it.
    - **New rows:** get an automatic company overview in the Fleet tab.
    - **Fallback:** the YAML list.
17. **Navigation.**
    - **Driven by the URL:** `?view=radar|turbo|target|market|log|fleet&t=TICKER`, so cards, brief tickers and scan results link to Details.
    - **Radar filters follow card verdicts and show counts:** Risk, Opportunity, Hold, Held, Watch.
19. **Radar scope** (`ui.radar`, `ui.ring`, `ui.rows`). The Radar tab opens on a round scope with one dot per stock:
    - **Direction is the card verdict:** buy zone at the top, risk bottom-left, hold/watch bottom-right. Wedges widen with their count.
    - **Distance is how soon it needs you** (`ui.ring`):
      - **Act now (middle):** an urgent risk signal, a reduce/exit plan on a risk verdict, a buy verdict inside its entry zone, or earnings within 2 days.
      - **Getting close (dashed ring):** a buy verdict within 3% of its zone, an owned stock within 3% of its stop, a trim plan, or earnings within 7 days.
      - **Nothing to do (edge):** everything else. These dots have no labels, to keep the phone view readable.
    - **Reasons never contradict the verdict:** a buy zone only counts on a buy verdict, and an exit only on a risk verdict. A missing price makes no claim.
    - **Dots:** filled means owned, hollow means watchlist. Act-now buy and risk dots pulse. The filter fades dots instead of removing them.
    - **Tapping a dot previews it** under the scope: the same row as the list, plus "Close" and "Open full details →".
      - **How it works:** pure CSS with hidden radio inputs, one per ticker, plus generated `:checked` rules, so there's no rerun and it's instant.
      - **Don't put `checked` on any radio:** Streamlit renders markdown HTML through React, which turns a pre-checked radio into a locked, controlled input, so taps do nothing.
      - **When it resets:** the preview closes whenever the fragment redraws (a filter tap or a fresh sweep).
    - **The list:** the old cards are now one row per stock, act-now first. Details still shows the full card.
      - **The call on top** (`ui.action`), from the plan stance: BUY NOW / BUY ON DIP / BUY ON BREAKOUT / BUY MORE / WAIT / HOLD / SELL SOME / SELL / PASS.
      - **No selling a watchlist name:** a sell or trim on a watchlist name reads PASS.
      - **Don't sell into a bounce** (`ui.reassess`): a SELL or SELL SOME becomes **REASSESS** in two cases. The decision then moves to the close, with one level to watch.
        - **Stop retaken:** the trailing stop that triggered the sell is back below the live price (pre/after-hours prices count).
        - **Strong rebound:** the stock is up 3% or more today.
        - **On Details:** a "Reassess before selling" banner, so both pages give the same answer.
        - **Unchanged:** the plan is shown as "IF IT FAILS". The engine verdict and the phone pushes don't change.
      - **Below the call:** the price, why it sits where it does, and the plan. The "OWNED · T1" tag shows only on holdings.
18. **Diagnostics** (Log → System diagnostics).
    - **Status shown:** code version, New York time and session, data source, ticker list source, and whether the Finnhub fallback is on.
    - **Per-stock table:** quote source and errors, and whether fundamentals are "ok" or "blocked".
    - **Buttons:** "Test Finnhub key" and "Fetch raw quote".

## 3. Code map

| File | Role |
|---|---|
| `dashboard.py` | Streamlit app: header, hero, tiles, views, live watcher, tracker startup |
| `stockwatch/engine.py` | `evaluate()` for one ticker (everything comes together here); `scan()` for the portfolio |
| `stockwatch/data.py` | `YahooProvider`, `DemoProvider`, `CachedProvider` (cache with TTLs, deduplicates concurrent fetches), quote and bar parsing, Yahoo throttle |
| `stockwatch/technical.py` / `fundamental.py` / `relative.py` | the scores |
| `stockwatch/catalysts.py` / `deepdive.py` / `street.py` / `sec.py` / `analogs.py` | the signal layers above |
| `stockwatch/tradeplan.py` / `turbo.py` / `briefing.py` | turning analysis into decisions and plain English |
| `stockwatch/market.py` | S&P 500 scan (`python -m stockwatch.market [--demo] [--notify]`) |
| `stockwatch/live.py` | background tracker, sweep and market-scan locks |
| `stockwatch/scanner.py` | `run_once`, `refresh_quotes`, CLI (`python -m stockwatch.scanner [--once] [--demo]`) |
| `stockwatch/store.py` | SQLite: snapshots, alerts (deduplicated by ticker+code within a cooldown), ticker overrides, market scans, watermark |
| `stockwatch/notify.py` | console / ntfy / Telegram / email |
| `stockwatch/finnhub.py` | Finnhub fallback client (paced under 60 requests a minute) |
| `stockwatch/sec_audit.py` | read-only SEC financial-data audit (valuation Phase 1, `docs/SEC_DATA_AUDIT.md`); not imported by the app |
| `stockwatch/sec_quality.py` | read-only SEC data-quality checks: selection provenance, revisions, stale and conflicting figures, checks against the filing (Phase 1B, `docs/SEC_DATA_QUALITY.md`); not imported by the app |
| `stockwatch/valuation_lab.py` | read-only valuation research: which model fits each company and why, reverse valuation and cash runway, gated on Phase 1B data quality (Phase 2A-1, `docs/VALUATION_RESEARCH.md`; assumptions in `valuation_assumptions.yaml`); not imported by the app |
| `stockwatch/config.py` | portfolio loading: Google Sheet, then `STOCKWATCH_PORTFOLIO` secret, then `portfolio.yaml`, then `portfolio.example.yaml` |
| `stockwatch/ui.py` | all CSS and HTML builders (cards, panels, tables, ladders) |
| `.github/workflows/scan.yml` | scheduled scan and push job, plus the daily S&P job |
| `.github/workflows/sec-audit.yml` | manual-only job that runs the SEC data audit on example tickers |
| `tests/test_stockwatch.py` | 128 tests: pure functions, fake providers, fake Yahoo/SEC/Finnhub responses |

**Data flow:** the provider fetches (cached), `engine.evaluate` builds an `Evaluation` (scores, signals, research,
plan), `store.save_snapshot` writes JSON to SQLite, and the dashboard reads only the store. Alerts of severity 2 or
higher go into the alerts table and out through `notify`.

## 4. Data sources and their quirks (read before debugging "missing data")

| Source | Used for | Notes |
|---|---|---|
| Yahoo via `yfinance` 1.7 | prices (daily and minute bars), fundamentals, analyst data, news, calendar, options | **Streamlit Cloud's shared servers get Yahoo's token ("crumb") throttled**: HTTP 429 on the token, then 401 on quote, fundamental and analyst endpoints. Chart (price) data keeps working. Mitigations: at most 3 requests in flight, retries for "database is locked", bar-based quotes, near-empty fundamentals raise instead of being cached |
| SEC EDGAR | filings, share counts, fundamentals fallback, earnings-date estimate | free; at most 4 requests in flight. Set `SEC_USER_AGENT` to a name and email (Streamlit **and** GitHub): without it requests use a generic identifier, SEC may refuse some, and the app warns once in its logs (`sec.user_agent_status()`). A value entered over two lines is joined into one. Ticker → CIK: the bundled S&P list first, then SEC's full ticker list (daily). A failed download is retried after 10 minutes rather than cached, and `sec.cik_lookup` says why a ticker has no CIK |
| Finnhub (free key) | fallback for analyst ratings, targets (if the plan allows), earnings history and calendar, insiders, key ratios, news | `FINNHUB_API_KEY`; requests paced 1.05 seconds apart; short interest and institutional ownership need a paid plan |
| GitHub raw (datasets/s-and-p-500-companies) | S&P 500 constituents | refreshed daily, bundled copy as fallback |
| Google Sheet (CSV export) | the ticker list | needs link sharing, or "Publish to web" as CSV |

Fundamentals precedence: Yahoo first, then Finnhub (card label `FUND·FH`), then SEC (`FUND·SEC`). Results that came
back empty are cached until their TTL runs out, so **reboot the app after adding a key**.

## 5. Configuration (names only; the values live in the Streamlit and GitHub secrets)

| Setting | Where | Purpose |
|---|---|---|
| `STOCKWATCH_SHEET_URL` | Streamlit + GitHub | Google Sheet with the ticker list |
| `STOCKWATCH_PORTFOLIO` | Streamlit + GitHub | YAML holdings; backup list when the sheet can't be read |
| `FINNHUB_API_KEY` | Streamlit (+ GitHub) | second data source |
| `SEC_USER_AGENT` | Streamlit + GitHub | "Name email" for SEC requests |
| `NTFY_TOPIC` (+ optional `NTFY_SERVER`, `NTFY_TOKEN`), `DASHBOARD_URL` (variable) | GitHub | phone pushes; don't also set it in Streamlit, or pushes arrive twice |
| `TELEGRAM_*`, `SMTP_*`, `ALERT_EMAIL_TO` | optional | other notification channels |
| `STOCKWATCH_SWEEP_SECONDS` / `_QUOTE_SECONDS` / `_MARKET_SECONDS` | optional | live tracker intervals (120 / 60 / 1800) |
| `STOCKWATCH_DEMO=1` | local | synthetic offline data |
| `portfolio.yaml` `settings` / `tiers` | file or secret | intervals, cooldown, `risk_per_trade_pct`, tier weights, stops, maximum position size |

**The repo is public:** never commit keys, the ntfy topic, the sheet link or holdings.

## 6. Running and testing

```bash
pip install -r requirements.txt
python -m pytest -q                                   # 128 tests, no network needed
STOCKWATCH_DEMO=1 streamlit run dashboard.py          # offline UI with synthetic data
python -m stockwatch.scanner --once --demo            # one sweep from the CLI
python -m stockwatch.market --demo                    # S&P scan from the CLI
```
On Streamlit Cloud the app deploys from this branch with main file `dashboard.py`. After code changes, use **Reboot app**:
cached objects are keyed on a hash of the code, but a reboot also clears data caches. UI changes were verified with
Playwright screenshots at phone width (390px).

## 7. Decisions and lessons worth keeping

- **Unknown is not bad.** Blocked or missing data must never score as zero: mark it unavailable and say why on screen.
- **Use one consistent answer.** When signals conflict (exit vs bullish, buy vs watch, estimates up vs down), reconcile them or show none, never both.
- **Don't trust Yahoo's `marketState`.** Use the New York clock and trade timestamps.
- **Streamlit reruns.**
  - **Keep button results:** the page auto-reloads when the tracker lands results, so long actions and button results must be captured in `on_click` callbacks or session state, or run on the tracker thread.
  - **Key caches on the code:** `cache_resource` objects are keyed on `CODE_VERSION`, so deploys don't keep running old classes.
  - **Fill the page in during a slow first sweep:** Streamlit Cloud wipes the database on every reboot, and with Yahoo refusing data the first sweep of 49 stocks takes minutes.
    - **Each stock shows as it lands:** `engine.scan(on_ready=...)` hands each result over as it finishes, and `run_once` saves stocks with nothing on screen straight away. Their final save then replaces that early copy (`Store.replace_latest`), keeping one snapshot per sweep for the "what changed" comparisons.
    - **Progress on the page:** "N of 49 stocks ready".
    - **S&P scan waits:** it doesn't start until the first portfolio sweep is done.
  - **Stop the page from waiting:** heavy work belongs in the background tracker, and the page only reads the store. The page never queues for Yahoo: the Market tile and Details chart read the tracker's last copy (`CachedProvider.peek_history`), and Sweep now starts a background thread. With Yahoo throttled after a reboot, an inline fetch left the page blank for minutes. Use fragments for parts that redraw often (the Radar filter list).
- **Respect the free limits:** Yahoo throttled to 3 requests in flight, SEC to 4, Finnhub paced under 60 a minute, plus caching. Bulk downloads for many tickers.
- **The plans are mechanical** (structure plus ATR), refined by the stock's own history. They're a decision aid, not advice, and the app says so.

## 8. Known limits and open items

- Yahoo throttling on Streamlit Cloud can return. Check diagnostics: "blocked" fundamentals, quote errors.
- The live tracker only runs while the free Streamlit app is awake. The GitHub job covers alerts while it sleeps.
- Market holidays aren't modelled: on a holiday the session label is wrong, though the prices are right.
- Report days in the earnings track record are estimated; peers are industry giants (Yahoo's industry leaders).
- No overnight (24-hour) session data; Yahoo has none.
- Short interest and institutional ownership are missing whenever Yahoo is blocked (paid on Finnhub).
- In the owner's data: NVDA (~25%) and GOOGL (~20%) are above the Tier 1 limit of 15%, so either accept that or raise `max_position_pct`. Several small caps (ONDS, RDW, SPAI, COSM, RR) show RISK - REVIEW for real reasons: trailing stops hit, cash burn, dilution.

## 9. Ideas discussed but not built

- **"What to do today":** a ranked action list.
- **Daily digest pushes:** before the open and after the close.
- **Signal backtest:** how past verdicts and alerts actually performed.
- **Portfolio view:** an X-ray (sector, size, correlation) and a risk meter.
- **Performance tracking:** returns against SPY.
- **Personal price alerts and notes**, plus comparing two stocks side by side.
- **AI analyst:** a written opinion on any stock (needs a Claude API key).
- **Broker import,** plus average costs in the sheet, which would turn on P&L and cost-based stops.
- **Holidays:** a market-holiday calendar.
