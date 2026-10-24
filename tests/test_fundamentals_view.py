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
