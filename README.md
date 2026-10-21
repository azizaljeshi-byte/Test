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

**Position checks:** stop-loss vs cost, halfway-to-stop warning, target price reached, concentration.

**Verdicts:** `OPPORTUNITY - ADD`, `STRONG HOLD`, `HOLD`, `TRIM / REVIEW`, `RISK - REVIEW`.
Watchlist verdicts: `BUY SETUP`, `WATCH`, `AVOID`.

## Alerts

Signals of severity 2 or higher are saved to `data/stockwatch.db` and sent out. The same alert for the same ticker won't repeat within `alert_cooldown_hours`.
Alerts always print to the console. Set these environment variables to also send them by Telegram or email:

```bash
export TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=you@gmail.com SMTP_PASSWORD=app-password ALERT_EMAIL_TO=you@gmail.com
```

To scan 24/7, run the scanner as a service (systemd, `tmux`, or a small cloud VM). Or run `--once` from cron.

## Use it from your phone

You don't need a computer that stays on. This setup uses two free services:

### 1. Alerts on your phone (Telegram + GitHub Actions)
1. In Telegram, message **@BotFather** and send `/newbot`. Follow the steps and copy the **bot token** it gives you.
2. Send any message to your new bot. Then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the `chat` → `id` number.
3. In GitHub, open the repo → **Settings → Secrets and variables → Actions → New repository secret**. Add three secrets:
   - `TELEGRAM_BOT_TOKEN`: the bot token
   - `TELEGRAM_CHAT_ID`: the chat id
   - `STOCKWATCH_PORTFOLIO`: the full text of your `portfolio.yaml` (paste it in)
4. Go to **Actions → StockWatch scan → Run workflow** to test it. After that it runs every 15 minutes during US market hours and messages you when something new happens.

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
