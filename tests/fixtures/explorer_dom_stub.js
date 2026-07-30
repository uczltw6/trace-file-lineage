/* Minimal DOM stub for running the shipped explorer script under a bare JS
   engine (node or JavaScriptCore). It implements only what the explorer
   touches, and records listeners so interactions can be dispatched.

   DATA_JSON must already be defined by the caller. */
'use strict';
if (typeof print === 'undefined') { globalThis.print = console.log; }

var CALLS = { rafs: 0, listeners: 0, created: 0 };

function El(tag) {
  this.tagName = tag;
  this.children = [];
  this.attrs = {};
  this.classes = {};
  this.style = {};
  this.textContent = '';
  this._html = '';
  this._on = {};
  CALLS.created += 1;
}
El.prototype.setAttribute = function (key, value) { this.attrs[key] = String(value); };
El.prototype.getAttribute = function (key) { return this.attrs[key]; };
El.prototype.appendChild = function (child) { this.children.push(child); return child; };
El.prototype.append = function () {
  for (var i = 0; i < arguments.length; i += 1) this.children.push(arguments[i]);
};
El.prototype.addEventListener = function (type, handler) {
  CALLS.listeners += 1;
  (this._on[type] = this._on[type] || []).push(handler);
};
El.prototype.fire = function (type, event) {
  var handlers = this._on[type] || [];
  var payload = event || {
    preventDefault: function () {}, stopPropagation: function () {},
    clientX: 0, clientY: 0, pointerId: 1, key: 'Enter', deltaY: -1,
    target: { closest: function () { return null; } }
  };
  for (var i = 0; i < handlers.length; i += 1) handlers[i](payload);
  return handlers.length;
};
El.prototype.setPointerCapture = function () {};
El.prototype.getBoundingClientRect = function () {
  return { left: 0, top: 0, width: 1200, height: 800 };
};
El.prototype.add = function (option) { this.children.push(option); };
Object.defineProperty(El.prototype, 'innerHTML', {
  get: function () { return this._html; },
  set: function (value) { this._html = String(value); }
});

function makeElement(tag) {
  var element = new El(tag);
  element.classList = {
    toggle: function (name, on) {
      element.classes[name] = (on === undefined) ? !element.classes[name] : !!on;
      return element.classes[name];
    },
    add: function (name) { element.classes[name] = true; },
    remove: function (name) { element.classes[name] = false; },
    contains: function (name) { return !!element.classes[name]; }
  };
  return element;
}

var REGISTRY = {};
function register(id, tag) {
  var element = makeElement(tag);
  element.value = '';
  REGISTRY[id] = element;
  return element;
}

['graph', 'viewport', 'edges', 'nodes'].forEach(function (id) { register(id, 'svg'); });
register('side', 'aside');
register('status', 'p');
register('search', 'input');
register('relation', 'select');
register('assurance', 'select');
register('reset', 'button');
register('toggle-table', 'button');
register('table-body', 'tbody');
register('focus', 'input').checked = true;
register('depth', 'select');
register('lineage-data', 'script').textContent = DATA_JSON;
REGISTRY.assurance.value = '0';
REGISTRY.depth.value = '2';

var document = {
  _on: {},
  getElementById: function (id) {
    if (!REGISTRY[id]) throw new Error('explorer referenced a missing element: #' + id);
    return REGISTRY[id];
  },
  createElementNS: function (namespace, tag) { return makeElement(tag); },
  createElement: function (tag) { return makeElement(tag); },
  body: makeElement('body'),
  addEventListener: function (type, handler) {
    CALLS.listeners += 1;
    (this._on[type] = this._on[type] || []).push(handler);
  },
  fire: function (type, event) {
    var handlers = this._on[type] || [];
    for (var i = 0; i < handlers.length; i += 1) handlers[i](event || {});
    return handlers.length;
  }
};
var window = { devicePixelRatio: 1 };
function Option(text, value) { this.text = text; this.value = value; }
function requestAnimationFrame(callback) {
  CALLS.rafs += 1;
  if (CALLS.rafs < 500) callback();
  return CALLS.rafs;
}
function cancelAnimationFrame() {}
