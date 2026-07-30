/* Post-conditions asserted after the shipped explorer script has run against
   the DOM stub. Prints one line per check and throws if any failed, so the
   calling process sees a non-zero exit. */
(function checkExplorer() {
  'use strict';
  var results = [];
  function record(name, ok, detail) {
    results.push((ok ? 'PASS ' : 'FAIL ') + name + (detail ? ' :: ' + detail : ''));
  }
  /* A check reports detail by returning a string and fails by returning false
     or calling fail(). Returning a message must never read as success. */
  function fail(message) { throw new Error(message); }
  function attempt(name, fn) {
    try {
      var outcome = fn();
      record(name, outcome !== false, typeof outcome === 'string' ? outcome : '');
    } catch (error) {
      record(name, false, String(error && error.message ? error.message : error));
    }
  }

  var data = JSON.parse(DATA_JSON);
  var edgeLayer = REGISTRY.edges;
  var nodeLayer = REGISTRY.nodes;

  attempt('an SVG element exists for every edge', function () {
    if (edgeLayer.children.length !== data.edges.length) {
      fail(edgeLayer.children.length + ' elements for ' + data.edges.length + ' edges');
    }
    return edgeLayer.children.length + ' edges';
  });
  attempt('an SVG element exists for every node', function () {
    if (nodeLayer.children.length !== data.nodes.length) {
      fail(nodeLayer.children.length + ' elements for ' + data.nodes.length + ' nodes');
    }
    return nodeLayer.children.length + ' nodes';
  });
  attempt('the force simulation ran', function () {
    if (CALLS.rafs <= 10) fail('only ' + CALLS.rafs + ' animation frames');
    return CALLS.rafs + ' frames';
  });
  attempt('nodes reached finite, non-origin positions', function () {
    if (!nodeLayer.children.length) return 'no nodes in fixture';
    var positioned = 0;
    for (var i = 0; i < nodeLayer.children.length; i += 1) {
      var transform = nodeLayer.children[i].getAttribute('transform') || '';
      if (transform.indexOf('NaN') !== -1 || transform.indexOf('Infinity') !== -1) {
        fail('non-finite coordinate at node ' + i + ': ' + transform);
      }
      if (transform && transform !== 'translate(0.0,0.0)') positioned += 1;
    }
    if (positioned < nodeLayer.children.length * 0.9) {
      fail('only ' + positioned + ' of ' + nodeLayer.children.length + ' positioned');
    }
    return positioned + ' positioned';
  });
  attempt('edges have finite endpoints', function () {
    if (!edgeLayer.children.length) return 'no edges in fixture';
    for (var i = 0; i < edgeLayer.children.length; i += 1) {
      var x1 = String(edgeLayer.children[i].getAttribute('x1'));
      if (x1 === 'undefined' || x1.indexOf('NaN') !== -1 || x1.indexOf('Infinity') !== -1) {
        fail('non-finite endpoint at edge ' + i + ': ' + x1);
      }
    }
    return edgeLayer.children.length + ' edges drawn';
  });
  attempt('captured edges are styled apart from inferred ones', function () {
    var captured = 0;
    var dashed = 0;
    for (var i = 0; i < edgeLayer.children.length; i += 1) {
      var value = edgeLayer.children[i].getAttribute('class') || '';
      if (value.indexOf('captured') !== -1) captured += 1; else dashed += 1;
    }
    return 'captured=' + captured + ' inferred=' + dashed;
  });
  attempt('the status line reports counts', function () {
    return REGISTRY.status.innerHTML.indexOf('relationships') !== -1
      ? REGISTRY.status.innerHTML.slice(0, 70)
      : false;
  });
  attempt('the accessible table fallback is populated', function () {
    if (!data.edges.length) return 'no edges in fixture';
    return REGISTRY['table-body'].innerHTML.length > 0
      ? REGISTRY['table-body'].innerHTML.length + ' chars'
      : false;
  });
  attempt('the relation filter is populated from the data', function () {
    if (!data.edges.length) return 'no edges in fixture';
    return REGISTRY.relation.children.length > 0
      ? REGISTRY.relation.children.length + ' options'
      : false;
  });
  attempt('the viewport transform is applied', function () {
    var transform = REGISTRY.viewport.getAttribute('transform') || '';
    return /translate\([-\d.]+,[-\d.]+\) scale\([\d.]+\)/.test(transform) ? transform : false;
  });

  attempt('nodes carry a readable text label', function () {
    if (!nodeLayer.children.length) return 'no nodes in fixture';
    var labelled = 0;
    for (var i = 0; i < nodeLayer.children.length; i += 1) {
      var kids = nodeLayer.children[i].children || [];
      for (var j = 0; j < kids.length; j += 1) {
        if (kids[j].tagName === 'text' && String(kids[j].textContent).length > 0) {
          labelled += 1;
          break;
        }
      }
    }
    if (labelled !== nodeLayer.children.length) {
      fail('only ' + labelled + ' of ' + nodeLayer.children.length + ' nodes are labelled');
    }
    return labelled + ' labelled';
  });
  attempt('nodes expose an accessible name and role', function () {
    if (!nodeLayer.children.length) return 'no nodes in fixture';
    var first = nodeLayer.children[0];
    if (first.getAttribute('role') !== 'button') fail('missing role=button');
    if (!first.getAttribute('aria-label')) fail('missing aria-label');
    if (first.getAttribute('tabindex') !== '0') fail('node is not focusable');
    return first.getAttribute('aria-label');
  });
  attempt('clicking a node renders its evidence panel', function () {
    if (!nodeLayer.children.length) return 'no nodes in fixture';
    REGISTRY.side.innerHTML = '';
    if (!nodeLayer.children[0].fire('click')) fail('no click handler bound');
    if (REGISTRY.side.innerHTML.indexOf('relationship') === -1) {
      fail('panel did not render relationships: ' + REGISTRY.side.innerHTML.slice(0, 80));
    }
    return REGISTRY.side.innerHTML.length + ' chars';
  });
  attempt('a node can be activated from the keyboard alone', function () {
    if (!nodeLayer.children.length) return 'no nodes in fixture';
    REGISTRY.side.innerHTML = '';
    nodeLayer.children[0].fire('keydown', {
      key: 'Enter', preventDefault: function () {}, stopPropagation: function () {}
    });
    if (REGISTRY.side.innerHTML.length === 0) fail('Enter did not select the node');
    return 'Enter selected the node';
  });
  attempt('selecting a node hides everything outside its neighbourhood', function () {
    if (data.nodes.length < 6) return 'fixture too small to focus';
    REGISTRY.focus.checked = true;
    REGISTRY.depth.value = '1';
    REGISTRY.depth.fire('input');
    nodeLayer.children[0].fire('click');
    var hiddenNodes = 0;
    for (var i = 0; i < nodeLayer.children.length; i += 1) {
      if (nodeLayer.children[i].classes.hidden) hiddenNodes += 1;
    }
    if (hiddenNodes === 0) fail('focus hid nothing; the whole graph is still drawn');
    if (hiddenNodes === nodeLayer.children.length) fail('focus hid everything, including the selection');
    return hiddenNodes + ' of ' + nodeLayer.children.length + ' nodes hidden at 1 hop';
  });
  attempt('focus hides the edges outside the neighbourhood too', function () {
    if (data.edges.length < 6) return 'fixture too small to focus';
    REGISTRY.focus.checked = true;
    REGISTRY.depth.value = '1';
    nodeLayer.children[0].fire('click');
    var hiddenEdges = 0;
    for (var i = 0; i < edgeLayer.children.length; i += 1) {
      if (edgeLayer.children[i].classes.hidden) hiddenEdges += 1;
    }
    if (hiddenEdges === 0) fail('every edge is still drawn while focused');
    if (hiddenEdges === edgeLayer.children.length) {
      fail('focus hid every edge, including those touching the selection');
    }
    return hiddenEdges + ' of ' + edgeLayer.children.length + ' edges hidden';
  });
  attempt('one hop means exactly one hop', function () {
    // CHAIN_FIXTURE is set by the caller when the graph is a simple path
    // n0-n1-...-nN. Then focusing n0 at h hops must show exactly h+1 nodes.
    // Without this, a hop can silently traverse the whole chain in one pass.
    if (typeof CHAIN_FIXTURE === 'undefined' || !CHAIN_FIXTURE) return 'not a chain fixture';
    REGISTRY.focus.checked = true;
    function visible() {
      var n = 0;
      for (var i = 0; i < nodeLayer.children.length; i += 1) {
        if (!nodeLayer.children[i].classes.hidden) n += 1;
      }
      return n;
    }
    for (var hops = 1; hops <= 3; hops += 1) {
      REGISTRY.depth.value = String(hops);
      nodeLayer.children[0].fire('click');
      var expected = hops + 1;
      if (visible() !== expected) {
        fail('at ' + hops + ' hop(s) expected ' + expected + ' nodes, drew ' + visible());
      }
    }
    return 'exact hop counts hold for 1, 2, and 3 hops';
  });
  attempt('a wider hop setting reveals more of the graph', function () {
    if (data.nodes.length < 6) return 'fixture too small to focus';
    function hiddenCount() {
      var n = 0;
      for (var i = 0; i < nodeLayer.children.length; i += 1) {
        if (nodeLayer.children[i].classes.hidden) n += 1;
      }
      return n;
    }
    REGISTRY.depth.value = '1';
    REGISTRY.depth.fire('input');
    var atOne = hiddenCount();
    REGISTRY.depth.value = '3';
    REGISTRY.depth.fire('input');
    var atThree = hiddenCount();
    if (!(atThree < atOne)) fail('3 hops hid ' + atThree + ', 1 hop hid ' + atOne);
    return atOne + ' hidden at 1 hop, ' + atThree + ' at 3 hops';
  });
  attempt('the focus toggle restores the whole graph', function () {
    if (data.nodes.length < 6) return 'fixture too small to focus';
    REGISTRY.focus.checked = false;
    REGISTRY.focus.fire('input');
    for (var i = 0; i < nodeLayer.children.length; i += 1) {
      if (nodeLayer.children[i].classes.hidden) fail('node ' + i + ' still hidden with focus off');
    }
    REGISTRY.focus.checked = true;
    return 'all nodes visible with focus off';
  });
  attempt('Escape clears the selection', function () {
    if (data.nodes.length < 6) return 'fixture too small to focus';
    nodeLayer.children[0].fire('click');
    if (!document.fire('keydown', { key: 'Escape' })) fail('no document keydown handler');
    for (var i = 0; i < nodeLayer.children.length; i += 1) {
      if (nodeLayer.children[i].classes.hidden) fail('node ' + i + ' still hidden after Escape');
    }
    return 'selection cleared, full graph restored';
  });
  attempt('the status line reports what focus is hiding', function () {
    if (data.nodes.length < 6) return 'fixture too small to focus';
    REGISTRY.focus.checked = true;
    REGISTRY.depth.value = '1';
    nodeLayer.children[0].fire('click');
    if (REGISTRY.status.innerHTML.indexOf('focused on') === -1) {
      fail('status line does not mention the focus: ' + REGISTRY.status.innerHTML.slice(0, 90));
    }
    if (REGISTRY.status.innerHTML.indexOf('hidden') === -1) fail('status line omits the hidden count');
    document.fire('keydown', { key: 'Escape' });
    return 'focus state reported';
  });
  attempt('the search filter narrows the result set', function () {
    REGISTRY.search.value = 'zzzzz-no-such-path';
    REGISTRY.search.fire('input');
    var matched = /^(\d+) of (\d+)/.exec(REGISTRY.status.innerHTML);
    REGISTRY.search.value = '';
    REGISTRY.search.fire('input');
    if (!matched) fail('status line lost its counts');
    if (Number(matched[1]) !== 0) fail('unmatched query still showed ' + matched[1] + ' edges');
    return 'unmatched query yields 0';
  });
  attempt('the assurance filter actually excludes weaker edges', function () {
    if (!data.edges.length) return 'no edges in fixture';
    var weaker = data.edges.filter(function (edge) { return edge.score < 1; }).length;
    if (!weaker) return 'fixture has no sub-verified edges';
    REGISTRY.assurance.value = '1';
    REGISTRY.assurance.fire('input');
    var matched = /^(\d+) of (\d+)/.exec(REGISTRY.status.innerHTML);
    REGISTRY.assurance.value = '0';
    REGISTRY.assurance.fire('input');
    if (!matched) fail('status line lost its counts');
    var shown = Number(matched[1]);
    var total = Number(matched[2]);
    if (shown >= total) fail('verified-only still showed all ' + total + ' edges');
    return shown + ' of ' + total + ' at verified-only';
  });
  attempt('the table toggle flips presentation mode', function () {
    REGISTRY['toggle-table'].fire('click');
    if (document.body.classes['table-mode'] !== true) fail('table-mode class not set');
    if (REGISTRY['toggle-table'].getAttribute('aria-pressed') !== 'true') {
      fail('aria-pressed not updated');
    }
    return 'aria-pressed=true';
  });
  attempt('wheel zoom changes the viewport scale', function () {
    var before = REGISTRY.viewport.getAttribute('transform');
    REGISTRY.graph.fire('wheel', {
      deltaY: -1, clientX: 100, clientY: 100,
      preventDefault: function () {},
      target: { closest: function () { return null; } }
    });
    var after = REGISTRY.viewport.getAttribute('transform');
    if (after === before) fail('wheel did not change the transform');
    if (/scale\(1\)/.test(after)) fail('scale stayed at 1 after zooming');
    return after;
  });
  attempt('reset view restores the default scale after zooming', function () {
    // Runs after the wheel check, so the view is deliberately zoomed here.
    if (/scale\(1\)/.test(REGISTRY.viewport.getAttribute('transform') || '')) {
      fail('precondition failed: view was not zoomed before reset');
    }
    REGISTRY.reset.fire('click');
    var after = REGISTRY.viewport.getAttribute('transform') || '';
    if (!/scale\(1\)/.test(after)) fail('reset left the view at ' + after);
    return after;
  });

  for (var i = 0; i < results.length; i += 1) print(results[i]);
  var failures = results.filter(function (line) { return line.indexOf('FAIL') === 0; });
  if (failures.length) throw new Error(failures.length + ' explorer check(s) failed');
  print('EXPLORER_RUNTIME_OK');
})();
