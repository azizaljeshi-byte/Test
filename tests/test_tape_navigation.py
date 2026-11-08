"""Display-only Tape tokens and URL navigation, without providers or live work."""
import ast
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest

from stockwatch import design


class Links(HTMLParser):
    def __init__(self, markup):
        super().__init__(); self.links=[]; self.feed(markup)
    def handle_starttag(self, tag, attrs):
        if tag=='a': self.links.append(dict(attrs))


def test_five_fixed_destinations_and_all_secondary_routes_select_more():
    for route in design.VIEWS:
        links=Links(design.bottom_nav(route,'light')).links
        assert [parse_qs(a['href'][1:])['view'][0] for a in links]==['radar','portfolio','quick','rising','more']
        assert all(a['target']=='_self' and parse_qs(a['href'][1:])['theme']==['light'] for a in links)
        selected=[a for a in links if a.get('aria-current')=='page']
        assert len(selected)==1
        assert parse_qs(selected[0]['href'][1:])['view']==[route if route in design.PRIMARY_VIEWS else 'more']
        assert design.resolve_view(route)==route
    assert design.resolve_view('invalid')=='radar'
    assert design.resolve_view('target')=='target'  # existing alert URLs stay on Details


def test_more_contains_requested_groups_and_no_untrusted_query_injection():
    assert list(design.MORE_GROUPS)==['Look up','Practice accounts']
    links=[a for group in design.MORE_GROUPS for a in Links(design.more_group(group,'dark')).links]
    assert {parse_qs(a['href'][1:])['view'][0] for a in links}=={'target','market','ai','ext','paper','log'}
    html=design.bottom_nav('" onclick="x','"><script>x</script>')
    assert '<script>' not in html and 'onclick' not in html
    assert all(parse_qs(a['href'][1:])['theme']==['auto'] for a in Links(html).links)


def contrast(a,b):
    def lum(h):
        rgb=[int(h[i:i+2],16)/255 for i in (1,3,5)]
        rgb=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
        return sum(v*w for v,w in zip(rgb,(.2126,.7152,.0722)))
    bright,dark=sorted((lum(a),lum(b)),reverse=True)
    return (bright+.05)/(dark+.05)


@pytest.mark.parametrize('tokens',[design.TAPE_DARK,design.TAPE_LIGHT])
def test_tokens_keep_text_and_gain_loss_readable_on_background_and_cards(tokens):
    for text in ('ink','soft','muted','gain','loss'):
        for surface in ('bg','surface','raised'):
            assert contrast(tokens[text],tokens[surface])>=4.5,(text,surface)


def test_tape_css_safe_area_clearance_font_and_native_controls():
    css=design.theme_css('auto')
    for token in ('#0d1a2c','#14253c','#233855','#f2efe8','#9fb0c8','#4fd6a5','#ff8a7a'):
        assert token in css
    assert 'Familjen+Grotesk' in css and 'tabular-nums' in css
    assert 'position:fixed;bottom:0' in css and 'safe-area-inset-bottom' in css
    assert 'padding-bottom:calc(104px' in css
    for selector in ('stButtonGroup','stButton','stExpander','data-baseweb="select"','aria-pressed','focus-visible','stSelectbox','react-aria-ListBox','stCaptionContainer'):
        assert selector in css


def function(name):
    tree=ast.parse((Path(__file__).resolve().parents[1]/'dashboard.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    return ast.Module(body=[node],type_ignores=[])


def test_theme_callback_synchronizes_store_and_address_so_navigation_and_reload_keep_choice():
    saved={};params={'theme':'dark'}
    st=SimpleNamespace(session_state={'theme':'light'},query_params=params)
    scope={'st':st,'store':SimpleNamespace(set_setting=lambda k,v:saved.update({k:v})),'design':design}
    exec(compile(function('_save_theme'),'dashboard.py','exec'),scope)
    scope['_save_theme']()
    assert saved==params=={'theme':'light'}


def test_sweep_callback_stays_background_only_and_refuses_overlap():
    calls=[]
    scope={'st':SimpleNamespace(session_state=SimpleNamespace()),
           'live':SimpleNamespace(SWEEP_LOCK=SimpleNamespace(locked=lambda:False),sweep='fake-worker'),
           'data':'fake-provider','_in_background':lambda *a,**kw:calls.append((a,kw))}
    exec(compile(function('scan_now'),'dashboard.py','exec'),scope)
    scope['scan_now']()
    assert calls==[(('fake-worker','fake-provider'),{'name':'stockwatch-sweep-now'})]
    scope['live'].SWEEP_LOCK.locked=lambda:True
    scope['scan_now']()
    assert len(calls)==1 and 'already running' in scope['st'].session_state.sweep_note
