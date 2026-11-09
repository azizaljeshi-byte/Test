"""The one call per stock: the New call in plain words; fundamentals are guidance only (owner, 9 Nov)."""
from stockwatch import simplecall
from test_stockhead import snap


def test_every_new_call_word_has_one_plain_word_and_group():
    seen = {}
    for call in ("EXIT", "AVOID", "ON THE LINE", "WAIT FOR TURN", "BUY", "ADD", "HOLD", "WAIT"):
        s = snap(); s["payload"]["technical"]["one_call"]["call"] = call
        c = simplecall.of(s)
        seen[call] = (c["word"], c["group"])
    assert seen == {"EXIT": ("Sell", "sell"), "AVOID": ("Avoid", "sell"), "ON THE LINE": ("On the line", "watch"), "WAIT FOR TURN": ("Watch", "watch"),
                    "BUY": ("Buy", "buy"), "ADD": ("Add", "buy"), "HOLD": ("Hold", "hold"), "WAIT": ("Wait", "hold")}


def test_unknown_call_or_error_is_no_call_with_the_reason_never_a_guess():
    s = snap(); s["payload"]["technical"]["one_call"] = {"known": False, "call": "UNKNOWN", "why": "no exit line"}
    c = simplecall.of(s)
    assert c["word"] == "No call" and c["group"] == "unknown" and c["why"] == "no exit line" and c["sure"] is None
    s = snap(); s["payload"]["error"] = "no data"
    assert simplecall.of(s)["word"] == "No call"
    s = snap(); s["payload"]["technical"] = {}
    assert simplecall.of(s)["group"] == "unknown"


def test_how_sure_is_counted_only_for_a_sell_or_a_buy():
    s = snap(); s["payload"]["technical"]["one_call"]["call"] = "HOLD"
    assert simplecall.of(s)["sure"] is None
    s = snap(); s["payload"]["technical"]["one_call"]["call"] = "EXIT"
    sure = simplecall.of(s)["sure"]
    assert sure is None or (0 <= sure[0] <= sure[1] and sure[1] >= 3)


def test_the_fundamentals_score_never_moves_the_call_and_unknown_is_not_zero():
    out = []
    for f in (0.0, 50.0, 100.0, None):
        s = snap(); s["fundamental_score"] = f
        c = simplecall.of(s); out.append((c["word"], c["why"]))
        assert ("unknown" in simplecall.fund_line(c)) == (f is None)
    assert len(set(out)) == 1
