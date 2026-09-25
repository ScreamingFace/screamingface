const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {execFileSync}=require('node:child_process');
// Exercise the exact deployed grammar, not a separately retyped JS policy.
const pattern=execFileSync(process.env.SF_TEST_PYTHON || 'python3',['-c',
 'from analytics_service.bridge_origins import COLAB_PATTERN; print(COLAB_PATTERN)'],{encoding:'utf8'}).trim();
const live='https://6ernmmrpvem-496ff2e9c6d22116-0-colab.googleusercontent.com';
const script=fs.readFileSync('src/analytics_service/bridge.js','utf8');
test('Colab policy accepts legitimate changing hosts and rejects hostile origins', async()=>{
 for(const origin of [live,live.replace('6ernmmrpvem','rb49gy8dleg'),live+'.evil',live+':443',
   live+'/path',live+'\n',live.replace('https:','http:'),live.replace('6ernmmrpvem','a.b'),
   live.replace('6ernmmrpvem','x'.repeat(64)),'null','https://attacker.googleusercontent.com']){
  let handler,calls=0;const replies=[];const parent={postMessage:(...args)=>replies.push(args)};
  vm.runInNewContext(script,{allowedParents:[],colabParentPattern:pattern,
   window:{parent,addEventListener:(_,h)=>{handler=h;}},AbortController,TextEncoder,setTimeout,clearTimeout,
   fetch:async()=>{calls++;return {ok:true,json:async()=>({choice:'unknown'})};}});
  await handler({source:parent,origin,data:{version:1,nonce:'0123456789abcdef',command:'state'}});
  const allowed=origin===live || origin===live.replace('6ernmmrpvem','rb49gy8dleg');
  assert.equal(calls,allowed?1:0,origin);
  if(allowed)assert.equal(replies[0][1],origin);
 }
});
