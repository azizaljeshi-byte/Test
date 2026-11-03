"""Offline rendering and queue-only integration. No key, provider or AI is needed."""
import ast
import copy
from html.parser import HTMLParser
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from stockwatch import ask_ai, ask_ai_view as view
from test_ask_ai import FakeStore


class Text(HTMLParser):
    def __init__(self, markup):
        super().__init__(); self.parts=[]; self.skip=False
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag=='style':self.skip=True

    def handle_endtag(self, tag):
        if tag=='style':self.skip=False

    def handle_data(self, data):
        if not self.skip:self.parts.append(data)

    @property
    def text(self):
        return ' '.join(self.parts)


def row(call='BUY', p60=None, close=None, **changes):
    return {**ask_ai.sample_verdict(), 'verdict':call, 'scored':{'plus60':p60,'close':close}, **changes}


@pytest.mark.parametrize('call,color',[('BUY','#3dffa8'),('HOLD','#ffb020'),('SELL','#ff697b'),('AVOID','#ff697b')])
def test_each_verdict_has_its_color_changes_confidence_and_no_trade_footer(call,color):
    h=view.html(row(call))
    text=Text(h).text
    assert f'style="--call:{color}"' in h
    assert call in text and 'What would change it' in text and 'Confidence: 2 of 5' in text
    assert 'places no trade' in text and 'scored at +60 min and at the close' in text
    assert '03 Nov 07:58 NY' in text


def test_unknowns_stay_unknown_and_levels_stay_sorted_with_equal_spacing():
    v=row(price=None)
    v['levels']=[{'label':'Low','price':4,'kind':'support'}, {'label':'Missing','price':None,'kind':'resistance'},
                 {'label':'High','price':10,'kind':'exit_line'}, {'label':'Same','price':10,'kind':'price'}]
    v['facts']=[{'label':'Missing fact','value':None,'tone':'bad'},{'label':'Real zero','value':0,'tone':'neutral'}]
    h=view.html(v);t=Text(h).text
    assert 'unknown' in t and 'Missing fact unknown' in t and 'Real zero 0' in t
    assert h.index('<span>High</span>') < h.index('<span>Price · last close</span>') < h.index('<span>Low</span>') < h.index('<span>Missing</span>')
    assert 'aiv-level exit' in h and 'aiv-level support' in h and 'aiv-level price' in h
    assert 'top:' not in h[h.index('<section'):]


def test_unasked_asking_failed_and_invalid_verdict_never_show_sample_advice():
    assert 'Not asked yet' in view.html(None)
    assert 'Asking…' in view.html(row(status='asking'))
    h=view.html(row(status='failed',error='<script>failed</script>'))
    assert '&lt;script&gt;failed&lt;/script&gt;' in h and '<script>' not in h
    assert 'What would change it' not in Text(h).text
    assert 'No valid verdict' in view.html(row(call='MAYBE'))


def test_ai_text_and_metadata_cannot_inject_html_css_or_script():
    v=row(ticker='<img src=x onerror=alert(1)>',headline='<script>x</script>',name='<b>Name</b>')
    v['levels']=[{'label':'<img onerror=x>','price':100,'kind':'price" onclick="x'}]
    v['facts']=[{'label':'<svg onload=x>','value':'<script>fact</script>','tone':'bad" onclick="x'}]
    h=view.html(v)
    assert '<script>' not in h and '<img ' not in h and '<svg ' not in h
    assert '&lt;script&gt;x&lt;/script&gt;' in h and 'aiv-level resistance' in h
    assert 'class="aiv-bad" onclick' not in h
    assert '<script>' not in view.history_html([v])


