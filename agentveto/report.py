"""Single-file HTML report.

Deliberate constraints:

- No CDN, no build step, no external assets. The file must render correctly
  when someone double-clicks it on a plane, or when it is attached to a bug
  report six months from now.
- Everything is escaped through textContent. Agent output is untrusted input;
  a prompt that says "</script>" must not break the viewer.
- Read-only viewer. It renders an embedded JSON blob and nothing else.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .store import Store

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agentveto - __RUN_NAME__</title>
<style>
:root{
  --bg:#FAFAF8; --surface:#FFFFFF; --ink:#1F1E1D; --ink2:#5F5E5A; --ink3:#8A8880;
  --line:#E5E3DC; --line2:#D3D1C7;
  --llm:#0F6E56; --tool:#BA7517; --chain:#185FA5; --other:#888780; --error:#A32D2D;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1400px;margin:0 auto;padding:24px 28px 60px}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding-bottom:16px;border-bottom:1px solid var(--line)}
.brand{font-weight:600;letter-spacing:-.02em;font-size:16px}
.brand span{color:var(--ink3);font-weight:400}
.title{font-size:16px;font-weight:500}
.pill{font-size:12px;padding:2px 9px;border-radius:20px;font-weight:500}
.pill.ok{background:#E1F5EE;color:var(--llm)}
.pill.error{background:#FCEBEB;color:var(--error)}
.pill.running{background:#FAEEDA;color:#854F0B}
.stamp{margin-left:auto;font-size:12px;color:var(--ink3)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin:18px 0 20px}
.metric{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.metric .l{font-size:11px;color:var(--ink3);letter-spacing:.03em}
.metric .v{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;line-height:1.3}
.toolbar{display:flex;align-items:center;gap:14px;margin-bottom:10px;flex-wrap:wrap}
.search{flex:1;min-width:200px;max-width:340px;padding:7px 11px;border:1px solid var(--line2);
  border-radius:8px;background:var(--surface);font:inherit;font-size:13px;color:var(--ink)}
.search:focus{outline:2px solid #9FE1CB;outline-offset:-1px;border-color:transparent}
.legend{display:flex;gap:12px;font-size:12px;color:var(--ink3);align-items:center}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.main{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:18px;align-items:start}
@media (max-width:1040px){.main{grid-template-columns:minmax(0,1fr)}}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.panelhead{font-size:11px;letter-spacing:.06em;color:var(--ink3);padding:11px 14px;
  border-bottom:1px solid var(--line);background:#FBFAF7;text-transform:uppercase}
.head{display:grid;grid-template-columns:minmax(0,1fr) 240px 66px 82px;gap:0;
  padding:8px 14px;font-size:11px;color:var(--ink3);border-bottom:1px solid var(--line)}
.head div:not(:first-child){text-align:right}
.row{display:grid;grid-template-columns:minmax(0,1fr) 240px 66px 82px;align-items:center;
  padding:6px 14px;border-bottom:1px solid #F2F0EA;cursor:pointer;position:relative}
.row:hover{background:#FBFAF7}
.row.sel{background:#E1F5EE}
.row.hidden{display:none}
.nm{display:flex;align-items:center;gap:7px;min-width:0}
.kind{font-size:10px;font-weight:600;letter-spacing:.04em;padding:1px 6px;border-radius:4px;flex:none}
.kind.llm{background:#E1F5EE;color:var(--llm)}
.kind.tool{background:#FAEEDA;color:#854F0B}
.kind.chain{background:#E6F1FB;color:var(--chain)}
.kind.span{background:#F1EFE8;color:var(--ink2)}
.txt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
.dur,.cst{font-size:12px;color:var(--ink2);text-align:right;font-variant-numeric:tabular-nums}
.track{position:relative;height:18px;background:#F7F6F3;border-radius:4px;overflow:hidden}
.bar{position:absolute;top:0;height:100%;border-radius:3px;min-width:2px}
.bar.llm{background:var(--llm)}.bar.tool{background:var(--tool)}
.bar.chain{background:var(--chain)}.bar.span{background:var(--other)}
.bar.error{background:var(--error)}
.tag{font-size:10px;color:var(--chain);border:1px solid #B5D4F4;border-radius:3px;padding:0 4px;flex:none}
.tag.veto{color:#6D28D9;border-color:#C9B8F5;background:#F3EEFD}
.err{font-size:10px;color:var(--error);border:1px solid #F7C1C1;border-radius:3px;padding:0 4px;flex:none}
.detail{padding:14px 16px;font-size:13px}
.detail h3{font-size:14px;font-weight:600;margin-bottom:3px;word-break:break-word}
.kv{display:grid;grid-template-columns:78px 1fr;gap:4px 10px;margin:12px 0;font-size:12.5px}
.kv dt{color:var(--ink3)}
.kv dd{font-variant-numeric:tabular-nums;word-break:break-word}
.sect{margin-top:14px}
.sect .h{font-size:11px;letter-spacing:.06em;color:var(--ink3);margin-bottom:5px;text-transform:uppercase}
pre{background:#F7F6F3;border:1px solid var(--line);border-radius:8px;padding:10px 12px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;line-height:1.6;
  max-height:280px;overflow:auto;white-space:pre-wrap;word-break:break-word}
pre.errbox{background:#FCEBEB;border-color:#F5CFCF;color:var(--error)}
.empty{padding:40px 16px;text-align:center;color:var(--ink3);font-size:13px}
footer{margin-top:26px;font-size:12px;color:var(--ink3);text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">agentveto <span>runtime control</span></div>
    <div class="title" id="title"></div>
    <div class="pill" id="status"></div>
    <div class="stamp" id="stamp"></div>
  </header>

  <div class="metrics" id="metrics"></div>

  <div class="main">
    <div>
      <div class="toolbar">
        <input class="search" id="q" placeholder="Filter steps...">
        <div class="legend">
          <span><i style="background:var(--llm)"></i>llm</span>
          <span><i style="background:var(--tool)"></i>tool</span>
          <span><i style="background:var(--chain)"></i>chain</span>
          <span><i style="background:var(--error)"></i>error</span>
        </div>
      </div>
      <div class="panel">
        <div class="head"><div>Step</div><div>Timeline</div><div>Duration</div><div>Cost</div></div>
        <div id="rows"></div>
      </div>
    </div>
    <div class="panel"><div class="panelhead">Step detail</div><div class="detail" id="detail"></div></div>
  </div>

  <footer>Generated by agentveto &middot; self-contained, works offline</footer>
</div>

<script id="tl-data" type="application/json">__DATA__</script>
<script>
(function(){
  var D = JSON.parse(document.getElementById('tl-data').textContent);
  var spans = D.spans || [], run = D.run || {};
  var byId = {};
  spans.forEach(function(s){ byId[s.id] = s; });

  function depth(s){
    var d = 0, cur = s, guard = 0;
    while (cur && cur.parent_id && byId[cur.parent_id] && guard++ < 100){ d++; cur = byId[cur.parent_id]; }
    return d;
  }
  function fmtDur(ms){
    if (ms == null) return '-';
    if (ms < 1000) return Math.round(ms) + ' ms';
    return (ms/1000).toFixed(2) + ' s';
  }
  function fmtCost(c){
    if (c == null) return '-';
    if (c === 0) return '$0';
    return c < 0.01 ? '$' + c.toFixed(5) : '$' + c.toFixed(4);
  }
  function fmtNum(n){ return (n==null? '-' : String(n).replace(/\\B(?=(\\d{3})+(?!\\d))/g, ',')); }
  function el(tag, cls, text){
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function pretty(raw){
    if (!raw) return '';
    try { return JSON.stringify(JSON.parse(raw), null, 2); } catch (e) { return String(raw); }
  }

  var total = 0;
  spans.forEach(function(s){
    s._depth = depth(s);
    total = Math.max(total, (s.offset_ms||0) + (s.duration_ms||0));
  });
  if (!total) total = 1;

  var llmCalls = 0, replayed = 0, errors = 0, toolCalls = 0;
  spans.forEach(function(s){
    if (s.kind === 'llm') llmCalls++;
    if (s.kind === 'tool') toolCalls++;
    if (s.replayed) replayed++;
    if (s.status === 'error') errors++;
  });

  document.getElementById('title').textContent = run.name || 'run';
  var st = document.getElementById('status');
  st.textContent = run.status || 'unknown';
  st.className = 'pill ' + (run.status === 'error' ? 'error' : (run.status === 'running' ? 'running' : 'ok'));
  document.getElementById('stamp').textContent = run.finished ? new Date(run.finished*1000).toLocaleString() : '';

  var mx = [
    ['Duration', fmtDur(run.duration_ms)],
    ['Steps', String(spans.length)],
    ['LLM calls', String(llmCalls)],
    ['Tool calls', String(toolCalls)],
    ['Tokens in', fmtNum(run.tokens_in)],
    ['Tokens out', fmtNum(run.tokens_out)],
    ['Cost', fmtCost(run.total_cost)],
    ['Errors', String(errors)]
  ];
  if (replayed) mx.push(['Replayed', String(replayed)]);
  var mw = document.getElementById('metrics');
  mx.forEach(function(p){
    var m = el('div','metric');
    m.appendChild(el('div','l',p[0]));
    m.appendChild(el('div','v',p[1]));
    mw.appendChild(m);
  });

  var rowsEl = document.getElementById('rows');
  var selected = null;

  function renderDetail(s){
    var box = document.getElementById('detail');
    box.innerHTML = '';
    if (!s){ box.appendChild(el('div','empty','Select a step to inspect its input and output.')); return; }
    box.appendChild(el('h3', null, s.name));
    var dl = el('dl','kv');
    function pair(k,v){ dl.appendChild(el('dt',null,k)); dl.appendChild(el('dd',null,v)); }
    pair('Kind', s.kind);
    pair('Status', s.status);
    if (s.model) pair('Model', s.model);
    pair('Duration', fmtDur(s.duration_ms));
    if (s.kind === 'llm'){
      pair('Tokens', fmtNum(s.tokens_in) + ' in / ' + fmtNum(s.tokens_out) + ' out');
      pair('Cost', fmtCost(s.cost) + (s.pricing_known ? '' : ' (unknown model)'));
      if (s.replayed) pair('Source', 'replayed from recording');
    }
    var vd = null;
    try { if (s.attributes){ var _b = JSON.parse(s.attributes); if (_b && _b.veto) vd = _b.veto; } } catch (e) {}
    var attrs = pretty(s.attributes);
    if (attrs && attrs !== '{}') pair('Attributes', attrs);
    if (vd){
      pair('Veto', (vd.effect === 'deny' ? 'DENIED' : 'allowed') +
           (vd.asked ? ' (required human approval)' : '') +
           (vd.rule ? ' - rule: ' + vd.rule : '') +
           (vd.reason ? ' - ' + vd.reason : ''));
    }
    box.appendChild(dl);

    if (s.error){
      var es = el('div','sect'); es.appendChild(el('div','h','Error'));
      var ep = el('pre','errbox', s.error); es.appendChild(ep); box.appendChild(es);
    }
    [['Input', s.input], ['Output', s.output]].forEach(function(p){
      if (!p[1]) return;
      var sec = el('div','sect');
      sec.appendChild(el('div','h',p[0]));
      sec.appendChild(el('pre', null, pretty(p[1])));
      box.appendChild(sec);
    });
  }

  function select(id){
    if (selected){ var prev = rowsEl.querySelector('[data-id="' + selected + '"]'); if (prev) prev.className = 'row'; }
    selected = id;
    var row = rowsEl.querySelector('[data-id="' + id + '"]');
    if (row) row.className = 'row sel';
    renderDetail(byId[id]);
  }

  spans.forEach(function(s){
    var v = null;
    try { if (s.attributes){ var _a = JSON.parse(s.attributes); if (_a && _a.veto) v = _a.veto; } } catch (e) {}
    var row = el('div','row');
    row.setAttribute('data-id', s.id);
    row.style.paddingLeft = (14 + s._depth * 14) + 'px';

    var nm = el('div','nm');
    nm.appendChild(el('span','kind ' + s.kind, s.kind));
    nm.appendChild(el('span','txt', s.name));
    if (v && v.effect === 'deny') nm.appendChild(el('span','tag veto','veto'));
    if (s.replayed) nm.appendChild(el('span','tag','replay'));
    if (s.status === 'error') nm.appendChild(el('span','err','error'));
    row.appendChild(nm);

    var track = el('div','track');
    var bar = el('div','bar ' + (s.status === 'error' ? 'error' : s.kind));
    bar.style.left = ((s.offset_ms||0) / total * 100) + '%';
    bar.style.width = Math.max(((s.duration_ms||0) / total * 100), 0.4) + '%';
    track.appendChild(bar);
    row.appendChild(track);

    row.appendChild(el('div','dur', fmtDur(s.duration_ms)));
    row.appendChild(el('div','cst', s.kind === 'llm' ? fmtCost(s.cost) : ''));

    row.addEventListener('click', function(){ select(s.id); });
    rowsEl.appendChild(row);
  });

  document.getElementById('q').addEventListener('input', function(e){
    var q = e.target.value.trim().toLowerCase();
    spans.forEach(function(s){
      var row = rowsEl.querySelector('[data-id="' + s.id + '"]');
      if (!row) return;
      var hit = !q || s.name.toLowerCase().indexOf(q) >= 0 || (s.model && s.model.toLowerCase().indexOf(q) >= 0);
      row.style.display = hit ? '' : 'none';
    });
  });

  document.addEventListener('keydown', function(e){
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if (document.activeElement === document.getElementById('q')) return;
    var idx = selected ? spans.findIndex(function(s){ return s.id === selected; }) : -1;
    idx = e.key === 'ArrowDown' ? Math.min(idx + 1, spans.length - 1) : Math.max(idx - 1, 0);
    if (spans[idx]) { select(spans[idx].id); e.preventDefault(); }
  });

  if (spans.length) select(spans[0].id); else renderDetail(null);
})();
</script>
</body>
</html>
"""


