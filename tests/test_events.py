"""Phone pushes (stockwatch/events.py): what is sent, once, and nothing before the first look."""

from stockwatch import events, notify
from stockwatch.config import Holding


class FakeStore:
    def __init__(self):
        self.d = {}

    def get_setting(self, k, default=None):
        return self.d.get(k, default)

    def set_setting(self, k, v):
        self.d[k] = v


def snap(t, call, as_of="2026-10-29", fund=90.0, tech=80.0):
    oc = {"known": True, "call": call, "close": 283.82, "exit_line": 316.6, "band_line": 311.0, "as_of": as_of, "risk": {"grade": "Safe"}, "why": "w"}
    return {"ticker": t, "price": 100.0, "composite": 70.0, "fundamental_score": fund, "technical_score": tech,
            "payload": {"technical": {"one_call": oc}, "quote": {}}}


def capture(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "ntfy_send", lambda title, text, priority=3, tags="", click=None, channel="calls": sent.append((title, text, priority, channel)) or "sent")
    return sent


def test_each_trade_gets_its_own_push_in_the_agreed_wording(monkeypatch):
    sent = capture(monkeypatch)
    book = {"trades": [
        {"ticker": "AAA", "entry": 10.0, "shares": 100, "size": 1000.0, "stop0": 9.0, "status": "OPEN"},
        {"ticker": "BBB", "entry": 20.0, "shares": 10, "status": "CLOSED", "closed": "2026-10-30 15:00", "result": 5.0, "pct": 2.5, "minutes": 48},
        {"ticker": "CCC", "status": "CLOSED", "closed": "2026-10-30 14:00", "result": -3.0}]}
    did = [{"ticker": "AAA", "action": "ENTER", "price": 10.0, "reason": "bounce"},
           {"ticker": "BBB", "action": "EXIT", "price": 20.5, "reason": "stop hit"}]
    events.trades("Quick", did, book)
    assert len(sent) == 2
    t0, b0, p0, c0 = sent[0]
    assert t0 == "Quick bought AAA (fake money)" and p0 == 3 and c0 == "log"
    assert "100 shares at 10.00 = $1,000" in b0 and "Stop 9.00 · risk $100.00" in b0 and "Reason: bounce" in b0
    t1, b1, p1, _ = sent[1]
    assert t1 == "Quick sold BBB (fake money)" and p1 == 4 and "+2.5% · +$5.00 · held 48 min" in b1
    events.trades("Quick", [], book)
    assert len(sent) == 2


def test_sell_message_counts_todays_closed_trades():
    book = {"trades": [{"ticker": "B", "entry": 20.0, "status": "CLOSED", "closed": "2026-10-30 15:00", "result": 5.0},
                       {"ticker": "C", "status": "CLOSED", "closed": "2026-10-30 14:00", "result": -3.0},
                       {"ticker": "D", "status": "CLOSED", "closed": "2026-10-29 14:00", "result": 9.0}]}
    title, body, prio, tag = events.trade_message("New call", {"ticker": "B", "action": "SELL_ALL", "price": 21.0, "reason": "x"}, book, day="2026-10-30")
    assert "New call today: 2 closed · 1 won · 1 lost" in body and prio == 4 and tag == "money_with_wings"


def test_first_look_only_learns_then_an_owned_exit_is_pushed_once(monkeypatch):
    sent = capture(monkeypatch)
    st, hold = FakeStore(), [Holding("AAA", 1, 10), Holding("WWW", 2, 0)]
    assert events.call_flips(st, [snap("AAA", "HOLD"), snap("WWW", "WAIT")], hold)["learned"] is True
    assert sent == []
    out = events.call_flips(st, [snap("AAA", "EXIT", "2026-10-30"), snap("WWW", "WAIT")], hold)
    assert out["exits"] == 1 and sent[0][0] == "AAA: exit signal on a stock you own" and sent[0][2] == 5 and sent[0][3] == "calls"
    events.call_flips(st, [snap("AAA", "EXIT", "2026-10-30"), snap("WWW", "WAIT")], hold)
    assert len(sent) == 1                                            # the same call is not pushed twice


