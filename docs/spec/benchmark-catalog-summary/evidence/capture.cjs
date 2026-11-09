const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('node:fs/promises');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:"chrome"});
 const context=await browser.newContext(); const page=await context.newPage();
 await page.addInitScript(()=>{
  window.cardReady=null;
  new MutationObserver(()=>{const c=document.querySelector('#benchmark-cards');if(c&&!c.hidden&&c.children.length&&window.cardReady===null)window.cardReady=performance.now();}).observe(document,{subtree:true,childList:true,attributes:true});
 });
 const bodies={};let pending=[];
 page.on('response',r=>{if(new URL(r.url()).pathname.startsWith('/v1/'))pending.push(r.text().then(body=>{bodies[new URL(r.url()).pathname+new URL(r.url()).search]=JSON.parse(body);}));});
 const samples=[];
 for(let i=0;i<3;i++){
  await page.goto('https://leaderboard.screamingface.ai/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.cardReady!==null);
  samples.push(await page.evaluate(()=>({cardsMs:Math.round(window.cardReady),api:performance.getEntriesByType('resource').filter(r=>r.name.includes('/v1/')).map(r=>({path:new URL(r.name).pathname+new URL(r.name).search,start:r.startTime,duration:r.duration,bytes:r.encodedBodySize,ttfb:r.responseStart-r.requestStart})),cards:document.querySelector('#benchmark-cards').children.length})));
  await Promise.all(pending);pending=[];
 }
 await fs.writeFile(require('node:path').join(__dirname,'live.json.gz'),require('node:zlib').gzipSync(JSON.stringify({capturedAt:new Date().toISOString(),samples,bodies},null,2)));
 console.log(JSON.stringify(samples.map(s=>({cardsMs:s.cardsMs,apiRequests:s.api.length,bytes:s.api.reduce((n,r)=>n+r.bytes,0),catalogMs:s.api[0].duration}))));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
