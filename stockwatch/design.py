"""The shared look: two themes (dark and light) and the small pieces every page reuses.

Display only. Nothing here reads data or changes a score, signal, verdict, plan or alert. The pieces take plain values
and return HTML strings; the pages decide what to show (see docs/TIGHTENING.md, sections 3, 7 and 10).

Colour is never the only signal: every status also has a word (ACT, BUY, WATCH, CALM) and every comment line an icon.
"""
from __future__ import annotations

from html import escape
from urllib.parse import urlencode

THEMES = {"auto": "Auto", "dark": "Dark", "light": "Light"}
DEFAULT_THEME = "auto"

# Tape tokens: one source for shared HTML, legacy components and native widgets.
TAPE_DARK = {"bg":"#0d1a2c", "surface":"#14253c", "raised":"#1b304b", "line":"#233855",
             "ink":"#f2efe8", "soft":"#9fb0c8", "muted":"#9fb0c8", "gain":"#4fd6a5", "loss":"#ff8a7a",
             "on":"#0d1a2c", "on-c":"#0d1a2c"}
TAPE_LIGHT = {"bg":"#f2f4f7", "surface":"#fffefb", "raised":"#e6edf4", "line":"#c7d2df",
              "ink":"#15243a", "soft":"#485a71", "muted":"#52657c", "gain":"#146b4b", "loss":"#a7382c",
              "on":"#fffefb", "on-c":"#fffefb"}
DARK = {"act":TAPE_DARK["loss"], "buy":TAPE_DARK["gain"], "watch":"#e5c58b", "calm":TAPE_DARK["soft"],
        "bad":TAPE_DARK["loss"], "weak":"#d4a69c", "neutral":TAPE_DARK["soft"], "good":TAPE_DARK["gain"], "strong":TAPE_DARK["gain"]}
LIGHT = {"act":TAPE_LIGHT["loss"], "buy":TAPE_LIGHT["gain"], "watch":"#775b1c", "calm":TAPE_LIGHT["soft"],
         "bad":TAPE_LIGHT["loss"], "weak":"#945344", "neutral":TAPE_LIGHT["soft"], "good":TAPE_LIGHT["gain"], "strong":TAPE_LIGHT["gain"]}
FONT = '"Familjen Grotesk", system-ui, sans-serif'


def _palette_vars(p: dict) -> str:
    return "".join(f"--dz-{k}:{v};" for k, v in p.items())


def _theme_vars(tokens: dict, palette: dict, scheme: str) -> str:
    legacy = {"bg":"bg", "panel":"surface", "panel2":"raised", "line":"line", "ink":"ink", "soft":"soft", "muted":"muted",
              "opp":"gain", "risk":"loss", "info":"soft"}
    return (_palette_vars(tokens) + _palette_vars(palette) + f"color-scheme:{scheme};" +
            "".join(f"--{key}:{tokens[value]};" for key,value in legacy.items()) + f"--warn:{palette['watch']};" +
            f"--sans:{FONT};--head:{FONT};--mono:{FONT};")