def test_watchlist_new_buy_and_other_changes_are_quiet_and_batched(monkeypatch):
    sent = capture(monkeypatch)
    st, hold = FakeStore(), [Holding("WWW", 2, 0), Holding("XXX", 2, 0)]
    events.call_flips(st, [snap("WWW", "WAIT"), snap("XXX", "WAIT")], hold)
    events.call_flips(st, [snap("WWW", "EXIT"), snap("XXX", "BUY")], hold)
    assert len(sent) == 1 and "1 new buy signal" in sent[0][0] and sent[0][2] == 2
    assert "XXX: New buy signal" in sent[0][1] and "Watchlist: 1 other changes" in sent[0][1]


def test_many_status_changes_in_one_sweep_go_out_as_one_push_each_side(monkeypatch):
    sent = capture(monkeypatch)
    names = ["W1", "W2", "W3", "W4"]
    own = ["O1", "O2", "O3"]
    hold = [Holding(t, 2, 0) for t in names] + [Holding(t, 1, 10) for t in own]
    st = FakeStore()
    events.call_flips(st, [snap(t, "HOLD") for t in names + own], hold)
    out = events.call_flips(st, [snap(t, "WAIT FOR TURN", "2026-10-30") for t in names] + [snap(t, "EXIT", "2026-10-30") for t in own], hold)
    assert out["watch_changes"] == 4 and out["owned_changes"] == 3
    assert len(sent) == 1
    assert sent[0][2] == 5 and all(t in sent[0][1] for t in own)
    assert "Watchlist: 4 other changes" in sent[0][1]


def test_extras_never_push(monkeypatch):
    sent = capture(monkeypatch)
    st, hold = FakeStore(), []
    events.call_flips(st, [snap("EEE", "WAIT")], hold, frozenset({"EEE"}))
    events.call_flips(st, [snap("EEE", "BUY")], hold, frozenset({"EEE"}))
    assert sent == []


def test_not_configured_sends_nothing_and_never_raises(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert events.test() == "not configured"
    assert events.trades("Quick", [{"ticker": "A", "action": "ENTER", "price": 1.0}]) == "not configured"


def test_ntfy_send_builds_a_plain_ascii_title_and_hides_the_topic(monkeypatch):
    seen = {}

    class R:
        def read(self):
            return b""
    monkeypatch.setenv("NTFY_TOPIC", "secret-topic-123")
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda req, timeout=10: seen.update(url=req.full_url, h=dict(req.header_items())) or R())
    assert notify.ntfy_send("Quick – trade", "hi", 9, "tag") == "sent"
    assert seen["url"].endswith("/secret-topic-123") and seen["h"]["Priority"] == "5"
    assert seen["h"]["Title"].isascii()
    assert "secret-topic-123" not in notify._scrub("failed secret-topic-123")


def test_owned_stock_on_the_line_is_priority_4_and_log_topic_falls_back(monkeypatch):
    sent = capture(monkeypatch)
    st, hold = FakeStore(), [Holding("AAA", 1, 10)]
    events.call_flips(st, [snap("AAA", "HOLD")], hold)
    events.call_flips(st, [snap("AAA", "ON THE LINE", "2026-10-30")], hold)
    assert sent[0][2] == 4 and sent[0][0] == "AAA: near the exit level" and "A close below 311.00 gives an exit signal" in sent[0][1]


def test_log_channel_uses_its_own_topic_when_set(monkeypatch):
    seen = []

    class R:
        def read(self):
            return b""
    monkeypatch.setenv("NTFY_TOPIC", "calls-t")
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda req, timeout=10: seen.append(req.full_url) or R())
    notify.ntfy_send("a", "b", channel="log")
    monkeypatch.setenv("NTFY_TOPIC_LOG", "log-t")
    notify.ntfy_send("a", "b", channel="log")
    notify.ntfy_send("a", "b")
    assert [u.rsplit("/", 1)[1] for u in seen] == ["calls-t", "log-t", "calls-t"]


