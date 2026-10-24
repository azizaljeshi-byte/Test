# US pre-market briefing (Briefing tab)

`stockwatch/premarket.py`, shown in the **☀ Briefing** tab. Display only: nothing here changes a score, status, call or alert.

## What it shows
- Where the market stands: S&P 500, Nasdaq 100, Dow, Russell 2000 (the ETFs SPY, QQQ, DIA, IWM) with the futures move (ES, NQ, YM, RTY) when there is one, and the last session.
- Macro: VIX, US 10Y yield, dollar (DXY), oil (WTI), gold, Bitcoin. A rising VIX or yield is coloured as pressure.
- The 11 sectors (SPDR ETFs), strongest first, with the sector's tracked names from your list.
- Your exposure by industry: owned positions grouped by sector as **percent only, never amounts**.
- Biggest moves (3% or more) among your tracked names: last session, and pre-market / after-hours / live.
- News on your tracked names (last 36 hours, owned first) and Finnhub market headlines.

## How it runs
One bulk price download for about 30 market symbols plus the scan snapshots the app already holds. It builds on its own thread (`premarket.request`), never inside the page, is reused for 5 minutes, and the page fills in by itself. A part that can't be built is listed under "Missing", never silently dropped. A bar dated today is treated as incomplete before the close, and always for futures and crypto.

## Limits (also shown on the page)
- Movers cover your tracked names, not the whole market.
- No economic calendar and no written reason per sector: the app can't research those by itself. The chat-based briefing still does that.
- Market headlines need `FINNHUB_API_KEY`; without it the page says so.
- Not checked against live Yahoo or Finnhub from the build environment.
- No scheduled Telegram digest yet (a weekday 8:55 New York message would need a GitHub Actions schedule and a market-holiday check).
