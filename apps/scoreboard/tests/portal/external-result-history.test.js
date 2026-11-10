"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function node(tag, cls, text) {
  return {tag, className: cls, textContent: text == null ? "" : String(text), children: [], attrs: {}, hidden: false,
    appendChild(n) { this.children.push(n); return n; },
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(k, v) { this[k] = v; },
  };
}
const descendants = n => [n, ...n.children.flatMap(descendants)];
async function load(responses, params={benchmark:"board", result:"row"}) {
  const ids = {};
  const calls = [];
  const P = {
    el: node, link(cls, href, text) { const n=node("a",cls,text); n.setAttribute("href",href); return n; },
    formatDate: v => v || "—", formatScore: v => String(v), EM_DASH: "—",
    httpUrlOrNull(v) { try { const u=new URL(v); return ["http:","https:"].includes(u.protocol) ? u.href : null; } catch { return null; } },
    requireParam(k) { if (!params[k]) throw Error("missing"); return params[k]; },
    ready(fn) { fn(); },
    fetchJson(url) { calls.push(url); const r=responses.shift(); return r instanceof Error ? Promise.reject(r) : Promise.resolve(r); },
  };
  const context = { window: {ScorePortal:P}, document: { getElementById(id) { return ids[id] || (ids[id]=node("div")); } }, encodeURIComponent, URL, Number };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../../portal/external-result-history.js"),"utf8"), context);
  await new Promise(resolve=>setImmediate(resolve));
  return {ids,calls};
}
const version = (revision, score, source_url="https://example.org/results") => ({revision, score, source_url, recorded_at: null, observed_at: "2026-11-01T00:00:00Z", metric_name:"accuracy", metadata:{comparison_note:"<script>unsafe()</script>"}});
const response = (versions, next_before=null) => ({model_name:"<img onerror=x>", current_revision:3, versions,next_before});

test("history shows current and previous values with safe links and literal text", async()=>{
  const {ids}=await load([response([version(3,0.82),version(2,0.8,"javascript:alert(1)")])]);
  assert.equal(ids["history-model"].textContent,"<img onerror=x>");
  const cards=ids["history-versions"].children;
  assert.equal(cards.length,2);
  const text=cards.map(c=>descendants(c).map(n=>n.textContent));
  assert.ok(text[0].includes("Current result"));
  assert.ok(text[1].includes("Previous result"));
  assert.ok(text[0].includes("0.82"));
  assert.ok(text[0].includes("Date unknown"));
  assert.ok(text[0].includes("<script>unsafe()</script>"));
  const links=descendants(cards[0]).filter(n=>n.tag==="a");
  assert.equal(links[0].attrs.href,"https://example.org/results");
  assert.equal(links[0].attrs.rel,"noopener noreferrer");
  assert.equal(descendants(cards[1]).filter(n=>n.tag==="a").length,0);
});

test("more history appends a bounded older page and preserves the current label",async()=>{
  const {ids,calls}=await load([response([version(3,0.82),version(2,0.8)],2),response([version(1,0.7)])]);
  await ids["history-more"].click();
  assert.equal(calls[1],"/v1/leaderboard/board/external-results/row/history?limit=20&before=2");
  assert.equal(ids["history-versions"].children.length,3);
  assert.equal(ids["history-more"].hidden,true);
});

test("load errors offer a retry and missing parameters make no request",async()=>{
  const {ids}=await load([Error("offline"),response([version(3,0.82)])]);
  assert.equal(ids["history-status"].textContent,"Could not load history. Try again.");
  assert.equal(ids["history-more"].textContent,"Retry");
  await ids["history-more"].click();
  assert.equal(ids["history-versions"].children.length,1);
  const missing=await load([],{});
  assert.equal(missing.calls.length,0);
  assert.equal(missing.ids["history-status"].textContent,"Open history from a leaderboard result.");
});

test("no retained versions has an honest empty state",async()=>{
  const {ids}=await load([response([])]);
  assert.equal(ids["history-status"].textContent,"No saved history yet.");
});
