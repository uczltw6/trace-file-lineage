"""Self-contained CSS and JavaScript for the local HTML explorer.

Kept as plain strings rather than f-strings so the JavaScript stays readable and
needs no brace escaping. `render_html` injects the projected graph separately.
No external stylesheet, font, script, or network request is used.
"""

from __future__ import annotations

EXPLORER_CSS = """
:root {
  color-scheme: light dark;
  --bg: #fbfbfd;
  --panel: #ffffff;
  --ink: #14161a;
  --muted: #5c6370;
  --line: #d9dce3;
  --captured: #1f7a4d;
  --inferred: #8a8f9a;
  --accent: #2f6feb;
  --verified: #1f7a4d;
  --strong: #2f6feb;
  --candidate: #b8791b;
  --weak: #9aa0ab;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a;
    --panel: #1b1e24;
    --ink: #e8eaed;
    --muted: #9aa0ab;
    --line: #2e333c;
    --captured: #4ec98a;
    --inferred: #6b7280;
    --accent: #6aa2ff;
    --verified: #4ec98a;
    --strong: #6aa2ff;
    --candidate: #e0a94a;
    --weak: #6b7280;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
header {
  display: flex;
  flex-wrap: wrap;
  gap: .6rem;
  align-items: center;
  padding: .7rem 1rem;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}
h1 { font-size: 15px; margin: 0 .8rem 0 0; font-weight: 650; letter-spacing: -.01em; }
label { display: inline-flex; align-items: center; gap: .35rem; color: var(--muted); font-size: 12px; }
input, select, button {
  font: inherit;
  font-size: 13px;
  padding: .3rem .45rem;
  color: var(--ink);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 6px;
}
input:focus-visible, select:focus-visible, button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
button { cursor: pointer; }
button[aria-pressed="true"] { background: var(--accent); color: #fff; border-color: var(--accent); }
#layout { display: flex; height: calc(100vh - 53px); }
#stage { position: relative; flex: 1; min-width: 0; }
svg { width: 100%; height: 100%; display: block; touch-action: none; cursor: grab; }
svg.dragging { cursor: grabbing; }
.edge { stroke: var(--inferred); stroke-width: 1.1; stroke-dasharray: 4 3; fill: none; }
.edge.captured { stroke: var(--captured); stroke-width: 1.8; stroke-dasharray: none; }
.edge.dim { stroke-opacity: .12; }
.node circle { stroke: var(--panel); stroke-width: 1.5; cursor: pointer; }
.node text {
  font-size: 10px;
  fill: var(--muted);
  pointer-events: none;
  paint-order: stroke;
  stroke: var(--bg);
  stroke-width: 3px;
}
.node.dim { opacity: .2; }
.node.selected circle { stroke: var(--accent); stroke-width: 3; }
.node.selected text { fill: var(--ink); font-weight: 650; }
#side {
  width: 340px;
  flex: 0 0 340px;
  border-left: 1px solid var(--line);
  background: var(--panel);
  overflow-y: auto;
  padding: 1rem;
}
#side h2 { font-size: 13px; margin: 0 0 .5rem; }
#side p { color: var(--muted); font-size: 12px; margin: .3rem 0; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; overflow-wrap: anywhere; }
.pill {
  display: inline-block;
  padding: .05rem .4rem;
  border-radius: 999px;
  font-size: 11px;
  border: 1px solid var(--line);
  color: var(--muted);
}
.rel { border-top: 1px solid var(--line); padding: .5rem 0; }
.rel .arrow { color: var(--muted); font-size: 11px; }
details summary { cursor: pointer; color: var(--muted); font-size: 12px; }
details pre {
  white-space: pre-wrap;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: .4rem;
  font-size: 11px;
  margin: .35rem 0 0;
}
#legend {
  position: absolute;
  left: .75rem;
  bottom: .75rem;
  background: color-mix(in srgb, var(--panel) 88%, transparent);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: .5rem .6rem;
  font-size: 11px;
  color: var(--muted);
}
#legend div { display: flex; align-items: center; gap: .4rem; }
#legend .swatch { width: 22px; height: 0; border-top: 2px solid var(--inferred); border-top-style: dashed; }
#legend .swatch.captured { border-top: 2px solid var(--captured); border-top-style: solid; }
#status { padding: .4rem 1rem; font-size: 12px; color: var(--muted); border-top: 1px solid var(--line); background: var(--panel); }
#status .warn { color: var(--candidate); }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: .4rem; border-bottom: 1px solid var(--line); font-size: 12px; vertical-align: top; }
th { position: sticky; top: 0; background: var(--panel); }
tr.captured td:nth-child(2) { color: var(--captured); font-weight: 650; }
#table-view { display: none; overflow: auto; height: 100%; padding: 0 1rem 1rem; }
body.table-mode #stage { display: none; }
body.table-mode #table-view { display: block; }
.visually-hidden {
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap;
}
"""


