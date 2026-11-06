"""Keep the study data on Drive: the 5-year daily bars and the earnings dates the studies downloaded, as plain files that open anywhere.
Reads data/study_cache_5y.pkl and data/earnings_dates_cache.pkl (written by the studies); writes into the Drive backup folder under
Study results/data: daily_bars_5y.csv.gz (ticker, date, Open, High, Low, Close, Volume) and earnings_dates.csv (ticker, date)."""
from __future__ import annotations

import pickle
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def save(root: Path = ROOT, folder: Path | None = None) -> list:
    import pandas as pd
    if folder is None:
        from stockwatch import backup
        folder = backup.backup_dir() / "Study results" / "data"
    folder.mkdir(parents=True, exist_ok=True)
    done = []
    bars = root / "data" / "study_cache_5y.pkl"
    if bars.exists():
        frames = pickle.loads(bars.read_bytes())[0]
        parts = []
        for t, df in frames.items():
            x = df.copy()
            x.insert(0, "ticker", t)
            x.index.name = "date"
            parts.append(x.reset_index())
        out = folder / "daily_bars_5y.csv.gz"
        pd.concat(parts, ignore_index=True).to_csv(out, index=False, compression="gzip")
        done.append(out.name)
        shutil.copy2(bars, folder / bars.name)
    ed = root / "data" / "earnings_dates_cache.pkl"
    if ed.exists():
        dates = pickle.loads(ed.read_bytes())
        out = folder / "earnings_dates.csv"
        pd.DataFrame([(t, str(d)) for t, v in dates.items() for d in v], columns=["ticker", "date"]).to_csv(out, index=False)
        done.append(out.name)
        shutil.copy2(ed, folder / ed.name)
    return done


def main() -> None:
    try:
        files = save()
        print("Saved on Drive (Study results/data): " + (", ".join(files) if files else "nothing to save yet"))
    except Exception as e:
        print(f"Could not save the study data: {e}")


if __name__ == "__main__":
    main()
