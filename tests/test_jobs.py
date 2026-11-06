from stockwatch import jobs


class FakeProc:
    def __init__(self, running=True): self.running = running
    def poll(self): return None if self.running else 0


def setup(tmp_path, name="stab_study"):
    (tmp_path / "data").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "stab_study.py").write_text("print('hi')")
    (tmp_path / "data" / "run_job.txt").write_text(name)
    jobs._running["p"] = None


def test_nothing_runs_without_the_trigger(tmp_path):
    (tmp_path / "data").mkdir()
    jobs._running["p"] = None
    assert jobs.tick(tmp_path, spawn=lambda *a, **k: FakeProc()) is None


def test_trigger_starts_the_named_job_once_and_is_consumed(tmp_path):
    setup(tmp_path)
    seen = []
    assert jobs.tick(tmp_path, spawn=lambda cmd, **k: seen.append(cmd) or FakeProc()) == "stab_study"
    assert seen[0][-1].endswith("stab_study.py") and not (tmp_path / "data" / "run_job.txt").exists()
    assert (tmp_path / "data" / "run_job.txt.done").read_text().startswith("started")
    assert (tmp_path / "data" / "stab_study.txt").exists()
    (tmp_path / "data" / "run_job.txt").write_text("stab_study")          # a second request while it runs waits
    assert jobs.tick(tmp_path, spawn=lambda *a, **k: FakeProc()) is None and (tmp_path / "data" / "run_job.txt").exists()


def test_unknown_job_is_refused_and_reported(tmp_path):
    setup(tmp_path, name="rm -rf")
    assert jobs.tick(tmp_path, spawn=lambda *a, **k: FakeProc()) is None
    assert "unknown job" in (tmp_path / "data" / "run_job.txt.done").read_text() and not (tmp_path / "data" / "run_job.txt").exists()