def test_history_uses_only_ready_real_scored_calls_and_the_correct_denominators():
    rows=[row('BUY',2.0),row('BUY',-1),row('BUY',None),row('AVOID',-3),row('HOLD',4),
          row('BUY',99,status='failed'),row('AVOID',-99,status='asking'),row('BUY',99,demo=True)]
    t=Text(view.history_html(rows)).text
    assert '5 AI verdicts' in t and '50% BUY rose' in t and '100% AVOID fell' in t
    assert '+2.00%' in t and '-1.00%' in t and '+99.00%' in t  # synthetic row visible but excluded from statistics
    assert 'Synthetic demo rows are excluded' in t and 'Asking…' not in t and 'Failed' in t
    t=Text(view.history_html([row('BUY',0.0),row('AVOID',0.0)])).text
    assert '0% BUY rose' in t and '0% AVOID fell' in t  # an actual flat scored return isn't unknown


def test_empty_or_unscored_history_has_no_made_up_zero_percent():
    for rows in ([],[row()],[row('AVOID')]):
        t=Text(view.history_html(rows)).text
        assert '— BUY rose' in t and '— AVOID fell' in t and '0%' not in t
    assert 'No verdicts saved yet' in Text(view.history_html([])).text


def test_rendering_is_pure_and_handles_nonfinite_price_and_score():
    v=row(price=float('nan'),p60=float('inf'));before=copy.deepcopy(v)
    assert 'unknown' in Text(view.html(v)).text
    assert '— BUY rose' in Text(view.history_html([v])).text
    assert v['levels']==before['levels']
    tree=ast.parse(Path(view.__file__).read_text())
    names={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
    assert not names&{'streamlit','requests','urllib','ask_ai','store','agent','quick','paper_newcall'}


class State(dict):
    def __getattr__(self,name):return self[name]
    def __setattr__(self,name,value):self[name]=value


def callbacks(store, demo):
    source=(Path(__file__).resolve().parents[1]/'dashboard.py').read_text()
    tree=ast.parse(source)
    keep=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_ai_submit','_ai_candidate_selected')]
    st=SimpleNamespace(session_state=State(ai_ticker='isrg',ai_candidate=''))
    scope={'st':st,'store':store,'ask_ai':ask_ai,'base':SimpleNamespace(settings=SimpleNamespace(data_provider='demo' if demo else 'yahoo')),
           'selected_provider':lambda s:s,'re':re}
    exec(compile(ast.Module(body=keep,type_ignores=[]),'dashboard.py','exec'),scope)
    return st,scope


def test_page_callback_only_queues_and_demo_only_saves_a_marked_sample(monkeypatch):
    monkeypatch.setattr(ask_ai,'ask',lambda *a,**k:pytest.fail('inline AI call'))
    s=FakeStore();st,scope=callbacks(s,False)
    scope['_ai_submit']()
    assert ask_ai.latest(s,'ISRG')['status']=='asking'
    assert ask_ai._queue(s)==['ISRG']
    monkeypatch.setattr(ask_ai,'request',lambda *a,**k:pytest.fail('demo queued AI'))
    s=FakeStore();st,scope=callbacks(s,True)
    scope['_ai_submit']()
    assert ask_ai.latest(s,'ISRG')['demo'] and not ask_ai._queue(s)


def test_candidate_selection_does_not_ask_and_invalid_input_does_not_queue():
    s=FakeStore();st,scope=callbacks(s,False)
    st.session_state.ai_candidate='MSFT';scope['_ai_candidate_selected']()
    assert st.session_state.ai_ticker=='MSFT' and not ask_ai._queue(s)
    st.session_state.ai_ticker='<script>';scope['_ai_submit']()
    assert not ask_ai._queue(s) and 'Enter a ticker' in st.session_state.ai_note


@pytest.mark.parametrize("render", [lambda v, **kw: view.html(v, **kw),
                                  lambda v, **kw: view.history_html([v], **kw)])
def test_ticker_links_escape_text_and_encode_query_and_respect_tracking(render):
    ticker = 'FICT&<"/#'
    h = render(row(ticker=ticker), tracked={ticker})
    assert 'href="?view=target&amp;t=FICT%26%3C%22%2F%23" target="_self"' in h
    assert 'FICT&amp;&lt;&quot;/#</a>' in h
    assert '<a href=' not in render(row(ticker=ticker), tracked=set())
    assert '<a href=' not in render(row(ticker=None))


@pytest.mark.parametrize("stamp, expected", [
    ("2026-11-03T02:46:00-05:00", "03 Nov 02:46 NY"),
    ("2026-11-03T07:46:00Z", "03 Nov 02:46 NY"),
    ("2026-07-03T07:46:00+00:00", "03 Jul 03:46 NY"),
    ("2026-11-03T02:46:00", "03 Nov 02:46 (time zone unknown)"),
    (None, "unknown time"), ("invalid", "invalid"),
])
def test_saved_time_is_new_york_in_card_and_history(stamp, expected):
    v = row(asked_at=stamp)
    assert "Saved " + expected in Text(view.html(v)).text
    assert expected in Text(view.history_html([v])).text


@pytest.mark.parametrize('previous, expected', [(None, None), ({'verdict':'HOLD'}, 'HOLD → BUY'),
                                              ({'verdict':'BUY'}, 'BUY → BUY'), ({'verdict':None}, 'unknown → BUY')])
def test_previous_change_and_recheck_tag_in_card_and_history(previous, expected):
    v = row(previous=previous, recheck=True)
    for markup in (view.html(v), view.history_html([v])):
        text = Text(markup).text
        assert 're-check at the open' in text
        if expected:
            assert expected in text
        else:
            assert '→' not in text
    assert 're-check at the open' not in Text(view.html(row(previous=previous))).text
    assert 're-check at the open' not in Text(view.history_html([row(previous=previous)])).text


def test_previous_text_is_escaped_and_unknown_confidence_remains_unknown():
    v = row(previous={'verdict':'<script>x</script>', 'confidence':None, 'price':None, 'asked_at':None},
            confidence=None, price=None, recheck=True)
    for markup in (view.html(v), view.history_html([v])):
        assert '<script>' not in markup and '&lt;script&gt;' in markup
    assert 'Confidence: unknown' in Text(view.html(v)).text
    assert 'unknown' in Text(view.html(v)).text


def test_history_native_re_evaluate_buttons_queue_their_own_stock_and_disable_per_stock(monkeypatch):
    store = FakeStore()
    for ticker in ('FICTA', 'FICTA', 'FICTB'):
        ask_ai.save(store, row(ticker=ticker, demo=False))
    ask_ai.request(store, 'FICTB')
    store.latest_snapshots = lambda: [{'ticker':'FICTA'}, {'ticker':'FICTB'}]
    st, scope = callbacks(store, False)
    buttons = []
    class Container:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def text(self, value): pass
        def button(self, label, **kw): buttons.append((label, kw))
    st.container = lambda **kw: Container()
    st.columns = lambda widths: (Container(), Container())
    st.markdown = lambda *a, **kw: None
    st.caption = lambda *a: None
    st.button = lambda *a, **kw: None
    tree = ast.parse((Path(__file__).resolve().parents[1]/'dashboard.py').read_text())
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_ai_answer')
    func.decorator_list = []
    scope['ask_ai_view'] = view
    exec(compile(ast.Module(body=[func], type_ignores=[]), 'dashboard.py', 'exec'), scope)
    scope['_ai_answer']('FICTA')
    by_ticker = {kw['args'][0]:kw for label,kw in buttons if label == 'Re-evaluate'}
    assert len(buttons) == len(by_ticker) == 2
    assert not by_ticker['FICTA']['disabled'] and by_ticker['FICTB']['disabled']
    monkeypatch.setattr(ask_ai, 'ask', lambda *a, **kw: pytest.fail('inline AI call'))
    action = by_ticker['FICTA']
    action['on_click'](*action['args'])
    assert ask_ai.latest(store, 'FICTA')['status'] == 'asking'
    assert ask_ai._queue(store) == ['FICTB', 'FICTA']
    scope['_ai_answer']('FICTA')
    assert all(kw['disabled'] for _,kw in buttons[-2:])
    # A stale second click also returns without another request.
    monkeypatch.setattr(ask_ai, 'request', lambda *a, **kw: pytest.fail('duplicate request while asking'))
    action['on_click'](*action['args'])
