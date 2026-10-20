const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const crypto = require('node:crypto');
const python = fs.readFileSync('src/screamingface/_analytics/colab.py', 'utf8');
const source = python.split('_SCRIPT = r"""')[1].split('"""')[0];
const origin = 'https://analytics.dev.screamingface.ai';
function run(command, choice='unknown', options={}) {
  const calls=[], listeners=new Set();
  let removed=false, timeout, pending;
  const frame={remove:()=>{removed=true}, contentWindow:{postMessage(message,target) {
    assert.equal(target,origin);
    calls.push(message.command);
    if(options.noReply) return;
    const result=message.command==='id' ? {choice:'accepted',consent_version:'1',
      persistent_id:'40ac79d4-3b7c-4eac-82db-535281ce7085',id_scope:'browser'} :
      {choice:message.command==='decline'?'declined':choice,consent_version:'1'};
    const data={...message,result};
    pending={source:frame.contentWindow,origin,data};
    if(!options.manual) queueMicrotask(()=>{
      for(const handler of [...listeners]) handler(pending);
    });
  }}};
  const context={document:{createElement:()=>frame,body:{appendChild:()=>{
    if(!options.noLoad) queueMicrotask(()=>frame.onload());
  }}},location:{origin:'https://abc-0123456789abcdef-0-colab.googleusercontent.com'},
    window:{addEventListener:(_,fn)=>listeners.add(fn),removeEventListener:(_,fn)=>listeners.delete(fn)},
    crypto,encodeURIComponent,clearTimeout,
    setTimeout:(fn)=>{timeout=setTimeout(fn,options.timeout??1000);return timeout}};
  const promise=vm.runInNewContext(source.replace('COMMAND',JSON.stringify(command))
    .replace('ANALYTICS_ORIGIN',JSON.stringify(origin)).replace('BATCH',JSON.stringify({events:[]})).replace('TIMEOUT_MS','1800'),context);
  return {promise,calls,frame,listeners,get removed(){return removed},
    get reply(){return pending},
    send(message){for(const handler of [...listeners]) handler(message)}};
}
test('unknown/declined state never asks for ID',async()=>{
  for(const choice of ['unknown','declined']) {
    const h=run('state',choice);
    assert.equal((await h.promise).choice,choice);
    assert.deepEqual(h.calls,['state']);
    assert.equal(h.removed,true);assert.equal(h.listeners.size,0);
    assert.ok(h.frame.src.includes('parent_origin=https%3A%2F%2Fabc-'));
    assert.equal(h.frame.referrerPolicy,'no-referrer');
  }
});
test('accepted state and acceptance never initiate ID retrieval themselves',async()=>{
  for(const command of ['state','accept']) {
    const h=run(command,'accepted');
    assert.equal((await h.promise).choice,'accepted');
    assert.deepEqual(h.calls,[command]);
  }
  const h=run('id','accepted');
  assert.equal((await h.promise).id_scope,'browser');
  assert.deepEqual(h.calls,['id']);
});
for(const field of ['source','origin','version','nonce','command','missing-data']) {
  test(`forged ${field} cannot resolve a request`,async()=>{
    const h=run('state','accepted',{manual:true});
    let resolved=false;
    h.promise.then(()=>{resolved=true});
    await new Promise(r=>setImmediate(r));
    const good=h.reply;
    const forged={...good,data:{...good.data,result:{choice:'forged'}}};
    if(field==='source') forged.source={};
    else if(field==='origin') forged.origin='https://evil.example';
    else if(field==='missing-data') forged.data=null;
    else forged.data[field]=field==='version'?2:'wrong';
    h.send(forged);
    await new Promise(r=>setImmediate(r));
    assert.equal(resolved,false);
    assert.equal(h.listeners.size,1);
    assert.equal(h.removed,false);
    assert.deepEqual(h.calls,['state']);
    h.send(good);
    assert.equal((await h.promise).choice,'accepted');
    assert.equal(h.listeners.size,0);
    assert.equal(h.removed,true);
  });
}
test('events use bridge transport only',async()=>{
  const h=run('events');await h.promise;
  assert.deepEqual(h.calls,['events']);
});
test('hung load and reply clean up and fail closed',async()=>{
  for(const option of [{noLoad:true},{noReply:true}]) {
    const h=run('state','accepted',{...option,timeout:5});
    assert.equal((await h.promise).unavailable,true);
    assert.equal(h.removed,true);assert.equal(h.listeners.size,0);
    if(option.noLoad) {h.frame.onload();await new Promise(r=>setImmediate(r));}
    assert.ok(!h.calls.includes('id'));
  }
});
