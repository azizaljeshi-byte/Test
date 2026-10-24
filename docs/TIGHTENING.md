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
zig-zag lightning line with a dot, D a fill-from-left power line with the bolt at the tip). My pick is B. The owner has not
chosen yet. Known sample faults to fix in the build: the tag in A touches the reason text, and the left label in D touches the bolt.

**Zone grades.** Drop the HIGH / MEDIUM / LOW badges on support and resistance zones. Show one plain-English recommendation
per zone instead, from a single legend that is the same on every card (a universal legend). Wording to draft and test, for example:
- Support: "Likely to hold: a good place to buy" / "May hold: buy small" / "Weak: don't count on it".
- Resistance: "Likely to stop a rise: a good place to sell" / "May stop a rise" / "Weak: price may pass through".
The grading in `zones.py` (HIGH 4 or more points, MEDIUM 2 to 3, LOW otherwise) stays underneath; only the words on screen change.
Keep the reasons line (touches, round number, heavy volume, age) as the proof. Samples of the wording are still to be shown.

## 4. To find out first (testing)
- How often the checks disagree with the call, and on which stocks.
- Whether the graded zones (HIGH, MEDIUM, LOW) predict reactions better than the automatic CIS levels.
- Which of the first live news and TradingView or Stooq reads fail, and why.
