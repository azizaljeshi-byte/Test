from stockwatch import guide
from test_dayboard import make


def full(s):
    s["payload"]["plan"].update(entry=99.5, risk_per_share=4.5, rr=2.0)
    return s


def test_a_clean_buy_in_the_zone_says_buy_with_a_limit_order_and_a_size():
    s = full(make("NOW", "strong_uptrend", mom="strong"))
    gs = guide.gates(s)
    assert all(g["state"] in ("ok", "none") for g in gs)
    assert guide.verdict(s, gs)[0] == "BUY"
    html = guide.card(s, 50000, 1.0, 15)
    assert "Trade guide" in html and "limit order" in html and "Shares" in html and 'class="tg-v good"' in html


def test_a_failed_gate_says_wait_and_names_it_never_two_answers():
    s = make("NOW", "strong_uptrend", mom="falling", second={"source": "TradingView", "signal": "sell"})
    word, cls, line = guide.verdict(s, guide.gates(s))
    assert word != "BUY"
    assert "falling" in guide.card(s, 50000, 1.0, 15) and "SELL" in guide.card(s, 50000, 1.0, 15)


def test_a_missing_read_is_not_read_never_a_pass_or_a_fail():
    s = make("NOW", None)
    gs = {g["title"]: g for g in guide.gates(s)}
    assert gs["Chart"]["state"] == "none" and gs["Momentum"]["state"] == "none" and "not read" in gs["Chart"]["note"]


def test_the_capped_size_says_why_and_no_account_asks_for_one():
    s = full(make("NOW", "strong_uptrend", mom="strong"))
    assert "capped" in guide.buy_tab(s, 50000, 1.0, 1) and "limit" in guide.buy_tab(s, 50000, 1.0, 1)
    assert "Type your account size" in guide.buy_tab(s, 0, 1.0, 15)


def test_a_watchlist_name_has_nothing_to_sell_and_a_held_sell_says_all():
    assert "nothing to sell" in guide.sell_tab(make("NOW", "pullback", held=False))
    assert "Sell <b>" in guide.sell_tab(make("TRIM", "breakdown"))
    assert "NO SELL" in guide.sell_tab(make("HOLD", "strong_uptrend"))


def test_no_order_advice_unless_the_verdict_is_buy():
    bad = full(make("NOW", "strong_uptrend", mom="falling"))
    html = guide.buy_tab(bad, 50000, 1.0, 15)
    assert "limit order" not in html and "planning only" in html


def test_shares_are_whole_and_a_too_small_account_says_so():
    import copy
    s = copy.deepcopy(make("NOW", "pullback", mom="strong"))
    s["payload"]["plan"].update(entry=147.29, risk_per_share=47.21, stop=100.08)
    small = guide.buy_tab(s, 2517, 1.0, 15)
    assert "too small" in small and "47.21" in small and "<b>1</b>" not in small
    big = guide.buy_tab(s, 50000, 1.0, 15)
    assert "too small" not in big and "lose about" in big
    assert "$472.10" in big                                              # 10 whole shares at 47.21


def test_a_price_already_below_the_chart_floor_says_the_exit_was_hit():
    import copy
    s = copy.deepcopy(make("NOW", "pullback", mom="strong"))          # the sample's inner dicts are shared between tests
    s["payload"]["plan"].update(entry=147.29, risk_per_share=47.21, stop=100.08)
    s["payload"]["technical"]["price_status"]["levels"] = {"support_low": 178.59}
    s["payload"]["quote"] = {}
    s["price"] = 147.0
    assert "already below the chart floor" in guide.buy_tab(s, 50000, 1.0, 15)
