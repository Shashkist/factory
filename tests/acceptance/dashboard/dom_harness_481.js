// Copy of dom_harness_68.js for the #481 exam, plus: step.snapshot (served as snapshot.json; 404 when absent) and
// `updated` (the serialized #updated header node) in every step's output.
// Minimal fake browser for the #51 exam: runs the real index.html + app.js in a node vm.
// usage: node dom_harness_51.js <index.html> <app.js> <scenario.json>
// scenario: {now: ISO, steps: [{now?: ISO, live: <object|string|{http: N}|{error: true}>}]}
// Step 0 answers the page's first live.json fetch. Every later step fires the page's timers
// (delay <= 10000 ms) and answers the next live.json fetch. Prints one JSON document.
"use strict";
const fs = require("fs");
const vm = require("vm");

const [indexPath, appPath, scenarioPath] = process.argv.slice(2);
const scenario = JSON.parse(fs.readFileSync(scenarioPath, "utf8"));
const html = fs.readFileSync(indexPath, "utf8");
const appSrc = fs.readFileSync(appPath, "utf8");

const flags = { innerHTML: [], style_attr: [], errors: [] };
let nowMs = Date.parse(scenario.now);

class TextNode {
  constructor(t) { this.nodeType = 3; this.data = String(t); this.parentNode = null; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
}

const VOID = new Set(["meta", "link", "br", "img", "input", "hr"]);
const dataKey = (k) => "data-" + String(k).replace(/[A-Z]/g, (m) => "-" + m.toLowerCase());

class Element {
  constructor(tag, ns) {
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this.localName = tag.toLowerCase();
    this.namespaceURI = ns || null;
    this.attrs = {}; this.childNodes = []; this.parentNode = null; this.listeners = {};
    const self = this;
    this.classList = {
      add(...c) { const s = new Set(self._classes()); c.forEach((x) => s.add(x)); self.attrs["class"] = [...s].join(" "); },
      remove(...c) { self.attrs["class"] = self._classes().filter((x) => !c.includes(x)).join(" "); },
      contains(c) { return self._classes().includes(c); },
      toggle(c, force) {
        const has = self._classes().includes(c);
        const want = force === undefined ? !has : !!force;
        if (want) this.add(c); else this.remove(c);
        return want;
      },
    };
    this.style = new Proxy({}, {
      set: (o, k, v) => { o[k] = v; return true; },
      get: (o, k) => (k === "setProperty" ? (a, b) => { o[a] = b; } : o[k]),
    });
    this.dataset = new Proxy({}, {
      get: (o, k) => self.attrs[dataKey(k)],
      set: (o, k, v) => { self.attrs[dataKey(k)] = String(v); return true; },
    });
  }
  _classes() { return (this.attrs["class"] || "").split(/\s+/).filter(Boolean); }
  get className() { return this.attrs["class"] || ""; }
  set className(v) { this.attrs["class"] = String(v); }
  get id() { return this.attrs.id || ""; }
  set id(v) { this.attrs.id = String(v); }
  get hidden() { return "hidden" in this.attrs; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get title() { return this.attrs.title || ""; }
  set title(v) { this.attrs.title = String(v); }
  get href() { return this.attrs.href || ""; }
  set href(v) { this.attrs.href = String(v); }
  get rel() { return this.attrs.rel || ""; }
  set rel(v) { this.attrs.rel = String(v); }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get parentElement() { return this.parentNode; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) {
    this.childNodes.forEach((c) => { c.parentNode = null; });
    this.childNodes = [];
    if (v !== "" && v !== null && v !== undefined) this.appendChild(new TextNode(v));
  }
  get innerText() { return this.textContent; }
  set innerText(v) { this.textContent = v; }
  set innerHTML(v) { flags.innerHTML.push(String(v)); }
  get innerHTML() { return ""; }
  set outerHTML(v) { flags.innerHTML.push(String(v)); }
  insertAdjacentHTML(_p, v) { flags.innerHTML.push(String(v)); }
  setAttribute(k, v) {
    if (k.toLowerCase() === "style") flags.style_attr.push(String(v));
    this.attrs[k] = String(v);
  }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  _adopt(n) {
    if (typeof n === "string") n = new TextNode(n);
    if (n.parentNode) n.parentNode.removeChild(n);
    n.parentNode = this;
    return n;
  }
  appendChild(n) { n = this._adopt(n); this.childNodes.push(n); return n; }
  append(...ns) { ns.forEach((n) => this.appendChild(n)); }
  prepend(...ns) { ns.reverse().forEach((n) => this.insertBefore(n, this.childNodes[0] || null)); }
  insertBefore(n, ref) {
    n = this._adopt(n);
    const i = ref ? this.childNodes.indexOf(ref) : -1;
    if (i < 0) this.childNodes.push(n); else this.childNodes.splice(i, 0, n);
    return n;
  }
  removeChild(n) {
    const i = this.childNodes.indexOf(n);
    if (i >= 0) { this.childNodes.splice(i, 1); n.parentNode = null; }
    return n;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  replaceChildren(...ns) { this.textContent = ""; ns.forEach((n) => this.appendChild(n)); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  removeEventListener() {}
  focus() {}
  contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
  getElementsByTagName(t) { return this.querySelectorAll(t); }
  querySelectorAll(sel) { return query(this, sel); }
  querySelector(sel) { return query(this, sel)[0] || null; }
  matches(sel) { return sel.split(",").some((s) => matchChain(this, splitSel(s))); }
  closest(sel) {
    for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (n.matches(sel)) return n;
    return null;
  }
}

function splitSel(s) { return s.trim().split(/\s*(>)\s*|\s+/).filter((x) => x); }

function matchSimple(el, s) {
  const re = /([#.][\w-]+|\[[^\]]+\]|^[\w*-]+)/g;
  let m;
  while ((m = re.exec(s))) {
    const t = m[1];
    if (t[0] === "#") { if (el.id !== t.slice(1)) return false; }
    else if (t[0] === ".") { if (!el._classes().includes(t.slice(1))) return false; }
    else if (t[0] === "[") {
      const mm = /^\[([\w:-]+)(?:(=)["']?([^"'\]]*)["']?)?\]$/.exec(t);
      if (!mm) return false;
      const v = el.attrs[mm[1]];
      if (v === undefined) return false;
      if (mm[2] === "=" && v !== mm[3]) return false;
    } else if (t !== "*" && el.localName !== t.toLowerCase()) return false;
  }
  return true;
}
function matchChain(el, parts) {
  if (!matchSimple(el, parts[parts.length - 1])) return false;
  if (parts.length === 1) return true;
  let rest = parts.slice(0, -1);
  let child = false;
  if (rest[rest.length - 1] === ">") { child = true; rest = rest.slice(0, -1); }
  if (child) return !!el.parentNode && el.parentNode.nodeType === 1 && matchChain(el.parentNode, rest);
  for (let p = el.parentNode; p && p.nodeType === 1; p = p.parentNode) if (matchChain(p, rest)) return true;
  return false;
}
function query(root, sel) {
  const groups = sel.split(",").map(splitSel);
  const out = [];
  (function walk(n) {
    n.childNodes.forEach((c) => {
      if (c.nodeType !== 1) return;
      if (groups.some((g) => matchChain(c, g))) out.push(c);
      walk(c);
    });
  })(root);
  return out;
}

// ---- parse index.html into the fake tree ----
function parseHtml(src) {
  const root = new Element("#root");
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<!doctype[^>]*>|<\/([\w-]+)\s*>|<([\w-]+)((?:\s+[^\s=>/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*\/?>|([^<]+)/gi;
  let m;
  while ((m = re.exec(src))) {
    const top = stack[stack.length - 1];
    if (m[1]) {
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].localName === m[1].toLowerCase()) { stack.length = i; break; }
      }
    } else if (m[2]) {
      const el = new Element(m[2]);
      const ar = /([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
      let a;
      while ((a = ar.exec(m[3] || ""))) el.attrs[a[1]] = a[2] ?? a[3] ?? a[4] ?? "";
      top.appendChild(el);
      if (!VOID.has(el.localName) && !/\/>$/.test(m[0])) stack.push(el);
    } else if (m[4] !== undefined && m[4].trim() !== "") top.appendChild(new TextNode(m[4]));
  }
  return root;
}

const tree = parseHtml(html);
const htmlEl = tree.querySelector("html") || tree;
const body = tree.querySelector("body") || tree;

const document = {
  documentElement: htmlEl, body,
  getElementById: (id) => query(tree, "#" + id)[0] || null,
  querySelector: (s) => tree.querySelector(s),
  querySelectorAll: (s) => tree.querySelectorAll(s),
  createElement: (t) => new Element(t),
  createElementNS: (ns, t) => new Element(t, ns),
  createTextNode: (t) => new TextNode(t),
  createDocumentFragment: () => new Element("#fragment"),
  addEventListener() {},
  write() { flags.innerHTML.push("document.write"); },
  hidden: false, readyState: "complete",
};

// ---- fake timers, clock, fetch ----
const timers = [];
let timerId = 0;
const delays = [];
const fetchLog = [];
let liveResponse = { live: {} };
let snapshotResponse = null;

function addTimer(fn, ms, repeat) {
  const t = { id: ++timerId, fn, ms: Number(ms) || 0, repeat };
  timers.push(t);
  delays.push(t.ms);
  return t.id;
}
function clearTimer(id) {
  const i = timers.findIndex((t) => t.id === id);
  if (i >= 0) timers.splice(i, 1);
}

function makeResponse(status, raw) {
  return {
    ok: status >= 200 && status < 300, status,
    json: () => Promise.resolve().then(() => JSON.parse(raw)),
    text: () => Promise.resolve(raw),
  };
}
function fakeFetch(url, opts) {
  const u = String(url);
  fetchLog.push({ url: u, cache: opts && opts.cache });
  if (/snapshot\.json/.test(u)) {
    return Promise.resolve(snapshotResponse ? makeResponse(200, JSON.stringify(snapshotResponse)) : makeResponse(404, ""));
  }
  if (!/live\.json/.test(u)) return Promise.resolve(makeResponse(404, ""));
  const r = liveResponse.live;
  if (r && typeof r === "object" && r.error) return Promise.reject(new TypeError("network down"));
  if (r && typeof r === "object" && r.http) return Promise.resolve(makeResponse(r.http, ""));
  if (typeof r === "string") return Promise.resolve(makeResponse(200, r));
  return Promise.resolve(makeResponse(200, JSON.stringify(r)));
}

class FakeDate extends Date {
  constructor(...a) { if (a.length) super(...a); else super(nowMs); }
  static now() { return nowMs; }
}

const sandbox = {
  document, console, fetch: fakeFetch, Date: FakeDate,
  setInterval: (f, ms) => addTimer(f, ms, true), clearInterval: clearTimer,
  setTimeout: (f, ms) => addTimer(f, ms, false), clearTimeout: clearTimer,
  requestAnimationFrame: (f) => addTimer(f, 16, false),
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  navigator: { userAgent: "exam-harness" },
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  location: { href: "https://factory.example.test/", search: "", hash: "" },
  Node: Element, Element, HTMLElement: Element,
  URL, URLSearchParams, encodeURIComponent,
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.globalThis = sandbox;
sandbox.addEventListener = () => {};
const ctx = vm.createContext(sandbox);

function ser(n) {
  if (n.nodeType === 3) return n.data;
  return { t: n.localName, a: n.attrs, c: n.childNodes.map(ser) };
}
const flush = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setImmediate(r)); };

process.on("unhandledRejection", (e) => flags.errors.push("unhandledRejection: " + (e && e.message)));

(async () => {
  const out = { steps: [], delays: null };
  for (let i = 0; i < scenario.steps.length; i++) {
    const step = scenario.steps[i];
    if (step.now) nowMs = Date.parse(step.now);
    liveResponse = { live: step.live };
    if (step.snapshot !== undefined) snapshotResponse = step.snapshot;
    fetchLog.length = 0;
    try {
      if (i === 0) {
        vm.runInContext(appSrc, ctx, { filename: "app.js" });
      } else {
        for (const t of timers.slice()) {
          if (t.ms <= 10000) {
            if (!t.repeat) clearTimer(t.id);
            t.fn();
          }
        }
      }
    } catch (e) { flags.errors.push("throw: " + (e && e.message)); }
    await flush();
    for (const c of step.clicks || []) {
      const lane = tree.querySelectorAll("div").find((n) => n.attrs["data-lane"] === String(c.lane));
      const btn = lane && lane.querySelectorAll("button").find((b) => b.attrs["data-st"] === c.st);
      if (!btn) { flags.errors.push("no lane button " + c.lane + "/" + c.st); continue; }
      for (const f of btn.listeners.click || []) f({ preventDefault() {}, target: btn });
      await flush();
    }
    const live = document.getElementById("live");
    out.steps.push({
      live: live ? ser(live) : null,
      updated: document.getElementById("updated") ? ser(document.getElementById("updated")) : null,
      fetches: fetchLog.slice(),
      innerHTML: flags.innerHTML.slice(), style_attr: flags.style_attr.slice(),
      errors: flags.errors.slice(),
      pwned: sandbox.pwned === undefined ? null : sandbox.pwned,
    });
  }
  out.delays = delays;
  console.log(JSON.stringify(out));
})();
