"""Phone pushes for what the system DOES (owner, 30 Oct: ntfy). Display and delivery only: nothing here changes a call, a rule or a trade.

Two feeds, two ntfy topics, so each can have its own sound and mute setting on the phone:
  LOG    (NTFY_TOPIC_LOG) what the system did: Quick or the New call account opened or closed a trade, one push per account per cycle
  (The wording of each message follows the design the owner approved on 30 Oct: icon, ticker and event in the title, then the reason
   with real numbers, then the next step.)
  CALLS  (NTFY_TOPIC) the New call changing on tracked stocks. Stocks you OWN come first: EXIT or AVOID is priority 5 with the
         Rotate suggestion, ON THE LINE is 4, any other change 3. The watchlist reports a new BUY or ADD, and any other status change in one quiet batch (priority 2). Three or more owned changes in one sweep are one push too.
  LOG    also: a tracked stock moving a lot before the open or after the close (owned: 3% or more, others: 5% or more), once per
         stock per session, owned first.
If only NTFY_TOPIC is set, both feeds go to it.

The first time it runs it only learns the current calls, so a restart never floods the phone with old news. Each (stock, call,
chart date) is pushed once. It sends nothing until NTFY_TOPIC is set in the owner's private settings file; failures are logged
and skipped, never raised: a push must never stop the tracker."""
from __future__ import annotations

import json
import logging
import os

from . import notify, ui

log = logging.getLogger("stockwatch.events")
SEEN_KEY = "push_seen"
SELL_CALLS = ("EXIT", "AVOID")
BUY_CALLS = ("BUY", "ADD")
MAX_LINES = 12
OWN_GROUP_FROM = 3                           # this many of your stocks changing in one sweep go out as one push
MOVE_OWNED, MOVE_OTHER = 0.03, 0.05
OWN_LINES, OTHER_SHOWN = 5, 6                 # a long list is cut: the biggest owned moves, then the biggest others on one line
MOVES_KEY = "push_moves"


def _link(ticker: str | None = None) -> str | None:
    base = (os.getenv("DASHBOARD_URL") or "").rstrip("/")
    if not base:
        return None
    return f"{base}/?view=target&t={ticker}" if ticker else base


FAIL_KEY, OUTBOX_KEY = "push_failures", "push_outbox"
OUTBOX_MAX, GROUP_FROM = 30, 6                  # unsent pushes kept for a retry; this many trades in one cycle go out as one push


def _remember(store, key: str, item, keep: int) -> None:
    """Keep the last few items of a list in the settings table. Never raises."""
    if store is None:
        return
    try:
        rows = json.loads(store.get_setting(key) or "[]")
        rows = (rows if isinstance(rows, list) else []) + [item]
        store.set_setting(key, json.dumps(rows[-keep:]))
    except Exception:
        log.exception("could not record %s", key)


def _push(title: str, lines: list[str], priority: int, tags: str, ticker: str | None = None, channel: str = "calls",
          store=None, retry: bool = True) -> str:
    if not lines:
        return ""
    rest = len(lines) - MAX_LINES
    text = "\n".join(lines[:MAX_LINES] + ([f"+{rest} more"] if rest > 0 else []))
    try:
        return notify.ntfy_send(title, text, priority, tags, _link(ticker), channel)
    except notify.DeliveryError as e:
        log.warning("push failed: %s", e)
        err = f"failed: {e}"
    except Exception as e:                                   # never stop the tracker
        log.warning("push failed: %s", notify._scrub(f"{type(e).__name__}: {e}"))
        err = "failed"
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _remember(store, FAIL_KEY, {"at": now, "title": title, "error": err}, 20)          # so a missing notification can be explained
    if retry:
        _remember(store, OUTBOX_KEY, {"title": title, "text": text, "priority": priority, "tags": tags,
                                      "ticker": ticker, "channel": channel}, OUTBOX_MAX)
    return err


def resend(store) -> int:
    """Try the pushes that failed earlier (a busy or unreachable ntfy). Each is tried once more; whatever fails again is dropped.
    Returns how many went out."""
    try:
        queued = json.loads(store.get_setting(OUTBOX_KEY) or "[]")
    except ValueError:
        queued = []
    if not isinstance(queued, list) or not queued:
        return 0
    store.set_setting(OUTBOX_KEY, "[]")
    sent = 0
    for m in queued[-OUTBOX_MAX:]:
        try:
            r = _push(m["title"], [m["text"]], m["priority"], m["tags"], m.get("ticker"), m.get("channel", "calls"), store, retry=False)
            sent += 1 if r == "sent" else 0
        except Exception:
            log.exception("resend failed")
    return sent


