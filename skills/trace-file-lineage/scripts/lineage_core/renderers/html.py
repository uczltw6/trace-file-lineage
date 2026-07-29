from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def render_html(graph: dict[str, Any], destination: Path) -> Path:
    payload = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>File Lineage Explorer</title>
<style>
:root{{color-scheme:light dark;font-family:system-ui,sans-serif}} body{{margin:0;padding:1rem;max-width:1200px;margin-inline:auto}}
.controls{{display:flex;gap:.75rem;flex-wrap:wrap}} input,select,button{{font:inherit;padding:.5rem}} table{{width:100%;border-collapse:collapse;margin-top:1rem}}
th,td{{text-align:left;padding:.45rem;border-bottom:1px solid color-mix(in srgb,currentColor 25%,transparent)}} .captured{{font-weight:700}} .inferred{{opacity:.8}}
code{{overflow-wrap:anywhere}} details{{margin:.25rem 0}} .muted{{opacity:.7}}
</style></head><body>
<h1>File Lineage Explorer</h1>
<div class="controls"><label>Search <input id="search" type="search"></label><label>Relation <select id="relation"><option value="">All</option></select></label><label>Minimum assurance <select id="score"><option value="0">All</option><option value="0.3">Weak signal+</option><option value="0.55">Candidate+</option><option value="0.8">Strong candidate+</option><option value="1">Verified only</option></select></label><label>Run <select id="run"><option value="">All</option></select></label></div>
<p id="summary" class="muted"></p><table><thead><tr><th>Source</th><th>Relation</th><th>Target</th><th>Confidence</th><th>Evidence</th></tr></thead><tbody id="rows"></tbody></table>
<script id="data" type="application/json">{payload}</script>
<script>
const graph=JSON.parse(document.getElementById('data').textContent); const nodes=new Map(graph.nodes.map(n=>[n.id,n]));
const search=document.getElementById('search'), relation=document.getElementById('relation'), score=document.getElementById('score'), run=document.getElementById('run'), rows=document.getElementById('rows');
[...new Set(graph.edges.map(e=>e.relation))].sort().forEach(v=>relation.add(new Option(v,v))); (graph.runs||[]).forEach(v=>run.add(new Option(v.task||v.id,v.id)));
function esc(v){{return String(v??'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c]))}}
function render(){{const q=search.value.toLowerCase(), min=Number(score.value), rel=relation.value; const filtered=graph.edges.filter(e=>{{const a=nodes.get(e.source_id)||{{}},b=nodes.get(e.target_id)||{{}}; return e.score>=min&&(!rel||e.relation===rel)&&(!q||`${{a.path}} ${{b.path}} ${{e.relation}}`.toLowerCase().includes(q));}}); rows.innerHTML=filtered.map(e=>{{const a=nodes.get(e.source_id)||{{}},b=nodes.get(e.target_id)||{{}};const ev=e.evidence.map(x=>`<details><summary>${{esc(x.kind)}} · ${{esc(x.mode)}}</summary><code>${{esc(JSON.stringify(x.facts))}}</code></details>`).join('');return `<tr class="${{e.mode==='captured'?'captured':'inferred'}}"><td><code>${{esc(a.path||a.label)}}</code></td><td>${{esc(e.relation)}}</td><td><code>${{esc(b.path||b.label)}}</code></td><td>${{esc(e.assurance||e.confidence||'unknown')}}</td><td>${{ev}}</td></tr>`;}}).join('');document.getElementById('summary').textContent=`${{filtered.length}} of ${{graph.edges.length}} relationships. Bold rows are captured; muted rows are inferred.`;}}
[search,relation,score,run].forEach(el=>el.addEventListener('input',render));render();
</script></body></html>"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination
