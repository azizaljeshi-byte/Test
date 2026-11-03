# Brief 1: the "Ask the AI" tab (screen only)

**Goal.** A new tab where the owner picks one stock (from the candidate list or by typing a ticker), asks the AI, and reads a verdict:
BUY / HOLD / SELL / AVOID, how sure it is, one plain line why, what would change it, a price ladder picture, a short facts table.
Below that, a "How the AI did" table. Owner reads on a phone: short labels, big verdict, little text.

**Scope: the screen only.** Claude writes the AI call (`ask_ai.ask`) separately. You build against the contract in `stockwatch/ask_ai.py`
and its `sample_verdict()`, so nothing needs the AI, a key or the network.

## Build
- `stockwatch/ask_ai_view.py`: `html(verdict: dict) -> str` for the verdict card and `history_html(rows: list[dict]) -> str` for "How the AI did". Pure functions, no Streamlit calls, so they are testable. Follow the style of `stockwatch/quick_view.py` / `ui.py`.
- `dashboard.py`: a new tab "Ask the AI". Contents, top to bottom:
  1. Ticker box plus a list of today's candidate tickers to tap (`candidates` module has them). Button "Ask".
  2. The verdict card (`ask_ai_view.html(ask_ai.latest(store, ticker))`), or "Not asked yet" when `latest` is None, or "Asking..." when `status == "asking"`, or the `error` text when `status == "failed"`.
  3. "How the AI did" (`ask_ai.history(store)`).
- Until Claude's `ask_ai.request()` exists, the Ask button saves `sample_verdict(ticker)` through `ask_ai.save` **only when `STOCKWATCH_DEMO=1`**; otherwise it is disabled with the label "AI not connected yet".

## The verdict card (top to bottom)
1. Header: ticker big, name and sector small, price on the right with "last close" or "now".
2. Verdict block: verdict word in a coloured box (BUY green, HOLD amber, SELL and AVOID red), a one-line meaning ("Wait. Not a buy yet."), five confidence dots ("2 of 5"), then `headline`.
3. "What would change it": three rows BUY / HOLD / SELL with `change_buy`, `change_hold`, `change_sell`, each tinted green / amber / red.
4. Price ladder: a vertical line, levels placed by price (highest at the top), each with its number and label. Colours by `kind`: exit_line green dashed, price blue solid, resistance grey dotted, support red dashed. Space levels so labels never overlap (equal spacing is fine; keep the order by price).
5. Facts table: label left, value right, colour by `tone`. A `value` of None shows "unknown" in grey, never 0.
6. Footer: "Saved <time> · scored at +60 min and at the close · places no trade".

## History table ("How the AI did")
Three small tiles: verdicts count, share of BUY calls that rose, share of AVOID calls that fell (use `scored["plus60"]`; show "-" until any are scored, never 0%).
Then rows: time, ticker, verdict, +60 min, close (None shows "-").

## Don't
- Don't add trades, orders or any link to Quick / New call. The tab is read-only advice.
- Don't call the network or an AI from the page. Page reloads often; long work belongs on the tracker thread (Claude's part).
- Don't touch scoring, signals, verdicts, trade plans or thresholds.

## Check
- Tests for both `html` and `history_html`: each verdict colour, a None fact shows "unknown", a failed or asking status, empty history.
- `STOCKWATCH_DEMO=1 streamlit run dashboard.py`, screenshot the tab at 390px with Playwright (Chromium under `/opt/pw-browsers/`), attach it to the PR.
- Visual reference: the owner's mockup shows dark cards (`#131b2e` on `#0a0f1c`), 14-16px rounded corners, 26px bold ticker. Match the app's existing look first; the mockup is only a guide.
