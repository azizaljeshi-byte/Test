"""Event-driven signals: upcoming earnings, analyst rating changes, news headlines.

Headline scanning is keyword-based: it flags headlines worth reading, it doesn't
understand them.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from .signals import OPPORTUNITY, RISK, Signal

SEVERE_NEGATIVE = ["fraud", "bankruptcy", "chapter 11", "delist", "going concern", "default",
                   "dilution", "reverse split", "restatement", "subpoena"]
# "offering" alone also means products ("new AI offerings"); only share sales count
SHARE_SALE = re.compile(r"\b(stock|share|equity|public|secondary|follow-on|registered direct|at-the-market|atm|"
                        r"convertible|priced|proposed|underwritten)\s+(notes\s+)?offering\b|\boffering of\b.*\b(shares|"
                        r"stock|notes|units|warrants)\b|\bprices?\b.*\boffering\b", re.I)
NEGATIVE = ["downgrade", "lawsuit", "probe", "investigation", "sec ", "recall", "misses", "miss ",
            "cuts guidance", "lowers guidance", "plunge", "tumble", "layoffs", "short seller",
            "halt", "warning", "resigns", "slump"]
POSITIVE = ["beats", "raises guidance", "upgrade", "record revenue", "contract", "partnership",
            "approval", "approves", "buyback", "repurchase", "surge", "soar", "wins", "awarded"]

BUYISH = re.compile(r"buy|outperform|overweight|positive|accumulate", re.I)
NEWS_WINDOW_HOURS = 72
RATING_WINDOW_DAYS = 10


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _matches(title: str, words: list[str]) -> bool:
    t = f" {title.lower()} "
    return any(w in t for w in words)


def _severe(title: str) -> bool:
    return bool(SHARE_SALE.search(title)) or _matches(title, SEVERE_NEGATIVE)


def analyze(events: dict, owned: bool, tier: int, today: date | None = None) -> tuple[dict, list[Signal]]:
    today = today or date.today()
    now = datetime.now(timezone.utc)
    out: list[Signal] = []
    m: dict = {"earnings_date": None, "days_to_earnings": None, "news": [], "rating_changes": []}

    # --- earnings
    ed = events.get("earnings_date")
    if ed:
        days = (ed - today).days
        m["earnings_date"], m["days_to_earnings"] = ed.isoformat(), days
        if 0 <= days <= 7:
            if owned:
                out.append(Signal(RISK, "event", "earnings_soon",
                                  f"Earnings in {days} day{'s' if days != 1 else ''} ({ed:%b %d}) - expect a big move"
                                  + ("; consider position size" if tier == 2 else ""), 2))
            else:
                out.append(Signal(RISK, "event", "earnings_soon",
                                  f"Earnings in {days} days ({ed:%b %d}) - consider waiting for the report", 1))
        elif 7 < days <= 14:
            out.append(Signal(RISK, "event", "earnings_upcoming", f"Earnings in {days} days ({ed:%b %d})", 1))

    # --- analyst rating changes
    for rc in events.get("rating_changes") or []:
        when = _aware(rc["date"])
        recent = (now - when).days <= RATING_WINDOW_DAYS
        m["rating_changes"].append({**rc, "date": when.date().isoformat()})
        if not recent:
            continue
        firm, to = rc.get("firm") or "an analyst", rc.get("to_grade") or "?"
        if rc.get("action") == "up":
            out.append(Signal(OPPORTUNITY, "analyst", "upgrade",
                              f"Upgraded by {firm}: {rc.get('from_grade') or '?'} -> {to}", 2))
        elif rc.get("action") == "down":
            out.append(Signal(RISK, "analyst", "downgrade",
                              f"Downgraded by {firm}: {rc.get('from_grade') or '?'} -> {to}", 2))
        elif rc.get("action") == "init" and BUYISH.search(to):
            out.append(Signal(OPPORTUNITY, "analyst", "initiated_buy", f"{firm} initiated coverage at {to}", 1))
    m["rating_changes"] = m["rating_changes"][:6]

    # --- news headlines (one signal per direction: the most serious recent headline)
    worst = best = None
    m["news_today"] = 0
    for n in events.get("news") or []:
        published = _aware(n["published"])
        tone = ("negative" if _severe(n["title"]) or _matches(n["title"], NEGATIVE)
                else "positive" if _matches(n["title"], POSITIVE) else "neutral")
        m["news"].append({**n, "published": published.isoformat(timespec="minutes"), "tone": tone})
        if (now - published).total_seconds() <= 36 * 3600:
            m["news_today"] += 1
        if (now - published).total_seconds() > NEWS_WINDOW_HOURS * 3600:
            continue
        title = n["title"]
        if _severe(title):
            if worst is None or worst[0] < 2:
                worst = (2, title)
        elif _matches(title, NEGATIVE):
            worst = worst or (1, title)
        elif _matches(title, POSITIVE):
            best = best or title
    if worst:
        out.append(Signal(RISK, "news", "news_negative", f'Headline: "{worst[1]}"', worst[0]))
    if best:
        out.append(Signal(OPPORTUNITY, "news", "news_positive", f'Headline: "{best}"', 1))
    m["news"] = m["news"][:8]
    return m, out
