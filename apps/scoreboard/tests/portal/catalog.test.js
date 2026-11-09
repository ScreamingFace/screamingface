"use strict";
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const logic = require('../../portal/leaderboard-logic.js');

function element(tag) {
  return {tag, children: [], attrs: {}, listeners: {}, hidden: false, value: '', checked: false,
    textContent: '', get firstChild() { return this.children[0] || null; },
    appendChild(child) { this.children.push(child); return child; },
    removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); },
    fire(k) { (this.listeners[k] || []).forEach(fn => fn()); }, focus() { this.focused = true; }};
}
const catalog = Array.from({length: 22}, (_, i) => ({id: `b-${i}`, display_name: `Board ${String(i).padStart(2,'0')}`, best_score: i === 0 ? 0 : i === 1 ? -2 : .5}));
catalog.push({id: 'unscored', display_name: 'Empty', best_score: null});
async function page(data = catalog, fail = false) {
  const nodes = Object.fromEntries(['status','cards','more','search','scored','count','clear','include','controls'].map(k => [`benchmark-${k}`,element('div')]));
  nodes['benchmark-scored'].checked = true;
  const requests=[];
  const context={window:{SFLeaderboardLogic:logic,location:{protocol:'http:',origin:'http://test'}},
    SFLeaderboardLogic:logic, document:{readyState:'complete',createElement:element,
      getElementById(id){return nodes[id] || null;},addEventListener(){}},
    fetch:async url=>{requests.push(url);if(fail) throw Error('offline');return {ok:true,text:async()=>JSON.stringify({benchmarks:data})};}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../portal/main.js'),'utf8'),context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../portal/catalog.js'),'utf8'),context);
  await new Promise(setImmediate);
  const ids=()=>nodes['benchmark-cards'].children.map(c=>new URL(c.attrs.href,'http://test').searchParams.get('id'));
  return {nodes,requests,ids, query(value){nodes['benchmark-search'].value=value;nodes['benchmark-search'].fire('input');}};
}
test('one summary request, alphabetical scores including zero/negative, nine per batch',async()=>{
  const p=await page([...catalog].reverse());
  assert.deepEqual(p.requests,['http://test/v1/benchmarks/summary']);
  assert.deepEqual(p.ids(),catalog.slice(0,9).map(b=>b.id));
  p.nodes['benchmark-more'].fire('click');assert.equal(p.ids().length,18);
  p.nodes['benchmark-more'].fire('click');assert.equal(p.ids().length,22);
  assert.equal(p.nodes['benchmark-more'].hidden,true);
  assert.equal(p.requests.length,1);
});
test('search reaches beyond page one, trims/case-folds and clearing resets paging',async()=>{
  const p=await page();p.query('  BOARD 21  ');assert.deepEqual(p.ids(),['b-21']);
  p.query('B-20');assert.deepEqual(p.ids(),['b-20']);
  p.nodes['benchmark-clear'].fire('click');assert.equal(p.ids().length,9);
  assert.equal(p.nodes['benchmark-search'].value,'');
  assert.equal(p.nodes['benchmark-search'].focused,true);
});
test('include unscored retains query, filter applies before pagination',async()=>{
  const p=await page();p.query('empty');assert.deepEqual(p.ids(),[]);
  assert.equal(p.nodes['benchmark-include'].hidden,false);
  p.nodes['benchmark-include'].fire('click');assert.deepEqual(p.ids(),['unscored']);
  assert.equal(p.nodes['benchmark-search'].value,'empty');
  assert.equal(p.nodes['benchmark-scored'].checked,false);
  p.query('');assert.equal(p.ids().length,9);
});
test('no matches, empty catalog and failed summary have distinct states',async()=>{
  const p=await page();p.query('missing');assert.deepEqual(p.ids(),[]);
  assert.equal(p.nodes['benchmark-status'].className,'state state-empty');
  assert.equal(p.nodes['benchmark-include'].hidden,true);
  const empty=await page([]);assert.equal(empty.nodes['benchmark-status'].className,'state state-empty');
  const failed=await page([],true);assert.equal(failed.nodes['benchmark-status'].className,'state state-error');
  assert.equal(failed.nodes['benchmark-controls'].hidden,true);
  assert.equal(failed.requests.length,1);
});
