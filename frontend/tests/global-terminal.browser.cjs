/* Real local global exports only; run after research.pipeline.global_terminal.
 * LPPL_GLOBAL_RESULTS points to its output root. Start scripts/preview_global_terminal.py first.
 */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.LPPL_PLAYWRIGHT_MODULE||'playwright');
const root=process.env.LPPL_GLOBAL_RESULTS;
assert.ok(root,'LPPL_GLOBAL_RESULTS must contain real completed exports');
const origin=process.env.LPPL_PREVIEW_URL||'http://127.0.0.1:8796';
const output=process.env.LPPL_SCREENSHOT_DIR;
const read=name=>JSON.parse(fs.readFileSync(path.join(root,'global',name),'utf8'));
const catalog=read('catalog.json'),checks=[],errors=[],writes=[],badRequests=[];
const pass=s=>{checks.push(s);console.log('PASS '+s)};
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.LPPL_BROWSER_EXECUTABLE});
 try{
  for(const width of [1440,390]){
   const context=await browser.newContext({viewport:{width,height:960}});
   await context.route('**/app/lppl-chart.js',async route=>{
    const response=await route.fetch();const body=await response.text();
    await route.fulfill({response,body:body+'\n;const mount=LPPLChart.mount;LPPLChart.mount=function(...a){const c=mount(...a),set=c.setData;c.setData=function(d){window.__qaData=d;return set(d);};window.__qaChart=c;return c;};'});
   });
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   page.on('request',req=>{if(req.method()!=='GET')writes.push(req.url());
    if(page.url().includes('chart.html')&&/\/api\/(market|replay|query)|\/stock\/US_(SPX|NDX|IXIC|DJI)/.test(req.url()))badRequests.push(req.url());});
   await page.goto(origin+'/home.html?market=us');
   await page.locator('a.row[data-sym="US_SPX"]').waitFor();
   assert.equal(await page.locator('#market-us').getAttribute('aria-selected'),'true');
   assert.equal(await page.locator('#rows a.row').count(),4);
   for(const [market,count] of [['jp',1],['kr',2],['us',4]]){
    await page.locator('#market-'+market).click();
    await page.waitForFunction(n=>document.querySelectorAll('#rows a.row[data-sym]').length===n,count);
    const codes=await page.locator('#rows a.row').evaluateAll(nodes=>nodes.map(n=>n.dataset.sym));
    assert.ok(codes.every(c=>c.startsWith(market.toUpperCase()+'_')));
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   if(output){fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,'global-home-'+width+'.png'),fullPage:true})}
   pass(width+': four market tabs and no mixed index identities');
   await page.locator('a.row[data-sym="US_SPX"]').click();
   await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
   assert.equal(await page.locator('#return-link').getAttribute('href'),'home.html?market=us');
   await page.locator('#return-link').click();await page.waitForURL('**/home.html?market=us');
   pass(width+': index click and return restore US market tab');
   await page.locator('#hs-i').click();await page.locator('#odm-i').fill('MRVL');
   const mrvl=page.locator('#odm-l a[href*="code=US_MRVL"]');await mrvl.first().waitFor();
   assert.match(await mrvl.first().getAttribute('href'),/kind=stock/);
   await mrvl.first().click();await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
   assert.equal((await page.evaluate(()=>window.__qaData.symbol)).toUpperCase(),'US_MRVL');
   pass(width+': MRVL search opens its own US stock result');
   for(const asset of catalog.assets){
    assert.equal(asset.status,'complete_sample',asset.id+' must have completed actual fits');
    const record=read(asset.id+'_latest.json'),history=read(asset.id+'_history.json');
    await page.goto(origin+'/chart.html?code='+asset.id+'&kind='+asset.kind+'&from=home.html');
    await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
    assert.equal((await page.evaluate(()=>window.__qaData.symbol)).toUpperCase(),asset.id);
    assert.equal(await page.locator('#terminal-asset').inputValue(),asset.id);
    assert.equal(await page.locator('#chart-page').getAttribute('data-model-as-of'),record.asof);
    assert.deepEqual(await page.evaluate(()=>window.__qaData.top),record.research.cycles_1_5);
    if(asset.id==='KR_KOSPI'){
     await page.locator('#terminal-rule').selectOption('box');
     await page.waitForFunction(()=>window.__qaData?.researchRule==='box');
     assert.deepEqual(await page.evaluate(()=>window.__qaData.top),record.top);
     await page.locator('#terminal-rule').selectOption('cycles_1_5');
     await page.waitForFunction(()=>window.__qaData?.researchRule==='cycles_1_5');
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    assert.match(await page.locator('#asset-type').innerText(),asset.kind==='stock'?/USD/:/指数/);
    assert.equal(await page.locator('#period-selector').isVisible(),false);
    assert.equal(await page.locator('#terminal-backtest-link').isVisible(),false);
    if(asset.id==='US_MRVL'){
     assert.doesNotMatch(await page.locator('#terminal-alert-detail').innerText(),/沪深300/);
     if(!await page.locator('#evidence-panel').isVisible())await page.locator('#evidence-toggle').click();
     await page.locator('#evidence-note summary').click();
     assert.match(await page.locator('#evidence-note').innerText(),/完成 27 个窗口/);
     if(width===390)await page.locator('#evidence-close').click();
    }
    const date=history.frames[0].asof;
    await page.locator('#terminal-mode-replay').click();
    await page.locator('#terminal-asof').fill(date);await page.locator('#terminal-asof').dispatchEvent('change');
    await page.waitForFunction(d=>document.querySelector('#chart-page')?.dataset.modelAsOf===d,date);
    assert.ok(await page.evaluate(d=>window.__qaData.bars.every(b=>b.date<=d),date));
    const frozen=await page.evaluate(()=>JSON.stringify(window.__qaData.top));
    const count=await page.evaluate(()=>window.__qaData.bars.length);
    await page.locator('#terminal-show-future').check();
    await page.waitForFunction(n=>window.__qaData.bars.length>n,count);
    assert.equal(await page.evaluate(()=>JSON.stringify(window.__qaData.top)),frozen);
    assert.equal(await page.evaluate(()=>window.__qaData.asof),date);
    if(output&&['US_MRVL','KR_KOSPI'].includes(asset.id))await page.screenshot({path:path.join(output,asset.id+'-'+width+'.png'),fullPage:true});
    pass(width+': '+asset.id+' real current and exact archive; later prices do not change model');
   }
   await page.goto(origin+'/chart.html?code=KR_KOSPI&kind=index&asof=2001-01-01');
   await page.locator('#error-panel').waitFor({state:'visible'});
   assert.equal(await page.locator('#chart-page').getAttribute('data-loaded'),null);
   pass(width+': absent global archive does not use latest or dispatch A-share job');
   await context.close();
  }
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(badRequests,[]);
  const result={checks,pageErrors:errors,writes,badRequests,sourceGeneratedAt:catalog.generated_at,counts:catalog.counts};
  if(output)fs.writeFileSync(path.join(output,'acceptance.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