def test_a_pasted_address_still_gives_the_topic_name(monkeypatch):
    seen = []

    class R:
        def read(self):
            return b""
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda req, timeout=10: seen.append(req.full_url) or R())
    for pasted in ("ntfy.sh/my-topic", "https://ntfy.sh/my-topic/", "my-topic"):
        monkeypatch.setenv("NTFY_TOPIC", pasted)
        notify.ntfy_send("a", "b")
    assert seen == ["https://ntfy.sh/my-topic"] * 3


def moved(t, chg, sess="pre", stale=False, state="PRE"):
    sn = snap(t, "HOLD")
    sn["payload"]["quote"] = {"ext_session": sess, "ext_change": chg, "ext_price": 50.0, "ext_stale": stale, "market_state": state}
    return sn


def test_premarket_movers_are_pushed_once_owned_first_with_their_own_threshold(monkeypatch):
    sent = capture(monkeypatch)
    st, hold = FakeStore(), [Holding("OWN", 1, 5), Holding("WL", 2, 0)]
    snaps = [moved("WL", -0.04), moved("WL2", 0.06), moved("OWN", -0.035), moved("QUIET", 0.01), moved("OLD", 0.2, stale=True)]
    assert events.moves(st, snaps, hold, day="2026-10-30") == 2
    title, text, prio, chan = sent[0]
    assert chan == "log" and prio == 4 and text.splitlines()[:2] == ["You own", "OWN -3.5% \u00b7 50.00"]
    assert "Watchlist: WL2 +6.0%" in text and "WL -4" not in text and "QUIET" not in text and "OLD " not in text
    assert events.moves(st, snaps, hold, day="2026-10-30") == 0 and len(sent) == 1       # once per stock per session
    assert events.moves(st, [moved("OWN", -0.05, "post", state="POST")], hold, day="2026-10-30") == 1   # after-hours is a new session
    assert events.moves(st, snaps, hold, day="2026-10-31") == 2                          # a new day starts again


def test_extras_and_regular_session_are_not_pushed_as_moves(monkeypatch):
    sent = capture(monkeypatch)
    assert events.moves(FakeStore(), [moved("EEE", 0.5)], [], frozenset({"EEE"}), day="d") == 0
    assert events.moves(FakeStore(), [moved("RRR", 0.5, state="REGULAR")], [], day="d") == 0 and sent == []


def test_a_long_list_is_cut_to_the_biggest_moves(monkeypatch):
    sent = capture(monkeypatch)
    hold = [Holding(f"O{i}", 1, 5) for i in range(8)]
    snaps = [moved(f"O{i}", -0.03 - i / 100) for i in range(8)] + [moved(f"W{i}", 0.05 + i / 100) for i in range(9)]
    events.moves(FakeStore(), snaps, hold, day="d")
    title, text, prio, chan = sent[0]
    lines = text.splitlines()
    assert title == "Pre-market: 17 moved (8 you own)" and lines[1].startswith("O7 -10.0%") and "+3 more you own" in lines
    assert lines[-1].startswith("Watchlist: W8 +13.0%") and "(+3 more)" in lines[-1] and len(lines) == 8
    assert "HOLD" not in text                                          # a plain HOLD or WAIT is not worth a line


def test_a_buy_push_waits_while_the_tape_is_under_its_line_and_shows_the_live_price_and_the_close(monkeypatch):
    sent = capture(monkeypatch)
    st, hold = FakeStore(), [Holding("XXX", 2, 0)]

    def live(price):
        s = snap("XXX", "BUY")
        s["payload"]["quote"] = {"market_state": "REGULAR", "live_price": price, "live_change": 0.0}
        s["payload"]["technical"]["one_call"]["distance_swings"] = 0.5
        return s

    events.call_flips(st, [snap("XXX", "WAIT")], hold)                              # the first look
    events.call_flips(st, [live(300.0)], hold)                                      # BUY, but live 300 is under its line 316.6
    assert sent == []
    events.call_flips(st, [live(320.0)], hold)                                      # back above the line: now it is pushed, once
    assert len(sent) == 1 and "XXX: New buy signal. Price 320.00." in sent[0][1]
    events.call_flips(st, [live(321.0)], hold)
    assert len(sent) == 1


