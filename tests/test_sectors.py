from stockwatch import sectors


def snap(sector, chg):
    return {"payload": {"profile": {"sector": sector}, "quote": {"live_change": chg}}}


def test_healthy_weak_and_no_read():
    snaps = {f"H{i}": snap("Health", c) for i, c in enumerate([0.01, 0.02, -0.005, 0.0])}
    snaps.update({f"T{i}": snap("Tech", c) for i, c in enumerate([-0.03, -0.05, 0.01])})
    snaps.update({"X1": snap("Energy", 0.02), "X2": snap("Energy", 0.01)})
    snaps["N"] = {"payload": {"quote": {"live_change": 0.01}}}
    r = sectors.read(snaps)
    assert r["Health"]["healthy"] is True and r["Tech"]["healthy"] is False
    assert r["Energy"]["healthy"] is None                       # two names: unknown, not unhealthy
    assert sectors.note(snaps["H0"], r).startswith("healthy: Health")
    assert sectors.note(snaps["T0"], r).startswith("WOULD BLOCK: Tech")
    assert sectors.note(snaps["X1"], r).startswith("no read")
    assert sectors.note(snaps["N"], r) == "no read: sector unknown"


def test_missing_change_is_not_counted_as_zero():
    snaps = {f"A{i}": snap("Tech", None) for i in range(5)}
    assert sectors.read(snaps) == {}


def test_stamp_tags_only_the_new_entry_and_changes_nothing_else():
    snaps = {f"H{i}": snap("Health", 0.01) for i in range(3)}
    trades = [{"id": 1, "ticker": "H0", "status": "OPEN"}, {"id": 2, "ticker": "H1", "status": "OPEN"}]
    sectors.stamp(trades, [{"ticker": "H1", "action": "ENTER"}, {"ticker": "H0", "action": "EXIT"}], snaps)
    assert "sector_gate" in trades[1] and "sector_gate" not in trades[0]
    sectors.stamp(trades, [], snaps)
