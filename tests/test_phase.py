from stockwatch import phase, ui


def snap(code, mom, live=None, atr=2.0, call=None, price=100.0, state="REGULAR"):
    q = {"market_state": state, "live_price": price, "live_change": live} if live is not None else {}
    return {"ticker": "X", "price": price, "payload": {"quote": q, "technical": {
        "atr": atr, "price_status": {"code": code, "label": code.replace("_", " ")},
        "momentum": {"known": True, "momentum": mom}, "one_call": {"call": call} if call else {}}}}


def word(*a, **k):
    r = phase.phase(snap(*a, **k))
    return r and r["label"]


def test_the_five_words():
    assert word("strong_uptrend", "strong") == "RIDING"
    assert word("record_high", "building", live=0.01) == "RIDING"
    assert word("strong_uptrend", "fading") == "SLOWING"
    assert word("pullback", "building") == "PULLING BACK"
    assert word("weakening", "stabilising") == "STABILISING"
    assert word("testing_support", "stabilising") == "STABILISING"
    assert word("weakening", "falling") == "FALLING"
    assert word("breakdown", "weak") == "FALLING"


def test_giving_back_today_turns_riding_into_slowing():
    # down 2% on a 2.00 daily range at a price of 100 = 1 daily range
    assert word("strong_uptrend", "strong", live=-0.02) == "SLOWING"
    assert word("strong_uptrend", "strong", live=-0.005) == "RIDING"
    assert word("strong_uptrend", "strong", live=-0.02, state="CLOSED") == "RIDING"      # no live session: today's move is not used


def test_a_confirmed_breakdown_is_never_stabilising():
    assert word("deep_breakdown", "stabilising") == "FALLING"


def test_missing_or_unclear_reads_give_no_word():
    assert word("unknown", "strong") is None
    s = snap("strong_uptrend", "strong")
    s["payload"]["technical"]["momentum"] = {"known": False, "why": "short history", "momentum": None}
    assert phase.phase(s) is None
    assert word("strong_uptrend", "stabilising") is None
    assert phase.phase({"payload": {}}) is None


def test_never_contradicts_the_new_call():
    assert word("strong_uptrend", "strong", call="EXIT") is None
    assert word("breakdown", "falling", call="BUY") is None
    assert word("breakdown", "falling", call="EXIT") == "FALLING"


def test_chip_is_plain_and_safe():
    h = ui.phase_chip(snap("strong_uptrend", "strong"))
    assert "Move" in h and "riding" in h
    assert ui.phase_chip({"payload": {}}) == ""


def test_breakdown_bouncing_label_does_not_change_the_phase_code():
    for code in phase.BREAKDOWN:
        s=snap(code,'falling',live=0.024,price=102.4,atr=2,call='EXIT')  # previous close 100; up 1.2 ATR
        r=phase.phase(s)
        assert r['code']=='FALLING' and r['label']=='BOUNCING TODAY'
        assert 'daily chart still broken' in r['why']
        assert 'bouncing today' in ui.phase_chip(s)
        assert s['payload']['technical']['one_call']['call']=='EXIT'
        assert word(code,'falling',live=0.01,price=101,atr=2)=='FALLING'  # +0.5 ATR
        assert word(code,'falling',live=0.02,price=102,atr=2)=='BOUNCING TODAY'  # equality, 1.0 ATR
        assert word(code,'falling')=='FALLING'
        assert word(code,'falling',live=0.03,atr=None)=='FALLING'
        assert word(code,'falling',live=0.03,price=None)=='FALLING'
        assert word(code,'falling',live=0.03,state='CLOSED')=='FALLING'
    assert word('strong_uptrend','strong',live=0.024,price=102.4)=='RIDING'
