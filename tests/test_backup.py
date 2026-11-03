import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from stockwatch import backup
from stockwatch.data import NY


def tree(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for rel, text in {"dashboard.py": "x", "stockwatch/a.py": "y", "docs/N.md": "z", "my_settings.txt.bat": 'set "KEY=secret"',
                      "my_settings_TEMPLATE.bat": "t", "data/stockwatch.db": "db", ".venv/lib/x.py": "v", "previous/old.py": "o",
                      "stockwatch/__pycache__/a.cpython-314.pyc": "c", "update_ready.txt": "u"}.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return root


def test_the_zip_holds_the_code_and_never_the_settings_data_or_environment(tmp_path):
    root, out = tree(tmp_path), tmp_path / "t.zip"
    assert backup.make_zip(root, out) == 4
    names = set(zipfile.ZipFile(out).namelist())
    assert names == {"dashboard.py", "stockwatch/a.py", "docs/N.md", "my_settings_TEMPLATE.bat"}
    assert not (tmp_path / "t.zip.part").exists()


def test_it_runs_once_a_day_after_the_session_closes_and_keeps_the_last_fourteen(tmp_path, monkeypatch):
    root, folder = tree(tmp_path), tmp_path / "drive"
    folder.mkdir()
    for d in range(1, 17):
        (folder / f"{backup.PREFIX}2026-09-{d:02d}.zip").write_text("old")
    (folder / "notes.txt").write_text("mine")
    monkeypatch.setitem(backup._last_try, "at", 0.0)
    assert backup.run(None, datetime(2026, 10, 26, 19, 0, tzinfo=NY), root, folder) == ""          # session still open
    msg = backup.run(None, datetime(2026, 10, 26, 20, 10, tzinfo=NY), root, folder)
    assert "code 4 files" in msg and "private data" in msg and (folder / f"{backup.PREFIX}2026-10-26.zip").exists()
    assert len(list(folder.glob(f"{backup.PREFIX}*.zip"))) == backup.KEEP and (folder / "notes.txt").exists()
    monkeypatch.setitem(backup._last_try, "at", 0.0)
    assert backup.run(None, datetime(2026, 10, 26, 21, 0, tzinfo=NY), root, folder) == ""          # already done today


def test_the_private_zip_holds_a_consistent_database_copy_the_settings_and_never_the_template(tmp_path):
    root = tree(tmp_path)
    (root / "data" / "stockwatch.db").unlink()
    con = sqlite3.connect(root / "data" / "stockwatch.db")
    con.execute("create table t (a)")
    con.execute("insert into t values (7)")
    con.commit()
    con.close()
    out = tmp_path / "d.zip"
    assert backup.make_data_zip(root, out) == 2
    z = zipfile.ZipFile(out)
    assert set(z.namelist()) == {"data/stockwatch.db", "my_settings.txt.bat"}
    z.extract("data/stockwatch.db", tmp_path / "x")
    assert sqlite3.connect(tmp_path / "x" / "data" / "stockwatch.db").execute("select a from t").fetchone() == (7,)


def test_a_missing_folder_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setitem(backup._last_try, "at", 0.0)
    msg = backup.run(None, datetime(2026, 10, 26, 20, 10, tzinfo=NY), tree(tmp_path), tmp_path / "nope")
    assert "not found" in msg
