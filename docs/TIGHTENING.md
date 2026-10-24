# Tightening ideas (recorded, NOT built)

The owner asked to record these and not implement them until the current build has been tested and we know what is
missing. Nothing here is live. Entry and sell rules are methodology: each item below would be its own pull request,
marked as requested by the owner, with a before-and-after list of the calls it changes.

## 1. Entries that are not falling knives (owner: "an entry not in a falling knife")
Today the plan's entry zone is the highest of the nearest support, the 20-day and the 50-day average within 3 ATR below the
price, plus half an ATR (`tradeplan.build`). A stock that is only testing support, with falling momentum and a SELL from
TradingView, can still read BUY MORE (seen on INTC, 2026-10-24); only a confirmed breakdown blocks a buy.

Proposed gates, a BUY or ADD shows only when all pass, otherwise WAIT with the missing condition as the trigger:
1. Structure: strong uptrend, pullback or record high (weakening, testing support and breakdown all block).
2. Momentum: strong, building or stabilising; falling, weak, fading or distribution block.
3. The turn has happened: the last completed close is back above the 20-day average or above the previous session's high.
4. Zone quality: the zone sits on a HIGH or MEDIUM graded support zone (`zones.py`) or the 50 or 200-day average.
5. Independent check: TradingView is not SELL and the Stooq price check does not disagree.
Open choice: strict (all five) or moderate (1 to 3 block, 4 and 5 show as warnings).

Interim display fix, also not built: when the Day Board's gauge contradicts a BUY (the card shows UNCLEAR), show WATCH
with the reason instead of a BUY card.

## 2. Selling is harder than buying (owner)
A drop does not say why it is dropping, and the right move depends on the cause. The app already labels the cause
(`momentum.py`: event-driven, market-wide, sector-wide, distribution, drift) and the old rows showed it on a FLOW line; the
Day Board moved it into the opened card. The news feed (`newsfeed.py`) now adds the missing piece, a HOT story next to the drop.
- Restore the cause on the closed sell and trim cards ("Why: distribution (sustained selling)") and add the top news line.
- A sell-read beside it: SELL STANDS for distribution, drift or critical news; CHECK FIRST for an event with no clear news,
  or a market-wide move. Display only first; the sell call, stops and alerts do not change.
- The existing "don't rush" rule (a sell waits for the close when the stock is bouncing or has retaken its stop) stays.
- Any later change to a sell rule is its own pull request and only if the owner asks, after watching how cause and
  outcome line up over a few weeks.

## 3. Plain-English legends (owner, 2026-10-24), design for later
Recorded only. Not built until testing is finished, and best done in the design session.

**Gauge line.** The gauge on each card repeats "BAD" three times (call, gauge word, end label), which is confusing. Replace it
with a line with a lightning bolt marking where the stock stands. Four samples were shown (A bolt on a gradient line with a
tag above, B five named steps Bad / Weak / Neutral / Good / Strong with the current one lit and each word shown once, C a
zig-zag lightning line with a dot, D a fill-from-left power line with the bolt at the tip). The owner chose A (2026-10-24). Alongside it, the owner wants less on the card: fewer lines and labels, so the call, the line and the plain-English zone
recommendations carry the meaning (what to remove is decided in the design session). Known sample faults to fix in the build: the tag in A touches the reason text, and the left label in D touches the bolt.

**Zone grades.** Drop the HIGH / MEDIUM / LOW badges on support and resistance zones. Show one plain-English recommendation
per zone instead, from a single legend that is the same on every card (a universal legend). Wording to draft and test, for example:
- Support: "Likely to hold: a good place to buy" / "May hold: buy small" / "Weak: don't count on it".
- Resistance: "Likely to stop a rise: a good place to sell" / "May stop a rise" / "Weak: price may pass through".
The grading in `zones.py` (HIGH 4 or more points, MEDIUM 2 to 3, LOW otherwise) stays underneath; only the words on screen change.
Keep the reasons line (touches, round number, heavy volume, age) as the proof. Samples of the wording are still to be shown.

