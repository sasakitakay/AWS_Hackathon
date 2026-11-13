"""自己完結のHTML(CSS、JS、埋め込みデータ)の生成(FR4、FR5.1、NFR1)。

外部のURL・ライブラリは読み込まない。データはJSONとして <script type="application/json"> に埋め込む。
埋め込むのは許可リストの項目だけ(認証情報を含めない)。同じ入力からは同じHTMLになる。
"""

import json

from .layout import LABEL_FONT, NODE_BOX_H, label_width, short_label

SEVERITY_COLORS = {1: "#f2c200", 2: "#f28c00", 3: "#d62728"}
NO_ALARM_COLOR = "#8fa3b8"


def build_payload(graph, positions):
    """HTMLに埋め込むデータ。許可リスト方式で項目を限定する。"""
    alarm_keys = ("alarmId", "alarmName", "alarmLevel", "occurredAt", "status")
    devices = []
    for d in graph["devices"]:
        x, y = positions[d["id"]]
        devices.append({
            "id": d["id"], "name": d["name"], "type": d["type"], "severity": d["severity"],
            "label": short_label(d["name"]), "isolated": bool(d.get("isolated")),
            "x": x, "y": y,
            "alarms": [dict((k, a[k]) for k in alarm_keys) for a in d["alarms"]],
        })
    edges = [dict((k, e[k]) for k in ("source", "target", "kind", "count", "names")) for e in graph["edges"]]
    unmatched = [dict((k, a[k]) for k in ("alarmId", "alarmName", "alarmLevel", "targetDeviceId",
                                           "occurredAt", "status")) for a in graph["unmatched_alarms"]]
    return {"devices": devices, "edges": edges, "warnings": list(graph["warnings"]),
            "unmatched": unmatched, "summary": dict(graph["summary"]),
            "view": compute_view(devices), "isolated_title": isolated_title(devices)}


def isolated_title(devices):
    """「接続なし」見出しの位置。接続なしの装置が無ければ None。"""
    iso = [d for d in devices if d["isolated"]]
    if not iso:
        return None
    return {"x": round(min(d["x"] for d in iso) - label_width(d_label(iso)) / 2, 1),
            "y": round(min(d["y"] for d in iso) - 40, 1), "count": len(iso)}


def d_label(iso):
    return max((d["label"] for d in iso), key=label_width)


def compute_view(devices):
    """最初の表示範囲(viewBox)。全ての装置とラベルが収まる大きさに、余白を付ける。"""
    if not devices:
        return {"x": 0, "y": 0, "w": 800, "h": 500}
    pad = 40.0
    min_x = min(d["x"] - label_width(d["label"]) / 2 for d in devices) - pad
    max_x = max(d["x"] + label_width(d["label"]) / 2 for d in devices) + pad
    min_y = min(d["y"] for d in devices) - 60.0
    max_y = max(d["y"] for d in devices) + NODE_BOX_H + pad
    return {"x": round(min_x, 1), "y": round(min_y, 1),
            "w": round(max(max_x - min_x, 400.0), 1), "h": round(max(max_y - min_y, 300.0), 1)}


def embed_json(payload):
    """</script> などでHTMLが壊れないよう、< > & を \\uXXXX にして埋め込み用の文字列にする。"""
    text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_html(graph, positions):
    html = _TEMPLATE
    html = html.replace("__COLOR1__", SEVERITY_COLORS[1])
    html = html.replace("__COLOR2__", SEVERITY_COLORS[2])
    html = html.replace("__COLOR3__", SEVERITY_COLORS[3])
    html = html.replace("__COLOR0__", NO_ALARM_COLOR)
    html = html.replace("__LABELFONT__", "%g" % LABEL_FONT)
    html = html.replace("__DATA__", embed_json(build_payload(graph, positions)))
    return html