# Apply the same tokens to native Streamlit widgets in all three theme modes.
_WIDGETS = """
.stApp{background:var(--dz-bg) !important;color:var(--dz-ink) !important}.stApp::after{display:none !important}
html,body,.stApp,button,input,textarea,select,[data-baseweb]{font-family:var(--sans) !important;font-variant-numeric:tabular-nums}
.stApp [data-testid="stMarkdownContainer"] *{font-family:var(--sans) !important;font-variant-numeric:tabular-nums}
[data-testid="stMarkdownContainer"],[data-testid="stCaptionContainer"],[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"],label,.stApp h1,.stApp h2,.stApp h3{color:var(--dz-ink) !important}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p,[data-testid="stCaption"] p{color:var(--dz-muted) !important}
[data-testid="stButtonGroup"] button,.stButton button,[data-baseweb="select"]>div,
[data-baseweb="input"],[data-baseweb="input"] input,textarea,[data-baseweb="popover"],[role="listbox"],
[data-baseweb="menu"],[data-baseweb="menu"] li,
[data-testid="stSelectbox"] [role="group"],[data-testid="stSelectbox"] input,
[data-testid="stSelectbox"] button,[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,
.react-aria-Popover,.react-aria-ListBox,.react-aria-ListBoxItem,[role="option"]{background:var(--dz-surface) !important;color:var(--dz-ink) !important;border-color:var(--dz-line) !important}
[data-testid="stButtonGroup"] button,.stButton button{border:1px solid var(--dz-line) !important;min-height:44px}
[data-testid="stButtonGroup"] button[aria-checked="true"],
[data-testid="stButtonGroup"] button[aria-pressed="true"]{background:var(--dz-ink) !important;color:var(--dz-bg) !important}
[data-testid="stButtonGroup"] button *,.stButton button *{color:inherit !important}
.stButton button:disabled{opacity:.55}
[data-testid="stExpander"],[data-testid="stExpander"] details{background:var(--dz-surface) !important;border-color:var(--dz-line) !important;color:var(--dz-ink) !important}
header[data-testid="stHeader"]{background:transparent !important}
a:focus-visible,button:focus-visible{outline:2px solid var(--dz-ink) !important;outline-offset:3px}
.stApp .js-plotly-plot text{font-family:var(--sans) !important;font-variant-numeric:tabular-nums}
.mc-title{text-shadow:none !important;letter-spacing:.02em !important;color:var(--dz-ink) !important}
.mc-tile,.mc-card{background:var(--dz-surface) !important}
/* Remaining screens keep their layouts; legacy semantic colours follow the active theme. */
.stApp [style*="--c:#3dffa8"]{--c:var(--dz-buy) !important}.stApp [style*="color:#3dffa8"]{color:var(--dz-buy) !important}
.stApp [style*="--c:#ff4d7a"]{--c:var(--dz-act) !important}.stApp [style*="color:#ff4d7a"]{color:var(--dz-act) !important}
.stApp [style*="--c:#ffb020"]{--c:var(--dz-watch) !important}.stApp [style*="color:#ffb020"]{color:var(--dz-watch) !important}
.stApp [style*="--c:#36c5f0"]{--c:var(--dz-calm) !important}.stApp [style*="color:#36c5f0"]{color:var(--dz-calm) !important}
.aiv [style*="--call:#3dffa8"]{--call:var(--dz-gain) !important}
.aiv [style*="--call:#ff697b"]{--call:var(--dz-loss) !important}
.aiv [style*="--call:#ffb020"]{--call:var(--dz-watch) !important}
.aiv-good{color:var(--dz-gain) !important}.aiv-bad{color:var(--dz-loss) !important}.aiv-neutral{color:var(--dz-ink) !important}
.aiv-level{color:var(--dz-soft) !important}.aiv-level.exit{color:var(--dz-gain) !important;border-color:var(--dz-gain) !important}
.aiv-level.support{color:var(--dz-loss) !important;border-color:var(--dz-loss) !important}.aiv-level.price{color:var(--dz-ink) !important;border-color:var(--dz-line) !important}
.block-container{padding-bottom:calc(104px + env(safe-area-inset-bottom,0px)) !important}
.tape-nav{position:fixed;bottom:0;left:0;right:0;z-index:999;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));
 background:var(--dz-bg);border-top:1px solid var(--dz-line);padding:8px max(8px,env(safe-area-inset-right,0px)) calc(8px + env(safe-area-inset-bottom,0px)) max(8px,env(safe-area-inset-left,0px));gap:2px}
.tape-nav a{display:flex;align-items:center;justify-content:center;min-height:44px;min-width:0;font-size:12px;
 color:var(--dz-soft) !important;text-decoration:none !important;border-radius:9px;font-weight:500}
.tape-nav a[aria-current="page"]{color:var(--dz-ink) !important;background:var(--dz-surface);font-weight:700}
.stApp h2.tape-group{font-size:13px !important;font-weight:600 !important;color:var(--dz-soft) !important;margin:16px 0 8px !important;padding:0 !important}
.tape-more{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:20px}
.tape-more a{display:block;background:var(--dz-surface);border:1px solid var(--dz-line);border-radius:14px;padding:14px;
 min-height:62px;color:var(--dz-ink) !important;text-decoration:none !important;font-size:15px;font-weight:600}
.tape-more small{display:block;color:var(--dz-soft);font-size:12px;font-weight:400;margin-top:4px}
"""


