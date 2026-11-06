from datetime import datetime

from stockwatch import paper_layout as pl
from stockwatch.data import NY


def test_money_adds_up_and_leaves_unpriced_out():
    pos = {"AAA": {"shares": 10, "entry": 100.0}, "BBB": {"shares": 5, "entry": 20.0}}
    m = pl.money(4_000.0, 5_000.0, pos, {"AAA": 110.0})              # BBB has no price now
    assert m["used"] == 1_100.0 and m["cash"] + m["used"] - 5_000.0 == m["realized"] == 100.0
    assert m["unreal"] == 100.0 and m["unpriced"] == 1                # unknown is left out, not counted as 0
    assert m["total"] == 4_000.0 + 1_100.0 + 100.0                    # the unpriced one is carried at its entry


def test_times_are_shown_on_the_riyadh_clock():
    assert pl.riyadh("2026-11-04 12:02") == "Nov 4 · 20:02"           # 12:02 New York (EST) is 20:02 in Riyadh
    assert pl.riyadh(None) == "—"


def test_status_tags():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=NY)
    base = {"entry": 100.0, "stop": 95.0, "peak_at": datetime(2026, 11, 4, 11, 58, tzinfo=NY).isoformat()}
    assert pl.status(base, 101.0, now)[0] == "RISING"
    assert pl.status({**base, "peak_at": datetime(2026, 11, 4, 11, 40, tzinfo=NY).isoformat()}, 101.0, now)[0] == "SLOWING"
    assert pl.status({**base, "stop": 101.0}, 103.0, now)[0] == "RIDING"
    assert pl.status({**base, "read": "down 1%: watching, falling or stabilising?"}, 98.0, now)[0] == "DIP WATCH"
    assert pl.status({**base, "read": "falling: -1.9% and still sliding"}, 98.0, now)[0] == "FALLING"
    assert pl.status(base, 98.0, now)[0] == "BELOW ENTRY" and pl.status(base, None, now) == ("", "")


def test_card_shows_profit_and_loss_figures():
    pos = {"shares": 10, "entry": 100.0, "stop": 95.0}
    t = {"ticker": "AAA", "opened": "2026-11-04 12:02"}
    up, dn = pl.open_card(t, pos, 110.0, [("BOUNCE", "o")]), pl.open_card(t, pos, 90.0, [])
    assert "IN PROFIT" in up and "+$100.00 · +10.0%" in up and "BOUNCE" in up and "Bought Nov 4 · 20:02" in up
    assert "IN LOSS" in dn and "−$100.00 · −10.0%" in dn
    assert "NO PRICE" in pl.open_card(t, pos, None, [])
