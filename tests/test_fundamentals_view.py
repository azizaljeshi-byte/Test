from stockwatch import fundamental, fundamentals_view as fv
from test_dayboard import make

STRONG = {"revenue_growth": 1.15, "earnings_growth": 0.5, "operating_margin": 0.25, "roe": 0.3, "debt_to_equity": 0.1,
          "current_ratio": 3.0, "pe_forward": 15.0, "peg": 0.8, "target_mean_price": 140.0, "free_cash_flow": 5e8,
          "recommendation_mean": 1.6}


def snap_with(metrics, score=98.0, source=None, research=None):
    s = make("HOLD", "pullback")
    s["fundamental_score"] = score
    s["payload"]["fundamental"] = {**metrics, "coverage": 90, **({"source": source} if source else {})}
    s["payload"]["research"] = research or {}
    return s


def real_metrics(raw, price=100.0):
    _, m, _ = fundamental.analyze(raw, price)
    return m


def test_a_strong_company_reads_strong_with_good_icons_and_a_source():
    html = fv.fundamentals(snap_with(real_metrics(STRONG), source="SEC filings"))
    assert "Fundamentals Strong" in html and "SEC filings" in html and "Revenue growth: +115%" in html
    assert 'dz-k-good' in html and "of 10 measures" in html


def test_the_words_follow_the_same_bands_as_the_score():
    weak = {"revenue_growth": -0.2, "debt_to_equity": 3.0, "operating_margin": -0.1}
    lines, got = fv.measure_lines(real_metrics(weak))
    kinds = {t.split(":")[0]: k for k, t in lines}
    assert got == 3 and kinds["Revenue growth"] == "bad" and kinds["Debt to equity"] == "bad" and kinds["Operating margin"] == "bad"


def test_too_little_data_says_unknown_and_never_scores_zero():
    s = snap_with({"revenue_growth": 0.1}, score=50.0)
    s["payload"]["fundamental"]["coverage"] = 10
    html = fv.fundamentals(s)
    assert "Fundamentals n/a" in html and "unknown: only 1 of 10 measures" in html and (chr(34) + "fv-pls" + chr(34)) not in html


def test_revenue_and_profit_per_share_are_drawn_when_the_research_has_them():
    rq = [{"period": f"2026-0{i}-30", "revenue": 100e6 + i * 10e6, "gross_margin": 0.6, "op_margin": 0.2} for i in (5, 4, 3, 2, 1)]
    qs = [{"quarter": "2026-07-31", "eps_estimate": 1.0, "eps_actual": 1.1, "reaction": -0.2},
          {"quarter": "2026-04-30", "eps_estimate": 1.0, "eps_actual": 0.9, "reaction": 0.05}]
    html = fv.fundamentals(snap_with(real_metrics(STRONG), research={"earnings": {"revenue_q": rq, "quarters": qs}}))
    assert "Revenue, last 5 quarters" in html and "$150.0M" in html and "BEAT" in html and "MISS" in html and "-20%" in html


def test_the_report_card_letters_company_line_delivery_and_insiders_are_folded_in():
    s = snap_with(real_metrics(STRONG), source="Yahoo", research={
        "earnings": {"reported": 4, "beats": 0, "avg_move": 0.14, "quarters": [
            {"quarter": f"2026-0{i}-30", "eps_estimate": 1.0, "eps_actual": 0.8} for i in (7, 6, 5, 4)]},
        "smart_money": {"buyers_90d": 1, "short_pct_float": 0.22, "institution_pct": 0.55}})
    s["payload"]["profile"] = {"name": "Acme Corp", "industry": "Software", "country": "United States", "market_cap": 15.5e9,
                               "employees": 1126, "website": "https://example.com", "summary": "Makes things."}
    html = fv.fundamentals(s)
    assert "Acme Corp" in html and "website" in html and "Report card" in html and "Beat 0 of the last 4" in html
    assert "1 buyer in 90 days" in html and "22% of shares are sold short" in html and "Institutions own 55%" in html
    assert "not part of the fundamentals rating" in html and "Overall" not in html


def test_reaction_needs_a_volume_spike():
    import numpy as np, pandas as pd
    from stockwatch import deepdive
    idx = pd.bdate_range("2026-08-01", periods=90)
    hist = pd.DataFrame({"Close": np.linspace(50, 60, 90), "Volume": 1_000_000.0}, index=idx)
    assert deepdive._reaction(hist, "2026-06-30") == (None, None)     # no spike: report not in the bars yet
    hist.loc[idx[10], "Volume"] = 5_000_000.0
    day, move = deepdive._reaction(hist, "2026-06-30")
    assert day == idx[10].date().isoformat() and move is not None


def test_pending_revenue_note():
    import inspect
    from stockwatch import fundamentals_view as fv
    assert "quarterly report" in inspect.getsource(fv)


def test_report_day_uses_the_real_report_date_and_an_option_expiry_friday_is_not_picked():
    import numpy as np, pandas as pd
    from stockwatch import deepdive
    idx = pd.bdate_range("2026-06-15", periods=120)
    hist = pd.DataFrame({"Close": np.linspace(100, 110, 120), "Volume": 1_000_000.0}, index=idx)
    witching = pd.Timestamp("2026-09-18")                          # 80 days after the quarter end, heavy volume
    hist.loc[witching, "Volume"] = 6_000_000.0
    assert deepdive._reaction(hist, "2026-06-30")[0] != "2026-09-18"      # outside the 10-50 day window now
    hist.loc[pd.Timestamp("2026-08-07"), "Close"] = hist.loc[pd.Timestamp("2026-08-06"), "Close"] * 1.05
    after_close = [{"date": "2026-08-06", "hour": 16}]                 # reported after the close on the 6th: the move is on the 7th
    day, move = deepdive._reaction(hist, "2026-06-30", after_close)
    assert day == "2026-08-07" and abs(move - 0.05) < 1e-6
    day, _ = deepdive._reaction(hist, "2026-06-30", [{"date": "2026-08-06", "hour": 7}])
    assert day == "2026-08-06"                                         # a morning report moves the same day


def test_a_loss_quarter_is_not_drawn_to_scale_and_still_reads_beat_when_the_loss_is_smaller():
    from stockwatch import fundamentals_view as fv
    q = [{"quarter": "2026-06-30", "eps_actual": -6.75, "eps_estimate": -7.25, "reaction": None},
         {"quarter": "2026-03-31", "eps_actual": 2.03, "eps_estimate": 1.91, "reaction": -0.01}]
    html = fv._eps(q)
    assert "loss quarter" in html and ">BEAT<" in html and html.count("fv-ls") == 1


def test_institutional_ownership_over_100_is_explained_without_altering_scores():
    import copy
    from stockwatch import briefing
    for value in (0.62,1.0,1.35,None):
        s=snap_with(real_metrics(STRONG),research={'smart_money':{'institution_pct':value}})
        before=copy.deepcopy(s)
        markup=fv.fundamentals(s)
        card=briefing.overview(s)
        smart=next(g for g in card['grades'] if g['area']=='Smart money')
        assert s==before
        if value is None:
            assert 'Institutions ' not in markup and 'institutions' not in smart['note']
        elif value>1:
            assert 'Institutions hold more than 100% of shares (funds report overlapping holdings)' in markup
            assert 'institutions: over 100% (overlap)' in smart['note']
            assert '135%' not in markup and '135%' not in smart['note']
        else:
            assert f'Institutions own {value*100:.0f}%' in markup
            assert f'institutions own {value*100:.0f}%' in smart['note']
        assert smart['score']==50.0
