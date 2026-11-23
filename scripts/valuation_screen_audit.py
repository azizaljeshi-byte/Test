"""Aggregate valuation sensitivity on an explicit private database; never lists stocks.

Run locally: python scripts/valuation_screen_audit.py --database PATH
The database is opened read-only; no network, account writes or private rows printed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stockwatch.valuation_screen import audit


def report(path: Path) -> dict:
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT s.price, s.fundamental_score, s.payload FROM snapshots s '
                            'JOIN (SELECT ticker, MAX(id) AS mid FROM snapshots GROUP BY ticker) m ON s.id=m.mid')
        snaps = [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows]
    return audit(snaps)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.database), indent=2, allow_nan=False))
