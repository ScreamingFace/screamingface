"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
function node(tag, cls, text) {
  return {tag, className: cls, textContent: text == null ? "" : String(text), children: [], attrs: {},
    appendChild(n) { this.children.push(n); return n; },
    setAttribute(k, v) { this.attrs[k] = v; },
  };
}
const P = {el:node, EM_DASH:"—", formatDate:v=>v,
  link(cls, href, text) { const n=node("a",cls,text); n.setAttribute("href",href); return n; }};
const context={window:{ScorePortal:P},URL};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,"../../portal/external-results.js"),"utf8"),context);
const external = context.window.SFExternalResults;
const baseline={id:"outside",model_name:"Example model",score:0.8,ranking_eligible:true,source_url:"https://example.org/table"};
function render(health) {
  const [row]=external.selectRows([], [{...baseline,source_health:health}], 50);
  return external.renderRow(row,node("td",null,"0.8"));
}
test("unchecked source keeps rank, score and clickable Source button with visible date",()=>{
  const row=render({available:false,checked_at:"2026-11-11",last_available_at:"2026-11-10T10:00:00Z"});
  assert.equal(row.children[0].textContent,"1");
  assert.equal(row.children[5].textContent,"0.8");
  const source=row.children[8];
  assert.equal(source.children[0].textContent,"Source ↗");
  assert.equal(source.children[0].attrs.href,baseline.source_url);
  assert.equal(source.children[0].attrs.rel,"noopener noreferrer");
  assert.equal(source.children[1].textContent,"Source unchecked");
  assert.equal(source.children[2].textContent,"Last available Nov 10, 2026");
});
test("first failure has no invented successful check date",()=>{
  const source=render({available:false,last_available_at:null}).children[8];
  assert.equal(source.children[2].textContent,"No successful check yet");
});
test("healthy, recovered and unknown sources have no failure notice",()=>{
  for (const health of [undefined,null,{available:true},{available:"false"}]) {
    assert.equal(render(health).children[8].children.length,1);
  }
});
test("source checks do not change mixed ranking",()=>{
  const rows=external.selectRows([{score:0.7,spec_id:"Community"}], [{...baseline,source_health:{available:false}}],50);
  assert.deepEqual(Array.from(rows,r=>[r.spec_id,r.rank,r.score]),[["Example model",1,0.8],["Community",2,0.7]]);
});