def _trades_of(book) -> list[dict]:
    return (book.get("trades") if isinstance(book, dict) else getattr(book, "trades", None)) or []


def _money(v) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) and abs(v) >= 1000 else f"${v:,.2f}" if isinstance(v, (int, float)) else "n/a"


def _today_tally(book, day: str) -> str:
    done = [t for t in _trades_of(book) if t.get("status") == "CLOSED" and str(t.get("closed") or "")[:10] == day]
    won = sum(1 for t in done if (t.get("result") or 0) > 0)
    return f"{len(done)} closed · {won} won · {len(done) - won} lost"


def trade_message(account: str, d: dict, book=None, day: str | None = None) -> tuple[str, str, int, str] | None:
    """(title, body, priority, tag) for one buy or sell of a fake-money account, or None for anything else."""
    from datetime import datetime

    from .data import NY
    act, t, price = str(d.get("action") or ""), d.get("ticker"), d.get("price")
    trade = next((x for x in reversed(_trades_of(book)) if x.get("ticker") == t), None) or {}
    px = f"{price:,.2f}" if isinstance(price, (int, float)) else "n/a"
    if act == "ENTER":
        shares, size = trade.get("shares"), trade.get("size")
        stop = trade.get("stop0", trade.get("stop"))
        risk = trade.get("risk")
        if risk is None and isinstance(stop, (int, float)) and isinstance(price, (int, float)) and shares:
            risk = (price - stop) * shares
        lines = [f"{shares} shares at {px} = {_money(size)}" if shares else f"at {px}"]
        if isinstance(stop, (int, float)):
            lines.append(f"Stop {stop:,.2f}" + (f" · risk {_money(risk)}" if isinstance(risk, (int, float)) else ""))
        lines.append(f"Reason: {d.get('reason', '')}")
        return f"{account} bought {t} (fake money)", "\n".join(lines), 3, "moneybag"
    if act in ("EXIT", "SELL_ALL", "SELL"):
        entry, res = trade.get("entry"), trade.get("result")
        pct = trade.get("pct")
        if pct is None and isinstance(entry, (int, float)) and entry and isinstance(price, (int, float)):
            pct = (price / entry - 1) * 100
        head = " · ".join(x for x in (f"{pct:+.1f}%" if pct is not None else "", f"{'+' if (res or 0) >= 0 else '-'}${abs(res):,.2f}" if isinstance(res, (int, float)) else "",
                                      f"held {trade['minutes']} min" if trade.get("minutes") is not None else "") if x)
        lines = [head or f"sold at {px}", f"Reason: {d.get('reason', '')}"]
        if book is not None:
            lines.append(f"{account} today: {_today_tally(book, day or datetime.now(NY).date().isoformat())}")
        return f"{account} sold {t} (fake money)", "\n".join(lines), 4, "money_with_wings"
    return None


def trades(account: str, did: list[dict] | None, book=None, store=None) -> str:
    """One push per buy or sell the account made this cycle (fake money). A burst of GROUP_FROM or more is one push with a line
    each, so it can't trip the push service's rate limit. Returns the last outcome or ''."""
    res = ""
    msgs = [m for m in (trade_message(account, d, book) for d in did or []) if m]
    if len(msgs) >= GROUP_FROM:
        buys = [m for m in msgs if m[3] == "moneybag"]
        for kind, group, tag, prio in (("bought", buys, "moneybag", 3), ("sold", [m for m in msgs if m[3] != "moneybag"], "money_with_wings", 4)):
            if group:
                lines = [m[0].replace(f"{account} {kind} ", "").replace(" (fake money)", "") + ": " + m[1].replace("\n", " · ") for m in group]
                res = _push(f"{account} {kind} {len(group)} stocks (fake money)", lines, prio, tag, None, "log", store)
        return res
    for title, body, prio, tag in msgs:
        res = _push(title, [body], prio, tag, None, "log", store)
    return res


