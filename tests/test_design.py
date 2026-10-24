"""The shared look (stockwatch/design.py): theme blocks, plain-English wording and the small HTML pieces."""
import re

from stockwatch import design
from stockwatch.store import Store


def test_each_theme_is_one_style_block_and_an_unknown_one_falls_back_to_auto():
    dark, light, auto = (design.theme_css(m) for m in ("dark", "light", "auto"))
    assert "prefers-color-scheme" not in dark and "prefers-color-scheme" not in light
    assert "prefers-color-scheme: light" in auto
    assert "--dz-bg:#f4f5f8" in light and "--dz-bg:#f4f5f8" in auto and "--dz-bg:#f4f5f8" not in dark
    assert "--bg:#f4f5f8" in light                         # the app's older styles read these, so the whole app re-themes
    assert design.theme_css("nonsense") == auto
    assert all(x.startswith("<style>") and x.endswith("</style>") for x in (dark, light, auto))


def test_zone_words_are_plain_english_and_never_show_the_grade():
    assert design.zone_words("support", "HIGH")[0] == "Likely to hold: a good place to buy"
    assert design.zone_words("resistance", "MEDIUM")[0] == "May stop a rise"
    assert design.zone_words("support", "LOW")[0].startswith("Weak")
    html = design.zone_row("resistance", 148.95, 149.14, "HIGH", ["2 touches", "round number"])
    assert "Likely to stop a rise" in html and "HIGH" not in html and "148.95 to 149.14" in html
    assert design.zone_row("support", 142.6, None, "MEDIUM").count("142.60") == 1


def test_fundamentals_rating_bands_and_unknown_is_never_a_zero():
    assert design.fundamentals_rating(32) == ("Weak", 2)
    assert design.fundamentals_rating(24.9) == ("Poor", 1) and design.fundamentals_rating(25) == ("Weak", 2)
    assert design.fundamentals_rating(64.9) == ("Fair", 3) and design.fundamentals_rating(65) == ("Good", 4)
    assert design.fundamentals_rating(80) == ("Strong", 5) and design.fundamentals_rating(100) == ("Strong", 5)
    assert design.fundamentals_rating(None) is None and design.fundamentals_rating(float("nan")) is None
    assert "Fundamentals n/a" in design.rating("Fundamentals", None)
    assert "Fundamentals Weak" in design.rating("Fundamentals", design.fundamentals_rating(32))


def test_technical_rating_follows_the_gauge_step():
    assert [design.technical_rating(i)[0] for i in range(5)] == ["Bad", "Weak", "Neutral", "Good", "Strong"]
    assert design.technical_rating(None) is None


def test_pips_fill_the_first_n_and_unknown_is_empty():
    assert design.pips(2).count('class="on"') == 2 and design.pips(None).count('class="on"') == 0
    assert design.pips(9).count('class="on"') == 5


def test_gauge_line_has_one_tag_two_end_words_and_no_bolt_when_unclear():
    g = design.gauge_line(0)
    assert g.count("BAD") == 1 and ">Weak<" in g and ">Strong<" in g and "dz-bolt" in g and "left:10%" in g
    u = design.gauge_line(None, "No read: only 2 checks")
    assert "dz-bolt" not in u and "No read: only 2 checks" in u


def test_icon_lines_escape_text_and_name_their_meaning():
    h = design.icon_line("bad", "Risk: <b>61%</b> below its 52-week high.")
    assert "&lt;b&gt;" in h and "▼" in h and "dz-k-bad" in h and "Bad for the stock" in h
    assert "▲" in design.icon_line("good", "x") and "!" in design.icon_line("careful", "x")
    assert "dz-k-info" in design.icon_line("something else", "x")
    assert design.icon_key().count("dz-ic") == 4


