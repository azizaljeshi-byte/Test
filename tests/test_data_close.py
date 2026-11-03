"""A daily history fetched before the close is refreshed once after it, so the last bar is the final close."""
def test_history_fetched_before_the_close_is_fetched_again_after_it():
    from datetime import datetime
    from stockwatch.data import NY, partial_after_close
    mid, late = datetime(2026, 10, 27, 15, 58, tzinfo=NY), datetime(2026, 10, 27, 16, 10, tzinfo=NY)
    assert partial_after_close(mid, late) is True                                        # last bar was a mid-session price
    assert partial_after_close(datetime(2026, 10, 27, 16, 6, tzinfo=NY), late) is False  # already fetched after the close
    assert partial_after_close(mid, datetime(2026, 10, 27, 15, 59, tzinfo=NY)) is False  # still in the session
    assert partial_after_close(datetime(2026, 10, 23, 15, 0, tzinfo=NY), datetime(2026, 10, 24, 17, 0, tzinfo=NY)) is False  # weekend
