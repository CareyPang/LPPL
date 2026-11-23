/* Read-only acceptance against live research. No job submissions or synthetic market data. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.LPPL_PLAYWRIGHT_MODULE||'playwright');
const origin=process.env.LPPL_PREVIEW_URL||'http://127.0.0.1:8796',output=process.env.LPPL_GLOBAL_BROWSER_OUTPUT;
assert.ok(output,'set LPPL_GLOBAL_BROWSER_OUTPUT to a D: analysis directory');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.LPPL_BROWSER_EXECUTABLE});const checks=[],errors=[],writes=[];
 try{for(const width of [1440,390]){
  const context=await browser.newContext({viewport:{width,height:1000}});
  await context.route('**/app/lppl-chart.js',async route=>{const response=await route.fetch();await route.fulfill({response,body:await response.text()+'\n;const originalMount=LPPLChart.mount;LPPLChart.mount=function(...args){const chart=originalMount(...args),originalSet=chart.setData;chart.setData=function(data){window.__qaData=data;return originalSet(data);};return chart;};'});});
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(request.method()!=='GET')writes.push(request.url());});
  for(const code of ['US_IXIC','US_NDX','US_MRVL']){
   await page.goto(origin+'/chart.html?code='+code+'&kind='+(code==='US_MRVL'?'stock':'index'));
   await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
   await page.waitForFunction(()=>document.querySelector('#global-analysis')?.dataset.status==='available');
   assert.equal(await page.locator('#global-analysis-run').isEnabled(),true);
   const data=await page.evaluate(()=>window.__qaData),study=data.raw.research.aftershock;
   assert.equal(study.symbol,code);assert.equal(study.asof,data.modelAsOf);
   const card=page.locator('#terminal-aftershock');assert.equal(await card.isVisible(),true);
   for(const key of ['omori','bath','productivity']){
    const module=study.modules[key],target=page.locator('#terminal-'+key);assert.ok((await target.innerText()).includes(module.summary||module.reason));
    await target.locator('summary').click();if(module.anchor_date)assert.ok((await target.innerText()).includes(module.anchor_date));
   }
   if(code==='US_IXIC'){assert.match(await card.innerText(),/并非负向主震/);assert.match(await card.innerText(),/之后 0 个完整交易日/);assert.match(await page.locator('#terminal-productivity').innerText(),/区间包含0|区间包含 0/);}
   assert.doesNotMatch(await card.innerText(),/\[object Object\]|undefined|NaN/);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   assert.ok(await page.locator('#global-analysis-run').evaluate(el=>el.getBoundingClientRect().height>=44));
   await card.screenshot({path:path.join(output,code+'-aftershock-'+width+'.png')});await page.locator('#global-analysis').screenshot({path:path.join(output,code+'-run-controls-'+width+'.png')});
   checks.push(width+': '+code+' real modules, source dates, readable controls');
  }
  await page.locator('#terminal-asset').selectOption('US_NDX');await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.code==='US_NDX'&&document.querySelector('#chart-page')?.dataset.loaded==='true');
  assert.match(await page.locator('#asset-name').innerText(),/100/);assert.equal(await page.locator('#global-analysis-run').isEnabled(),true);checks.push(width+': MRVL to NDX identity-preserving asset navigation');
  await page.goto(origin+'/chart.html?code=US_IXIC&kind=index&asof=2026-11-13');await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
  const historical=await page.evaluate(()=>window.__qaData);assert.equal(historical.modelAsOf,'2026-11-13');assert.equal(historical.raw.research.aftershock.asof,'2026-11-13');
  assert.equal(await page.locator('#global-analysis-asof').inputValue(),'2026-11-13');assert.match(await page.locator('#events-note').innerText(),/历史|当时/);
  const frozen=JSON.stringify(historical.raw.research.aftershock),top=JSON.stringify(historical.top),before=historical.bars.length;
  await page.locator('#terminal-show-future').check();await page.waitForFunction(n=>window.__qaData.bars.length>n,before);
  assert.equal(await page.evaluate(()=>JSON.stringify(window.__qaData.raw.research.aftershock)),frozen);assert.equal(await page.evaluate(()=>JSON.stringify(window.__qaData.top)),top);
  assert.equal(await page.locator('#chart-page').getAttribute('data-model-as-of'),'2026-11-13');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  await page.locator('#terminal-aftershock').screenshot({path:path.join(output,'US_IXIC-historical-'+width+'.png')});checks.push(width+': exact historical study preserved when later prices are revealed');await context.close();
 }
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);const result={checks,errors,writes};fs.writeFileSync(path.join(output,'acceptance.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