def test_a_failed_push_is_recorded_and_tried_again_once(monkeypatch):
    store = FakeStore()
    calls = {"n": 0}

    def flaky(title, text, priority=3, tags="", click=None, channel="calls"):
        calls["n"] += 1
        if calls["n"] == 1:
            raise notify.DeliveryError("ntfy HTTP 429")
        return "sent"

    monkeypatch.setattr(notify, "ntfy_send", flaky)
    assert events._push("T", ["line"], 3, "bell", None, "log", store).startswith("failed")
    import json
    assert json.loads(store.d[events.FAIL_KEY])[0]["error"] == "failed: ntfy HTTP 429"
    assert len(json.loads(store.d[events.OUTBOX_KEY])) == 1
    assert events.resend(store) == 1 and json.loads(store.d[events.OUTBOX_KEY]) == []
    assert events.resend(store) == 0                                  # nothing left to send


def test_a_burst_of_trades_goes_out_as_one_push_per_side(monkeypatch):
    sent = capture(monkeypatch)
    did = [{"ticker": t, "action": "ENTER", "price": 10.0, "reason": "BUY: near its line"} for t in "ABCDEFG"]
    events.trades("New call", did, {"trades": [{"ticker": t, "shares": 10, "size": 100.0, "stop": 9.0} for t in "ABCDEFG"]})
    assert len(sent) == 1 and sent[0][0] == "New call bought 7 stocks (fake money)" and sent[0][3] == "log"
    assert all(t in sent[0][1] for t in "ABCDEFG")
    sent.clear()
    events.trades("Quick", did[:2], None)
    assert len(sent) == 2                                              # a few stay one push each


# ---- Log-tab signals: volume only while the market is open (calls feed, with the call); the rest in one log push
class AlertStore(FakeStore):
    def __init__(self, rows=()):
        super().__init__()
        self.rows = list(rows)

        class _C:
            def __init__(c, outer):
                c.o = outer

            def execute(c, *_a):
                class _R:
                    def fetchone(r):
                        return (max([x["id"] for x in c.o.rows] or [0]),)
                return _R()
        self.conn = _C(self)

    def alerts_after(self, i):
        return [r for r in self.rows if r["id"] > i]


def alert(i, t, code, msg, price=10.0):
    return {"id": i, "ticker": t, "code": code, "message": msg, "price": price}


def test_signals_learn_first_then_split_volume_and_news(monkeypatch):
    sent = capture(monkeypatch)
    st = AlertStore([alert(1, "OLD", "estimates_rising", "old news")])
    hold = [Holding("AAA", 1, 10)]
    snaps = [snap("AAA", "ADD"), snap("BBB", "HOLD")]
    assert events.signals(st, snaps, hold, session="REGULAR") == {"volume": 0, "news": 0} and sent == []     # first look: learn only
    st.rows += [alert(2, "AAA", "volume_surge_down", "2.0x average volume on a -5.0% day"),
                alert(3, "BBB", "volume_surge_up", "3.0x average volume on a +6.0% day"),
                alert(4, "BBB", "estimates_rising", "Analysts are raising estimates"),
                alert(5, "AAA", "earnings_setup_good", "Earnings in 4 days")]
    assert events.signals(st, snaps, hold, session="REGULAR") == {"volume": 2, "news": 2}
    vol, news = sent
    assert vol[3] == "calls" and vol[2] == 4 and "AAA (you own it)" in vol[1] and "call: ADD" in vol[1] and "call: HOLD" in vol[1]
    assert news[3] == "log" and news[0] == "News: 2 new signals" and news[1].splitlines()[0].startswith("AAA (you own it)")
    assert events.signals(st, snaps, hold, session="REGULAR") == {"volume": 0, "news": 0}                  # each is pushed once


def test_volume_is_not_pushed_outside_the_regular_session_and_not_later(monkeypatch):
    sent = capture(monkeypatch)
    st = AlertStore()
    snaps = [snap("BBB", "HOLD")]
    events.signals(st, snaps, [], session="CLOSED")
    st.rows.append(alert(1, "BBB", "volume_surge_up", "3.0x average volume on a +6.0% day"))
    assert events.signals(st, snaps, [], session="POST") == {"volume": 0, "news": 0} and sent == []
    assert events.signals(st, snaps, [], session="REGULAR") == {"volume": 0, "news": 0} and sent == []