def _oc(snap: dict) -> dict:
    oc = ((snap.get("payload") or {}).get("technical") or {}).get("one_call")
    return oc if isinstance(oc, dict) and oc.get("known") else {}


def call_flips(store, snaps: list[dict], holdings, extras=frozenset()) -> dict:
    """Push the New call changes on tracked stocks since the last look. Returns {"exits": n, "buys": n, "learned": bool}."""
    from . import rotation
    resend(store)                                            # anything that failed to send earlier gets one more try
    try:
        seen = json.loads(store.get_setting(SEEN_KEY) or "null")
    except ValueError:
        seen = None
    learning = seen is None
    seen = seen if isinstance(seen, dict) else {}
    owned = {h.ticker for h in holdings if h.shares and h.shares > 0}
    fresh_own, fresh_buy, fresh_other = [], [], []
    for s in snaps:
        t = s["ticker"]
        oc = _oc(s)
        call = oc.get("call")
        if not call or t in extras:
            continue
        key = f"{t}|{call}|{oc.get('as_of')}"
        if t in seen and seen[t] == key:
            continue
        before = (seen.get(t) or "").split("|")[1] if t in seen else None
        was = seen.get(t)
        seen[t] = key
        if learning or call == before:
            continue
        if t in owned:
            fresh_own.append((s, before))
        elif call in BUY_CALLS and before not in BUY_CALLS:
            lc = ui.live_check(s)
            if lc and lc["word"].startswith("under"):       # the tape has already broken the line: not a buy now; look again next sweep
                if was is None:
                    seen.pop(t, None)
                else:
                    seen[t] = was
                continue
            fresh_buy.append(s)
        elif before is not None and call not in BUY_CALLS:      # any other change on a watchlist stock goes in one quiet batch
            fresh_other.append((s, before))
    out = {"exits": sum(1 for s, _ in fresh_own if _oc(s)["call"] in SELL_CALLS), "owned_changes": len(fresh_own),
           "buys": len(fresh_buy), "watch_changes": len(fresh_other), "learned": learning}
    own_msgs = []
    if fresh_own:
        sells = {s["ticker"] for s, _ in fresh_own if _oc(s)["call"] in SELL_CALLS}
        rows = {r["ticker"]: r for r in rotation.build(snaps, [h for h in holdings if h.ticker in sells])}
        for s, before in fresh_own:
            oc, r = _oc(s), rows.get(s["ticker"]) or {}
            call, t = oc["call"], s["ticker"]
            tech = (s.get("payload") or {}).get("technical") or {}
            if call in SELL_CALLS:
                first = f"Closed {oc.get('close')}, under the exit line {oc.get('exit_line')}" + (
                    f" ({oc['distance_swings']:+.1f} swings)." if isinstance(oc.get("distance_swings"), (int, float)) else ".")
                dc, vr = tech.get("day_change"), tech.get("volume_ratio")
                if isinstance(dc, (int, float)) and dc <= -0.03:
                    first += f" Fell {abs(dc) * 100:.1f}%" + (f" on {vr:.0f}x volume." if isinstance(vr, (int, float)) and vr >= 2 else ".")
                frac = rotation.TRIM.get(call)
                second = f"{before} \u2192 {call}." + (f" Suggested: trim {frac:.0%}." if frac else "")
                lines = [first, second]
                if r.get("picks"):
                    lines.append("Move the money to: " + ", ".join(f"{p['ticker']} ({p['call']})" for p in r["picks"]) + ".")
                elif r.get("note"):
                    lines.append(r["note"][0].upper() + r["note"][1:] + ".")
                title, prio, tag = f"{t} (you own it) turned {call}", 5, "rotating_light"
            elif call == "ON THE LINE":
                band = oc.get("band_line")
                lines = [f"Close {oc.get('close')}, exit line {oc.get('exit_line')}, band down to {band}.",
                         f"No new buys. A close under {band} turns it EXIT."]
                title, prio, tag = f"{t} (you own it) is on its exit line", 4, "warning"
            else:
                lines = [f"{before} \u2192 {call}. {oc.get('why', '')}"]
                title, prio, tag = f"{t} (you own it): {before} -> {call}", 3, "bell"
            own_msgs.append((t, before, call, title, lines, prio, tag))
        if len(own_msgs) >= OWN_GROUP_FROM:                     # many at once: one push, a line each, at the most urgent priority
            lines = [f"{t}: {before} \u2192 {call}. {ls[0]}" if call in SELL_CALLS else f"{t}: {before} \u2192 {call}."
                     for t, before, call, _ti, ls, _p, _tg in own_msgs]
            top = max(own_msgs, key=lambda m: m[5])
            _push(f"{len(own_msgs)} of your stocks changed", lines, top[5], top[6], top[0], store=store)
        else:
            for t, _b, _c, title, lines, prio, tag in own_msgs:
                _push(title, lines, prio, tag, t, store=store)
    if fresh_buy:
        lines = []
        for s in fresh_buy:
            oc = _oc(s)
            sw = oc.get("distance_swings")
            px, close = ui._now(s)[0], oc.get("close")
            lines.append(f"{s['ticker']} {oc.get('call')} \u00b7 {px if px == px and px else s.get('price', 0):,.2f} now"
                         + (f" \u00b7 closed {close:,.2f}, {sw:.1f} swings above its line {oc.get('exit_line')}"
                            if isinstance(sw, (int, float)) and isinstance(close, (int, float)) else ""))
        _push(f"Watchlist: {len(lines)} New call buy signal{'s' if len(lines) != 1 else ''}", lines, 2, "chart_with_upwards_trend", fresh_buy[0]["ticker"], store=store)
    if fresh_other:
        lines = [f"{s['ticker']}: {b} \u2192 {_oc(s)['call']}" for s, b in fresh_other]
        _push(f"Watchlist: {len(lines)} status change{'s' if len(lines) != 1 else ''}", lines, 2, "bar_chart", fresh_other[0][0]["ticker"], store=store)
    store.set_setting(SEEN_KEY, json.dumps(seen))
    return out


