// Run with PLAYWRIGHT_MODULE pointing to an installed playwright package.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('node:fs/promises');
const {execFileSync}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'../../../..');
const ORIGIN='http://127.0.0.1:8773';
const BASE='ffdc7e93f8f17e7622db0148c51982eca1e6a720';
const baseline=Object.fromEntries(['index.html','main.js'].map(file=>[file,execFileSync('git',['show',`${BASE}:apps/scoreboard/portal/${file}`],{cwd:ROOT})]));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function main(){
 const live=JSON.parse(require('node:zlib').gunzipSync(await fs.readFile(path.join(__dirname,'live.json.gz'))));
 const ref=live.samples[1].api;
 const timings=Object.fromEntries(ref.map(r=>[r.path,r.duration]));
 const catalogDelay=timings['/v1/benchmarks'];
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const results=[];
 for(const profile of ['local','rtt150','trace-replay'])for(const variant of ['baseline','summary']){
  const context=await browser.newContext();
  await context.addInitScript(()=>{
   window.cardReady=null;
   new MutationObserver(()=>{const c=document.querySelector('#benchmark-cards');if(c&&!c.hidden&&c.children.length&&window.cardReady===null)window.cardReady=performance.now();}).observe(document,{subtree:true,childList:true,attributes:true});
  });
  await context.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.origin!==ORIGIN)return route.abort();
   if(url.pathname==='/' || (variant==='baseline'&&url.pathname==='/main.js')){
    const file=url.pathname==='/'?'index.html':'main.js';
    const body=variant==='baseline'?baseline[file]:await fs.readFile(path.join(ROOT,'apps/scoreboard/portal',file));
    return route.fulfill({status:200,contentType:url.pathname==='/'?'text/html':'text/javascript',body});
   }
   if(url.pathname.startsWith('/v1/')){
    const start=performance.now();
    const response=await route.fetch();assert.equal(response.status(),200);
    const delay=profile==='rtt150'?150:profile==='trace-replay'?(timings[url.pathname+url.search]??catalogDelay):0;
    // Trace replay pads old requests to measured end-to-end durations. The new
    // endpoint uses catalog-delay + actual local work: an explicit model, not a forecast.
    const wait=profile==='trace-replay'&&variant==='baseline'?Math.max(0,delay-(performance.now()-start)):delay;
    await sleep(wait);return route.fulfill({response});
   }
   return route.continue();
  });
  const page=await context.newPage();
  for(let i=0;i<5;i++){
   await page.goto(ORIGIN,{waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>window.cardReady!==null);
   const result=await page.evaluate(()=>{const api=performance.getEntriesByType('resource').filter(r=>r.name.includes('/v1/'));return {cardsMs:Math.round(window.cardReady),apiToCardsMs:Math.round(window.cardReady-Math.min(...api.map(r=>r.startTime))),requests:api.length,decodedBytes:api.reduce((s,r)=>s+r.decodedBodySize,0),visible:document.querySelectorAll('#benchmark-cards .card:not([hidden])').length};});
   assert.equal(result.requests,variant==='baseline'?87:1);assert.equal(result.visible,9);
   results.push({profile,variant,run:i,...result});
  }
  await context.close();
 }
 await browser.close();
 await fs.writeFile(path.join(__dirname,'comparison.json'),JSON.stringify({profiles:{local:'Loopback browser + actual PostgreSQL app',rtt150:'150ms added per API request, both variants',traceReplay:'Old requests padded to recorded live durations; summary assumes catalog delay plus actual work'},results},null,2));
 for(const profile of ['local','rtt150','trace-replay'])for(const variant of ['baseline','summary']){
  const r=results.filter(r=>r.profile===profile&&r.variant===variant).sort((a,b)=>a.apiToCardsMs-b.apiToCardsMs);
  console.log(JSON.stringify({profile,variant,medianApiToCards:r[2].apiToCardsMs,range:[r[0].apiToCardsMs,r[4].apiToCardsMs],requests:r[0].requests,bytes:r[0].decodedBytes}));
 }
}
main().catch(e=>{console.error(e);process.exit(1)});