## 4. Say why a check was skipped (owner, 2026-10-24), small fix for after testing
The Day Board shows "Price data not re-checked" with no reason. The reason already exists in `stooq.check` ("Stooq could not be
reached", "Stooq has no daily prices for this ticker", "only N sessions overlap"), but `dayboard._data` drops it. Show the
reason on the line, and do the same for any other skipped check, per the rule that missing data is unknown and says why.
A skipped check is not counted, so the count reads "5/5 sure", not "6/6".

## 5. A WATCH card with a BAD gauge (owner, 2026-10-24), found on a sub-dollar stock
That card shows WATCH (yellow, "be careful") while the gauge reads BAD and the checks list breakdown, falling momentum and a
TradingView SELL. Cause: the sell call is held back by the "don't rush" rule (`ui.reassess`: the stock bounced +3.2% in the
last session, so the app waits for the close below the trailing stop before selling), and `dayboard.word` returns WATCH for it.
The gauge and the checks do not know about that wait, so the card gives two answers, against the rule to never show conflicting
answers. The checks also show dashes for all six because they are scored against a WATCH call.
Proposed, for after testing: when the word is WATCH only because a sell is waiting for the close, say so in the word
("WATCH · SELL IF IT CLOSES BELOW 0.33"), keep the gauge as is, and score the checks against the held sell so they show ticks.
No change to the sell rule itself.

## 6. Go back toward the previous list design (owner, 2026-10-24), for the design session
After using the deployed Day Board, the owner finds the previous design (the Radar rows, `ui.radar` and `ui.rows`, still in the
code but unused) better for information and for listing the stocks. The "All calm" chips show only a ticker and a percentage,
with no price and no reason. Recorded for the design session after testing. The owner will send samples of how he likes to see
the cards, and those samples, not the current Day Board, are the starting point. Keep from the Day Board only what he still wants
(for example the call word, the plain-English zone recommendations and the lightning-line gauge A).

## 7. The agreed card design: Yahoo-style list (owner, 2026-10-24), for the design session after testing
Samples were shown and the owner approved the look. Only the description is recorded here (the sample pages use his real
tickers, so they stay out of the public repo). This replaces the Day Board list and cards in section 6.
- **Closed card (a row).** Ticker and company name, a small price chart, price, and a coloured change pill, as on Yahoo
  Finance. The whole card is tinted by status: red ACT, green BUY, amber WATCH, blue CALM, with a coloured left edge. One call
  word as a small tag (SELL SOME, SELL BELOW 0.33, WAIT, BUY MORE, HOLD), one plain reason line, and an alerts bell in the
  corner (filled = alerts on, outline = off). Where the call is WATCH only because a sell is waiting for the close, the tag says
  what it waits for (section 5).
- **Opened card (tap the row).** Header with the call, price and reason; the lightning-line gauge (version A: one tag, ends
  "Weak" and "Strong"); "How sure": the count of agreeing checks, a bar, the six checks with ticks, and the real reason for any
  skipped check (section 4); support and resistance zones with the plain-English recommendations instead of HIGH / MEDIUM / LOW
  (section 3); the plan in two lines; the top news item with its tier; the bell for that stock.
- **Below the list.** "Your top movers" (bars for the day's biggest moves among his stocks) and "Upcoming events", a calendar
  by date (earnings and similar) where each event is tinted by status and has its own bell.
- **Two themes.** Dark (matches the app) and light (like Yahoo). The owner can switch between them and wants to be able to
  change the look as he likes, so keep colours as named variables in one place and let him choose the theme, and later which
  lines show on the closed card and how the list is sorted. The choice is kept per device, no keys or accounts.
- **Kept rules.** One answer per card (no conflicting words), missing data shown as unknown with the reason, plain English, short
  labels, tappable links, phone width (390 px) first, tint plus the call word so colour is never the only signal.
- **Order of work.** Test the current build first; then build the list and closed card, the opened card, then movers and
  events, then the theme switch. Display only: no change to scoring, calls, stops or alerts.

## 8. Tabs: hide Fleet and Research, apply the design everywhere (owner, 2026-10-24), for after testing
Recorded only; the owner asked to write it down and keep the change for later. The tab change was tried on a throwaway branch
and dropped, so none of it is in the code.
- **Hide Fleet and Research** from the tab bar (Radar, Turbo, Details, S&P 500, Log and Briefing stay). Plan: a `HIDDEN_VIEWS`
  tuple in `dashboard.py`, the segmented control built from the other views, and the pages still opening at `?view=fleet` and
  `?view=research` (checked: both render). The two hints that say "Add it on the Fleet tab" (Details and Turbo) become a tappable
  "Fleet page" link to `?view=fleet`. Without that link there is no way to add or remove a ticker in the app, so keep it.
- **Tab bar colours (owner, 2026-10-24).** The tabs use the same colours as the cards and both themes, from the same named
  colour variables: dark or light surface, the selected tab filled in the accent colour, the rest muted. No separate palette for the bar.
- **Same design across the entire app (owner, 2026-10-24).** Not only Radar: every tab and page takes the agreed card look,
  both themes and the same colours: Radar (dot map and list), Turbo, Details, S&P 500, Log, Briefing, and the hidden Fleet and
  Research pages when opened. The Details page (seen on a stock with an AVOID badge, FUND / TECH / ALL bars, a WEAKENING box and
  a stack of notes) becomes the opened card of section 7: call, gauge line, how sure, zones, plan, news, in that order, with the
  two explanation blocks kept (see the next point). One stock looks the same wherever it appears. Build from shared pieces (status colours, call tag,
  price and change pill, bell, gauge line, zone row, news line) so each tab reuses them, one tab per pull request.
- **Keep the explanation blocks (owner, 2026-10-24: "I like these comments, very good").** On Details, the structure block (for
  example WEAKENING: the close is below the 50 and 200-day averages, why a breakdown cannot be confirmed, "Not owned: nothing to exit",
  plus the TradingView and Stooq lines) and the momentum block (for example FALLING, distribution: the heavy-volume days, the
  volume ratio, RSI, MACD, market and sector moves, the as-of date) are valued and stay in the redesign. They are not removed
  or folded away when the card gets shorter: they move onto the opened card as two "why" blocks in the new look, in plain
  English, and the closed card stays short. Any text trimming in the design session must not lose their reasons.
- **Two levels, and a Details button (owner, 2026-10-24).** Tapping a card opens it in place (the summary and the two "why"
  blocks). A "Details" button on the opened card goes to the full Details page for that stock (the tappable link
  `?view=target&t=TICKER`), which shows everything: scores, the six sections (Overview, Key levels, Analysis & numbers,
  Scenarios, Past reactions, What changes), the news with every source, and the history. The Details page gets the same look
  and keeps all of its content; nothing there is removed in the redesign.
- **Icons on every comment line (owner, 2026-10-24, chose design B).** Each line of Why, Changed and Watch next gets an icon on a
  small colour chip and a lightly tinted bar with a coloured left edge: green ▲ good for the stock, red ▼ bad for the stock,
  amber ! be careful, blue i just so you know, with a four-item key at the top. The icon comes from the type of line the app
  already produces (risk, opportunity, key level, trigger, warning), not from reading the words; a line that mixes good and bad
  takes the worse side. The words do not change.
- **Details page layout, approved (owner, 2026-10-24).** Top to bottom: section pills (Overview, Key levels, Analysis & numbers,
  Scenarios, Past reactions); header card with price, change, after-hours, bell, call, one plain sentence, the gauge line and the
  scores; How sure (with the reason for any skipped check); the structure and momentum blocks; Why, with icons; Where it may stop
  or turn (only true levels; "None found" with the reason when there is no support); Plan; Changed; Watch next; Calendar; News;
  buttons (full numbers, back to Radar).
- **Calendar (owner, 2026-10-24).** On Details, a Today-to-event line and event rows (date block, title, one line, a bell for
  that event), past events dimmed. Shows only events the app already knows (earnings, ex-dividend, upgrades and downgrades,
  filings), nothing invented. The same events feed the Upcoming events list on Radar.
- **Key levels / technical evidence page (owner, 2026-10-24, modelled on a phone Technical screen from Investing.com).** Under
  the Key levels pill: a technical summary (one verdict with a sell / neutral / buy bar and counts); our graded zones first; pivot
  points (R3 to S3, Classic and Fibonacci, from the last session, resistance red, support green); moving averages (MA5, 10, 20, 50,
  100, 200, simple and exponential, each value with Buy or Sell by price above or below); and an indicator table with value and
  plain read: RSI (14), Stochastic (9,6), StochRSI, MACD (12,26), ADX (14), Williams %R, CCI (14), ATR (14), Highs/Lows (14),
  Ultimate Oscillator, ROC, Bull/Bear Power (13). The owner wants these because they back up the call with visible evidence.
  - Oversold and overbought show amber ("a bounce is possible"), not Buy or Sell; ATR is volatility, not a direction.
  - **The summary counts as one check in the "x/6 sure" total, not as 12 or 14.** These indicators mostly measure the same
    thing (trend and momentum), so counting each one would inflate confidence (`docs/INDICATORS.md`, Principle). It is the same
    kind of read as the TradingView rating we already use as a second opinion, and the table shows what is behind it.
  - Computed by the app from the daily bars it already holds (no new data source or key), so it still works when TradingView
    is blocked; show our reading beside TradingView's and say when they differ. The rule that turns the readings into
    "Strong sell" to "Strong buy" is set during testing and written here before it is built.
  - Display only: no change to scoring, calls, stops or alerts.
- **News in the design.** Add the news the app already collects (`newsfeed.py`) to the new look: a news line with its tier tag
  (HOT, IMPORTANT, ROUTINE) and sources on the opened card, a "Critical news" strip at the top of Radar, and a marker on the
  dot map for a stock with HOT news. The Day Board never showed the news strip clearly, which is why it was hard to find.
- **The owner finds the current look annoying** and asked for more professional options (design session): the Yahoo-style
  list was the direction chosen so far, with three more directions to compare before anything is built.

## 9. Dot map: a chart of where every stock stands (owner, 2026-10-24), design only, for after testing
The owner asked for a horizontal chart like the old Radar, with stocks moving up and down and bigger dots for stocks that need
more attention (sell or buy). A sample was shown; nothing is built.
- **Axes.** Left to right is the gauge: Bad, Weak, Neutral, Good, Strong (the five steps of the gauge), as faint colour bands.
  Up and down is today's move, with a dashed "flat today" line.
- **Dots.** Colour is the call (red act, amber watch, green buy, muted blue calm). Size is how much attention it needs: big for
  act and buy, medium for watch, small for calm. Act and buy dots get a slow pulse ring, off when the phone asks for reduced
  motion. Big dots carry the ticker inside; small calm ones carry a small ticker above.
- **Tap.** A dot opens that stock's card (section 7) under the chart, with a dashed ring on the selected dot.
- **Zoom (owner, 2026-10-24).** The default view shows dots only, no names, so the whole book fits and stays calm. The chart zooms
  with pinch or + and − buttons in the corner. Choosing a filter (Act, Watch, Buy, Calm) zooms the chart onto those dots
  automatically and turns the names on (ticker and today's change inside big dots, ticker above small ones); "All" zooms back
  out. The axis bands (Bad to Strong) rescale and only the visible ones are labelled. Dots outside the filter are hidden.
  Sample frames: all, Act zoomed, Watch zoomed. The label on a small dot can spill over its edge; widen or move it in the build.
- **Open choices.** Whether size also reflects position size; where the chart sits (top of Radar, or its own tab); collisions
  when many calm stocks cluster (nudge apart, or tap-to-zoom). A one-line strip version was tried and dropped: too cramped.
- **Data.** Needs no new data: the gauge position, today's change and the call already exist for every stock.

## 10. Fundamentals, earnings and major news on the card (owner, 2026-10-24), for after testing
Samples shown and agreed; nothing is built.
- **Fundamentals rating on the closed card.** One word and five pips beside the technical rating: Fundamentals Poor, Weak, Fair,
  Good or Strong, and Technicals Bad, Weak, Neutral, Good or Strong. Draft score bands (to set in testing): Poor under 25, Weak 25
  to 44, Fair 45 to 64, Good 65 to 79, Strong 80 and over. Shown as "unknown" with the reason when fewer than 3 measures are
  readable.
- **Fundamentals tab behind Details.** The rating and score; a source line (SEC filing type, period and filing date, "based on
  N of M measures"); the four pillars (Growth, Quality, Balance sheet, Valuation) with a bar and a word; every measure with a
  B icon, its value, a plain note, a source tag (SEC or Yahoo) and its data status (usable, stale, needs reconciliation,
  unknown); a four to five quarter revenue chart; and a flags-from-filings line.
- **Tightening, agreed (owner: "agree with your tightening").** Make SEC the main source for the financial pillars, with Yahoo kept
  for price-based measures (today SEC is only the fallback, and `docs/SEC_DATA_QUALITY.md` is read-only and not wired in). Then:
  1. SEC first for growth, margins, cash flow and balance sheet, with the source and filing date on each figure.
  2. Trends, not only levels (margin rising or falling, growth speeding up or slowing down).
  3. Cash runway and dilution for loss-making companies, where ROE says little.
  4. Debt against cash, and interest cover.
  5. Cash quality: operating cash flow against reported profit.
  6. Different rules for banks and insurers (several measures do not apply, per the SEC quality work).
  7. Red flags from filings: restatement (8-K 4.02), auditor change (4.01), late filing, amended 10-K.
  8. Show how many measures the rating rests on; unknown when too few are reported.
  9. Show the fair-value range only when at least two methods agree.
  Scoring changes are a separate pull request and only after testing, per the methodology rule.
- **Earnings on the card (owner, 2026-10-24).** Two short lines: last quarter's result as BEAT, MISS or IN LINE with the EPS
  surprise, and next quarter's date with the expected EPS and revenue and the days left. Draft rule (set in testing): beat above
  +2% surprise, miss below -2%, otherwise in line. Where the revenue expectation or company guidance is not reported by a source,
  say "not available", never a guess. Actual results come from the company's filing (SEC); expectations are analyst
  consensus (Yahoo, or Finnhub when Yahoo is blocked).
- **Earnings tab behind Details.** Next quarter box (date, days left, usual move on report days, expected EPS and revenue,
  company guidance, analyst count and revisions), then the last four quarters, each as actual vs expected with BEAT or MISS.
- **Major news on the card (owner, 2026-10-24).** One line with the top ranked story, its tier tag (HOT, IMPORTANT, ROUTINE),
  headline, age and source, from the multi-source feed in `newsfeed.py`; the full ranked list sits under Major news and releases
  on Details. Only the top technical and fundamental reads, one earnings pair and one news line show on the closed card, so it
  stays short; everything else is behind the tap.

## 12. One accurate trade decision per stock, as if it trades automatically (owner, 2026-10-24), methodology, for after testing
Found on the DIS Details page: "STRONG HOLD" on the card, a WEAKENING chart, a plan stop of 106.48 and a structure exit of 110.13 at
the same time. The owner wants the system built as if it were going to trade on its own, with no information hidden and one accurate
decision. Nothing here is built; it changes how calls, stops and exits are decided, so it goes in as its own pull request flagged as a
methodology change, after testing on real tickers and the owner's go-ahead.
- **One decision per stock**, from fixed rules in a fixed order: hard exit, then warning exit, then risk limit, then entry or hold.
  The composite score stops being an action word ("STRONG HOLD"); it becomes a quality rating next to the decision.
- **The decision card has:** the action; entry (zone, order type, size) for a buy; a **warning exit** (a daily close below the
  support floor) and a **hard stop** (during the day, protects against a gap through the floor); a target; the reasons not to buy
  more (blocks); and when it is reviewed (each daily close, and before earnings).
- **The two exits are two stages of one exit, not two answers.** DIS: close below 110.13 triggers the exit; a gap through it is
  caught by the 106.48 stop. Both are shown, each with its job.
- **No decision without fresh data.** A missing check says which one and shows "no decision", never a guess (and never a score of 0).
- **Nothing hidden.** Every check and level stays on the page, split into evidence that agrees and evidence that disagrees.
- **Owner to decide in testing:** at the warning exit, sell all or sell half; whether the warning exit acts after the close only or
  also during the day.
- **Where the company is heading, drawn not written (owner, 2026-10-24): version C, small tiles.** Five tiles instead of the
  paragraph: Analysts say (rating word, buy/hold/sell bar and counts), Street target (price with the % to it and how many
  analysts), 12-month range (bear to bull with now marked), Chance higher (ring), EPS growth (this year, next year). Every price
  carries the $ sign. A source that has no figure shows "not available" on its tile, never a guess.
- **Display first:** until this is built, stage 4 of the design shows the Details page with the decision on top and every source
  under it, labelled, and changes no call.

## 11. To find out first (testing)
- How often the checks disagree with the call, and on which stocks.
- Whether the graded zones (HIGH, MEDIUM, LOW) predict reactions better than the automatic CIS levels.
- Which of the first live news and TradingView or Stooq reads fail, and why.