_TEMPLATE = u"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>NOIM 構成図</title>
<style>
body { margin: 0; font-family: sans-serif; font-size: 14px; color: #222; }
header { padding: 8px 14px; background: #1f2d3d; color: #fff; }
header h1 { margin: 0 0 6px 0; font-size: 18px; }
.chips span, .chips button { display: inline-block; margin: 0 8px 2px 0; padding: 2px 8px; border-radius: 10px; background: #34495e; color: #fff; font: inherit; border: 2px solid transparent; }
.chips button { cursor: pointer; }
.chips button:hover { border-color: #9fb3c8; }
.chips button.on { border-color: #fff; background: #1b6ca8; box-shadow: 0 0 0 1px #fff inset; }
.chips button.off { opacity: 0.55; text-decoration: line-through; }
.chips button:disabled { cursor: default; opacity: 0.5; }
.chips .alarm { background: #b03a2e; }
.chips button.alarm.on { background: #8e2a20; }
.chips .hint { background: none; color: #9fb3c8; font-size: 12px; padding: 0; }
.notes { padding: 6px 14px; }
.notes details { margin: 4px 0; padding: 4px 8px; border-radius: 4px; }
.notes .warn { background: #fff4d6; border: 1px solid #e0b100; }
.notes .unm { background: #fde8e8; border: 1px solid #d62728; }
.notes ul { margin: 4px 0 4px 18px; padding: 0; }
.notes summary { cursor: pointer; font-weight: bold; }
#main { display: flex; height: calc(100vh - 190px); min-height: 480px; }
#graph { flex: 1; background: #f7f9fb; border-top: 1px solid #ccd; cursor: grab; }
#side { width: 340px; overflow: auto; padding: 8px 12px; border-left: 1px solid #ccd; box-sizing: border-box; }
#side h2 { font-size: 15px; margin: 10px 0 4px 0; }
.legend div { margin: 2px 0; }
.dot { display: inline-block; width: 12px; height: 12px; border-radius: 6px; margin-right: 6px; vertical-align: middle; border: 1px solid #556; }
.line { display: inline-block; width: 30px; border-top: 3px solid #667; margin-right: 6px; vertical-align: middle; }
.line.lsp { border-top: 3px dashed #667; }
.alarm-item { margin: 3px 0; padding: 3px 6px; border-left: 4px solid #999; background: #f4f4f4; }
.alarm-item.rec { opacity: 0.45; }
.link { color: #1a5fb4; cursor: pointer; text-decoration: underline; }
.small { color: #556; font-size: 12px; }
text.label { font-size: __LABELFONT__px; fill: #222; pointer-events: none; text-anchor: middle; paint-order: stroke; stroke: #f7f9fb; stroke-width: 3px; }
.node { cursor: pointer; }
text.grouptitle { font-size: 13px; font-weight: bold; fill: #556; }
</style>
</head>
<body>
<header>
<h1>NOIM 構成図</h1>
<div class="chips" id="chips"></div>
</header>
<div class="notes" id="notes"></div>
<div id="main">
<svg id="graph" viewBox="0 0 1200 760" preserveAspectRatio="xMidYMid meet">
<g id="edges"></g>
<g id="nodes"></g>
</svg>
<div id="side">
<div class="legend">
<h2>凡例</h2>
<div><span class="dot" style="background:__COLOR3__"></span>重大度3(重度・発生中)</div>
<div><span class="dot" style="background:__COLOR2__"></span>重大度2(中度・発生中)</div>
<div><span class="dot" style="background:__COLOR1__"></span>重大度1(軽度・発生中)</div>
<div><span class="dot" style="background:__COLOR0__"></span>発生中のアラームなし(復旧済みのみを含む)</div>
<div><span class="line"></span>物理接続(実線)</div>
<div><span class="line lsp"></span>LSP接続(点線)</div>
<div class="small">ドラッグで移動、ホイールで拡大縮小、装置・線のクリックで詳細。上部のボタン: 装置=全体表示に戻す、物理接続・LSP接続=線の表示/非表示、アラーム装置・接続なし=注目、警告=一覧の開閉。</div>
</div>
<div id="detail"></div>
</div>
</div>
<script id="viz-data" type="application/json">__DATA__</script>
<script>
(function () {
  var DATA = JSON.parse(document.getElementById('viz-data').textContent);
  var COLORS = {0: '__COLOR0__', 1: '__COLOR1__', 2: '__COLOR2__', 3: '__COLOR3__'};
  var LEVEL_TEXT = {1: '軽度', 2: '中度', 3: '重度'};
  var KIND_TEXT = {physical: '物理接続', lsp: 'LSP接続'};
  var svg = document.getElementById('graph');
  var NS = svg.namespaceURI;
  var edgesG = document.getElementById('edges');
  var nodesG = document.getElementById('nodes');
  var detail = document.getElementById('detail');
  var byId = {};
  var nodeEls = {};
  var edgeEls = [];
  var selected = null;

  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) { if (attrs.hasOwnProperty(k)) { e.setAttribute(k, attrs[k]); } }
    if (parent) { parent.appendChild(e); }
    return e;
  }
  function h(tag, text, parent, cls) {
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) { e.textContent = text; }
    if (cls) { e.className = cls; }
    if (parent) { parent.appendChild(e); }
    return e;
  }
  function shorten(s, n) { return s.length > n ? s.substring(0, n) + '…' : s; }

  DATA.devices.forEach(function (d) { byId[d.id] = d; });

  // 上部: サマリ(ボタンとして働く)
  var S = DATA.summary;
  var chips = document.getElementById('chips');
  var hiddenKinds = {physical: false, lsp: false};
  var focusMode = null;   // null | 'alarm' | 'isolated'
  var chipEls = {};
  function chip(key, text, cls, onClick, enabled) {
    var b = h('button', text, chips, cls);
    b.setAttribute('type', 'button');
    b.setAttribute('aria-pressed', 'false');
    b.setAttribute('data-chip', key);
    if (!enabled) { b.disabled = true; }
    b.addEventListener('click', function () { if (!b.disabled) { onClick(); } });
    chipEls[key] = {el: b, cls: cls};
    return b;
  }
  function setChip(key, pressed, off) {
    var c = chipEls[key];
    c.el.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    c.el.className = (c.cls ? c.cls + ' ' : '') + (pressed ? 'on' : '') + (off ? ' off' : '');
  }
  function isFocused(d) {
    if (focusMode === 'alarm') { return d.severity > 0; }
    if (focusMode === 'isolated') { return d.isolated; }
    return true;
  }
  function applyState() {
    edgeEls.forEach(function (x) {
      x.path.style.display = hiddenKinds[x.edge.kind] ? 'none' : '';
      var both = isFocused(byId[x.edge.source]) && isFocused(byId[x.edge.target]);
      x.path.style.opacity = (focusMode && !both) ? '0.08' : '';
    });
    DATA.devices.forEach(function (d) {
      nodeEls[d.id].g.style.opacity = isFocused(d) ? '' : '0.15';
    });
    setChip('physical', false, hiddenKinds.physical);
    setChip('lsp', false, hiddenKinds.lsp);
    setChip('alarm', focusMode === 'alarm', false);
    setChip('isolated', focusMode === 'isolated', false);
    setChip('devices', false, false);
  }
  function toggleKind(kind) { hiddenKinds[kind] = !hiddenKinds[kind]; applyState(); }
  function toggleFocus(mode) { focusMode = (focusMode === mode) ? null : mode; applyState(); }
  function resetAll() {
    hiddenKinds = {physical: false, lsp: false};
    focusMode = null;
    vb = {x: INIT.x, y: INIT.y, w: INIT.w, h: INIT.h};
    applyVb();
    select(null);
    showOverview();
    applyState();
  }
  var warnBox = null, unmBox = null;
  function toggleDetails(box) { if (box) { box.open = !box.open; } }

  chip('devices', '装置 ' + S.devices, '', function () { resetAll(); }, true);
  chip('physical', '物理接続 ' + S.physical_edges, '', function () { toggleKind('physical'); }, true);
  chip('lsp', 'LSP接続 ' + S.lsp_edges, '', function () { toggleKind('lsp'); }, true);
  chip('isolated', '接続なし ' + S.isolated_devices, S.isolated_devices > 0 ? 'alarm' : '',
       function () { toggleFocus('isolated'); }, S.isolated_devices > 0);
  chip('alarm', 'アラーム装置 ' + S.alarm_devices + '(重度 ' + S.severity_devices['3'] + ' / 中度 ' +
       S.severity_devices['2'] + ' / 軽度 ' + S.severity_devices['1'] + ')', S.alarm_devices > 0 ? 'alarm' : '',
       function () { toggleFocus('alarm'); }, S.alarm_devices > 0);
  h('span', 'アラーム ' + S.alarms + '(発生中 ' + S.active_alarms + ' / 復旧済み ' + S.recovered_alarms + ')', chips, '');
  chip('unmatched', '対応する装置のないアラーム ' + S.unmatched_alarms, S.unmatched_alarms > 0 ? 'alarm' : '',
       function () { toggleDetails(unmBox); }, S.unmatched_alarms > 0);
  chip('warnings', '警告 ' + S.warnings, '', function () { toggleDetails(warnBox); }, S.warnings > 0);

  // 上部: 警告と、対応する装置のないアラーム
  var notes = document.getElementById('notes');
  if (DATA.warnings.length > 0) {
    var dw = h('details', null, notes, 'warn'); dw.open = true; warnBox = dw;
    h('summary', '警告(' + DATA.warnings.length + '件): 描けなかった接続など', dw);
    var uw = h('ul', null, dw);
    DATA.warnings.forEach(function (w) { h('li', w, uw); });
  }
  if (DATA.unmatched.length > 0) {
    var du = h('details', null, notes, 'unm'); du.open = true; unmBox = du;
    h('summary', '対応する装置のないアラーム(' + DATA.unmatched.length + '件)', du);
    var uu = h('ul', null, du);
    DATA.unmatched.forEach(function (a) {
      h('li', a.alarmId + ' / ' + a.alarmName + ' / 重大度' + a.alarmLevel + ' / ' + a.status +
        ' / 対象: ' + a.targetDeviceId + ' / ' + a.occurredAt, uu);
    });
  }

  // 辺
  function edgePath(e) {
    var a = byId[e.source], b = byId[e.target];
    if (e.kind === 'lsp') {
      var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      var dx = b.x - a.x, dy = b.y - a.y;
      return 'M' + a.x + ' ' + a.y + ' Q' + (mx - dy * 0.15) + ' ' + (my + dx * 0.15) + ' ' + b.x + ' ' + b.y;
    }
    return 'M' + a.x + ' ' + a.y + ' L' + b.x + ' ' + b.y;
  }
  DATA.edges.forEach(function (e) {
    var attrs = {d: edgePath(e), fill: 'none', stroke: e.kind === 'lsp' ? '#7a5fb0' : '#667',
                 'stroke-width': 1.5 + Math.min(e.count, 5) * 0.5, 'stroke-opacity': 0.8, 'class': 'edge'};
    if (e.kind === 'lsp') { attrs['stroke-dasharray'] = '7 5'; }
    var p = el('path', attrs, edgesG);
    var t = el('title', {}, p);
    t.textContent = KIND_TEXT[e.kind] + ' ' + byId[e.source].name + ' - ' + byId[e.target].name + ' (' + e.count + '本)';
    p.style.cursor = 'pointer';
    p.addEventListener('click', function () { showEdge(e); });
    edgeEls.push({edge: e, path: p});
  });

  // 装置
  DATA.devices.forEach(function (d) {
    var g = el('g', {'class': 'node', transform: 'translate(' + d.x + ',' + d.y + ')'}, nodesG);
    var r = d.severity > 0 ? 15 : 10;
    if (d.severity > 0) {
      el('circle', {r: r + 5, fill: 'none', stroke: COLORS[d.severity], 'stroke-width': 3, 'stroke-opacity': 0.45}, g);
    }
    var c = el('circle', {r: r, fill: COLORS[d.severity], stroke: '#2c3e50', 'stroke-width': 1.5}, g);
    var title = el('title', {}, g);
    title.textContent = d.name + '(' + d.type + ')';
    var label = el('text', {'class': 'label', y: r + 13}, g);
    label.textContent = d.label;
    nodeEls[d.id] = {g: g, circle: c};
    enableDrag(g, d);
  });

  function refreshEdges() {
    edgeEls.forEach(function (x) { x.path.setAttribute('d', edgePath(x.edge)); });
  }

  function toSvgPoint(ev) {
    var pt = svg.createSVGPoint();
    pt.x = ev.clientX; pt.y = ev.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }

  function enableDrag(g, d) {
    g.addEventListener('mousedown', function (ev) {
      ev.stopPropagation();
      var start = toSvgPoint(ev), ox = d.x, oy = d.y, moved = false;
      function move(e2) {
        var p = toSvgPoint(e2);
        if (Math.abs(p.x - start.x) + Math.abs(p.y - start.y) > 3) { moved = true; }
        d.x = ox + p.x - start.x; d.y = oy + p.y - start.y;
        g.setAttribute('transform', 'translate(' + d.x + ',' + d.y + ')');
        refreshEdges();
      }
      function up() {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
        if (!moved) { showDevice(d); }
      }
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
    });
  }

  // 拡大縮小・パン(最初の表示は全体が収まる範囲)
  var INIT = DATA.view;
  var vb = {x: INIT.x, y: INIT.y, w: INIT.w, h: INIT.h};
  function applyVb() { svg.setAttribute('viewBox', vb.x + ' ' + vb.y + ' ' + vb.w + ' ' + vb.h); }
  svg.addEventListener('wheel', function (ev) {
    ev.preventDefault();
    var p = toSvgPoint(ev);
    var f = ev.deltaY < 0 ? 0.85 : 1 / 0.85;
    vb.x = p.x - (p.x - vb.x) * f; vb.y = p.y - (p.y - vb.y) * f;
    vb.w *= f; vb.h *= f;
    applyVb();
  }, {passive: false});
  svg.addEventListener('mousedown', function (ev) {
    var start = toSvgPoint(ev), ox = vb.x, oy = vb.y;
    function move(e2) {
      var scale = vb.w / svg.getBoundingClientRect().width;
      vb.x = ox - (e2.clientX - ev.clientX) * scale; vb.y = oy - (e2.clientY - ev.clientY) * scale;
      applyVb();
    }
    function up() { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); }
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  });

  // 詳細パネル
  function alarmItem(a, parent) {
    var it = h('div', null, parent, 'alarm-item' + (a.status === 'recovered' ? ' rec' : ''));
    it.style.borderLeftColor = COLORS[a.alarmLevel];
    h('div', a.alarmName + '(重大度' + a.alarmLevel + ' ' + LEVEL_TEXT[a.alarmLevel] + ')', it);
    h('div', a.alarmId + ' / ' + (a.status === 'active' ? '発生中' : '復旧済み') + ' / ' + a.occurredAt, it, 'small');
  }
  function clear() { while (detail.firstChild) { detail.removeChild(detail.firstChild); } }
  function select(id) {
    if (selected && nodeEls[selected]) { nodeEls[selected].circle.setAttribute('stroke-width', 1.5); }
    selected = id;
    if (id && nodeEls[id]) { nodeEls[id].circle.setAttribute('stroke-width', 4); }
  }
  function deviceLink(id, parent) {
    var a = h('span', byId[id].name, parent, 'link');
    a.addEventListener('click', function () { showDevice(byId[id]); });
  }
  function backLink() {
    var b = h('div', '← アラーム装置の一覧', detail, 'link small');
    b.addEventListener('click', function () { select(null); showOverview(); });
  }
  function showDevice(d) {
    select(d.id);
    clear();
    backLink();
    h('h2', d.name, detail);
    h('div', '種別: ' + d.type, detail);
    h('div', 'ID: ' + d.id, detail, 'small');
    if (d.isolated) { h('div', '接続なし', detail, 'alarm-item'); }
    h('h2', 'アラーム(' + d.alarms.length + '件)', detail);
    if (d.alarms.length === 0) { h('div', 'なし', detail, 'small'); }
    d.alarms.forEach(function (a) { alarmItem(a, detail); });
    h('h2', '接続', detail);
    var any = false;
    DATA.edges.forEach(function (e) {
      if (e.source !== d.id && e.target !== d.id) { return; }
      any = true;
      var other = e.source === d.id ? e.target : e.source;
      var row = h('div', null, detail);
      h('span', KIND_TEXT[e.kind] + ' ' + e.count + '本: ', row, 'small');
      deviceLink(other, row);
      h('div', e.names.join(' / '), row, 'small');
    });
    if (!any) {
      h('div', d.isolated ? '接続なし(この装置につながる物理接続・LSP接続は、NOIM出力にありません)' : 'なし',
        detail, 'small');
    }
  }
  function showEdge(e) {
    select(null);
    clear();
    backLink();
    h('h2', KIND_TEXT[e.kind] + '(' + e.count + '本)', detail);
    var row = h('div', null, detail);
    deviceLink(e.source, row); h('span', ' - ', row); deviceLink(e.target, row);
    h('h2', '接続名', detail);
    e.names.forEach(function (n) { h('div', n, detail, 'small'); });
  }
  function showOverview() {
    clear();
    h('h2', '発生中のアラームがある装置', detail);
    var list = DATA.devices.filter(function (d) { return d.severity > 0; });
    list.sort(function (a, b) { return b.severity - a.severity; });
    if (list.length === 0) { h('div', 'なし', detail, 'small'); }
    list.forEach(function (d) {
      var row = h('div', null, detail);
      h('span', '重大度' + d.severity + ' ', row, 'small');
      deviceLink(d.id, row);
    });
  }
  if (DATA.isolated_title) {
    var gt = el('text', {'class': 'grouptitle', x: DATA.isolated_title.x, y: DATA.isolated_title.y}, nodesG);
    gt.textContent = '接続なし(' + DATA.isolated_title.count + ')';
  }
  applyVb();
  applyState();
  showOverview();
})();
</script>
</body>
</html>
"""
