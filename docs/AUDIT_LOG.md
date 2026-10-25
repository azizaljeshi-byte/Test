# Audit leads: what ChatGPT and Codex raised, and what we checked

Recorded 25 Oct 2026 at the owner's request: read the two audit issues and write down what is worth fixing, without changing anything now. Each item gets fixed in its own pull request later, and only the ones that change methodology need the owner's go-ahead first.

Sources: issue #65 (ChatGPT's code-level audit of commit 5256dbd, assigned to Claude) and issue #55 (Codex's independent audit brief, to be done after the last Claude phase). #65 is a list of leads to reproduce. Codex has since posted its interim audit in three comments on #55 (audited commit 5256dbd, 25 Oct 2026): 19 findings F01 to F19, 41 probes, and a browser run at 390 and 1440 px with no page errors. Codex's verdict: no P0, but NO-GO for trading-validity sign-off. It also says demo exploration and read-only research may go on. Nothing was run for this log. "Checked" below means Claude read the code and the lead is true as written; the reproducer and test still have to be written.

Status words: **checked** (code read, lead is true), **not checked** (not looked at yet), **by design** (a rule the owner chose), **decision** (needs the owner before any change).

## Fix first (could mislead a decision)

| # | Lead | Where | Status | Plain meaning |
|---|---|---|---|---|
| A1 | A watchlist stock with a serious risk (bankruptcy, restated accounts) can still show BUY SETUP, because the entry check runs before the risk check | `engine._verdict` | **checked** | Risk should win over opportunity. |
| A2 | A SELL turns into REASSESS on any rebound of 3% or more, even when the cause is serious (not just a price signal) | `ui.reassess` | **by design, keep as is** (owner, 25 Oct 2026) | The owner asked for this: never say sell into a bounce. Left unchanged. If it is ever revisited, the only question is whether a serious non-price cause (bankruptcy, restated accounts) should be exempt. |
| A3 | The second-source checks (TradingView, Finnhub, Stooq) only run when the chart already looks bad, so on a bullish buy the gate never sees them and passes | `engine.evaluate`, `status.entry_blockers` | **checked**, decision | Our own entry gate 5 is mostly asleep on healthy buys. Fail-open or fail-closed is the owner's call. |
| A4 | A quote marked "live" is not checked for age, and the paper account trusts it | `ui._now`, `paper_live.tick` | not checked | Could let paper trade on an old price. Cheap to fix. Paper only. |
| A5 | Target 1 falls back to "2 times the risk" when nothing real fits, so reward against risk looks fine by construction | `tradeplan.build` | **checked** | Should say "illustrative", not show as evidence. |

## Data and numbers

| # | Lead | Status | Plain meaning |
|---|---|---|---|
| B3 | Free cash flow equals operating cash flow when capex is missing | **checked** (`sec.py` line 424) | Missing capex should make FCF unknown, not equal to cash from operations. |
| B6 | RSI of a flat price series reads 100 (overbought) | **checked** (`technical.py` line 23) | Flat should be neutral or unknown. |
| B1 | The fundamental score can reach 100 from a few good metrics when others are missing | not checked, decision | Needs a "how much was measured" label. |
| B2 | Banks, software and heavy industry are scored with the same bands | not checked, decision | Methodology change; plan before building. |
| B4 | The live "fair value" is analyst targets and multiples, not the research DCF | not checked | Label it accurately. |
| B5 | The Street "probability" is a model assumption, not a calibrated chance | not checked | Wording: "model estimate". |
| B7 | Past-similar-days hit rates are not validated, and can move a plan to WAIT | not checked, decision | Needs a walk-forward test against a plain baseline. |
| B8 | News and SEC items show as alerts but do not change a buy; the earnings reaction is guessed from volume | not checked, decision | Split "unverified headline" from "verified thesis damage". |
| B9 | The market mood (SPY) is display only and does not gate entries | not checked, decision | Owner to say if risk-off should hold new buys. |
| B10 | A watchlist stock can show BUY ON DIP as a conditional plan | by design | Check the wording only. |

## Risk, alerts and operations

| # | Lead | Status |
|---|---|---|
| C1 | Time stops and sells are handled differently in the live plan, the cards and the paper account | not checked |
| C2 | One row per ticker: a repeated ticker in the Sheet keeps only the last row, so core and tactical lots cannot sit side by side. Portfolio risk is a separate report and does not hold back a buy | not checked, decision |
| C3 | An alert needs two scans in a row, so an urgent event can take about 30 minutes | not checked, decision |
| C4 | No holiday or half-day calendar; Yahoo prices adjusted for splits can differ from raw live prices; the Stooq cross-check runs only on weak stocks | not checked |
| C5 | No automatic test run on every pull request; the scan job and the app keep separate state; the app's database resets on every reboot | not checked |

## Codex brief (#55): where it overlaps

Leads 1 to 4 match A2, A3, A5 and B10. Lead 5 matches C3. Lead 6 matches B6, C4. Lead 7 matches B7 and the CIS note. Lead 8 matches C2. Leads 9 to 12 match C5 and the paper-trading persistence. Codex's report may add more; when it lands, add its findings here.

## Paper trading

- The paper account has its own rules, journal and report, and the live cards never use them. A4 is the one lead that touches it. It would add an age check on the live price before the paper account may enter.
- GO or NO-GO per ChatGPT's own register: autonomous real trading is NO-GO. Paper trading continues.

## Order we suggest (small pull requests)

