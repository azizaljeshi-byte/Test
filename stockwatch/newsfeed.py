"""Watchlist news from several sources, ranked, with the hottest sent to Telegram. Display and alerts only: nothing here
feeds a score, signal, verdict or plan (`catalysts.py` still reads only Yahoo's `events["news"]`; this module's stories
live in `events["wire"]`).

Sources, none needing a new key: Yahoo (what the app already fetched), Google News RSS (searched by company name),
SEC EDGAR 8-K filings (from the filings the scan already fetched) and Finnhub company news when its key is set.
Every source that fails says why; one failing never blocks the others.

Stories are merged across sources by headline (the same story from three sources is one story with three sources), then
given a tier by plain keyword rules, the same kind of rule `catalysts.py` uses:
  HOT        critical: bankruptcy, delisting, fraud, an SEC or DOJ probe, a restatement, trading halted, guidance cut or
             withdrawn, FDA rejection, a recall, a data breach, a CEO or CFO leaving suddenly, a short-seller report, a
             share sale, going-concern doubt, and 8-K items 1.03, 3.01, 4.02, 1.05
  IMPORTANT  analyst up/downgrades, earnings, deals (acquisitions, mergers), guidance raises, contracts, approvals, buybacks
  ROUTINE    everything else
Rank inside a tier: more independent sources, then newer, then a held stock over a watchlist one.

Only HOT stories go to Telegram (`NEWS_ALERT_MIN`), once each, and only when first seen within `ALERT_WINDOW_HOURS`.
The first run records what is already out there silently. A failed send stays unseen and retries next run. The scan runs
about every 15 minutes, so an alert is not instant.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

log = logging.getLogger(__name__)

NEWS_KEY = "__news_seen__"          # reserved entry in the alert memory: {story key: unix time first seen}
NEWS_ALERT_MIN = 3                  # 3 = HOT. Set to 4 to switch news alerts off without touching anything else.
ALERT_WINDOW_HOURS = 24
KEEP_DAYS = 7
MAX_PER_RUN = 6                     # a flood of news is spread over runs rather than sent as 30 messages
WINDOW_HOURS = 72
GOOGLE = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
TTL = 600
TIERS = {3: "HOT", 2: "IMPORTANT", 1: "ROUTINE"}

HOT = re.compile(
    r"bankruptcy|chapter 11|going concern|delist|\bfraud|\bsubpoena|restat(e|ement)|non-reliance|material weakness|"
    r"\b(sec|doj|ftc|justice department)\b.{0,30}\b(probe|investigat|charges|sues|subpoena)|"
    r"\b(probe|investigation)\b.{0,30}\b(sec|doj|ftc)\b|trading (halt|halted|suspended)|\bhalted\b|"
    r"(cuts?|lowers?|slashes|withdraws?|suspends?|pulls?)\b.{0,20}\b(guidance|outlook|forecast)|"
    r"\b(fda)\b.{0,30}\b(reject|refuse|complete response|clinical hold)|complete response letter|clinical hold|"
    r"\brecall|data breach|cyber ?attack|ransomware|"
    r"\b(ceo|cfo|chief executive|chief financial)\b.{0,25}\b(resign|steps down|ousted|fired|terminated|abruptly)|"
    r"short[- ]seller|short report|"
    r"(stock|share|equity|public|secondary|follow-on|registered direct|at-the-market|atm|convertible|priced|proposed|"
    r"underwritten)\s+(notes\s+)?offering|\bplunges?\b|\bcrash(es|ed)?\b|\btumbles? \d", re.I)
IMPORTANT = re.compile(
    r"downgrade|upgrade|price target|\b(earnings|results|revenue|eps)\b|\bbeats?\b|\bmiss(es|ed)?\b|"
    r"(raises?|boosts?|lifts?)\b.{0,20}\b(guidance|outlook|forecast)|acqui(re|res|sition)|merger|buyout|takeover|"
    r"\bdeal\b|contract|partnership|approv(al|es|ed)|buyback|repurchase|dividend|\blayoffs?\b|\bsurges?\b|\bsoars?\b|"
    r"\bjumps?\b|\bslumps?\b|lawsuit|sues", re.I)
ITEM_TIER = {"1.03": 3, "3.01": 3, "4.02": 3, "1.05": 3, "2.04": 2, "2.06": 2, "4.01": 2, "5.02": 2, "2.02": 2, "1.01": 2,
             "1.02": 2, "2.01": 2, "5.01": 2}

_lock = threading.Lock()
_slots = threading.Semaphore(3)
_cache: dict = {}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; StockWatch)"})
    with _slots, urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- sources

def _clean_name(name: str | None) -> str:
    n = re.sub(r"\b(inc|corp|corporation|co|ltd|plc|holdings|group|company|class [a-z]|common stock)\b\.?,?", "", name or "", flags=re.I)
    return re.sub(r"[\s,.]+$", "", re.sub(r"\s+", " ", n)).strip()


def parse_rss(text: str, source: str = "Google News") -> list[dict]:
    """Stories from an RSS feed; a malformed feed raises ValueError (the caller reports it)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"not a news feed ({e})")
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        pub = it.findtext("source") or ""
        if pub and title.endswith(" - " + pub):
            title = title[: -len(pub) - 3].strip()
        try:
            when = parsedate_to_datetime(it.findtext("pubDate") or "")
            when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if title:
            out.append({"title": title, "publisher": pub or source, "url": (it.findtext("link") or "").strip() or None,
                        "published": when, "source": source})
    return out


