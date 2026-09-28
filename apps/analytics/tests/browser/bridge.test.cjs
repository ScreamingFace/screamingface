const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('src/analytics_service/bridge.js', 'utf8');
function setup(fetcher = async () => ({ok:true,json:async()=>({choice:'unknown'})})) {
  let handler;
  const messages=[], requests=[];
  const parent={postMessage:(...args)=>messages.push(args)};
  const context = {allowedParents:['https://output.example'],window:{parent,
    addEventListener:(name, callback)=>{handler=callback;}},
    fetch:async (...args)=>{requests.push(args);return fetcher(...args);},
    AbortController, TextEncoder, setTimeout, clearTimeout};
  vm.runInNewContext(source,context);
  const send=(data={},overrides={})=>handler({source:parent,origin:'https://output.example',
    data:{version:1,nonce:'0123456789abcdef',command:'state',...data},...overrides});
  return {send,messages,requests};
}
test('strict source, origin, schema and commands reject without network/reply',async()=>{
  const h=setup();
  await h.send({}, {origin:'null'}); await h.send({}, {source:{}});
  await h.send({}, {origin:'https://output.example.evil'});
  await h.send({command:'navigate',url:'https://evil.example'});
  await h.send({nonce:'bad'}); await h.send({version:2});
  await h.send({extra:'private'});
  assert.equal(h.requests.length,0);assert.equal(h.messages.length,0);
});
test('state uses same origin cookies and exact reply target',async()=>{
  const h=setup(); await h.send();
  assert.equal(h.requests[0][0],'/bridge/consent/state');
  assert.equal(h.requests[0][1].credentials,'same-origin');
  assert.equal(h.requests[0][1].redirect,'error');
  assert.equal(h.messages[0][1],'https://output.example');
  assert.equal(h.messages[0][0].nonce,'0123456789abcdef');
  assert.equal(h.messages[0][0].result.choice,'unknown');
});
test('accept stores consent but never mints an ID itself',async()=>{
  const h=setup(); await h.send({command:'accept'});
  assert.equal(h.requests.length,1); assert.equal(h.requests[0][0],'/bridge/consent');
  assert.equal(JSON.parse(h.requests[0][1].body).choice,'accepted');
});
test('events go only to fixed cookie-checked route, deny extra envelope keys',async()=>{
  const h=setup();const batch={schema_version:1,consent_version:'1',consent_granted:true,events:[]};
  await h.send({command:'events',batch});
  assert.equal(h.requests[0][0],'/bridge/id/events');
  await h.send({command:'state',batch});
  assert.equal(h.requests.length,1);
});
test('one pending request: decline aborts previous work and suppresses late reply',async()=>{
  let finish;
  const h=setup((url)=>url.endsWith('/state')?new Promise(r=>{finish=r;}):
    Promise.resolve({ok:true,json:async()=>({choice:'declined'})}));
  const first=h.send();
  await h.send({command:'id',nonce:'1111111111111111'});
  assert.equal(h.requests.length,1);
  await h.send({command:'decline',nonce:'2222222222222222'});
  assert.equal(h.requests[0][1].signal.aborted,true);
  finish({ok:true,json:async()=>({choice:'accepted'})});await first;
  assert.equal(h.messages.filter(x=>x[0].nonce==='0123456789abcdef').length,0);
  assert.equal(h.messages.at(-1)[0].result.choice,'declined');
});
test('network or HTTP failures return sanitized unavailability',async()=>{
  for(const fetcher of [async()=>{throw Error('private')},async()=>({ok:false})]){
    const h=setup(fetcher);await h.send();
    assert.equal(h.messages[0][0].error,'unavailable');
    assert.ok(!JSON.stringify(h.messages).includes('private'));
  }
});
test('oversized message is dropped before fetch',async()=>{
  const h=setup();await h.send({command:'events',batch:{events:['x'.repeat(65537)]}});
  assert.equal(h.requests.length,0);assert.equal(h.messages[0][0].error,'unavailable');
});
test('deadline aborts a stalled fetch and releases the slot',async()=>{
  const h=setup((url,options)=>new Promise((resolve,reject)=>{
    options.signal.addEventListener('abort',()=>reject(Error('aborted')));
  }));
  await h.send();assert.equal(h.requests[0][1].signal.aborted,true);
  assert.equal(h.messages[0][0].error,'unavailable');
  await h.send();assert.equal(h.requests.length,2);
});
