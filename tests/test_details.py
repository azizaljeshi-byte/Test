from stockwatch import details
from test_dayboard import make


def with_chart(s, code, label, support_low=110.13, stop=106.48, price=112.52):
    s["price"] = price
    s["payload"]["technical"]["price_status"] = {"code": code, "label": label, "floor_known": True,
                                                  "levels": {"support_low": support_low, "support_high": 111.87}}
    s["payload"]["plan"] = {**(s["payload"].get("plan") or {}), "stop": stop}
    return s


def test_two_exits_are_shown_as_two_stages_highest_first_with_dollar_signs():
    s = with_chart(make("HOLD", "pullback"), "weakening", "WEAKENING")
    rows = details.exit_ladder(s)
    assert [r[0] for r in rows] == ["Chart exit", "Plan stop"] and rows[0][1] > rows[1][1]
    html = details.decision(s)
    assert "$110.13" in html and "$106.48" in html and "quality rating, not the decision" in html


def test_a_good_score_on_a_weakening_chart_says_so_and_does_not_hide_either():
    s = with_chart(make("HOLD", "pullback"), "weakening", "WEAKENING")
    s["verdict"] = "STRONG HOLD"
    html = details.decision(s)
    assert "but the chart reads weakening" in html and "Strong Hold" in html


def test_a_watchlist_name_has_no_exits():
    s = with_chart(make("HOLD", "pullback", held=False), "weakening", "WEAKENING")
    assert details.exit_ladder(s) == []


def test_icons_follow_the_wording_and_a_mixed_line_takes_the_worse_side():
    k = details.line_kind
    assert k("why", "Risk: Below ATR trailing stop") == "bad" and k("why", "Opportunity: Analysts are raising estimates") == "good"
    assert k("why", "Fundamentals are strong (98/100): best on growth (100)") == "good"
    assert k("why", "Fundamentals are weak (30/100)") == "bad"
    assert k("why", "Price trend is up - above its 200-day; RSI 75 (overbought).") == "careful"
    assert k("why", "Over 3 months it has underperformed the market by 31%") == "bad"
    assert k("changed", "First scan on record - nothing to compare yet.") == "info"
    assert k("watch", "Earnings on 2026-11-20 (24 days)") == "careful"
    assert k("watch", "Price is below its trailing stop (1.0) - the stop has been hit.") == "bad"


def test_the_brief_has_an_icon_on_every_line_and_a_key():
    html = details.brief_html({"headline": "X is fine.", "why": ["Risk: a", "Opportunity: b"], "changed": [], "watch": ["Key levels: x."]})
    assert html.count('class="dz-li') == 3 and "Good for the stock" in html and "Watch next" in html
