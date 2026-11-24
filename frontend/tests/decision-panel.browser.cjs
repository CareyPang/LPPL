const fs=require('fs');
const {chromium}=require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const out=process.env.LPPL_QA_OUTPUT || require('node:os').tmpdir()+'/lppl-decision-qa',base=process.env.LPPL_PREVIEW_URL || 'http://127.0.0.1:8797';
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || undefined});
 const results=[];
 for(const width of [1440,390]){
  const context=await browser.newContext({viewport:{width,height:width===390?844:1000}});
  const page=await context.newPage();const errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method())) writes.push(r.method()+' '+r.url());});
  for(const [name,path] of [
   ['kc50','/chart.html?code=sh000688&kind=index&from=home.html'],
   ['sse','/chart.html?code=sh000001&kind=index&from=home.html'],
   ['maotai','/chart.html?code=600519&kind=stock&from=home.html'],
   ['ixic','/chart.html?code=US_IXIC&kind=index&from=home.html?market=us'],
   ['hynix','/chart.html?code=KR_SKHYNIX&kind=stock&from=home.html?market=kr'],
   ['sse-history','/chart.html?code=sh000001&kind=index&asof=2026-11-20&from=home.html'],
   ['unknown','/chart.html?code=US_ZZZZZZ&kind=stock&from=home.html']]){
    const before=errors.length;
    await page.goto(base+path,{waitUntil:'domcontentloaded'});
    try{await page.waitForFunction(()=>document.querySelector('#chart-page').dataset.loaded==='true'||!document.querySelector('#error-panel').hidden,{timeout:25000});}catch{}
    try{await page.waitForFunction(()=>['ready','error'].includes(document.querySelector('#chart-page').dataset.decisionHistoryStatus),{timeout:14000});}catch{}
    await page.waitForTimeout(250);
    const snap=await page.evaluate(()=>({dataset:{...document.querySelector('#chart-page').dataset},width:innerWidth,scrollWidth:document.documentElement.scrollWidth,summary:document.querySelector('.terminal-summary').innerText,panel:document.querySelector('#decision-panel-host').innerText,error:document.querySelector('#error-panel').innerText,canvas:document.querySelectorAll('#chart-host canvas').length}));
    const checks={noOverflow:snap.scrollWidth<=width,noJsErrors:errors.length===before};
    if(name==='sse-history'){
     const original=snap.panel;
     const future=page.locator('#terminal-show-future');
     if(await future.isVisible()&&await future.isEnabled()){await future.check();await page.waitForTimeout(1500);checks.futureKeepsDecision=await page.locator('#decision-panel-host').innerText()===original;}
    }
    if(name==='sse'){
     await page.locator('#chart-fullscreen').click();checks.fullscreen=await page.locator('#fullscreen-exit').isVisible();await page.locator('#fullscreen-exit').click();
     const beforeOpen=await page.locator('#evidence-toggle').getAttribute('aria-expanded')==='true';
     await page.locator('#evidence-toggle').click();checks.evidenceToggle=(await page.locator('#evidence-toggle').getAttribute('aria-expanded')==='true')!==beforeOpen;
     if(!beforeOpen)await page.locator('#evidence-close').click();else await page.locator('#evidence-toggle').click();
    }
    if(name!=='unknown')await page.locator('#decision-panel-host').screenshot({path:out+'/'+name+'-'+width+'.png'}).catch(()=>{});
    results.push({name,width,...snap,checks,errors:errors.slice(before)});
    fs.writeFileSync(out+'/live-qa.json',JSON.stringify({results,writes},null,2));
    console.log(name,width,JSON.stringify(snap.dataset),JSON.stringify(checks));
  }
  await context.close();
 }
 await browser.close();
 if(results.some(r=>Object.values(r.checks).some(v=>v===false)))throw Error('Browser contract failed; inspect live-qa.json');
})().catch(e=>{console.error(e);process.exitCode=1});
