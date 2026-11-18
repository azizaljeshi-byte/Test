"""Break watch (stockwatch/break_watch.py): breaks of the 20-day level, the fixed qualified/confirmed rules, 5-session outcomes, the record."""
import json
from datetime import datetime

import gspread
import pandas as pd

from stockwatch import break_watch as bw
from stockwatch.data import NY


class FakeStore:
    def __init__(self):
        self.d = {}

    def get_setting(self, k, default=None):
        return self.d.get(k, default)

    def set_setting(self, k, v):
        self.d[k] = v


AFTER = datetime(2026, 11, 13, 17, 0, tzinfo=NY)


def frame(moves, side="up", n=70, end="2026-11-10"):
    """70 quiet sessions around 100 (closes 99-101, daily range 2, volume 1000), then `moves`: (close, high, low, volume) per session."""
    idx = pd.bdate_range(end=end, periods=n + len(moves))
    base = [100 + (1 if i % 2 else -1) * 0.8 for i in range(n)]
    rows = [(c, c + 1, c - 1, 1000) for c in base] + list(moves)
    df = pd.DataFrame(rows, columns=["Close", "High", "Low", "Volume"], index=idx)
    df["Open"] = df["Close"].shift(1).fillna(df["Close"])
    return df


UP = (104, 105, 103, 1500)                                  # a clear close above the 20-day high (100.8) on 1.5x volume


def ev_of(moves, **k):
    out = bw.events({"AAA": frame(moves, **k)}, AFTER)
    return out[0] if out else None


def test_a_clear_break_on_volume_is_qualified_and_a_weak_one_is_not():
    e = ev_of([UP])
    assert e["side"] == "up" and e["qualified"] is True and e["size"] > 0.5 and e["vol_x"] >= 1.2 and e["status"].startswith("Break day")
    assert ev_of([(101.4, 102.4, 100.4, 1500)])["qualified"] is False                   # barely through the line
    assert ev_of([(104, 105, 103, 900)])["qualified"] is False                           # no volume
    assert ev_of([(100.5, 101, 99, 1500)]) is None                                       # no break at all


def test_confirmed_continued_reversed_and_waiting():
    ok = ev_of([UP, (105, 106, 103, 1200), (105.5, 106, 104, 1000), (106, 107, 105, 1000), (106.5, 107, 105, 1000), (107, 108, 106, 1000)])
    assert ok["confirmed"] is True and ok["outcome"] == "Continued" and ok["seen"] == 5 and ok["status"].startswith("Continued")
    holding = ev_of([UP, (105, 106, 103, 1200), (105.5, 106, 104, 1000)])
    assert holding["confirmed"] is True and holding["outcome"] == "" and holding["status"] == "Holding: day 2 of 5"
    weak = ev_of([UP, (103.5, 106, 103, 800)])                                            # holds but weak volume: qualified, not confirmed
    assert weak["qualified"] is True and weak["confirmed"] is False
    back = ev_of([UP, (105, 106, 103, 1200), (100, 101, 99, 1200)])
    assert back["outcome"] == "Reversed" and "day 2" in back["status"] and back["confirmed"] is True
    ended = ev_of([UP, (103, 104, 102.5, 1200), (103, 104, 102, 1000), (103, 104, 102, 1000), (103, 104, 102, 1000), (103.5, 104, 102, 1000)])
    assert ended["outcome"] == "Neither"                                                  # stayed above the line, ended under the break close
    assert ev_of([UP])["confirmed"] is None


def test_down_break_needs_more_volume_and_closes_in_the_lower_half_to_confirm():
    down = (96, 97, 95, 1250)                                                             # 1.25x: enough for up, not for down
    assert ev_of([down])["side"] == "down" and ev_of([down])["qualified"] is False
    e = ev_of([(96, 97, 95, 1400), (95, 96.5, 94.5, 1100)])
    assert e["qualified"] is True and e["confirmed"] is True and e["d1_held"] is True and e["d1_strong"] is True
    e2 = ev_of([(96, 97, 95, 1400), (97, 98, 94, 1100)])                                # closed near the day's high: not a strong down close
    assert e2["d1_strong"] is False and e2["confirmed"] is False


def test_todays_unfinished_bar_is_not_used():
    df = frame([UP])
    early = datetime(2026, 11, 10, 11, 0, tzinfo=NY)                                      # the last bar is dated that same morning
    assert bw.events({"AAA": df}, early) == []
    assert len(bw.events({"AAA": df}, datetime(2026, 11, 10, 16, 30, tzinfo=NY))) == 1


def test_unusable_history_is_skipped_not_scored():
    short = frame([UP]).tail(30)
    zero = frame([UP]); zero["Volume"] = 0
    assert bw.events({"S": short, "Z": zero, "X": pd.DataFrame()}, AFTER) == []


def test_merge_keeps_resolved_breaks_after_they_leave_the_window():
    done = ev_of([UP, (105, 106, 103, 1200), (100, 101, 99, 1200)])
    live = ev_of([UP], end="2026-11-12") or ev_of([UP])
    state = bw.merge(None, [done, live], AFTER)
    assert len(state["resolved"]) == 1 and len(state["active"]) == 1
    again = bw.merge(state, [], AFTER)                                                    # a later scan no longer sees them
    assert len(again["resolved"]) == 1 and again["active"] == [] and bw.all_events(again)[0]["t"] == "AAA"