def google(ticker: str, name: str | None) -> list[dict]:
    """Google News for the company, last two days. The company name keeps tickers like RR or APP from matching noise."""
    short = _clean_name(name)
    q = (f'"{short}" stock' if short else f"{ticker} stock") + " when:2d"
    return parse_rss(_get(GOOGLE.format(q=urllib.parse.quote(q))))


def sec_stories(filings: list[dict] | None, ticker: str, now: datetime, hours: int = WINDOW_HOURS) -> list[dict]:
    """New 8-K filings as stories, tiered by their item numbers (bankruptcy, delisting and non-reliance are HOT)."""
    from . import sec
    out = []
    for f in filings or []:
        if f.get("form") not in ("8-K", "6-K"):
            continue
        try:
            when = datetime.fromisoformat(str(f["date"])).replace(tzinfo=timezone.utc) + timedelta(hours=12)
        except (KeyError, ValueError):
            continue
        if now - when > timedelta(hours=hours):
            continue
        items = [i.strip() for i in str(f.get("items") or "").split(",") if i.strip()]
        out.append({"title": sec.describe(f), "publisher": "SEC EDGAR", "url": f.get("url"), "published": when, "source": "SEC",
                    "tier": max([ITEM_TIER.get(i, 1) for i in items] or [1])})
    return out


def finnhub_stories(ticker: str) -> list[dict]:
    from . import finnhub
    return [{**n, "source": "Finnhub"} for n in finnhub.news(ticker, 2)]


def yahoo_stories(news: list[dict] | None) -> list[dict]:
    return [{**n, "source": "Yahoo"} for n in news or [] if n.get("title") and n.get("published")]


# ---------------------------------------------------------------- merge, tier, rank

STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "at", "by", "with", "is", "are", "its", "after", "from"}


def _tokens(title: str) -> frozenset:
    t = re.sub(r"[^a-z0-9 ]", " ", title.lower())
    return frozenset(w for w in t.split() if w not in STOP and len(w) > 1)


def _same(a: frozenset, b: frozenset) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= 0.55


def tier_of(title: str) -> int:
    if HOT.search(title):
        return 3
    return 2 if IMPORTANT.search(title) else 1


def story_key(ticker: str, title: str) -> str:
    """A stable id for one story: the ticker plus the sorted words that identify it."""
    return hashlib.sha1((ticker + "|" + " ".join(sorted(_tokens(title))[:8])).encode()).hexdigest()[:16]


def merge(ticker: str, held: bool, groups: dict[str, list[dict]], now: datetime) -> list[dict]:
    """One ranked list from every source's stories. Each story: title, tier, tier_label, sources, url, published, age_h."""
    stories: list[dict] = []
    for source, items in groups.items():
        for it in items:
            if now - it["published"] > timedelta(hours=WINDOW_HOURS) or it["published"] - now > timedelta(hours=2):
                continue
            tok = _tokens(it["title"])
            hit = next((s for s in stories if _same(tok, s["_tok"])), None)
            if hit:
                if source not in hit["sources"]:
                    hit["sources"].append(source)
                if it["published"] < hit["published"]:
                    hit["published"] = it["published"]
                hit["tier"] = max(hit["tier"], it.get("tier") or 1, tier_of(it["title"]))
                if source == "SEC" or (not hit["url"] and it.get("url")):
                    hit["url"] = it.get("url") or hit["url"]
                continue
            stories.append({"title": it["title"], "publisher": it.get("publisher"), "url": it.get("url"), "published": it["published"],
                            "sources": [source], "tier": max(it.get("tier") or 1, tier_of(it["title"])), "_tok": tok})
    for s in stories:
        s["age_h"] = max((now - s["published"]).total_seconds() / 3600, 0)
        s["tier_label"] = TIERS[s["tier"]]
        s["key"] = story_key(ticker, s["title"])
        s["held"] = held
        s["rank"] = s["tier"] * 100 + min(len(s["sources"]), 3) * 12 + (6 if s["age_h"] < 2 else 4 if s["age_h"] < 6 else 2 if s["age_h"] < 24 else 0) + (3 if held else 0)
        del s["_tok"]
        s["published"] = s["published"].isoformat(timespec="minutes")      # plain text, so a saved snapshot reads back the same
    return sorted(stories, key=lambda s: (-s["rank"], s["age_h"]))


