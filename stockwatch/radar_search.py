"""Radar search: keep the stocks whose ticker or company name matches what was typed. Display only."""


def name_of(snap: dict) -> str:
    p = snap.get("payload") or {}
    return (p.get("profile") or {}).get("name") or p.get("name") or ""


def matches(snap: dict, query: str) -> bool:
    """Every word typed must appear in the ticker or the company name (any case). A blank search keeps everything."""
    words = (query or "").lower().split()
    if not words:
        return True
    hay = f'{snap.get("ticker", "")} {name_of(snap)}'.lower()
    return all(w in hay for w in words)


def apply(snaps: list[dict], query: str) -> list[dict]:
    return [s for s in snaps if matches(s, query)]
