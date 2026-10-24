"""The shared look: two themes (dark and light) and the small pieces every page reuses.

Display only. Nothing here reads data or changes a score, signal, verdict, plan or alert. The pieces take plain values
and return HTML strings; the pages decide what to show (see docs/TIGHTENING.md, sections 3, 7 and 10).

Colour is never the only signal: every status also has a word (ACT, BUY, WATCH, CALM) and every comment line an icon.
"""
from __future__ import annotations

from html import escape

THEMES = {"auto": "Auto", "dark": "Dark", "light": "Light"}
DEFAULT_THEME = "auto"

# --- status colours: act (sell side), buy, watch, calm, and the gauge steps from bad to strong
DARK = {"act": "#ff7b78", "buy": "#3fd08d", "watch": "#f2b84b", "calm": "#8da2d6", "bad": "#ff6b6b", "weak": "#ffa566",
        "neutral": "#8a93a3", "good": "#8fd18a", "strong": "#3fd08d"}
LIGHT = {"act": "#d6383a", "buy": "#12935a", "watch": "#b87800", "calm": "#4a67d6", "bad": "#e5534b", "weak": "#e08a3c",
         "neutral": "#7d8696", "good": "#4fa86a", "strong": "#12935a"}

_VARS_DARK = ("--dz-bg:#0b1118;--dz-surface:#121a25;--dz-raised:#171f2c;--dz-line:#243041;--dz-ink:#e9eef5;--dz-soft:#aab3c3;"
              "--dz-muted:#8d99ab;--dz-on:#0b1118;--dz-on-c:#0b1118;")
_VARS_LIGHT = ("--dz-bg:#f4f5f8;--dz-surface:#ffffff;--dz-raised:#eef0f4;--dz-line:#dde1e8;--dz-ink:#12161c;--dz-soft:#3f4857;"
               "--dz-muted:#5d6675;--dz-on:#ffffff;--dz-on-c:#ffffff;")


def _palette_vars(p: dict) -> str:
    return "".join(f"--dz-{k}:{v};" for k, v in p.items())


# The app's older styles (ui.CSS) are written with these variables, so overriding them re-themes every page.
_LEGACY_LIGHT = ("--bg:#f4f5f8;--panel:#ffffff;--panel2:#f6f7fa;--line:#dde1e8;--ink:#12161c;--soft:#3f4857;--muted:#5d6675;"
                 "--opp:#12935a;--risk:#d6383a;--warn:#b87800;--info:#2468c9;")

# Streamlit's own widgets keep their dark colours unless told otherwise; only needed in the light theme.
_LIGHT_WIDGETS = """
.stApp{background:var(--dz-bg) !important}.stApp::after{display:none !important}
[data-testid="stMarkdownContainer"],[data-testid="stCaptionContainer"],[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"],label,.stApp h1,.stApp h2,.stApp h3{color:var(--dz-ink) !important}
[data-testid="stCaptionContainer"]{color:var(--dz-muted) !important}
[data-testid="stButtonGroup"] button,.stButton button,[data-baseweb="select"]>div{
  background:var(--dz-surface) !important;color:var(--dz-ink) !important;border:1px solid var(--dz-line) !important}
[data-testid="stButtonGroup"] button[aria-checked="true"]{background:var(--dz-ink) !important;color:var(--dz-bg) !important}
[data-testid="stButtonGroup"] button *,.stButton button *{color:inherit !important}
[data-testid="stExpander"],[data-testid="stExpander"] details{background:var(--dz-surface) !important;border-color:var(--dz-line) !important}
header[data-testid="stHeader"]{background:transparent !important}
"""


def theme_css(mode: str = DEFAULT_THEME) -> str:
    """The theme as one <style> block. Dark is the app's existing look; light overrides its colour variables; auto follows the
    phone's setting. An unknown mode falls back to auto."""
    mode = mode if mode in THEMES else DEFAULT_THEME
    dark = f":root{{{_VARS_DARK}{_palette_vars(DARK)}}}"
    light = f":root{{{_VARS_LIGHT}{_palette_vars(LIGHT)}{_LEGACY_LIGHT}}}{_LIGHT_WIDGETS}"
    if mode == "dark":
        body = dark
    elif mode == "light":
        body = dark + light
    else:
        body = dark + f"@media (prefers-color-scheme: light){{{light}}}"
    return f"<style>{body}{COMPONENTS}</style>"


# ------------------------------------------------------------------ wording (plain English, the same everywhere)