def build(ticker: str, name: str | None, held: bool, yahoo: list[dict] | None, filings: list[dict] | None,
          finnhub_on: bool = False, now: datetime | None = None) -> dict:
    """{"stories": ranked list, "sources": {source: "ok" | why not}} for one ticker. Never raises."""
    now = now or datetime.now(timezone.utc)
    hit = _cache.get(ticker)
    if hit and time.monotonic() - hit[0] < TTL:
        groups, status = hit[1], hit[2]
    else:
        groups, status = {}, {}
        groups["Yahoo"], status["Yahoo"] = yahoo_stories(yahoo), ("ok" if yahoo else "no headlines")
        for label, fn in (("Google News", lambda: google(ticker, name)),
                          ("Finnhub", (lambda: finnhub_stories(ticker)) if finnhub_on else None)):
            if fn is None:
                status[label] = "no FINNHUB_API_KEY is set"
                continue
            try:
                groups[label], status[label] = fn(), "ok"
            except Exception as e:      # any source can fail; the others still count
                log.info("news %s %s failed: %s", label, ticker, e)
                status[label] = "could not be reached"
        with _lock:
            _cache[ticker] = (time.monotonic(), groups, status)
    groups = {**groups, "SEC": sec_stories(filings, ticker, now)}
    return {"stories": merge(ticker, held, groups, now), "sources": {**status, "SEC": "ok" if filings is not None else "no filings read"}}


# ---------------------------------------------------------------- Telegram alerts

def split(entries: dict) -> tuple[dict, dict | None]:
    """(alert memory without the news entry, the news memory or None when there is none yet: first run)."""
    rest = {k: v for k, v in entries.items() if k != NEWS_KEY}
    return rest, (dict(entries[NEWS_KEY]) if isinstance(entries.get(NEWS_KEY), dict) else None)


def join(entries: dict, seen: dict) -> dict:
    return {**entries, NEWS_KEY: seen}


def step(seen: dict | None, wires: dict[str, dict], now: datetime) -> tuple[dict, list[dict], dict]:
    """(memory, stories to send, counts). First run (seen is None) records everything silently. Only HOT stories first seen
    within the alert window are sent, newest first, at most MAX_PER_RUN. A sent story is marked only by `delivered`."""
    ts = now.timestamp()
    counts = {"baseline": 0, "ready": 0, "deferred": 0}
    first = seen is None
    seen = {k: v for k, v in (seen or {}).items() if ts - v < KEEP_DAYS * 86400}
    ready = []
    for ticker, wire in wires.items():
        for s in (wire or {}).get("stories", []):
            if s["key"] in seen:
                continue
            if first or s["tier"] < NEWS_ALERT_MIN or s["age_h"] > ALERT_WINDOW_HOURS:
                seen[s["key"]] = ts
                counts["baseline"] += first
                continue
            ready.append({**s, "ticker": ticker})
    ready.sort(key=lambda s: (-s["rank"], s["age_h"]))
    counts["deferred"] = max(len(ready) - MAX_PER_RUN, 0)
    ready = ready[:MAX_PER_RUN]
    counts["ready"] = len(ready)
    return seen, ready, counts


def delivered(seen: dict, story: dict, now: datetime) -> None:
    seen[story["key"]] = now.timestamp()


def message(story: dict) -> str:
    who = "held" if story.get("held") else "watchlist"
    ago = f'{story["age_h"] * 60:.0f} min ago' if story["age_h"] < 1 else f'{story["age_h"]:.0f} h ago'
    src = ", ".join(story["sources"])
    n = f" ({len(story['sources'])} sources)" if len(story["sources"]) > 1 else ""
    return (f'🚨 CRITICAL NEWS · {story["ticker"]} ({who})\n{story["title"]}\n'
            f'{src}{n} · {ago}' + (f'\n{story["url"]}' if story.get("url") else "")
            + (f'\nApp: {os.environ["DASHBOARD_URL"].rstrip("/")}/?view=target&t={story["ticker"]}' if os.getenv("DASHBOARD_URL") else ""))
