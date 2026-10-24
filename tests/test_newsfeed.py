"""Multi-source news, ranking and critical-news Telegram alerts (stockwatch/newsfeed.py). Offline, fakes only."""
from datetime import datetime, timedelta, timezone

import pytest

from stockwatch import catalysts, newsfeed, notify, ui

from test_ci_scan import FakeTelegram, Fleet, clean_env, configure, ev

_AUTOUSE = clean_env

T0 = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Acme cuts full-year guidance after weak orders - Reuters</title><link>https://g/1</link>
<pubDate>Sat, 24 Oct 2026 09:30:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Acme opens a new office - Local Paper</title><link>https://g/2</link>
<pubDate>Sat, 24 Oct 2026 08:00:00 GMT</pubDate><source url="x">Local Paper</source></item>
<item><title>no date here</title><link>https://g/3</link></item>
</channel></rss>"""


def item(title, source, hours_ago=1.0, **kw):
    return {"title": title, "publisher": source, "url": f"https://x/{abs(hash(title)) % 999}",
            "published": T0 - timedelta(hours=hours_ago), "source": source, **kw}


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    newsfeed._cache.clear()
    monkeypatch.setattr(newsfeed, "_get", lambda url: (_ for _ in ()).throw(OSError("network disabled in tests")))


# ---- parsing and tiers

def test_rss_is_parsed_and_the_publisher_suffix_dropped():
    out = newsfeed.parse_rss(RSS)
    assert [o["title"] for o in out] == ["Acme cuts full-year guidance after weak orders", "Acme opens a new office"]
    assert out[0]["publisher"] == "Reuters" and out[0]["published"].tzinfo


def test_a_broken_feed_raises_a_readable_error():
    with pytest.raises(ValueError, match="not a news feed"):
        newsfeed.parse_rss("<html><body>blocked")


@pytest.mark.parametrize("title,tier", [
    ("Acme files for Chapter 11 bankruptcy", 3), ("SEC opens investigation into Acme accounting", 3),
    ("Acme cuts full-year guidance", 3), ("Acme withdraws outlook", 3), ("FDA issues complete response letter for Acme drug", 3),
    ("Acme CEO abruptly resigns", 3), ("Acme prices $500M public offering of shares", 3), ("Trading halted in Acme", 3),
    ("Acme discloses data breach", 3), ("Short seller report targets Acme", 3), ("Acme plunges 20% on guidance", 3),
    ("Analyst downgrades Acme to hold", 2), ("Acme beats earnings estimates", 2), ("Acme to acquire Beta in $2B deal", 2),
    ("Acme raises outlook", 2), ("Acme opens a new office", 1), ("Why Acme is a top pick for 2027", 1),
    ("Acme launches new AI offerings", 1)])
def test_tiers(title, tier):
    assert newsfeed.tier_of(title) == tier


def test_sec_8k_items_set_the_tier():
    filings = [{"form": "8-K", "date": "2026-10-24", "items": "1.03,9.01", "url": "https://sec/1"},
               {"form": "8-K", "date": "2026-10-24", "items": "7.01", "url": "https://sec/2"},
               {"form": "10-Q", "date": "2026-10-24", "items": "", "url": "https://sec/3"},
               {"form": "8-K", "date": "2026-09-01", "items": "1.03", "url": "https://sec/4"}]
    out = newsfeed.sec_stories(filings, "ACME", T0)
    assert [o["tier"] for o in out] == [3, 1] and "bankruptcy" in out[0]["title"]      # the old one and the 10-Q are left out


# ---- merging and ranking

def test_the_same_story_from_three_sources_is_one_story_with_three_sources():
    groups = {"Yahoo": [item("Acme cuts full-year guidance after weak orders", "Yahoo", 2)],
              "Google News": [item("Acme cuts full-year guidance after weak orders - Reuters".replace(" - Reuters", ""), "Google News", 1.5)],
              "Finnhub": [item("Acme cuts its full-year guidance after weak orders", "Finnhub", 1)]}
    out = newsfeed.merge("ACME", True, groups, T0)
    assert len(out) == 1 and sorted(out[0]["sources"]) == ["Finnhub", "Google News", "Yahoo"] and out[0]["tier"] == 3


def test_different_stories_stay_separate_and_hot_ranks_above_more_sources():
    groups = {"Yahoo": [item("Acme opens a new office in Austin", "Yahoo", 1), item("Acme CEO abruptly resigns", "Yahoo", 5)],
              "Google News": [item("Acme opens a new office in Austin", "Google News", 1)]}
    out = newsfeed.merge("ACME", True, groups, T0)
    assert [o["tier_label"] for o in out] == ["HOT", "ROUTINE"]


def test_rank_inside_a_tier_prefers_more_sources_then_newer_then_held():
    a = {"Yahoo": [item("Analyst upgrades Acme to buy", "Yahoo", 3)]}
    b = {"Yahoo": [item("Acme beats earnings estimates", "Yahoo", 3)], "Finnhub": [item("Acme beats earnings estimates", "Finnhub", 3)]}
    both = newsfeed.merge("ACME", True, {"Yahoo": a["Yahoo"] + b["Yahoo"], "Finnhub": b["Finnhub"]}, T0)
    assert both[0]["title"].startswith("Acme beats") and len(both[0]["sources"]) == 2
    held = newsfeed.merge("A", True, a, T0)[0]["rank"]
    watch = newsfeed.merge("A", False, a, T0)[0]["rank"]
    assert held > watch


def test_old_and_future_stories_are_dropped():
    out = newsfeed.merge("A", True, {"Yahoo": [item("Acme CEO abruptly resigns", "Yahoo", 100), item("Acme files for bankruptcy", "Yahoo", -5)]}, T0)
    assert out == []


# ---- building from the sources

def test_build_uses_every_source_that_answers_and_says_why_one_did_not(monkeypatch):
    monkeypatch.setattr(newsfeed, "_get", lambda url: RSS)
    yahoo = [{"title": "Acme cuts full-year guidance after weak orders", "publisher": "Yahoo", "url": "https://y/1", "published": T0 - timedelta(hours=1)}]
    w = newsfeed.build("ACME", "Acme Inc.", True, yahoo, [], False, T0)
    assert w["stories"][0]["tier_label"] == "HOT" and set(w["stories"][0]["sources"]) == {"Yahoo", "Google News"}
    assert w["sources"]["Finnhub"] == "no FINNHUB_API_KEY is set" and w["sources"]["Google News"] == "ok"
    assert isinstance(w["stories"][0]["published"], str)                         # plain text, so a saved snapshot reads back the same


def test_a_failing_source_never_blocks_the_others():
    yahoo = [{"title": "Analyst downgrades Acme", "publisher": "Yahoo", "url": None, "published": T0 - timedelta(hours=1)}]
    w = newsfeed.build("ACME", "Acme", False, yahoo, None, False, T0)             # Google fails (network disabled)
    assert len(w["stories"]) == 1 and w["sources"]["Google News"] == "could not be reached"


def test_the_company_name_search_drops_corporate_suffixes():
    assert newsfeed._clean_name("Rolls-Royce Holdings plc") == "Rolls-Royce"
    assert newsfeed._clean_name("AppLovin Corporation Class A") == "AppLovin"


def test_extra_sources_never_feed_the_scores():
    events, sigs = catalysts.analyze({"news": [], "wire": [item("Acme files for bankruptcy", "Google News")]}, True, 1, T0.date())
    assert events["news"] == [] and not sigs


# ---- alerts

def wire(title, hours_ago=1.0, held=True, sources=("Google News",), tier=None):
    s = {"title": title, "url": "https://x/1", "published": (T0 - timedelta(hours=hours_ago)).isoformat(), "sources": list(sources),
         "tier": tier or newsfeed.tier_of(title), "age_h": hours_ago, "held": held}
    s["tier_label"] = newsfeed.TIERS[s["tier"]]
    s["key"] = newsfeed.story_key("A", title)
    s["rank"] = s["tier"] * 100
    return {"stories": [s], "sources": {}}


def test_first_run_is_a_silent_baseline_then_only_new_hot_stories_are_sent():
    w1 = {"A": wire("Acme files for bankruptcy")}
    seen, ready, c = newsfeed.step(None, w1, T0)
    assert ready == [] and c["baseline"] == 1 and len(seen) == 1
    seen, ready, _ = newsfeed.step(seen, w1, T0)
    assert ready == []                                                          # already known
    w2 = {"A": wire("Acme CEO abruptly resigns")}
    seen, ready, _ = newsfeed.step(seen, w2, T0)
    assert [r["ticker"] for r in ready] == ["A"]
    newsfeed.delivered(seen, ready[0], T0)
    _, ready, _ = newsfeed.step(seen, w2, T0)
    assert ready == []


def test_a_failed_send_is_offered_again_and_routine_or_old_stories_never_alert():
    seen, _, _ = newsfeed.step(None, {}, T0)
    w = {"A": wire("Acme CEO abruptly resigns")}
    _, ready, _ = newsfeed.step(seen, w, T0)
    _, again, _ = newsfeed.step(seen, w, T0)                                     # not delivered: still ready
    assert len(ready) == len(again) == 1
    seen2, none, _ = newsfeed.step(seen, {"A": wire("Acme opens a new office"), "B": wire("Acme files for bankruptcy", hours_ago=30)}, T0)
    assert none == [] and len(seen2) == 2


def test_a_flood_is_spread_over_runs():
    seen, _, _ = newsfeed.step(None, {}, T0)
    many = {f"T{i}": wire(f"Acme {i} CEO abruptly resigns") for i in range(9)}
    _, ready, c = newsfeed.step(seen, many, T0)
    assert len(ready) == newsfeed.MAX_PER_RUN and c["deferred"] == 3


def test_old_memory_is_pruned():
    old = {"k": (T0 - timedelta(days=9)).timestamp(), "new": T0.timestamp()}
    seen, _, _ = newsfeed.step(old, {}, T0)
    assert "k" not in seen and "new" in seen


def test_the_message_names_the_story_sources_and_link(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://app.example/")
    s = {**wire("Acme CEO abruptly resigns", 0.5, sources=("Google News", "SEC"))["stories"][0], "ticker": "ACME"}
    text = newsfeed.message(s)
    assert text.startswith("🚨 CRITICAL NEWS · ACME (held)") and "Google News, SEC (2 sources)" in text and "30 min ago" in text
    assert "https://x/1" in text and "https://app.example/?view=target&t=ACME" in text


def test_the_news_memory_rides_in_the_alert_file_without_touching_calls():
    entries = {"A": {"call": "HOLD"}, "__price_status__": {"A": {}}, newsfeed.NEWS_KEY: {"k": 1.0}}
    rest, seen = newsfeed.split(entries)
    assert seen == {"k": 1.0} and newsfeed.NEWS_KEY not in rest and "A" in rest
    assert newsfeed.split({"A": 1})[1] is None                                  # no news memory yet: first run
    assert newsfeed.join(rest, {"z": 2.0})[newsfeed.NEWS_KEY] == {"z": 2.0}


# ---- the scan, end to end with a fake Telegram

def hot_eval(ticker, title, hours_ago=1.0):
    e = ev(ticker, "HOLD")
    e.events = {"wire": wire(title, hours_ago)}
    for s in e.events["wire"]["stories"]:
        s["key"] = newsfeed.story_key(ticker, title)
    return e


def test_the_scan_baselines_then_sends_one_critical_story_once(monkeypatch, tmp_path):
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    r1 = fleet.run(hot_eval("HELD", "Acme files for bankruptcy"))
    assert fake.requests == [] and "first run" in r1.markdown()
    fleet.run(hot_eval("HELD", "Acme files for bankruptcy"))
    assert fake.requests == []                                                  # same story: nothing
    fleet.run(hot_eval("HELD", "Acme files for bankruptcy"), hot_eval("WATCH", "Acme CEO abruptly resigns"))
    assert len(fake.requests) == 1 and "CRITICAL NEWS · WATCH" in fake.requests[0]["text"]
    fleet.run(hot_eval("HELD", "Acme files for bankruptcy"), hot_eval("WATCH", "Acme CEO abruptly resigns"))
    assert len(fake.requests) == 1                                              # sent once only


def test_a_failed_critical_send_retries_next_run(monkeypatch, tmp_path):
    from test_ci_scan import http_error
    configure(monkeypatch)
    fake = FakeTelegram()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    fleet = Fleet(monkeypatch, tmp_path)
    fleet.run(hot_eval("HELD", "Quiet news"))
    fake.responses = [http_error(500, {"ok": False})]
    report = fleet.run(hot_eval("HELD", "Quiet news"), hot_eval("WATCH", "Acme CEO abruptly resigns"))
    assert report.errors and len(fake.requests) == 1
    fleet.run(hot_eval("HELD", "Quiet news"), hot_eval("WATCH", "Acme CEO abruptly resigns"))
    assert len(fake.requests) == 2 and "CEO abruptly" in fake.requests[1]["text"]


def test_the_cached_memory_and_public_log_reveal_no_headlines(monkeypatch, tmp_path):
    configure(monkeypatch)
    monkeypatch.setattr(notify.urllib.request, "urlopen", FakeTelegram())
    fleet = Fleet(monkeypatch, tmp_path)
    fleet.run(hot_eval("HELD", "Quiet news"))
    report = fleet.run(hot_eval("HELD", "Quiet news"), hot_eval("WATCH", "Acme CEO abruptly resigns"))
    assert "CEO" not in report.markdown() and b"CEO" not in fleet.state.read_bytes() and b"WATCH" not in fleet.state.read_bytes()


# ---- the screen

def snap_with(wire_dict, ticker="ACME"):
    return {"ticker": ticker, "payload": {"events": {"wire": wire_dict}}}


def test_the_strip_lists_critical_stories_with_sources_and_says_when_a_source_was_down():
    w = wire("Acme CEO abruptly resigns", 0.5, sources=("Google News", "SEC"))
    w["sources"] = {"Yahoo": "ok", "Finnhub": "no FINNHUB_API_KEY is set"}
    html = ui.news_strip([snap_with(w)])
    assert "Critical news · 1" in html and "Google News · SEC" in html and "Not read: Finnhub" in html and "?view=target&t=ACME" in html


def test_a_quiet_list_says_so_and_a_list_without_news_data_shows_nothing():
    quiet = wire("Acme opens a new office")
    assert "No critical news on your list" in ui.news_strip([snap_with(quiet)])
    assert ui.news_strip([{"ticker": "A", "payload": {"events": {}}}]) == ""


def test_details_ranks_every_story_and_escapes_text():
    w = {"stories": [wire("Acme CEO <b>abruptly</b> resigns")["stories"][0], wire("Analyst upgrades Acme to buy")["stories"][0]], "sources": {}}
    html = ui.wire_note(snap_with(w))
    assert "HOT" in html and "IMPORTANT" in html and "<b>abruptly</b>" not in html and "&lt;b&gt;" in html


def test_the_engine_keeps_the_wire_apart_from_the_scored_news():
    from stockwatch.config import Holding
    from stockwatch.data import DemoProvider
    from stockwatch.engine import evaluate
    from test_stockwatch import make_portfolio
    e = evaluate(Holding("AAA", 1, 10.0), make_portfolio(), DemoProvider())
    assert isinstance(e.events.get("wire"), dict) and "stories" in e.events["wire"]
    assert all("sources" not in n for n in e.events["news"])                      # the scored list is still Yahoo's alone