def moves(store, snaps: list[dict], holdings, extras=frozenset(), day: str | None = None) -> int:
    """Push stocks that moved in the pre-market or after-hours (log feed). Once per stock per session; owned stocks first and
    at a lower threshold. Returns how many were pushed."""
    from datetime import datetime

    from .data import NY
    day = day or datetime.now(NY).date().isoformat()
    try:
        done = json.loads(store.get_setting(MOVES_KEY) or "{}")
    except ValueError:
        done = {}
    if not isinstance(done, dict) or done.get("day") != day:
        done = {"day": day, "seen": []}
    owned = {h.ticker for h in holdings if h.shares and h.shares > 0}
    hits = []
    for s in snaps:
        t = s["ticker"]
        q = (s.get("payload") or {}).get("quote") or {}
        sess = q.get("ext_session")
        chg, px = q.get("ext_change"), q.get("ext_price")
        if t in extras or sess not in ("pre", "post") or q.get("ext_stale") or q.get("market_state") not in ("PRE", "POST"):
            continue
        if not isinstance(chg, (int, float)) or isinstance(chg, bool) or chg != chg or not isinstance(px, (int, float)):
            continue
        key = f"{t}|{sess}"
        if key in done["seen"] or abs(chg) < (MOVE_OWNED if t in owned else MOVE_OTHER):
            continue
        done["seen"].append(key)
        call = _oc(s).get("call")
        hits.append((t in owned, abs(chg), t, sess, chg, px, call))
    store.set_setting(MOVES_KEY, json.dumps(done))
    if not hits:
        return 0
    hits.sort(key=lambda h: (not h[0], -h[1]))
    own, other = [h for h in hits if h[0]], [h for h in hits if not h[0]]
    CALLS_SHOWN = ("EXIT", "AVOID", "ON THE LINE", "BUY", "ADD")           # a call is shown only when it matters
    lines = []
    if own:
        lines.append("You own")
        for _o, _a, t, _s, chg, px, call in own[:OWN_LINES]:
            lines.append(f"{t} {chg * 100:+.1f}% \u00b7 {px:,.2f}" + (f" \u00b7 {call}" if call in CALLS_SHOWN else ""))
        if len(own) > OWN_LINES:
            lines.append(f"+{len(own) - OWN_LINES} more you own")
    if other:
        shown = ", ".join(f"{t} {chg * 100:+.1f}%" for _o, _a, t, _s, chg, _p, _c in other[:OTHER_SHOWN])
        lines.append(f"Watchlist: {shown}" + (f" (+{len(other) - OTHER_SHOWN} more)" if len(other) > OTHER_SHOWN else ""))
    head = f"{'Pre-market' if hits[0][3] == 'pre' else 'After-hours'}: {len(hits)} moved" + (f" ({len(own)} you own)" if own and other else "")
    _push(head, lines, 4 if own else 3, "zap", hits[0][2], "log", store)
    return len(hits)