def test_call_tags_pills_bells_and_lines():
    assert "dz-act" in design.call_tag("SELL SOME") and "dz-buy" in design.call_tag("BUY MORE")
    assert "dz-watch" in design.call_tag("WATCH · SELL BELOW 0.33") and "dz-calm" in design.call_tag("HOLD")
    assert "dz-act" in design.call_tag("AVOID")
    assert "+3.2%" in design.change_pill(0.032) and "dz-dn" in design.change_pill(-0.025)
    assert "n/a" in design.change_pill(None) and "n/a" in design.change_pill(float("nan"))
    assert "dz-on" in design.bell(True) and "dz-off" in design.bell(False)
    n = design.news_line("hot", "Probe <opened>", "1h", "SEC")
    assert "dz-hot" in n and "HOT" in n and "&lt;opened&gt;" in n and "1h · SEC" in n
    assert "dz-rou" in design.news_line("ROUTINE", "x")
    assert "dz-r-buy" in design.result_line("BEAT", "EPS beat by 12%") and "dz-r-act" in design.result_line("miss", "x")
    assert "NEXT" in design.next_line("Nov 11 · EPS -0.31", "18d")


def test_every_css_variable_a_piece_uses_is_defined_in_both_themes():
    used = set(re.findall(r"var\(--dz-([a-z-]+)", design.COMPONENTS))
    for mode in ("dark", "light"):
        css = design.theme_css(mode)
        defined = set(re.findall(r"--dz-([a-z-]+):", css))
        assert used - {"c", "on-c"} <= defined, (mode, used - defined)


def test_the_theme_choice_is_kept_in_the_store(tmp_path):
    s = Store(tmp_path / "t.db")
    assert s.get_setting("theme") is None and s.get_setting("theme", "auto") == "auto"
    s.set_setting("theme", "light")
    s.set_setting("theme", "dark")
    assert Store(tmp_path / "t.db").get_setting("theme") == "dark"


def test_two_threads_can_share_one_store_without_losing_rows(tmp_path):
    import threading
    from stockwatch.store import Store
    s = Store(tmp_path / "t.db")
    bad = []

    def write():
        for i in range(1500):
            s.set_setting("k", str(i))

    def read():
        for _ in range(1500):
            try:
                s.watermark()
            except TypeError as e:
                bad.append(e)

    ts = [threading.Thread(target=write), threading.Thread(target=read), threading.Thread(target=read)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not bad


ST = {"consensus": {"label": "Buy", "analysts": 33, "buy": 29, "hold": 3, "sell": 1, "score": 1.7, "change_3m": None},
      "targets": {"low": 86.0, "median": 127.5, "high": 144.0},
      "growth": {"0q": {"eps": 0.53, "revenue": 0.12, "analysts": 23}, "0y": {"eps": 0.17, "revenue": 0.08, "analysts": 29},
                 "+1y": {"eps": 0.08, "revenue": 0.04, "analysts": 25}},
      "revisions": {"eps_30d": 0.002, "eps_90d": 0.017, "up30": 2, "down30": 4},
      "scenarios": [{"months": 3, "bear": 96.06, "base": 115.27, "bull": 138.34, "p_up": 0.55},
                    {"months": 12, "bear": 86.07, "base": 123.95, "bull": 178.5, "p_up": 0.6}],
      "sigma": 0.36, "sigma_source": "options", "implied_move_1m": 0.08}


def test_the_outlook_is_drawn_and_keeps_every_number_behind_more_numbers():
    from stockwatch import ui
    html = ui.outlook(ST, 112.52)
    assert "ol-lane" in html and "-24%" in html and "+59%" in html and "60%" in html and "ol-eps" in html
    assert "More numbers" in html and "$96.06" in html and "Next quarter" not in html and "This quarter" in html
    assert "options market" in html


def test_the_outlook_skips_what_it_cannot_draw_and_never_guesses():
    from stockwatch import ui
    html = ui.outlook({"consensus": ST["consensus"]}, 100.0)
    assert "class=\"ol-lane\"" not in html and "class=\"ol-eps\"" not in html and "More numbers" not in html and "Buy" in html


