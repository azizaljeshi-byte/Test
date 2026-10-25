"""The paper-trading account (owner, 2026-10-25): a fake account that follows `decision.decide` on a short test list, journals
every trade and every buy the entry gates held back, and reports how the rules did. Nothing here touches a real account,
a card, a score, a call or an alert.

State is plain data (`to_dict` / `from_dict`) so it can be kept in the store now and in a Google Sheet later.
Fills are simulated at the price passed in (the app polls every few minutes, so they are approximate).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import decision, tradeplan

START_CASH = 50_000.0
RISK_PCT = 1.0
MAX_POSITION_PCT = 15.0
MIN_TRADES_TO_JUDGE = 30


@dataclass
class Book:
    cash: float = START_CASH
    start: float = START_CASH
    positions: dict = field(default_factory=dict)      # ticker -> position dict
    trades: list = field(default_factory=list)         # one dict per trade, open and closed
    blocked: list = field(default_factory=list)        # buys the gates held back
    log: list = field(default_factory=list)            # the last decisions that did something
    next_id: int = 1

    def to_dict(self) -> dict:
        return {"cash": self.cash, "start": self.start, "positions": self.positions, "trades": self.trades,
                "blocked": self.blocked[-500:], "log": self.log[-200:], "next_id": self.next_id}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Book":
        d = d or {}
        return cls(**{k: d[k] for k in ("cash", "start", "positions", "trades", "blocked", "log", "next_id") if k in d})

    def equity(self, prices: dict) -> float:
        return self.cash + sum(p["shares"] * (prices.get(t) or p["entry"]) for t, p in self.positions.items())


def _ts(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def _open(book: Book, snap: dict, price: float, now: datetime, d: dict) -> dict | None:
    plan = snap["payload"].get("plan") or {}
    sizing = tradeplan.size({**plan, "entry": price, "risk_per_share": price - plan["stop"]}, book.equity({}), RISK_PCT, MAX_POSITION_PCT) \
        if plan.get("stop") and price > plan["stop"] else None
    if not sizing or sizing["shares"] < 1:
        return None
    shares = int(sizing["shares"])
    cost = shares * price
    if cost > book.cash:
        shares = int(book.cash // price)
        cost = shares * price
    if shares < 1:
        return None
    book.cash -= cost
    t = (plan.get("targets") or [{}])[0].get("price")
    trade = {"id": book.next_id, "ticker": snap["ticker"], "opened": _ts(now), "entry": price, "shares": shares, "size": round(cost, 2),
             "stop": plan["stop"], "target1": t, "reason": d["reason"], "status": "OPEN", "closed": None, "exit": None,
             "exit_reason": None, "result": 0.0, "r": None, "worst": 0.0, "best": 0.0, "risk": round(shares * (price - plan["stop"]), 2),
             "sold": 0, "proceeds": 0.0}
    book.next_id += 1
    book.trades.append(trade)
    book.positions[snap["ticker"]] = {"trade": trade["id"], "shares": shares, "entry": price, "stop": plan["stop"], "stage": "full",
                                      "t1_done": False, "below_since": None, "opened": now.isoformat()}
    return trade


def _sell(book: Book, ticker: str, price: float, fraction: float, now: datetime, reason: str) -> None:
    pos = book.positions[ticker]
    n = pos["shares"] if fraction >= 1 else max(1, int(pos["shares"] * fraction))
    n = min(n, pos["shares"])
    book.cash += n * price
    pos["shares"] -= n
    trade = next(t for t in book.trades if t["id"] == pos["trade"])
    trade["sold"] += n
    trade["proceeds"] += n * price
    if fraction < 1:
        pos["stage"] = "half" if reason.startswith("closing below") else pos["stage"]
    if pos["shares"] <= 0:
        cost = trade["entry"] * trade["shares"]
        trade["status"], trade["closed"], trade["exit"], trade["exit_reason"] = "CLOSED", _ts(now), round(trade["proceeds"] / trade["sold"], 2), reason
        trade["result"] = round(trade["proceeds"] - cost, 2)
        trade["r"] = round(trade["result"] / trade["risk"], 2) if trade["risk"] else None
        del book.positions[ticker]


def step(book: Book, snaps: dict, prices: dict, now: datetime, cfg: decision.Config = decision.Config()) -> list[dict]:
    """Apply one round of decisions for every test-list stock in `snaps` ({ticker: snapshot}). `now` is New York time.
    Returns what was done, newest last."""
    done = []
    for ticker, snap in snaps.items():
        price = prices.get(ticker)
        pos = book.positions.get(ticker)
        if pos and price:
            trade = next(t for t in book.trades if t["id"] == pos["trade"])
            move = (price / pos["entry"] - 1) * 100
            trade["worst"], trade["best"] = min(trade["worst"], round(move, 2)), max(trade["best"], round(move, 2))
        pos_view = None
        if pos:
            pos_view = {**pos, "below_since": datetime.fromisoformat(pos["below_since"]) if pos.get("below_since") else None}
        d = decision.decide(snap, pos_view, price, now, cfg)
        a = d["action"]
        if d.get("blocked"):
            if not book.blocked or book.blocked[-1].get("ticker") != ticker or book.blocked[-1].get("day") != now.date().isoformat():
                book.blocked.append({"day": now.date().isoformat(), "time": _ts(now), "ticker": ticker, "price": price, "reason": d["reason"]})
        if pos:
            if d.get("mark_below") and not pos.get("below_since"):
                pos["below_since"] = now.isoformat()
            if d.get("clear_below"):
                pos["below_since"] = None
        if a == "ENTER" and not pos and price:
            t = _open(book, snap, price, now, d)
            if t:
                done.append({"ticker": ticker, "action": "ENTER", "price": price, "reason": d["reason"], "time": _ts(now)})
        elif a in ("SELL_ALL", "SELL_PART") and pos and price:
            _sell(book, ticker, price, d["fraction"], now, d["reason"])
            if d.get("move_stop_to_entry") and ticker in book.positions:
                book.positions[ticker]["stop"] = max(book.positions[ticker]["stop"], book.positions[ticker]["entry"])
                book.positions[ticker]["t1_done"] = True
            done.append({"ticker": ticker, "action": a, "price": price, "reason": d["reason"], "time": _ts(now)})
    book.log = (book.log + done)[-200:]
    return done


def report(book: Book, prices: dict | None = None) -> dict:
    """Win rate, average R, result and the verdict. The verdict says "too few trades" until `MIN_TRADES_TO_JUDGE` have closed."""
    closed = [t for t in book.trades if t["status"] == "CLOSED"]
    wins = [t for t in closed if t["result"] > 0]
    rs = [t["r"] for t in closed if t["r"] is not None]
    avg_r = sum(rs) / len(rs) if rs else None
    out = {"opened": len(book.trades), "closed": len(closed), "open": len(book.positions), "wins": len(wins),
           "losses": len(closed) - len(wins), "win_rate": len(wins) / len(closed) if closed else None, "avg_r": avg_r,
           "result": round(sum(t["result"] for t in closed), 2), "equity": round(book.equity(prices or {}), 2), "blocked": len(book.blocked)}
    if len(closed) < MIN_TRADES_TO_JUDGE:
        out["verdict"] = f"Too few trades to judge ({len(closed)} of {MIN_TRADES_TO_JUDGE} needed)."
    elif avg_r is not None and avg_r > 0.2:
        out["verdict"] = "KEEP the rules: the average trade makes money after its risk."
    elif avg_r is not None and avg_r > 0:
        out["verdict"] = "Marginal: the average trade barely pays for its risk. Look at the losses before changing anything."
    else:
        out["verdict"] = "TIGHTEN: the average trade loses money. Read the losing trades for what they had in common."
    return out