ZONE_WORDS = {
    ("support", "HIGH"): ("Likely to hold: a good place to buy", "good"),
    ("support", "MEDIUM"): ("May hold: buy small only", "mid"),
    ("support", "LOW"): ("Weak: don't count on it", "weak"),
    ("resistance", "HIGH"): ("Likely to stop a rise: a good place to sell", "good"),
    ("resistance", "MEDIUM"): ("May stop a rise", "mid"),
    ("resistance", "LOW"): ("Weak: the price may pass through", "weak"),
}


def zone_words(kind: str, grade: str) -> tuple[str, str]:
    """(plain-English recommendation, tone) for a graded zone. The grade itself (HIGH, MEDIUM, LOW) is not shown."""
    return ZONE_WORDS.get((kind, grade), ("No read", "weak"))


FUND_BANDS = ((25, "Poor", 1), (45, "Weak", 2), (65, "Fair", 3), (80, "Good", 4), (101, "Strong", 5))
TECH_WORDS = {1: "Bad", 2: "Weak", 3: "Neutral", 4: "Good", 5: "Strong"}
STEP_KEYS = {1: "bad", 2: "weak", 3: "neutral", 4: "good", 5: "strong"}


def fundamentals_rating(score) -> tuple[str, int] | None:
    """(word, 1 to 5) from the 0 to 100 fundamental score; None when the score is unknown (never a zero).
    Draft bands from docs/TIGHTENING.md section 10: under 25 Poor, 25 to 44 Weak, 45 to 64 Fair, 65 to 79 Good, 80+ Strong."""
    if score is None or score != score:
        return None
    for top, word, step in FUND_BANDS:
        if score < top:
            return word, step
    return "Strong", 5


def technical_rating(step: int | None) -> tuple[str, int] | None:
    """(word, 1 to 5) from the gauge step 0 to 4 the Day Board already computes; None when the gauge is unclear."""
    if step is None:
        return None
    n = int(step) + 1
    return TECH_WORDS[n], n


# ------------------------------------------------------------------ pieces

STATUS_CLASS = {"ACT": "act", "SELL": "act", "BUY": "buy", "WATCH": "watch", "WAIT": "watch", "CALM": "calm", "HOLD": "calm",
                "UNCLEAR": "calm", "AVOID": "act"}


def status_of(word: str) -> str:
    """The colour family for a call word: act, buy, watch or calm."""
    w = (word or "").upper()
    for key, cls in STATUS_CLASS.items():
        if w.startswith(key):
            return cls
    return "calm"


def call_tag(word: str) -> str:
    return f'<span class="dz-call dz-{status_of(word)}">{escape(word)}</span>'


def change_pill(pct) -> str:
    """A coloured price change. Unknown shows a dash, not 0%."""
    if pct is None or pct != pct:
        return '<span class="dz-chg dz-flat">n/a</span>'
    cls = "up" if pct > 0 else "dn" if pct < 0 else "flat"
    return f'<span class="dz-chg dz-{cls}">{pct * 100:+.1f}%</span>'


def bell(on: bool = False, label: str = "Alerts") -> str:
    state = "on" if on else "off"
    return (f'<span class="dz-bell dz-{state}" role="img" aria-label="{escape(label)} {state}">'
            f'<svg viewBox="0 0 24 24" width="16" height="16" fill="{"currentColor" if on else "none"}" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>'
            f'<path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg></span>')


def pips(step: int | None, tone: str | None = None) -> str:
    """Five small bars, the first `step` filled. Unknown draws five empty ones."""
    n = 0 if step is None else max(0, min(5, int(step)))
    key = STEP_KEYS.get(n, "neutral")
    on = f' style="--dz-c:var(--dz-{tone or key})"'
    return f'<span class="dz-pips"{on}>' + "".join(f'<i class="{"on" if k < n else ""}"></i>' for k in range(5)) + "</span>"


def rating(label: str, value: tuple[str, int] | None, scale: str = "f") -> str:
    """'Fundamentals Weak' with its pips; 'Fundamentals n/a' when the rating is unknown."""
    if value is None:
        return f'<span class="dz-rate"><b>{escape(label)} n/a</b>{pips(None)}</span>'
    word, step = value
    return f'<span class="dz-rate" style="--dz-c:var(--dz-{STEP_KEYS[step]})"><b>{escape(label)} {escape(word)}</b>{pips(step)}</span>'