def build_report_data(store: Store, run_id: str) -> dict | None:
    run = store.get_run(run_id)
    if not run:
        return None
    spans = store.get_spans(run_id)
    start = run["started_at"]
    end = run.get("ended_at") or (spans[-1]["ended_at"] if spans and spans[-1]["ended_at"] else start)
    out = []
    for s in spans:
        s = dict(s)
        s["offset_ms"] = (s["started_at"] - start) * 1000.0
        out.append(s)
    return {
        "run": {
            "id": run["id"],
            "name": run["name"],
            "status": run["status"],
            "started_at": start,
            "finished": end,
            "duration_ms": (end - start) * 1000.0,
            "total_cost": run["total_cost"],
            "tokens_in": run["tokens_in"],
            "tokens_out": run["tokens_out"],
            "span_count": run["span_count"],
        },
        "spans": out,
    }


def render_html(data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    name = (data.get("run") or {}).get("name") or "run"
    safe_name = name.replace("<", "&lt;").replace(">", "&gt;")
    return TEMPLATE.replace("__DATA__", blob).replace("__RUN_NAME__", safe_name)


def report(
    run_id: str | None = None,
    out: str | None = None,
    *,
    db: str | None = None,
    store: Store | None = None,
) -> str:
    """Write a self-contained HTML report for a run. Returns the file path."""
    store = store or Store(db)
    if run_id is None:
        latest = store.latest_run()
        if not latest:
            raise SystemExit("No runs recorded yet. Run your agent with agentveto.init() first.")
        run_id = latest["id"]
    data = build_report_data(store, run_id)
    if data is None:
        raise SystemExit(f"No run found with id {run_id!r}")

    if out is None:
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in (data["run"]["name"] or "run")).lower()
        out = os.path.abspath(f"agentveto-{safe[:40]}.html")
    out = os.path.abspath(out)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(data))
    return out
