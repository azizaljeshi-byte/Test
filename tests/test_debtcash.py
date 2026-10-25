from stockwatch import debtcash, debtcash_view as dv


def f(start, end, val, filed="2025-01-01"):
    return {"start": start, "end": end, "val": val, "filed": filed}


def test_year_to_date_cash_flow_becomes_single_quarters():
    vals = [f("2024-01-01", "2024-03-31", 10), f("2024-01-01", "2024-06-30", 25), f("2024-01-01", "2024-09-30", 45),
            f("2024-01-01", "2024-12-31", 70), f("2025-01-01", "2025-03-31", 20)]
    q = {x["end"]: x["value"] for x in debtcash.quarterly(vals)}
    assert q == {"2024-03-31": 10, "2024-06-30": 15, "2024-09-30": 20, "2024-12-31": 25, "2025-03-31": 20}
    assert [x["end"] for x in debtcash.quarterly(vals)][0] == "2025-03-31"           # newest first
    assert debtcash.quarterly([f("2024-01-01", "2024-09-30", 45)]) == []             # a nine-month figure alone is not a quarter


def test_build_uses_filings_then_yahoo_and_never_turns_missing_into_zero():
    sec = {"debt_cash": {"cash": 60e9, "debt": 25e9, "equity": 60e9, "interest_ttm": 250e6, "ebit_ttm": 45e9,
                         "cfo_q": [{"end": f"2025-0{m}-30", "value": 10e9} for m in (9, 8, 7, 6)], "capex_q": [], "as_of": "2025-09-30"}}
    d = debtcash.build({"debt_to_equity": 40.0, "current_ratio": 4.4}, sec)
    assert d["source"] == "company filings" and abs(d["debt_to_equity"] - 25 / 60) < 1e-9 and d["fcf_ttm"] == 40e9
    y = debtcash.build({"total_cash": 5e9, "total_debt": None, "debt_to_equity": 150.0, "free_cash_flow": -1e9}, None)
    assert y["source"] == "Yahoo" and y["cash"] == 5e9 and y["debt"] is None and y["debt_to_equity"] == 1.5 and y["fcf_ttm"] == -1e9
    empty = debtcash.build({}, None)
    assert empty["cash"] is None and empty["debt"] is None and empty["source"] is None


def snap(d):
    return {"payload": {"research": {"debt_cash": d}}}


def healthy():
    q = [{"end": e, "value": 10e9} for e in ("2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31")]
    return debtcash.build({"current_ratio": 4.4}, {"debt_cash": {"cash": 60e9, "debt": 25e9, "equity": 60e9, "interest_ttm": 250e6,
                                                                  "ebit_ttm": 45e9, "cfo_q": q, "capex_q": [], "as_of": "2025-09-30"}})


def test_a_healthy_card_says_cash_covers_debt_and_shows_the_tiles_and_chart():
    html = dv.html(snap(healthy()))
    assert "Cash covers its debt 2.4 times" in html and "made cash in each of the last 4 quarters" in html
    assert "Net cash" in html and "+$35.0B" in html and "very safe" in html and "<svg" in html and "positive in 4 of 4" in html
    assert "Cash runway" not in html


def test_a_cash_burner_shows_runway_and_net_debt_and_a_red_headline():
    d = debtcash.build({"free_cash_flow": -0.6e9, "total_cash": 0.9e9, "total_debt": 1.3e9}, None)
    html = dv.html(snap(d))
    assert "Burning cash. Cash covers about 18 months" in html or "about 18 months" in html
    assert 'class="dc-hl careful"' in html or 'class="dc-hl bad"' in html
    assert "Net debt" in html and "debt is larger than cash" in html and "Cash runway" in html
    d2 = debtcash.build({"free_cash_flow": -1.2e9, "total_cash": 0.9e9, "total_debt": 1.3e9}, None)
    assert 'class="dc-hl bad"' in dv.html(snap(d2))                       # 9 months of cash is under the 18-month line


def test_missing_figures_say_not_available_and_never_zero():
    html = dv.html(snap(debtcash.build({}, None)))
    assert "not available" in html and "$0" not in html and "n/a" in html
    assert "Not read yet" in dv.html({"payload": {"research": {}}})
    t = dict((a, (b, n)) for a, b, c, n in dv.tiles(debtcash.build({}, None)))
    assert t["Interest cover"][0] == "n/a" and t["Debt to equity"][0] == "n/a"
    loss = debtcash.build({}, {"debt_cash": {"cash": 1, "debt": 1, "equity": 1, "ebit_ttm": -5, "interest_ttm": 1, "cfo_q": [], "capex_q": []}})
    assert dict((a, n) for a, b, c, n in dv.tiles(loss))["Interest cover"] == "no operating profit"


def test_fetch_facts_carries_the_debt_and_cash_block(monkeypatch):
    from stockwatch import sec

    def usd(vals):
        return {"units": {"USD": vals}}

    def fact(start, end, val, form="10-Q"):
        d = {"end": end, "val": val, "form": form, "filed": end}
        if start:
            d["start"] = start
        return d
    company = {"entityName": "Acme", "facts": {"us-gaap": {
        "CashAndCashEquivalentsAtCarryingValue": usd([fact(None, "2025-09-30", 60.0)]),
        "MarketableSecuritiesCurrent": usd([fact(None, "2025-09-30", 5.0)]),
        "LongTermDebtNoncurrent": usd([fact(None, "2025-09-30", 20.0)]),
        "StockholdersEquity": usd([fact(None, "2025-09-30", 50.0)]),
        "NetCashProvidedByUsedInOperatingActivities": usd([fact("2025-01-01", "2025-03-31", 10.0), fact("2025-01-01", "2025-06-30", 25.0)]),
        "PaymentsToAcquirePropertyPlantAndEquipment": usd([fact("2025-01-01", "2025-03-31", 1.0), fact("2025-01-01", "2025-06-30", 3.0)]),
    }}}
    monkeypatch.setattr(sec, "cik_for", lambda t: 1)
    monkeypatch.setattr(sec, "_get", lambda url: company)
    out = sec.fetch_facts("ACME")["debt_cash"]
    assert out["cash"] == 65.0 and out["debt"] == 20.0 and out["equity"] == 50.0 and out["interest_ttm"] is None
    assert [q["value"] for q in out["cfo_q"]] == [15.0, 10.0] and [q["value"] for q in out["capex_q"]] == [2.0, 1.0]