def theme_css(mode: str = DEFAULT_THEME) -> str:
    """Tape in dark/light, or the phone's preference. Unknown modes follow Auto."""
    mode = mode if mode in THEMES else DEFAULT_THEME
    dark = f":root{{{_theme_vars(TAPE_DARK,DARK,'dark')}}}"
    light = f":root{{{_theme_vars(TAPE_LIGHT,LIGHT,'light')}}}"
    body = dark if mode == "dark" else light if mode == "light" else dark + f"@media (prefers-color-scheme: light){{{light}}}"
    font = "@import url('https://fonts.googleapis.com/css2?family=Familjen+Grotesk:wght@400;500;600;700&display=swap');"
    return f"<style>{font}{body}{_WIDGETS}{COMPONENTS}</style>"


PRIMARY_VIEWS = {"radar":"Radar", "portfolio":"Portfolio", "quick":"Quick", "rising":"Momentum", "more":"More"}
MORE_GROUPS = {"Look up": {"target":("Details","Look up a tracked stock"), "market":("S&P 500","The wider market"),
                           "ai":("Ask the AI","Saved opinions and re-checks"), "ext":("Extended","Before and after the session")},
               "Practice accounts": {"paper":("Paper","The New call practice account"), "log":("Log","Updates and alerts")}}
# All previously supported routes remain valid, including the off-menu pages.
VIEWS = PRIMARY_VIEWS | {k:v[0] for group in MORE_GROUPS.values() for k,v in group.items()} | {
    "fleet":"Fleet", "research":"Research", "tests":"Test list"}


def resolve_view(value: str) -> str:
    return value if value in VIEWS else "radar"


def _view_link(view: str, theme: str) -> str:
    return escape("?" + urlencode({"view":view, "theme":theme if theme in THEMES else DEFAULT_THEME}), quote=True)


def bottom_nav(view: str, theme: str = DEFAULT_THEME) -> str:
    """URL-driven navigation survives full reloads; secondary routes select More."""
    selected = view if view in PRIMARY_VIEWS else "more"
    links = ''.join(f'<a href="{_view_link(key,theme)}" target="_self"' +
                    (' aria-current="page"' if key == selected else '') + f'>{escape(label)}</a>' for key,label in PRIMARY_VIEWS.items())
    return f'<nav class="tape-nav" aria-label="Main navigation">{links}</nav>'


def more_group(group: str, theme: str = DEFAULT_THEME) -> str:
    """Escaped links for one More group. Theme/Sweep use native callback widgets."""
    links = ''.join(f'<a href="{_view_link(key,theme)}" target="_self">{escape(label)}<small>{escape(note)}</small></a>'
                    for key,(label,note) in MORE_GROUPS.get(group,{}).items())
    return f'<div class="tape-more">{links}</div>'


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


def zone_row(kind: str, low: float, high: float | None, grade: str, reasons: list[str] | None = None, away: str = "") -> str:
    """A support or resistance zone with its plain-English recommendation (no HIGH / MEDIUM / LOW on screen)."""
    words, tone = zone_words(kind, grade)
    price = f"{low:.2f}" + (f" to {high:.2f}" if high is not None and abs(high - low) > 1e-9 else "")
    why = f'<small>{escape(" · ".join(reasons))}</small>' if reasons else ""
    far = f'<small class="dz-away">{escape(away)}</small>' if away else ""
    return (f'<div class="dz-zone dz-{kind}"><div><small>{"Support" if kind == "support" else "Resistance"}</small>'
            f'<b>{price}</b>{far}{why}</div><em class="dz-t-{tone}">{escape(words)}</em></div>')


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
.dz-ic{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:6px;font:800 .68rem/1 var(--sans);
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
.dz-zone>div{flex:1;min-width:0;overflow-wrap:anywhere}.dz-zone small{display:block;color:var(--dz-muted);font-size:.72rem}.dz-zone small.dz-away{color:var(--dz-soft)}.dz-zone b{font-size:1.02rem;color:var(--dz-ink)}
.dz-zone em{font-style:normal;font-size:.74rem;font-weight:700;text-align:right;flex:0 0 120px;line-height:1.25}
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
