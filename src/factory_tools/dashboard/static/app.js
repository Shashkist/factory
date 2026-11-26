"use strict";
// Reads snapshot.json (same directory) and renders it. All snapshot text goes in
// through textContent, never innerHTML: issue titles are untrusted.

var STATION_RULES = [
  ["Exam", /\bexam\b|acceptance/i],
  ["Build", /\bbuild|implement|coding|writing code/i],
  // Ship before Check: "CI green, squash-merging" and "smoke check" are Ship steps.
  ["Ship", /merge|deploy|smoke|ship|release/i],
  ["Check", /\bci\b|review|check|verify/i],
];

function stationFor(step) {
  var text = step || "";
  for (var i = 0; i < STATION_RULES.length; i++) {
    if (STATION_RULES[i][1].test(text)) return STATION_RULES[i][0];
  }
  return "Plan";
}

function el(tag, text, cls) {
  var node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
}

function link(href, text) {
  var a = el("a", text);
  if (/^https:\/\//.test(href || "")) a.href = href;
  a.rel = "noopener";
  return a;
}

function fill(id, rows, build, emptyText) {
  var ul = document.getElementById(id);
  ul.textContent = "";
  if (!rows || !rows.length) {
    ul.appendChild(el("li", emptyText || "Nothing here.", "empty"));
    return;
  }
  rows.forEach(function (row) {
    var li = el("li");
    build(li, row);
    ul.appendChild(li);
  });
}

function sparkline(days, label) {
  var ns = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(ns, "svg");
  var max = Math.max.apply(null, days.concat([1]));
  var w = 100 / days.length;
  svg.setAttribute("viewBox", "0 0 100 40");
  svg.setAttribute("preserveAspectRatio", "none");
  days.forEach(function (n, i) {
    var h = n ? Math.max(2, (n / max) * 36) : 1;
    var r = document.createElementNS(ns, "rect");
    r.setAttribute("x", i * w + 0.5);
    r.setAttribute("y", 40 - h);
    r.setAttribute("width", w - 1);
    r.setAttribute("height", h);
    var title = document.createElementNS(ns, "title");
    title.textContent = label ? label(n, i) : n + " closed";
    r.appendChild(title);
    svg.appendChild(r);
  });
  return svg;
}

function runLine(li, name, run) {
  li.appendChild(el("b", name + ": "));
  if (!run) {
    li.appendChild(el("span", "n/a", "empty"));
    return;
  }
  var done = run.status === "completed";
  var word = done ? run.conclusion || "completed" : run.status;
  var cls = done ? (run.conclusion === "success" ? "ok" : "bad") : "warn";
  var a = link(run.url, word);
  a.className = cls;
  li.appendChild(a);
}

var lastGenerated = null;

// Two sources, two ages: live.json (the laptop, every few seconds while a pass runs) and
// snapshot.json (GitHub issues, PRs and CI, rebuilt by a workflow on pushes to main and on a timer).
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// "17 Nov 00:12" in the viewer's time zone; "" for a missing or broken value.
function stamp(iso) {
  var d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  function p(n) { return (n < 10 ? "0" : "") + n; }
  return d.getDate() + " " + MONTHS[d.getMonth()] + " " + p(d.getHours()) + ":" + p(d.getMinutes());
}

// "4 min ago (17 Nov 00:12)"
function agoAt(iso) {
  var at = stamp(iso);
  return ago(iso) + (at ? " (" + at + ")" : "");
}

function showAge() {
  if (lastGenerated) document.getElementById("updated").textContent = "snapshot updated " + agoAt(lastGenerated);
}

function shortRepo(repo) { return S(repo).split("/").pop(); }

var snap = null;
var selRepo = "";   // the repository whose view is shown: from #/<short name>, else the host (the first repository)

function pickRepo(s) {
  var keys = Object.keys(s.repos || {});
  var want = "";
  try { want = decodeURIComponent((/^#\/(.*)$/.exec(location.hash) || [])[1] || ""); } catch (e) { /* a link cut mid-escape: open the host */ }
  return keys.filter(function (r) { return shortRepo(r) === want; })[0] || keys[0] || "";
}

function mine(items) {
  return arr(items).filter(function (i) { return canonRepo(S(i.repo)) === selRepo; });
}

function renderTabs(s) {
  var nav = document.getElementById("repo-tabs");
  nav.textContent = "";
  Object.keys(s.repos || {}).forEach(function (repo) {
    var a = el("a", shortRepo(repo) + " " + ((s.repos[repo].issues || {}).open || 0), repo === selRepo ? "tab sel" : "tab");
    a.href = "#/" + encodeURIComponent(shortRepo(repo));
    if (repo === selRepo) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  });
}

function render(s) {
  snap = s;
  lastGenerated = s.generated_at;
  hostRepo = Object.keys(s.repos || {})[0] || "";
  selRepo = pickRepo(s);
  var cur = (s.repos || {})[selRepo] || { issues: s.issues, claim: s.claim, throughput: s.throughput };
  cur.issues = cur.issues || { open: 0, closed: 0, by_status: {} };
  renderTabs(s);
  showAge();

  // pipeline
  var stations = document.querySelectorAll("#stations li");
  var claimLine = document.getElementById("claim");
  stations.forEach(function (li) { li.classList.remove("active"); });
  var claim = cur.claim;
  if (claim) {
    var st = stationFor(claim.step);
    stations.forEach(function (li) {
      if (li.dataset.station === st) li.classList.add("active");
    });
    claimLine.textContent = "";
    claimLine.appendChild(el("b", laneLabel("", claim.issue)));
    claimLine.appendChild(document.createTextNode(
      " " + (claim.step || "") + " (" + (claim.session || "?") + ", " +
      (claim.branch || "no branch") + ", heartbeat " + ago(claim.heartbeat) + ")"));
  } else {
    claimLine.textContent = "No issue is being worked on.";
  }

  // queue
  var by = cur.issues.by_status || {};
  document.getElementById("counts").textContent =
    cur.issues.open + " open, " + cur.issues.closed + " closed. Ready " + (by.ready || 0) +
    ", blocked " + (by.blocked || 0) + ", needs owner " + (by["needs-owner"] || 0) + ".";
  fill("queue", mine(s.queue), function (li, q) {
    li.appendChild(el("span", q.priority, "tag"));
    li.appendChild(document.createTextNode(" "));
    li.appendChild(link(q.url, laneLabel("", q.number) + " " + q.title));
  }, "No ready issues.");

  fill("open-prs", mine(s.prs.open), function (li, p) {
    li.appendChild(link(p.url, laneLabel("", p.number) + " " + p.title));
  }, "No open pull requests.");
  fill("merged", mine(s.prs.merged).slice(0, 8), function (li, p) {
    li.appendChild(link(p.url, laneLabel("", p.number) + " " + p.title));
    li.appendChild(el("div", ago(p.merged_at), "muted"));
  }, "Nothing merged yet.");
  fill("owner", mine(s.owner_open), function (li, o) {
    li.appendChild(el("span", o.id, "tag"));
    li.appendChild(document.createTextNode(o.title));
  }, "Nothing is waiting for the owner.");
  fill("decisions", mine(s.decisions).slice(-6).reverse(), function (li, d) {
    li.appendChild(el("span", d.id, "tag"));
    li.appendChild(document.createTextNode(d.title));
  }, "No decisions recorded.");

  // health
  var runs = s.runs || {};
  var health = document.getElementById("health");
  health.textContent = "";
  [selRepo].filter(function (r) { return runs[r]; }).forEach(function (repo) {   // runs are nested by repository, then workflow
    var names = ["CI", "Deploy", "Smoke"].filter(function (n) { return runs[repo][n]; });
    if (!names.length) names = [""];
    names.forEach(function (name) {
      var li = el("li");
      runLine(li, name || "CI", runs[repo][name]);
      health.appendChild(li);
    });
  });
  ["Server memory", "Server disk"].forEach(function (name) {
    var key = name === "Server memory" ? "memory" : "disk";
    var li = el("li");
    li.appendChild(el("b", name + ": "));
    var v = s.server && s.server[key];
    li.appendChild(el("span", v === undefined || v === null ? "n/a" : v,
      v === undefined || v === null ? "empty" : ""));
    health.appendChild(li);
  });

  // throughput
  var t = cur.throughput;
  var spark = document.getElementById("spark");
  spark.textContent = "";
  if (!t || !arr(t.closed_per_day).length) {
    document.getElementById("throughput").textContent = "No throughput data.";
    return;
  }
  spark.appendChild(sparkline(t.closed_per_day));
  document.getElementById("throughput").textContent =
    "Closed per day, last 14 days. Median lead time " +
    Math.round(t.median_lead_time_hours * 10) / 10 + " h. Open incidents " +
    t.open_incidents + ".";
}

document.getElementById("theme-toggle").addEventListener("click", function () {
  var root = document.documentElement;
  var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
  root.setAttribute("data-theme", next);
  try { localStorage.setItem("theme", next); } catch (e) { /* private mode */ }
});

function load() {
  fetch("snapshot.json", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (d) {
      snapPrs = d && d.prs ? d.prs : null;
      render(d);
      if (lastLive) renderLive(lastLive);   // lanes use the PR list: redraw once it arrives
    })
    .catch(function (e) {
      if (!lastGenerated) {
        document.getElementById("updated").textContent =
          "snapshot unavailable (" + e.message + ")";
      }
    });
}

// ---- Live section: live.json, polled every 3 s. Every value is untrusted text. ----

var LIVE_STATIONS = ["plan", "exam", "build", "check", "ship"];
var LIVE_ICONS = { start: "⏳", done: "✅", fail: "❌", wait: "⏸", skip: "⏭", stopped: "⏹" };
var LIVE_OFFLINE_MS = 2 * 60 * 1000;
var LIVE_IDLE_OFFLINE_MS = 35 * 60 * 1000;   // the runner polls every 30 min while it is not running
var LIVE_QUIET = { idle: 1, paused: 1, budget: 1 };
var LIVE_LOG_MAX = 60;
var LIVE_ROLE_ICONS = { manager: "🧭", "exam-writer": "📝", implementer: "🔨", reviewer: "🔍",
  researcher: "🔬", scribe: "✍️", agent: "🤖" };
var LIVE_ENDED = { done: 1, failed: 1, stopped: 1, ended: 1 };
var lastLive = null;
var lastRaw = null;
var livePending = false;

function S(v) { return v === undefined || v === null ? "" : String(v); }
function arr(v) { return Array.isArray(v) ? v : []; }

function lel(tag, text, cls, attrs) {
  var n = el(tag, text, cls);
  Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
  return n;
}

function elapsed(iso, until) {
  var t = Date.parse(iso);
  if (isNaN(t)) return "";
  var end = until ? Date.parse(until) : Date.now();
  if (isNaN(end)) end = Date.now();
  var min = Math.max(0, Math.round((end - t) / 60000));
  return min < 90 ? min + " min" : Math.round(min / 60) + " h";
}

function clock(iso) {
  var d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  function p(n) { return (n < 10 ? "0" : "") + n; }
  return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}

function joined(parts) { return parts.filter(Boolean).join(" · "); }

function runnerText(r) {
  var s = S(r.state);
  if (s === "running") {
    var pass = r.pass_no === null || r.pass_no === undefined ? "" :
      "pass " + r.pass_no + (r.budget === null || r.budget === undefined ? "" : " of " + r.budget);
    return joined(["Running", pass, r.pass_started ? elapsed(r.pass_started) : "", S(r.note)]);
  }
  var names = { idle: "Idle", paused: "Paused", budget: "Daily budget used" };
  return joined([names[s] || s, S(r.note)]);
}

var LIVE_STALE_MS = 15 * 60 * 1000;

// The one silence rule, for the agent and for its sub-steps.
function agentSilent(a, generated) {
  var gen = Date.parse(generated), last = Date.parse(a.last);
  return !isNaN(gen) && !isNaN(last) && gen - last >= LIVE_STALE_MS;
}

function agentLive(a, generated) {
  return a.state === "running" && !agentSilent(a, generated);
}

// A sub-step shows the hourglass only while it is the agent's latest, still open, and the agent is not silent.
function liveSubstep(a, s, subs, generated) {
  var t = Date.parse(s.at);
  var later = subs.some(function (x) { return Date.parse(x.at) > t; });   // strictly later: same-second steps tie
  return !later && !agentSilent(a, generated) && a.state !== "ended" && a.state !== "done";   // stopped/failed keep it: #51 exam
}

// The one rule for "is this sub-step current": a live start, or a wait.
function stepOpen(a, s, subs, generated) {
  return (s.status === "wait" || s.status === "start") && liveSubstep(a, s, subs, generated);   // a stale wait is not open either
}

function agentCard(a, titles, workers, generated) {
  var subs = arr(a.substeps);
  var card = lel("div", null, "live-agent", { "data-agent-id": S(a.id), "data-state": S(a.state) });
  var head = el("div", null, "live-head");
  head.appendChild(el("b", (LIVE_ROLE_ICONS[a.role] || "") + " " + S(a.role)));
  var latest = latestKeys(a).pop(), lr = null;
  subs.forEach(function (s) { var r = stepRef(a, s); if (laneKey(r.repo, r.issue) === latest) lr = r; });
  lr = lr || { repo: S(a.repo), issue: Number(a.issue) };
  var issue = !(lr.issue > 0) ? "" : " " + laneLabel(lr.repo, lr.issue) + " " + S(titles[latest]) + " ";
  if (issue) head.appendChild(el("span", issue));
  card.appendChild(head);
  var done = subs.filter(function (s) { return s.status === "done"; }).length;
  card.appendChild(el("div", joined([elapsed(a.started, LIVE_ENDED[a.state] ? a.last : null), subs.length ? done + "/" + subs.length : ""]), "muted"));
  var cur = null;
  subs.forEach(function (s) { if (stepOpen(a, s, subs, generated)) cur = s; });
  var lastSub = subs[subs.length - 1];
  cur = cur || (lastSub && lastSub.status !== "start" ? lastSub : null);   // never name a stale start as "now"
  if (cur) {
    var now = el("div", "now: ", "live-now");
    now.appendChild(lel("b", S(cur.substep), "", { "data-current-substep": "" }));
    card.appendChild(now);
    if (S(cur.detail)) card.appendChild(el("div", S(cur.detail), "live-detail muted"));
  }
  var ul = el("ul", null, "live-steps");
  subs.forEach(function (s) {
    var icon = s.status === "start" ? (liveSubstep(a, s, subs, generated) ? LIVE_ICONS.start : "–") : (LIVE_ICONS[s.status] || "");
    var r = stepRef(a, s);
    ul.appendChild(lel("li", icon + " " + S(s.substep) + (r.issue > 0 ? " " + laneLabel(r.repo, r.issue) : ""), "",
      { "data-substep": S(s.substep), "data-status": S(s.status) }));
  });
  card.appendChild(ul);
  workers.forEach(function (w) { card.appendChild(workerCard(w)); });
  return card;
}

function workerCard(w) {
  var card = lel("div", null, "live-worker", { "data-worker-id": S(w.id), "data-state": S(w.state) });
  card.appendChild(el("span", null, "live-dot"));
  card.appendChild(el("b", " " + (LIVE_ROLE_ICONS[w.role] || "") + " " + S(w.role)));
  card.appendChild(el("span", " " + joined([S(w.state), S(w.tool)]), "muted"));
  var tools = w.tools && typeof w.tools === "object" ? w.tools : {};
  var keys = Object.keys(tools);
  if (keys.length) {
    card.appendChild(el("div", keys.map(function (k) { return k + " " + tools[k]; }).join(" · "), "muted"));
    var box = el("div", null, "live-spark");
    box.appendChild(sparkline(keys.map(function (k) { return Number(tools[k]) || 0; }),
      function (n, i) { return keys[i] + " " + n; }));
    card.appendChild(box);
  }
  return card;
}

// ---- Lanes: one pipeline per task in flight, click a station for its sub-steps and agents. ----
var snapPrs = null;
var laneOpen = Object.create(null);   // issue -> station the viewer expanded (kept across polls)
var LANE_DETAILS = 3;   // sub-step details a lane shows
var LANE_MARK = { done: "✓", active: "●", failed: "✗", waiting: "⏸", pending: "" };
var ROLE_STATION = { researcher: "plan", planner: "plan", "exam-writer": "exam", implementer: "build", reviewer: "check" };
var foldOpen = Object.create(null);   // collapsible section -> open, kept across polls

function crewRef(title, d) {   // "#12" is the host's issue; "factory#1" names a repository present in the snapshot
  var m = /([\w.-]+)?#(\d+)/.exec(S(title));
  if (!m) return null;
  var issue = Number(m[2]), short = (m[1] || "").toLowerCase();
  var repos = Object.keys((snap && snap.repos) || {}).concat(arr(d && d.issues).map(function (i) { return S(i.repo); }));
  for (var j = 0; j < repos.length; j++) {
    if (!repos[j]) continue;
    if (short && shortRepo(repos[j]).toLowerCase() === short) return { repo: repos[j], issue: issue };
  }
  for (var k = 0; k < repos.length; k++) {   // else the short name right before the reference: "factory #53", "Factory PR #53", "factory issue #53"
    var nm = shortRepo(repos[k] || "").replace(/[^\w]/g, "\\$&");
    if (!nm) continue;
    var at = new RegExp("(^|[^\\w-])" + nm + "(\\s+(?:PR|issue))?\\s*#(\\d+)", "i").exec(S(title));
    if (at && Number(at[3]) === issue) return { repo: repos[k], issue: issue };
  }
  return { repo: "", issue: issue };   // no prefix, or "PR#547": not a repository name, so the host's issue
}

function prFor(issue, repo) {
  if (!snapPrs) return null;
  var all = arr(snapPrs.open).map(function (p) { return { p: p, open: true }; })
    .concat(arr(snapPrs.merged).map(function (p) { return { p: p, open: false }; }));
  var tag = "(#" + issue + ")";
  for (var i = 0; i < all.length; i++) {
    if (S(all[i].p.title).indexOf(tag) >= 0 && (!all[i].p.repo || all[i].p.repo === repo)) return all[i];
  }
  return null;
}

function crewNodes(crew) {
  var out = [];
  (function walk(list) { arr(list).forEach(function (n) { out.push(n); walk(n.children); }); })(crew);
  return out;
}

function dur(a, b) {
  var t0 = Date.parse(a), t1 = b ? Date.parse(b) : Date.now();
  if (isNaN(t0) || isNaN(t1)) return "";
  var s = Math.max(0, Math.round((t1 - t0) / 1000));
  return s < 90 ? s + " s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h";
}

function stepRef(a, s) {   // the issue a step belongs to (its own, else its predecessor's, else the agent's first) and its repository ("" = this one)
  var subs = arr(a.substeps);
  for (var j = subs.indexOf(s); j >= 0; j--) if (Number(subs[j].issue) > 0) return { repo: S(subs[j].repo), issue: Number(subs[j].issue) };
  return { repo: S(a.repo), issue: Number(a.issue) };
}

var hostRepo = "";   // the first repository of the snapshot: a lane with repo "" belongs to it
function canonRepo(repo) { return repo || hostRepo; }
function laneKey(repo, n) { repo = canonRepo(repo); return repo ? repo + "#" + n : String(n); }
function laneLabel(repo, n) {   // a view shows one repository: the number is enough; with no view the repository stays named
  return (selRepo || !repo ? "" : shortRepo(repo)) + "#" + n;
}

function latestKeys(a) {   // the lane keys holding the agent's latest sub-steps (same-second steps tie), in step order
  var subs = arr(a.substeps), max = 0, out = [];
  subs.forEach(function (s) { max = Math.max(max, Date.parse(s.at) || 0); });
  subs.forEach(function (s) {
    var r = stepRef(a, s), k = laneKey(r.repo, r.issue);
    if ((Date.parse(s.at) || 0) === max && r.issue > 0 && out.indexOf(k) < 0) out.push(k);
  });
  return out.length ? out : [laneKey(S(a.repo), Number(a.issue))];
}

// A pass is over once the runner is idle, or has a pass_ended stamp (the renderer clears it on every pass-start).
function passEnded(d) {
  var r = (d && d.runner) || {};
  return S(r.state) === "idle" || !!r.pass_ended;
}

// The crew of an ended pass is history: nothing in it is working, and its last tool call is not "now".
function settleCrew(n) {
  var c = {};
  Object.keys(n).forEach(function (k) { c[k] = n[k]; });
  if (c.state === "busy" || c.state === "thinking") c.state = "finished";
  c.tool = "";
  c.children = arr(n.children).map(settleCrew);
  return c;
}

function laneData(d) {
  var ended = passEnded(d);
  var lanes = Object.create(null);
  arr(d.issues).forEach(function (i) {
    if (Number(i.issue) > 0) lanes[laneKey(S(i.repo), i.issue)] = { issue: Number(i.issue), repo: S(i.repo), key: laneKey(S(i.repo), i.issue), title: S(i.title), station: S(i.station), steps: [], agents: [], crew: [] };
  });
  arr(d.agents).forEach(function (a) {
    arr(a.substeps).forEach(function (s) {
      var r = stepRef(a, s), l = lanes[laneKey(r.repo, r.issue)];
      if (!l) return;
      if (l.agents.indexOf(a) < 0) l.agents.push(a);
      l.steps.push({ s: s, a: a, open: stepOpen(a, s, arr(a.substeps), d.generated_at) });
    });
  });
  crewNodes(arr(d.crew).slice(0, 1)).forEach(function (n) {   // the current pass only: older passes' agents confuse the lane
    var r = crewRef(n.title, d), k = r ? laneKey(r.repo, r.issue) : "";
    if (r && lanes[k]) lanes[k].crew.push(n);
  });
  return Object.keys(lanes).map(function (k) {
    var l = lanes[k];
    l.last = l.steps.reduce(function (m, x) { return S(x.s.at) > m ? S(x.s.at) : m; }, "");
    // last update of any kind: a logged step or an agent's own activity on this task
    l.updated = l.crew.reduce(function (m, n) {
      return Date.parse(S(n.last)) > (Date.parse(m) || 0) ? S(n.last) : m;
    }, l.last);
    l.first = l.steps.reduce(function (m, x) { return !m || S(x.s.started) < m ? S(x.s.started) : m; }, "");
    var busy = ended ? [] : l.crew.filter(function (n) { return n.state === "busy" || n.state === "thinking"; });
    var openSteps = l.steps.filter(function (x) { return x.open; });
    l.running = !ended && (busy.length > 0 || l.agents.some(function (a) { return agentLive(a, d.generated_at) && latestKeys(a).indexOf(l.key) >= 0; }));
    var cur = LIVE_STATIONS.indexOf(l.station);
    busy.forEach(function (n) {   // an agent at work is the strongest evidence of where the task is
      var at = LIVE_STATIONS.indexOf(ROLE_STATION[S(n.type)] || "");
      if (at > cur) cur = at;
    });
    l.cur = cur;
    l.pr = prFor(l.issue, canonRepo(l.repo));   // only this repository's pull requests
    var merged = l.pr && !l.pr.open;
    l.shipped = !busy.length && !openSteps.some(function (x) { return x.s.station !== "ship"; }) && (merged ||
      (l.station === "ship" && l.steps.some(function (x) { return x.s.station === "ship" && x.s.status === "done"; }) && !openSteps.length));
    if (l.shipped) { l.running = false; cur = LIVE_STATIONS.length - 1; l.cur = cur; }
    var open = openSteps.slice().sort(function (a, b) { return S(a.s.started) < S(b.s.started) ? 1 : -1; })[0];
    var latest = l.steps.slice().sort(function (a, b) { return S(a.s.at) < S(b.s.at) ? 1 : -1; })[0];
    l.now = open || latest || null;
    l.nowOpen = !!open;
    l.marks = LIVE_STATIONS.map(function (st, idx) {
      var here = l.steps.filter(function (x) { return x.s.station === st; });
      var latest = here.reduce(function (m, x) { return !m || S(x.s.at) >= S(m.s.at) ? x : m; }, null);
      if (latest && latest.s.status === "fail" && idx >= cur) return "failed";
      if (idx < cur || l.shipped) return "done";
      if (idx === cur) return l.running ? "active" : "waiting";
      return "pending";
    });
    return l;
  }).sort(function (a, b) {
    return (Number(b.running) - Number(a.running)) || (Number(a.shipped) - Number(b.shipped)) || (S(b.last) > S(a.last) ? 1 : -1);
  });
}

function agentLine(n) {
  var row = lel("div", null, "lane-agent", { "data-state": S(n.state) });
  row.appendChild(el("span", null, "live-dot"));
  row.appendChild(el("b", " " + (LIVE_ROLE_ICONS[n.type] || LIVE_ROLE_ICONS.agent) + " " + S(n.type)));
  var what = n.tool ? S(n.tool) + (n.label ? " · " + S(n.label) : "") : (CREW_STATES[n.state] || S(n.state));
  row.appendChild(el("span", " " + what, n.tool ? "" : "muted"));
  if (n.last) row.appendChild(el("span", " · " + ago(n.last), "muted"));
  return row;
}

function laneDetail(l, st) {
  var box = lel("div", null, "lane-detail", { "data-lane-detail": st });
  box.appendChild(el("b", st.charAt(0).toUpperCase() + st.slice(1) + ": sub-steps"));
  var steps = l.steps.filter(function (x) { return x.s.station === st; })
    .sort(function (a, b) { return S(a.s.started) < S(b.s.started) ? -1 : 1; });
  if (!steps.length) box.appendChild(el("div", "No sub-steps recorded for this station.", "muted"));
  var ul = el("ul", null, "lane-steps");
  steps.forEach(function (x) {
    var open = x.open;
    var li = lel("li", null, "", { "data-status": S(x.s.status) });
    li.appendChild(el("span", (x.s.status === "start" && !open ? "–" : LIVE_ICONS[x.s.status] || "") + " "));
    li.appendChild(el("b", S(x.s.substep)));
    li.appendChild(el("span", " · " + joined([(LIVE_ROLE_ICONS[x.a.role] || "") + " " + S(x.a.role),
      clock(x.s.started), open ? "running " + dur(x.s.started) : x.s.status === "start" ? "" : dur(x.s.started, x.s.at)]), "muted"));
    if (x.s.detail) li.appendChild(el("div", S(x.s.detail), "lane-step-detail"));
    ul.appendChild(li);
  });
  box.appendChild(ul);
  var roles = { plan: ["manager", "researcher", "planner"], exam: ["exam-writer"], build: ["implementer"],
    check: ["reviewer", "implementer"], ship: ["manager"] }[st] || [];
  var who = l.crew.filter(function (n) { return roles.indexOf(S(n.type)) >= 0; });
  if (who.length) {
    box.appendChild(el("b", "Agents on this station"));
    who.forEach(function (n) { box.appendChild(agentLine(n)); });
  }
  return box;
}

function renderLanes(d, rerender) {
  var lanes = laneData(d);
  var sec = el("div", null, "lanes");
  var root = arr(d.crew)[0];
  var mgr = el("div", null, "lane-manager");
  mgr.appendChild(el("b", "🧭 Manager "));
  var rr = d.runner || {};
  var idle = passEnded(d);   // between passes: the crew block is the ended pass's, not live
  if (idle) {
    mgr.appendChild(el("span", joined(["Idle", rr.result ? "last pass: " + S(rr.result) : "",
      rr.pass_ended ? "ended " + agoAt(rr.pass_ended) : ""]), "muted"));
  } else if (root) {
    mgr.appendChild(lel("span", null, "live-dot", { "data-state": S(root.state) }));
    mgr.appendChild(el("span", " " + (CREW_STATES[root.state] || S(root.state)) +
      (root.tool ? " · now: " + S(root.tool) + (root.label ? " “" + S(root.label) + "”" : "") : "")));
  } else {
    mgr.appendChild(el("span", runnerText(d.runner || {}), "muted"));
  }
  sec.appendChild(mgr);
  var host = idle ? el("div", null, "lane-last") : sec;   // the lanes of an ended pass are history, folded under "Last pass"
  var nRun = lanes.filter(function (l) { return l.running; }).length;
  var nDone = lanes.filter(function (l) { return l.shipped; }).length;
  if (!idle) sec.appendChild(el("div", joined([lanes.length + " task" + (lanes.length === 1 ? "" : "s") + " in this pass",
    nRun + " working in parallel", nDone ? nDone + " shipped" : "", "click a station for its sub-steps"]), "muted"));
  var done = idle ? [] : lanes.filter(function (l) { return l.shipped; });
  lanes.filter(function (l) { return idle || !l.shipped; }).forEach(function (l) {
    var lane = lel("div", null, "lane", { "data-lane": l.key, "data-running": l.running && !idle ? "1" : "0" });
    var head = el("div", null, "lane-head");
    head.appendChild(el("b", laneLabel(l.repo, l.issue) + " " + l.title));
    var pr = l.pr;
    head.appendChild(el("span", " " + joined([pr ? "PR #" + S(pr.p.number) + (pr.open ? "" : " merged") : "",
      idle ? (l.shipped ? "shipped" : l.marks.indexOf("failed") >= 0 ? "failed" : "paused") : l.running ? "working" : "waiting", l.first && !idle ? "for " + dur(l.first) : "", l.updated ? "last update " + agoAt(l.updated) : ""]), "muted"));
    lane.appendChild(head);
    var bar = el("div", null, "lane-bar");
    LIVE_STATIONS.forEach(function (st, idx) {
      var mark = l.marks[idx];
      var b = lel("button", null, "lane-st", { type: "button", "data-mark": mark, "data-st": st,
        "aria-expanded": laneOpen[l.key] === st ? "true" : "false" });
      b.appendChild(el("span", LANE_MARK[mark] ? LANE_MARK[mark] + " " : ""));
      b.appendChild(el("span", st.charAt(0).toUpperCase() + st.slice(1)));
      var n = l.steps.filter(function (x) { return x.s.station === st; }).length;
      if (n) b.appendChild(el("span", " " + n, "lane-count"));
      b.addEventListener("click", function () {
        laneOpen[l.key] = laneOpen[l.key] === st ? null : st;
        rerender();
      });
      bar.appendChild(b);
    });
    lane.appendChild(bar);
    if (l.now) {
      var nowLine = el("div", null, "lane-now");
      nowLine.appendChild(el("span", l.nowOpen ? "now: " : "last: "));
      nowLine.appendChild(el("b", S(l.now.s.substep)));
      nowLine.appendChild(el("span", " · " + joined([(LIVE_ROLE_ICONS[l.now.a.role] || "") + " " + S(l.now.a.role),
        S(l.now.s.station), l.now.open ? dur(l.now.s.started) : ago(l.now.s.at)]), "muted"));
      lane.appendChild(nowLine);
    }
    l.steps.filter(function (x) { return S(x.s.detail) && x.s.station !== laneOpen[l.key]; })   // the open panel lists its own
      .sort(function (a, b) { return S(a.s.started) < S(b.s.started) ? -1 : 1; })
      .slice(-LANE_DETAILS)
      .forEach(function (x) { lane.appendChild(el("div", S(x.s.detail), "lane-step-detail muted")); });
    l.crew.filter(function (n) { return !idle && (n.state === "busy" || n.state === "thinking"); })
      .forEach(function (n) { lane.appendChild(agentLine(n)); });
    if (laneOpen[l.key]) lane.appendChild(laneDetail(l, laneOpen[l.key]));
    host.appendChild(lane);
  });
  if (idle && lanes.length) {
    var nShipped = lanes.filter(function (l) { return l.shipped; }).length;
    var nFailed = lanes.filter(function (l) { return !l.shipped && l.marks.indexOf("failed") >= 0; }).length;
    sec.appendChild(fold("last-pass", "Last pass: " + joined([nShipped + " shipped", (lanes.length - nShipped - nFailed) + " paused",
      nFailed ? nFailed + " failed" : ""]), host, true));
  }
  if (done.length) {
    var row = el("div", null, "lane-done");
    row.appendChild(el("b", "✓ Shipped this pass: "));
    done.forEach(function (l, i) {
      row.appendChild(el("span", (i ? " · " : "") + laneLabel(l.repo, l.issue) + " " + l.title + (l.pr ? " (PR #" + S(l.pr.p.number) + ")" : "")));
    });
    sec.appendChild(row);
  }
  return sec;
}

function fold(key, summary, content, startOpen) {
  var d = lel("details", null, "fold", { "data-fold": key });
  if (foldOpen[key] === undefined ? startOpen : foldOpen[key]) d.setAttribute("open", "");
  d.appendChild(el("summary", summary));
  d.appendChild(content);
  if (d.addEventListener) d.addEventListener("toggle", function () { foldOpen[key] = d.hasAttribute("open"); });
  return d;
}

// ---- Crew: every agent and subagent from the transcripts (scripts/factory_crew.py), nested by parent.
var CREW_STATES = { busy: "working", thinking: "thinking", waiting: "waiting on its agents", idle: "idle", finished: "finished" };

// Every age on the page: seconds below 120 s, then minutes below 90 min, then hours ("" for a broken value).
function ago(iso) {
  var t = Date.parse(iso);
  if (isNaN(t)) return "";
  var s = Math.max(0, Math.round((Date.now() - t) / 1000));
  return s < 120 ? s + " s ago" : s < 5400 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago";
}

function crewCard(n, depth) {
  var card = lel("div", null, "crew-card", { "data-crew-id": S(n.id), "data-state": S(n.state), "data-kind": S(n.kind) });
  var head = el("div", null, "crew-head");
  head.appendChild(el("span", null, "live-dot"));
  head.appendChild(el("b", " " + (LIVE_ROLE_ICONS[n.type] || LIVE_ROLE_ICONS.agent) + " " + S(n.type)));
  if (n.title) head.appendChild(el("span", " " + S(n.title), "crew-title"));
  card.appendChild(head);
  card.appendChild(el("div", joined([CREW_STATES[n.state] || S(n.state), S(n.model),
    n.started ? elapsed(n.started, n.state === "finished" ? n.last : null) : "", n.last ? "last active " + ago(n.last) : ""]), "muted"));
  if (n.tool) {
    var now = el("div", "now: ", "crew-now");
    now.appendChild(el("b", S(n.tool)));
    if (n.label) now.appendChild(el("span", " " + S(n.label)));
    card.appendChild(now);
  }
  var recent = arr(n.recent);
  if (recent.length) {
    var chips = el("div", null, "crew-recent");
    recent.forEach(function (t) { chips.appendChild(el("span", S(t), "crew-chip")); });
    card.appendChild(chips);
  }
  var kids = arr(n.children);
  if (kids.length && depth < 4) {
    var box = el("div", null, "crew-kids");
    kids.forEach(function (c) { box.appendChild(crewCard(c, depth + 1)); });
    if (Number(n.more) > 0) box.appendChild(el("div", "+" + Number(n.more) + " more", "muted"));
    card.appendChild(box);
  }
  return card;
}

function renderCrew(crew) {
  var list = arr(crew);
  if (!list.length) return null;
  var sec = el("div", null, "crew");
  list.forEach(function (n) { sec.appendChild(crewCard(n, 0)); });
  return sec;
}

function quiet(d) {
  return !!LIVE_QUIET[S((d.runner || {}).state)];
}

function liveAgeText(d) {
  var a = ago(d.generated_at);
  return a ? " · " + (quiet(d) ? "idle, last check " : "") + a : "";
}

function showRunner(d) {
  var r = document.getElementById("runner");
  if (r) r.textContent = "Runner: " + runnerText(d.runner || {}) + liveAgeText(d);
}

function inView(d) {   // live.json narrowed to the selected repository (the runner and the log are shared)
  if (!selRepo) return d;
  var view = {};
  Object.keys(d).forEach(function (k) { view[k] = d[k]; });
  view.issues = mine(d.issues);
  view.agents = [];
  arr(d.agents).forEach(function (a) {   // keep each agent's steps of this repository only
    var subs = arr(a.substeps);
    var own = subs.filter(function (x) {
      var r = stepRef(a, x);
      return !(Number(r.issue) > 0) || canonRepo(r.repo) === selRepo;
    });
    if (subs.length && !own.length) return;
    var copy = {};
    Object.keys(a).forEach(function (k) { copy[k] = a[k]; });
    copy.substeps = own;
    view.agents.push(copy);
  });
  view.log = arr(d.log).filter(function (e) { return !(Number(e.issue) > 0) || canonRepo(S(e.repo)) === selRepo; });
  view.crew = arr(d.crew).map(function prune(n) {   // d: the full live data
    var c = {};
    Object.keys(n).forEach(function (k) { c[k] = n[k]; });
    c.children = arr(n.children).filter(function (k) {
      var r = crewRef(k.title, d);
      return !r || canonRepo(r.repo) === selRepo;
    }).map(prune);
    return c;
  });
  return view;
}

function renderLive(full) {
  showRunner(full);
  var d = inView(full);
  if (passEnded(d)) d.crew = arr(d.crew).map(settleCrew);
  var titles = Object.create(null);
  var box = el("div", null, "live-box");
  var runner = el("div", runnerText(d.runner || {}), "live-runner");
  var age = el("span", liveAgeText(d), "muted");
  age.id = "live-age";
  runner.appendChild(age);
  box.appendChild(runner);

  box.appendChild(renderLanes(d, function () { renderLive(full); }));

  var line = el("div", null, "live-line");
  var at = {};
  LIVE_STATIONS.forEach(function (name) {
    var st = lel("div", null, "live-station", { "data-live-station": name });
    st.appendChild(el("b", name.charAt(0).toUpperCase() + name.slice(1)));
    at[name] = st;
    line.appendChild(st);
  });
  function station(name) { return at[S(name).toLowerCase()] || at.plan; }
  arr(d.issues).filter(function (i) { return Number(i.issue) > 0; }).forEach(function (i) {
    titles[laneKey(S(i.repo), i.issue)] = S(i.title);
    station(i.station).appendChild(el("div", laneLabel(S(i.repo), i.issue) + " " + S(i.title), "live-issue"));
  });
  // Workers carry no issue: one running agent with the same role owns the worker, else it goes in the row.
  var agents = arr(d.agents);
  var ownWorkers = Object.create(null);
  var loose = [];
  arr(full.workers).forEach(function (w) {   // matched on the full live data: workers carry no repository
    var same = arr(full.agents).filter(function (a) { return a.state === "running" && a.role === w.role; });
    if (same.length === 1) (ownWorkers[same[0].id] = ownWorkers[same[0].id] || []).push(w);
    else loose.push(w);
  });
  agents.forEach(function (a) { station(a.station).appendChild(agentCard(a, titles, ownWorkers[a.id] || [], d.generated_at)); });
  var stationsBox = el("div");
  stationsBox.appendChild(line);
  if (loose.length) {
    var row = el("div", null, "live-workers");
    loose.forEach(function (w) { row.appendChild(workerCard(w)); });
    stationsBox.appendChild(row);
  }
  box.appendChild(fold("stations", "All stations: every agent card with its sub-steps and tool use", stationsBox, false));

  var crew = renderCrew(d.crew);
  if (crew) {
    var all = crewNodes(d.crew);
    var working = all.filter(function (n) { return n.state === "busy" || n.state === "thinking"; }).length;
    box.appendChild(fold("crew", "Crew: " + all.length + " agents and subagents, " + working + " working", crew, false));
  }

  var log = el("div", null, "live-log");
  arr(d.log).slice(-LIVE_LOG_MAX).reverse().forEach(function (e) {
    log.appendChild(lel("div", joined([clock(e.at), S(e.agent), S(e.station), S(e.substep), S(e.status),
      S(e.detail)]), "live-row", { "data-log-row": "" }));
  });
  box.appendChild(fold("log", "Log: the last " + Math.min(arr(d.log).length, LIVE_LOG_MAX) + " steps, newest first", log, false));

  var body = document.getElementById("live-body");
  body.textContent = "";
  body.appendChild(box);
}

function showOffline() {
  var age = document.getElementById("live-age");
  if (age && lastLive) age.textContent = liveAgeText(lastLive);
  if (lastLive) showRunner(lastLive);
  var t = lastLive ? Date.parse(lastLive.generated_at) : NaN;
  // A fresh node every poll: the exam harness's ser() keeps attrs by reference, so a toggled node
  // would show its last state in every step.
  var banner = el("p", "Laptop offline or asleep: showing the last state received.", "live-offline");
  banner.id = "live-offline";
  banner.hidden = isNaN(t) || Date.now() - t <= (quiet(lastLive) ? LIVE_IDLE_OFFLINE_MS : LIVE_OFFLINE_MS);
  var old = document.getElementById("live-offline");
  if (old) old.remove();
  var body = document.getElementById("live-body");
  body.parentNode.insertBefore(banner, body);
}

function pollLive() {
  if (livePending) return;
  livePending = true;
  var ctl = typeof AbortController === "function" ? new AbortController() : null;
  var timer = ctl ? setTimeout(function () { ctl.abort(); }, 10000) : null;
  fetch("live.json?t=" + Date.now(), ctl ? { cache: "no-store", signal: ctl.signal } : { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.text();
    })
    .then(function (raw) {
      if (raw === lastRaw) return;
      var d = JSON.parse(raw);
      if (!d || typeof d !== "object" || d.schema !== 1) throw new Error("not live.json");
      if (lastLive && Date.parse(d.generated_at) < Date.parse(lastLive.generated_at)) return;
      renderLive(d);
      lastLive = d;
      lastRaw = raw;
    })
    .catch(function () { /* empty, half-written or unreachable: keep the last good state */ })
    .then(function () {
      if (timer !== null) clearTimeout(timer);
      livePending = false;
      showOffline();
      showAge();
    });
}

window.addEventListener("hashchange", function () {
  if (!snap) return;
  render(snap);
  if (lastLive) renderLive(lastLive);
});

load();
pollLive();
setInterval(pollLive, 3000);
setInterval(load, 5 * 60 * 1000);
setInterval(showAge, 5 * 1000);