def test_scorecard_counts_and_says_when_there_is_too_little_to_judge():
    good = ev_of([UP, (105, 106, 103, 1200), (105.5, 106, 104, 1000), (106, 107, 105, 1000), (106.5, 107, 105, 1000), (107, 108, 106, 1000)])
    bad = ev_of([UP, (105, 106, 103, 1200), (100, 101, 99, 1200)])
    rows = bw.scorecard([good, bad])
    up_all, up_c = rows[0], rows[2]
    assert up_all[0].startswith("Up") and up_all[3] == 2 and up_all[4] == 0.5 and up_all[5] == 0.5
    assert up_c[2] == 2 and up_all[-1].startswith("too few")
    assert up_all[7] == 0.40 and up_all[8] == 0.54                                        # the back-test beside the live numbers
    assert len(rows) == 6 and all(len(r) == len(bw.SCORE_COLS) for r in rows)
    assert all(len(bw.row_of(e, *bw.call_of(e))) == len(bw.COLS) for e in (ev_of([UP]), ev_of([UP, (105, 106, 103, 1200)])))


class FakeTab:
    id = 3
    frozen_row_count = 0

    def __init__(self):
        self.values, self.cleared = None, 0

    def clear(self):
        self.cleared += 1

    def update(self, range_name=None, values=None, value_input_option=None):
        self.values = values


class FakeSheet:
    def __init__(self, fail=False):
        self.tabs, self.fail, self.requests = {}, fail, []

    def worksheet(self, name):
        if self.fail:
            raise RuntimeError("boom https://docs.google.com/spreadsheets/d/SECRET")
        if name not in self.tabs:
            raise gspread.WorksheetNotFound(name)
        return self.tabs[name]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeTab()
        return self.tabs[title]

    def batch_update(self, body):
        self.requests.append(body)


def test_sheet_gets_both_tabs_and_errors_never_leak_the_link(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_SMALLCAP_SHEET_URL", "x")
    state = bw.merge(None, [ev_of([UP, (105, 106, 103, 1200)])], AFTER)
    sheet = FakeSheet()
    assert bw.to_google(state, connect=lambda env: sheet) == ""
    assert sheet.tabs[bw.TAB].values[0] == bw.COLS and sheet.tabs[bw.TAB].values[1][0] == "AAA" and sheet.tabs[bw.TAB].values[1][2].startswith("Likely to keep")
    assert sheet.tabs[bw.SCORE_TAB].values[0] == bw.SCORE_COLS and len(sheet.tabs[bw.SCORE_TAB].values) == 7
    assert len(sheet.requests) == 2 and sheet.tabs[bw.TAB].cleared == 1                   # styled once per tab, rewritten, never appended
    err = bw.to_google(state, connect=lambda env: FakeSheet(fail=True))
    assert "SECRET" not in err and "docs.google" not in err and "next whole-S&P scan" in err
    for v in ("STOCKWATCH_BREAKWATCH_SHEET_URL", "STOCKWATCH_BUYSIGNALS_SHEET_URL", "STOCKWATCH_BUYSETUP_SHEET_URL", "STOCKWATCH_SMALLCAP_SHEET_URL"):
        monkeypatch.delenv(v, raising=False)
    assert "not set up" in bw.to_google(state)


def test_record_saves_first_and_survives_a_failing_sheet(monkeypatch):
    monkeypatch.delenv("STOCKWATCH_SMALLCAP_SHEET_URL", raising=False)
    st = FakeStore()
    assert bw.record(st, [ev_of([UP])], AFTER, background=False) == ""
    saved = json.loads(st.d[bw.KEY])
    assert len(saved["active"]) == 1 and "not set up" in st.d[bw.ERROR_KEY]
    assert bw.record(st, [], AFTER, background=False) == "" and json.loads(st.d[bw.KEY])["active"] == []


def test_calls_say_what_is_likely_to_move_with_the_back_test_chance():
    wait = bw.call_of(ev_of([UP]))
    assert wait[0].startswith("Possible") and wait[1] == 50 and "day 1 decides" in wait[2]
    weak = bw.call_of(ev_of([(101.4, 102.4, 100.4, 1500)]))
    assert weak[0] == "Likely to fall back" and weak[1] == 37
    strong = bw.call_of(ev_of([UP, (105, 106, 103, 1200)]))
    assert strong[0] == "Likely to keep rising" and strong[1] == 66 and "strong half" in strong[2]
    later = bw.call_of(ev_of([UP, (105, 106, 103, 1200), (105.5, 106, 104, 1000), (106, 107, 105, 1000)]))
    assert later[0] == "Likely to keep rising" and later[1] == 79                       # it has already held 3 sessions
    wk = bw.call_of(ev_of([UP, (103.5, 106, 103, 800)]))
    assert wk[0] == "Could go either way" and wk[1] == 48
    d = bw.call_of(ev_of([(96, 97, 95, 1400), (95, 96.5, 94.5, 1100)]))
    assert d[0] == "Likely to keep falling" and d[1] == 57
    dw = bw.call_of(ev_of([(96, 97, 95, 1400), (97, 98, 94, 1100)]))
    assert dw[0] == "Likely to bounce" and dw[1] == 40


def test_the_live_list_has_only_open_breaks_best_first_and_finished_ones_drop_off():
    strong = ev_of([UP, (105, 106, 103, 1200)])
    weak = ev_of([(101.4, 102.4, 100.4, 1500)])
    done = ev_of([UP, (105, 106, 103, 1200), (100, 101, 99, 1200)])                        # reversed on day 2: finished
    state = bw.merge(None, [weak, strong, done], AFTER)
    live = bw.live_events(state)
    assert len(live) == 2 and live[0][1].startswith("Likely to keep") and live[1][1] == "Likely to fall back" and live[1][2] == 37
    assert len(bw.scorecard(bw.all_events(state))) == 6 and bw.scorecard(bw.all_events(state))[0][3] == 1      # the finished one is still counted