1. A1 first, with a table of cases and tests. A2 stays as the owner wants it.
2. A4 (paper), A5 (label), B3, B6.
3. A3 once the owner picks fail-open or fail-closed.
4. B1 and B2 as a methodology decision with the owner.
5. B7 and B8 after the first week of paper results.
6. C5 (automatic tests on every pull request) any time; it protects everything else.


## Codex's findings (#55, comment 1 of 3)

Codex's priority and status are quoted. "Same as" ties each one to the ChatGPT leads above. Nothing here is fixed yet. All of it waits for the owner.

| ID | Priority | What | Same as | Touches paper trading |
|---|---|---|---|---|
| F19 | P1 confirmed | Running Turbo on a stock you hold replaces its latest scan with a watchlist copy, so shares, stops and exposure disappear until the next sweep | new | Yes: paper reads the replaced plan |
| F01 | P1 confirmed | A SELL shown as REASSESS on a +4% bounce while Telegram still says REDUCE / EXIT | A2 | No |
| F02 | P1 confirmed | The second-source and price checks are skipped on bullish setups, and missing evidence passes the entry gates | A3 | Yes: paper uses the same gates |
| F03 | P1 confirmed | Target 1 becomes entry + 2R with rr 2.0 when no real target exists | A5 | Yes: the stretch cap and targets |
| F04 | P1 confirmed | A stored "regular" quote of any age is treated as live, so paper can enter on an old price | A4 | Yes |
| F05 | P1 confirmed | After 4:05 pm the paper tick returns early, so the end-of-day save to the Sheet never runs | new | Yes |
| F06 | P1 confirmed | A save throttled by the 60-second limit is not retried until the book changes again, and a failed save is not retried | new | Yes |
| F07 | P1 confirmed | If the app restarts empty and the Sheet cannot be reached, paper starts a fresh $50,000 book silently | new | Yes |
| F08 | P1 confirmed | Holidays and early closes read as regular sessions | C4 | Yes: Thanksgiving is 26 Nov, and the early close is 27 Nov |
| F09 | P1 confirmed | An urgent SELL needs two scans about 15 minutes apart, so it can take 15 to 30 minutes, and a lost cache silences the first one | C3 | No |
| F10 | P1 confirmed | Duplicate tickers keep only the last row, bad share numbers become zero, and infinity is accepted | C2 | No |
| F11 | P2 confirmed | Two readers can both pass the alert duplicate check and write the alert twice | new | No |
| F12 | P2 confirmed | A WATCH stock can show BUY ON PULLBACK; the contract is unclear | B10 | Possibly |
| F13 | P2 confirmed | Analog hit rates are descriptive, overlap in time, and paper has no fees or slippage, yet it can say KEEP after 30 trades | B7 | Yes: the report verdict |
| F14 | P2 confirmed | Taking a stock out of the test list while a position is open leaves that position unmanaged | new | Yes |
| F15 | P2 confirmed | Portfolio concentration divides by the priced positions only, with no cash | C2 | No |
| F16 | P2 confirmed | No lockfile and no automatic test run on every pull request | C5 | No |
| F17 | P3 confirmed | The Paper tab says both "not set up" and "the list was read" when no list is set | new (from PR #60) | Display only |
| F18 | P2 probable | Quote patches and snapshot replacement are not one transaction across the page and the tracker | C5 | Possibly |

Codex's 41 probes and the browser run found no page errors at either width. Codex ran the suite on the audited commit: 815 passed, 35 skipped, 1 failed. The one failure is a sandbox restriction on a private-files test, not a product fault.

## Before the first paper day

These come from the findings above. They cost nothing and need no code:
1. Do not run **Turbo** on a stock you hold (F19).
2. Do not remove a stock from the Test list while it has an open paper trade (F14).
3. Do not reboot the app mid-session if you can avoid it. If the Sheet cannot be read after a reboot, the paper book starts over (F07). The Sheet still holds the last save, so nothing is lost there.
4. Read the report as a first look only. It has no fees or slippage, so it cannot approve the rules (F13).

## Platform note (owner, 25 Oct 2026)

The owner's current live-data platform costs 19 SAR a month with no delay, so building our own live feed would cost more (the cheapest all-exchange feed is about $99 a month) and is not worth it. Paid data items stay at the bottom of the list. Revisit only if Yahoo's limits start hurting or the fleet grows to 100 to 200 stocks that need live prices fed into the rules.

## Combined order (small pull requests, owner decides each)

1. **Paper safety first:** F04, F05, F06, F07, F14, F17. All paper-only, so the paper test can be trusted.
2. **F19** Turbo overwrite. A held stock must keep its identity.
3. **A1** serious risk beats BUY SETUP (ChatGPT).
4. **F02 / A3** the independent checks. Needs the owner's fail-open or fail-closed choice.
5. **F03 / A5** label the fallback target as illustrative.
6. **F08** a holiday and early-close calendar, before 26 Nov.
7. **B3, B6** missing capex and flat-price RSI.
8. **F10** reject bad or duplicate holdings rows.
9. **F16** automatic tests on every pull request and a lockfile.
10. **F09** the urgent-risk path. Needs the owner's decision.
11. **F11, F18** alert and quote write safety.
12. **F13, B7** the walk-forward test, after a few weeks of paper results.
13. **Reassess (A2 / F01):** the owner wants it as is. If it is ever revisited, the open point is Telegram saying REDUCE / EXIT while the card says REASSESS.