EXPLORER_JS = """
'use strict';
const DATA = JSON.parse(document.getElementById('lineage-data').textContent);
const SVG_NS = 'http://www.w3.org/2000/svg';
const KIND_COLOR = {
  code: '#6aa2ff', notebook: '#a78bfa', data: '#4ec98a', image: '#e0a94a',
  document: '#f0776c', config: '#5ec8d8', activity: '#c0c4cc'
};
const ASSURANCE_MIN = { verified: 1, 'strong-candidate': 0.8, candidate: 0.55, 'weak-signal': 0.3 };

const nodes = DATA.nodes.map((n, i) => {
  const angle = (i / Math.max(1, DATA.nodes.length)) * Math.PI * 2;
  const radius = 120 + 260 * Math.sqrt(i / Math.max(1, DATA.nodes.length));
  return Object.assign({}, n, {
    x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, vx: 0, vy: 0, degree: 0
  });
});
const byId = new Map(nodes.map(n => [n.id, n]));
const edges = [];
for (const e of DATA.edges) {
  const source = byId.get(e.source_id);
  const target = byId.get(e.target_id);
  if (!source || !target) continue;
  source.degree += 1;
  target.degree += 1;
  edges.push(Object.assign({}, e, { source, target }));
}

const svg = document.getElementById('graph');
const viewport = document.getElementById('viewport');
const edgeLayer = document.getElementById('edges');
const nodeLayer = document.getElementById('nodes');
const side = document.getElementById('side');
const status = document.getElementById('status');
const searchBox = document.getElementById('search');
const relationBox = document.getElementById('relation');
const assuranceBox = document.getElementById('assurance');

[...new Set(edges.map(e => e.relation))].sort()
  .forEach(v => relationBox.add(new Option(v, v)));

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}
function nodeRadius(node) { return 4 + Math.min(7, Math.sqrt(node.degree) * 2); }
function nodeColor(node) { return KIND_COLOR[node.kind] || '#9aa0ab'; }
function shortLabel(node) {
  const name = node.label || node.path || '?';
  return name.length > 26 ? name.slice(0, 25) + '…' : name;
}

/* ---------- rendering ---------- */
const edgeEls = edges.map(edge => {
  const line = document.createElementNS(SVG_NS, 'line');
  line.setAttribute('class', 'edge' + (edge.mode === 'captured' ? ' captured' : ''));
  edgeLayer.appendChild(line);
  return line;
});
const nodeEls = nodes.map(node => {
  const group = document.createElementNS(SVG_NS, 'g');
  group.setAttribute('class', 'node');
  group.setAttribute('tabindex', '0');
  group.setAttribute('role', 'button');
  group.setAttribute('aria-label', (node.path || node.label) + ' (' + node.kind + ')');
  const circle = document.createElementNS(SVG_NS, 'circle');
  circle.setAttribute('r', String(nodeRadius(node)));
  circle.setAttribute('fill', nodeColor(node));
  const text = document.createElementNS(SVG_NS, 'text');
  text.setAttribute('x', String(nodeRadius(node) + 4));
  text.setAttribute('y', '3');
  text.textContent = shortLabel(node);
  group.append(circle, text);
  group.addEventListener('pointerdown', event => startNodeDrag(event, node));
  group.addEventListener('click', () => select(node));
  group.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(node); }
  });
  nodeLayer.appendChild(group);
  return group;
});

function draw() {
  for (let i = 0; i < edges.length; i += 1) {
    const el = edgeEls[i];
    const edge = edges[i];
    el.setAttribute('x1', edge.source.x.toFixed(1));
    el.setAttribute('y1', edge.source.y.toFixed(1));
    el.setAttribute('x2', edge.target.x.toFixed(1));
    el.setAttribute('y2', edge.target.y.toFixed(1));
  }
  for (let i = 0; i < nodes.length; i += 1) {
    nodeEls[i].setAttribute('transform',
      'translate(' + nodes[i].x.toFixed(1) + ',' + nodes[i].y.toFixed(1) + ')');
  }
}

/* ---------- force simulation ----------
   Repulsion uses a uniform grid so only nearby pairs interact. That keeps the
   cost near linear instead of the O(n^2) an all-pairs loop would cost at the
   explorer's node budget. */
const CELL = 60;
const REPULSION = 2600;
const SPRING = 0.0016;
const CENTER_PULL = 0.0012;
let alpha = 1;

function tick() {
  const grid = new Map();
  for (const node of nodes) {
    const key = Math.round(node.x / CELL) + ':' + Math.round(node.y / CELL);
    if (!grid.has(key)) grid.set(key, []);
    grid.get(key).push(node);
  }
  for (const node of nodes) {
    const cx = Math.round(node.x / CELL);
    const cy = Math.round(node.y / CELL);
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        const bucket = grid.get((cx + dx) + ':' + (cy + dy));
        if (!bucket) continue;
        for (const other of bucket) {
          if (other === node) continue;
          let ox = node.x - other.x;
          let oy = node.y - other.y;
          let distanceSquared = ox * ox + oy * oy;
          if (distanceSquared < 0.01) { ox = (Math.random() - 0.5) * 2; oy = (Math.random() - 0.5) * 2; distanceSquared = 4; }
          if (distanceSquared > CELL * CELL * 4) continue;
          const force = REPULSION / distanceSquared;
          const distance = Math.sqrt(distanceSquared);
          node.vx += (ox / distance) * force * alpha;
          node.vy += (oy / distance) * force * alpha;
        }
      }
    }
    node.vx -= node.x * CENTER_PULL;
    node.vy -= node.y * CENTER_PULL;
  }
  for (const edge of edges) {
    const dx = edge.target.x - edge.source.x;
    const dy = edge.target.y - edge.source.y;
    const distance = Math.sqrt(dx * dx + dy * dy) || 1;
    const pull = (distance - 90) * SPRING * alpha;
    const fx = (dx / distance) * pull * distance;
    const fy = (dy / distance) * pull * distance;
    edge.source.vx += fx; edge.source.vy += fy;
    edge.target.vx -= fx; edge.target.vy -= fy;
  }
  for (const node of nodes) {
    if (node.pinned) { node.vx = 0; node.vy = 0; continue; }
    node.vx *= 0.82; node.vy *= 0.82;
    node.x += Math.max(-30, Math.min(30, node.vx));
    node.y += Math.max(-30, Math.min(30, node.vy));
  }
  alpha *= 0.985;
}

let frame = null;
function animate() {
  tick();
  draw();
  if (alpha > 0.02) frame = requestAnimationFrame(animate);
  else frame = null;
}
function reheat(value) {
  alpha = Math.max(alpha, value);
  if (!frame) frame = requestAnimationFrame(animate);
}

/* ---------- pan, zoom, drag ---------- */
let view = { x: 0, y: 0, k: 1 };
function applyView() {
  viewport.setAttribute('transform',
    'translate(' + view.x + ',' + view.y + ') scale(' + view.k + ')');
}
function resetView() {
  const rect = svg.getBoundingClientRect();
  view = { x: rect.width / 2, y: rect.height / 2, k: 1 };
  applyView();
}
svg.addEventListener('wheel', event => {
  event.preventDefault();
  const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
  const next = Math.max(0.15, Math.min(5, view.k * factor));
  const rect = svg.getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  view.x = px - (px - view.x) * (next / view.k);
  view.y = py - (py - view.y) * (next / view.k);
  view.k = next;
  applyView();
}, { passive: false });

let panFrom = null;
svg.addEventListener('pointerdown', event => {
  if (event.target.closest('.node')) return;
  panFrom = { x: event.clientX - view.x, y: event.clientY - view.y };
  svg.classList.add('dragging');
  svg.setPointerCapture(event.pointerId);
});
svg.addEventListener('pointermove', event => {
  if (dragging) {
    const point = toGraph(event);
    dragging.x = point.x; dragging.y = point.y;
    dragging.pinned = true;
    draw();
    return;
  }
  if (!panFrom) return;
  view.x = event.clientX - panFrom.x;
  view.y = event.clientY - panFrom.y;
  applyView();
});
svg.addEventListener('pointerup', () => {
  panFrom = null;
  if (dragging) { dragging.pinned = false; dragging = null; reheat(0.25); }
  svg.classList.remove('dragging');
});

let dragging = null;
function toGraph(event) {
  const rect = svg.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left - view.x) / view.k,
    y: (event.clientY - rect.top - view.y) / view.k
  };
}
function startNodeDrag(event, node) {
  event.stopPropagation();
  dragging = node;
  svg.setPointerCapture(event.pointerId);
}

/* ---------- selection and evidence ---------- */
let selected = null;
function relatedEdges(node) {
  return edges.filter(edge => edge.source === node || edge.target === node);
}
function evidenceHtml(edge) {
  const items = (edge.evidence || []).map(item => {
    const where = item.location ? ' at ' + esc(item.location) : '';
    const facts = item.facts ? '<pre>' + esc(item.facts) + '</pre>' : '';
    return '<details><summary>' + esc(item.kind) + ' · ' + esc(item.mode) + where +
           '</summary>' + facts + '</details>';
  }).join('');
  return items || '<p>No rendered evidence.</p>';
}
function select(node) {
  selected = node;
  const rows = relatedEdges(node).map(edge => {
    const outgoing = edge.source === node;
    const other = outgoing ? edge.target : edge.source;
    return '<div class="rel"><div class="arrow">' +
      (outgoing ? '→ ' : '← ') + esc(edge.relation) +
      ' <span class="pill">' + esc(edge.assurance || 'unknown') + '</span>' +
      ' <span class="pill">' + esc(edge.mode) + '</span></div>' +
      '<code>' + esc(other.path || other.label) + '</code>' +
      evidenceHtml(edge) + '</div>';
  }).join('');
  side.innerHTML =
    '<h2><code>' + esc(node.path || node.label) + '</code></h2>' +
    '<p><span class="pill">' + esc(node.kind) + '</span> ' +
    (node.deleted ? '<span class="pill">deleted</span>' : '') + '</p>' +
    '<p>' + relatedEdges(node).length + ' relationship(s)</p>' +
    (rows || '<p>No supported relationships at the current filter.</p>');
  applyFilters();
}

/* ---------- filters ---------- */
function applyFilters() {
  const query = searchBox.value.trim().toLowerCase();
  const relation = relationBox.value;
  const minimum = Number(assuranceBox.value);
  const visibleNodes = new Set();
  let shown = 0;
  for (let i = 0; i < edges.length; i += 1) {
    const edge = edges[i];
    const text = (edge.source.path + ' ' + edge.target.path + ' ' + edge.relation).toLowerCase();
    const keep = edge.score >= minimum &&
      (!relation || edge.relation === relation) &&
      (!query || text.includes(query));
    edgeEls[i].classList.toggle('dim', !keep);
    if (keep) {
      shown += 1;
      visibleNodes.add(edge.source);
      visibleNodes.add(edge.target);
    }
  }
  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i];
    const matches = !query || (node.path || '').toLowerCase().includes(query);
    const keep = visibleNodes.has(node) || (matches && !relation && minimum <= 0.3);
    nodeEls[i].classList.toggle('dim', !keep);
    nodeEls[i].classList.toggle('selected', node === selected);
  }
  const truncated = DATA.truncated;
  status.innerHTML =
    shown + ' of ' + edges.length + ' relationships · ' + nodes.length + ' nodes · ' +
    'solid green = captured, dashed grey = inferred' +
    (truncated
      ? ' · <span class="warn">showing the ' + edges.length + ' highest-scoring of ' +
        truncated.total_edges + ' relationships; raise <code>explorer_edge_limit</code> ' +
        'or use <code>export --format json</code> for the complete graph</span>'
      : '');
  renderTable(minimum, relation, query);
}

function renderTable(minimum, relation, query) {
  const body = document.getElementById('table-body');
  const rows = edges.filter(edge => {
    const text = (edge.source.path + ' ' + edge.target.path + ' ' + edge.relation).toLowerCase();
    return edge.score >= minimum && (!relation || edge.relation === relation) &&
      (!query || text.includes(query));
  }).slice(0, 500);
  body.innerHTML = rows.map(edge =>
    '<tr class="' + (edge.mode === 'captured' ? 'captured' : '') + '">' +
    '<td><code>' + esc(edge.source.path || edge.source.label) + '</code></td>' +
    '<td>' + esc(edge.relation) + '</td>' +
    '<td><code>' + esc(edge.target.path || edge.target.label) + '</code></td>' +
    '<td>' + esc(edge.assurance || 'unknown') + '</td>' +
    '<td>' + evidenceHtml(edge) + '</td></tr>'
  ).join('');
}

[searchBox, relationBox, assuranceBox].forEach(el => el.addEventListener('input', applyFilters));
document.getElementById('reset').addEventListener('click', () => { resetView(); reheat(0.6); });
const toggle = document.getElementById('toggle-table');
toggle.addEventListener('click', () => {
  const active = document.body.classList.toggle('table-mode');
  toggle.setAttribute('aria-pressed', String(active));
});

resetView();
applyFilters();
reheat(1);
"""