def gauge_line(step: int | None, word: str | None = None) -> str:
    """The lightning line: a bolt on a bad-to-strong gradient with one tag above it, 'Weak' and 'Strong' at the ends.
    `step` is 0 to 4 (the Day Board's gauge); unknown draws no bolt, says why through `word`."""
    if step is None:
        return (f'<div class="dz-gauge"><div class="dz-gl"></div><div class="dz-ends"><span>Weak</span>'
                f'<span>{escape(word or "No read")}</span><span>Strong</span></div></div>')
    pos = (10, 30, 50, 70, 90)[max(0, min(4, int(step)))]
    tag = escape(word or TECH_WORDS[int(step) + 1].upper())
    bolt = ('<svg width="13" height="13" viewBox="0 0 24 24" fill="#ffd54a"><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>')
    return (f'<div class="dz-gauge"><div class="dz-gl"><span class="dz-gtag" style="left:{pos}%">{tag}</span>'
            f'<span class="dz-bolt" style="left:{pos}%">{bolt}</span></div>'
            f'<div class="dz-ends"><span>Weak</span><span>Strong</span></div></div>')


ICONS = {"good": ("▲", "Good for the stock"), "bad": ("▼", "Bad for the stock"), "careful": ("!", "Be careful"),
         "info": ("i", "Just so you know")}


def icon_line(kind: str, text: str) -> str:
    """One comment line with its icon: good, bad, careful or info. A line that mixes good and bad is passed in as bad."""
    glyph, name = ICONS.get(kind, ICONS["info"])
    return (f'<div class="dz-li dz-k-{kind if kind in ICONS else "info"}"><i class="dz-ic" title="{escape(name)}" '
            f'aria-label="{escape(name)}">{glyph}</i><p>{escape(text)}</p></div>')


def icon_key() -> str:
    return '<div class="dz-key">' + "".join(
        f'<span><i class="dz-ic dz-k-{k}">{g}</i>{escape(n)}</span>' for k, (g, n) in ICONS.items()) + "</div>"


def zone_row(kind: str, low: float, high: float | None, grade: str, reasons: list[str] | None = None) -> str:
    """A support or resistance zone with its plain-English recommendation (no HIGH / MEDIUM / LOW on screen)."""
    words, tone = zone_words(kind, grade)
    price = f"{low:.2f}" + (f" to {high:.2f}" if high is not None and abs(high - low) > 1e-9 else "")
    why = f'<small>{escape(" · ".join(reasons))}</small>' if reasons else ""
    return (f'<div class="dz-zone dz-{kind}"><div><small>{"Support" if kind == "support" else "Resistance"}</small>'
            f'<b>{price}</b>{why}</div><em class="dz-t-{tone}">{escape(words)}</em></div>')


def news_line(tier: str, headline: str, age: str = "", source: str = "") -> str:
    """One news line with its tier tag (HOT, IMPORTANT or ROUTINE), headline, age and source."""
    cls = {"HOT": "hot", "IMPORTANT": "imp"}.get(tier.upper(), "rou")
    meta = " · ".join(x for x in (age, source) if x)
    return (f'<div class="dz-ln"><span class="dz-tier dz-{cls}">{escape(tier.upper())}</span>'
            f'<span class="dz-x">{escape(headline)}</span><small>{escape(meta)}</small></div>')


def result_line(result: str, text: str, when: str = "") -> str:
    """Last quarter's result: BEAT, MISS or IN LINE, with the surprise in `text`."""
    cls = {"BEAT": "buy", "MISS": "act"}.get(result.upper(), "calm")
    return (f'<div class="dz-ln"><span class="dz-tier dz-r-{cls}">{escape(result.upper())}</span>'
            f'<span class="dz-x">{escape(text)}</span><small>{escape(when)}</small></div>')


def next_line(text: str, when: str = "") -> str:
    return (f'<div class="dz-ln"><span class="dz-tier dz-r-calm">NEXT</span><span class="dz-x">{escape(text)}</span>'
            f'<small>{escape(when)}</small></div>')


# ------------------------------------------------------------------ the pieces' styles, written with the theme variables

