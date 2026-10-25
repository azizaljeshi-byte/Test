# Audit leads: what ChatGPT and Codex raised, and what we checked

Recorded 25 Oct 2026 at the owner's request: read the two audit issues and write down what is worth fixing, without changing anything now. Each item gets fixed in its own pull request later, and only the ones that change methodology need the owner's go-ahead first.

Sources: issue #65 (ChatGPT's code-level audit of commit 5256dbd, assigned to Claude) and issue #55 (Codex's independent audit brief, to be done after the last Claude phase). Neither issue holds a finished report yet: #65 is a list of leads to reproduce, and #55 is the brief for Codex's own audit. Nothing was run for this log. "Checked" below means Claude read the code and the lead is true as written; the reproducer and test still have to be written.

Status words: **checked** (code read, lead is true), **not checked** (not looked at yet), **by design** (a rule the owner chose), **decision** (needs the owner before any change).

## Fix first (could mislead a decision)

| # | Lead | Where | Status | Plain meaning |
|---|---|---|---|---|
| A1 | A watchlist stock with a serious risk (bankruptcy, restated accounts) can still show BUY SETUP, because the entry check runs before the risk check | `engine._verdict` | **checked** | Risk should win over opportunity. |
| A2 | A SELL turns into REASSESS on any rebound of 3% or more, even when the cause is serious (not just a price signal) | `ui.reassess` | **checked**, decision | Only a price-only sell should be allowed to wait. Alerts and cards must agree. |
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

1. A1, then A2, with a table of cases and tests.
2. A4 (paper), A5 (label), B3, B6.
3. A3 once the owner picks fail-open or fail-closed.
4. B1 and B2 as a methodology decision with the owner.
5. B7 and B8 after the first week of paper results.
6. C5 (automatic tests on every pull request) any time; it protects everything else.
