"""Private reference market data for the CIS fixtures (Issue #31, data-license disposition).

The 23 October 2026 reference round used Yahoo-derived daily prices. Yahoo's terms are widely described as
personal-use only and no redistribution right was found, so those files are NOT in this public repository.
What stays public: the method documents, the packet schema, the analyst level packets, the acceptance ledger
and the handoff manifest, which pins every private file's SHA-256.

To use the private files, put the handoff files in a folder and point STOCKWATCH_CIS_DATA at it (default
~/.stockwatch/cis-data). Each file is used only if its hash matches the manifest; a missing or altered file is
reported as unavailable, never silently replaced. Without them, the CI tests that need real prices skip and
the Research view shows the levels and states without charts or history.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from . import features, level_packet

DATA_ENV = "STOCKWATCH_CIS_DATA"
DEFAULT_DIR = Path.home() / ".stockwatch" / "cis-data"
MANIFEST = level_packet.FIXTURES / "CIS-handoff-manifest.json"
# vendor-derived files: prices, evidence built from prices, and the scanner audit's captured app data
PRIVATE = ("ISRG-adjusted-daily.csv", "FICO-20261023-adjusted.csv", "CRDO-CRDO-20261023-adjusted.csv",
           "PODD-PODD-20261023-adjusted.csv", "SPY-20261023-adjusted.csv", "SPY-adjusted-daily.csv",
           "XLK-20261023-adjusted.csv", "CRDO-SPY-20261023-adjusted.csv", "CRDO-XLK-20261023-adjusted.csv",
           "PODD-SPY-20261023-adjusted.csv", "PODD-XLV-20261023-adjusted.csv", "ISRG-independent-evidence.json",
           "FICO-independent-evidence.json", "CRDO-independent-evidence.json", "PODD-independent-evidence.json",
           "CRDO-upside-evidence.json", "ISRG-scanner-audit.json")


class Missing(FileNotFoundError):
    """A private reference file isn't installed, or doesn't match the manifest."""


def directory() -> Path:
    return Path(os.getenv(DATA_ENV) or DEFAULT_DIR).expanduser()


@lru_cache(maxsize=1)
def manifest() -> dict[str, str]:
    return {f["name"]: f["sha256"] for f in json.loads(MANIFEST.read_text())["files"]}


@lru_cache(maxsize=None)
def _verified(path: str, mtime: float, size: int) -> str:
    return features.sha256_file(path)


def path(name: str) -> Path:
    """The verified private file, or Missing with the reason."""
    if name not in manifest():
        raise Missing(f"{name} isn't in the handoff manifest")
    p = directory() / name
    if not p.is_file():
        raise Missing(f"{name} isn't installed (set {DATA_ENV})")
    st = p.stat()
    if _verified(str(p), st.st_mtime, st.st_size) != manifest()[name]:
        raise Missing(f"{name} doesn't match the manifest's SHA-256; not used")
    return p


def available(names=PRIVATE) -> bool:
    try:
        for n in names:
            path(n)
        return True
    except Missing:
        return False


def status() -> str:
    missing = []
    for n in PRIVATE:
        try:
            path(n)
        except Missing as e:
            missing.append(str(e))
    return "installed and verified" if not missing else f"{len(missing)} of {len(PRIVATE)} missing: {missing[0]}"


def bars(name: str):
    return features.read_csv(path(name))


def load_json(name: str):
    return json.loads(path(name).read_text())