ALERT_KEY = "push_alert_id"
VOLUME_CODES = ("volume_surge_up", "volume_surge_down")
NEWS_LINES = 14


def signals(store, snaps: list[dict], holdings, extras=frozenset(), session: str | None = None) -> dict:
    """Push the new Log-tab signals (owner, 31 Oct). Two groups, display and delivery only:
      VOLUME  a volume surge goes on the CALLS feed with the stock's current call, only while the US market is open (regular
              session by the New York clock); outside the session it stays on the Log tab and is not pushed later.
      NEWS    every other new signal (estimates, earnings, S&P scan setups, moves outside the session ...) goes in ONE push per
              sweep on the LOG feed, stocks you own first. An outside-session move already pushed by `moves` is not repeated.
    The first run only learns the current position, so a restart never floods the phone. Returns {"volume": n, "news": n}."""
    from .data import us_session
    out = {"volume": 0, "news": 0}
    try:
        last = store.get_setting(ALERT_KEY)
        top = store.conn.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]
        if last is None:
            store.set_setting(ALERT_KEY, str(top))
            return out
        rows = store.alerts_after(int(last))
        store.set_setting(ALERT_KEY, str(max([top] + [r["id"] for r in rows])))
    except Exception:
        log.exception("could not read new signals")
        return out
    if not rows:
        return out
    session = session or us_session()
    owned = {h.ticker for h in holdings if h.shares and h.shares > 0}
    by_t = {s["ticker"]: s for s in snaps}
    try:
        moved = set(json.loads(store.get_setting(MOVES_KEY) or "{}").get("seen") or [])
    except ValueError:
        moved = set()
    vol, news = [], []
    for r in rows:
        t, code = r["ticker"], r["code"]
        if t in extras:
            continue
        if code in VOLUME_CODES:
            if session == "REGULAR":
                vol.append(r)
        elif code.startswith("ext_") and f"{t}|{code.split('_')[1]}" in moved:
            continue
        else:
            news.append(r)
    if vol:
        vol.sort(key=lambda r: (r["ticker"] not in owned, r["ticker"]))
        lines = []
        for r in vol:
            call = _oc(by_t.get(r["ticker"]) or {}).get("call")
            lines.append(f"{r['ticker']}{' (you own it)' if r['ticker'] in owned else ''} {r['message']}" + (f" \u00b7 call: {call}" if call else ""))
        _push(f"Volume: {len(lines)} stock{'s' if len(lines) != 1 else ''} on heavy volume", lines,
              4 if any(r["ticker"] in owned for r in vol) else 3, "chart_with_upwards_trend", vol[0]["ticker"], "calls", store)
        out["volume"] = len(vol)
    if news:
        news.sort(key=lambda r: (r["ticker"] not in owned, r["ticker"]))
        lines = [f"{r['ticker']}{' (you own it)' if r['ticker'] in owned else ''} @ {r['price']:.2f} \u2014 {r['message']}" for r in news]
        _push(f"News: {len(lines)} new signal{'s' if len(lines) != 1 else ''}", lines,
              4 if any(r["ticker"] in owned for r in news) else 2, "newspaper", news[0]["ticker"], "log", store)
        out["news"] = len(news)
    return out


def test() -> str:
    """Test pushes (no holdings in them) to the calls topic and, when set, the log topic. 'sent', 'not configured' or 'failed: why'."""
    try:
        res = notify.ntfy_send("StockWatch test: calls", "The CALLS feed works. No holdings are included in this message.", 3, "white_check_mark")
        if res == "sent" and (os.getenv("NTFY_TOPIC_LOG") or "").strip():
            notify.ntfy_send("StockWatch test: log", "The LOG feed works. No holdings are included in this message.", 3, "white_check_mark", channel="log")
        return res
    except notify.DeliveryError as e:
        return f"failed: {e}"
