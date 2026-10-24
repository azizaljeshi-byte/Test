"""The stock row: the price leads, big, with its change under it; the rest sits in a quieter facts block."""
from stockwatch import ui

from test_ci_scan import ev
from test_status_wiring import ps, snap_of


def snap(price=86.96, day=0.017, quote=None, code="testing_support"):
    e = ev("INTC", "HOLD", price=price)
    e.technical = {"price_status": ps(code), "day_change": day}
    s = snap_of(e)
    s["price"] = price
    s["payload"]["technical"] = e.technical
    s["payload"]["quote"] = quote or {}
    return s


def test_the_price_is_big_with_the_day_change_under_it():
    html = ui.row(snap())
    assert '<b class="big">86.96</b>' in html and '<span class="chg"' in html and "▲ +1.7%" in html
    assert html.index('class="big"') < html.index('class="why"') < html.index('class="facts"')


def test_a_falling_stock_reads_red_and_down():
    html = ui.row(snap(day=-0.021))
    assert "▼ -2.1%" in html and ui.RISK in html.split('class="chg"')[1].split("</span>")[0]


def test_after_hours_sits_on_its_own_quiet_line_not_in_the_price():
    q = {"market_state": "POST", "ext_price": 87.09, "ext_change": 0.001, "ext_session": "post"}
    html = ui.row(snap(quote=q))
    price_block = html.split('class="pxb"')[1].split("</div>")[0]
    assert "87.09" not in price_block and 'class="ext"' in html and "AH <b>87.09</b>" in html


def test_live_is_flagged_in_the_regular_session():
    q = {"market_state": "REGULAR", "live_price": 88.5, "live_change": 0.03, "fetched_at": "2026-10-23T15:40:00+00:00"}
    html = ui.row(snap(quote=q))
    assert '<b class="big">88.50</b>' in html and "● LIVE 15:40" in html and "+3.0%" in html


def test_no_trades_yet_is_said_not_hidden():
    q = {"market_state": "PRE", "ext_price": None}
    assert "PRE no trades yet" in ui.row(snap(quote=q))


def test_a_missing_price_shows_a_dash_not_a_crash():
    html = ui.row(snap(price=float("nan"), day=None))
    assert '<b class="big">—</b>' in html and "chg" not in html.split('class="why"')[0].split('class="pxb"')[1]


def test_facts_are_grouped_and_a_bare_row_has_no_empty_block():
    html = ui.row(snap())
    assert html.count('class="facts"') == 1 and '<div class="pl"><b>PLAN</b>' in html and "<b>LEVELS</b>" in html
    bare = ev("X", "HOLD")
    bare.plan = {}
    s = snap_of(bare)
    s["payload"]["technical"] = {}
    assert 'class="facts"' not in ui.row(s)


def test_the_other_screens_still_get_their_price_line():
    html = ui._price(snap())[1]
    assert "+1.7%" in html