COMPONENTS = """
.dz-call{display:inline-block;font-weight:800;font-size:.72rem;letter-spacing:.05em;padding:.16rem .6rem;border-radius:99px;
  background:var(--dz-c);color:var(--dz-on-c,#0b1118)}
.dz-act{--dz-c:var(--dz-act)}.dz-buy{--dz-c:var(--dz-buy)}.dz-watch{--dz-c:var(--dz-watch)}.dz-calm{--dz-c:var(--dz-calm)}
.dz-chg{display:inline-block;font-size:.76rem;font-weight:700;padding:.1rem .42rem;border-radius:6px;color:#fff;
  font-variant-numeric:tabular-nums}.dz-chg.dz-up{background:#2f8a62}.dz-chg.dz-dn{background:#c92a2a}
.dz-chg.dz-flat{background:var(--dz-raised);color:var(--dz-muted)}
.dz-bell{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--dz-raised);
  color:var(--dz-muted)}.dz-bell.dz-on{color:var(--dz-watch)}
.dz-pips{display:inline-flex;gap:3px}.dz-pips i{width:16px;height:5px;border-radius:3px;background:var(--dz-line)}
.dz-pips i.on{background:var(--dz-c,var(--dz-neutral))}
.dz-rate{display:inline-block;margin-right:16px;vertical-align:top}.dz-rate b{display:block;font-size:.78rem;margin-bottom:3px;
  color:var(--dz-c,var(--dz-muted))}
.dz-gauge{margin:6px 0 2px}.dz-gl{position:relative;height:5px;border-radius:9px;margin:40px 6px 8px;
  background:linear-gradient(90deg,var(--dz-bad),var(--dz-weak),var(--dz-neutral),var(--dz-good),var(--dz-strong))}
.dz-bolt{position:absolute;top:50%;transform:translate(-50%,-50%);width:28px;height:28px;border-radius:50%;
  background:var(--dz-bg);border:2px solid var(--dz-ink);display:grid;place-items:center}
.dz-gtag{position:absolute;bottom:24px;transform:translateX(-50%);font-size:.66rem;font-weight:800;letter-spacing:.06em;
  padding:.1rem .5rem;border-radius:7px;background:var(--dz-ink);color:var(--dz-bg);white-space:nowrap}
.dz-ends{display:flex;justify-content:space-between;font-size:.72rem;color:var(--dz-muted);margin:0 4px}
.dz-ic{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:6px;font:800 .68rem/1 system-ui;
  font-style:normal;flex:none;background:var(--dz-c);color:var(--dz-on-c,#0b1118)}
.dz-k-good{--dz-c:var(--dz-buy)}.dz-k-bad{--dz-c:var(--dz-act)}.dz-k-careful{--dz-c:var(--dz-watch)}.dz-k-info{--dz-c:var(--dz-calm)}
.dz-li{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;margin-bottom:6px;border-radius:12px;
  background:color-mix(in srgb,var(--dz-c) 10%,var(--dz-surface));border-left:3px solid var(--dz-c);color:var(--dz-ink)}
.dz-li .dz-ic{margin-top:2px}.dz-li p{margin:0;font-size:.93rem;line-height:1.4}
.dz-key{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:.78rem;color:var(--dz-muted);margin:0 2px 10px}
.dz-key span{display:flex;align-items:center;gap:6px}
.dz-zone{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 12px;border-radius:12px;
  margin-bottom:7px;background:var(--dz-surface);border-left:4px solid var(--dz-c)}
.dz-zone.dz-support{--dz-c:var(--dz-buy)}.dz-zone.dz-resistance{--dz-c:var(--dz-act)}
.dz-zone small{display:block;color:var(--dz-muted);font-size:.72rem}.dz-zone b{font-size:1.02rem;color:var(--dz-ink)}
.dz-zone em{font-style:normal;font-size:.74rem;font-weight:700;text-align:right;max-width:140px;line-height:1.25}
.dz-t-good{color:var(--dz-buy)}.dz-t-mid{color:var(--dz-watch)}.dz-t-weak{color:var(--dz-muted)}
.dz-ln{display:flex;gap:8px;align-items:center;font-size:.78rem;margin-top:8px;padding-top:8px;
  border-top:1px solid var(--dz-line);white-space:nowrap;overflow:hidden}
.dz-ln .dz-x{overflow:hidden;text-overflow:ellipsis;color:var(--dz-soft)}.dz-ln small{color:var(--dz-muted);flex:none}
.dz-tier{flex:none;font-size:.62rem;font-weight:800;letter-spacing:.05em;padding:.1rem .4rem;border-radius:5px;
  color:var(--dz-on-c,#0b1118);background:var(--dz-line)}
.dz-tier.dz-hot{background:var(--dz-act)}.dz-tier.dz-imp{background:var(--dz-watch)}
.dz-tier.dz-rou{background:var(--dz-line);color:var(--dz-soft)}
.dz-tier.dz-r-buy{background:var(--dz-buy)}.dz-tier.dz-r-act{background:var(--dz-act)}
.dz-tier.dz-r-calm{background:var(--dz-line);color:var(--dz-soft)}
@media (prefers-reduced-motion: reduce){.dz-pulse{animation:none !important}}
"""
