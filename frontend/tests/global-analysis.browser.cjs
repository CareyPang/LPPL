/* Real loopback jobs and archived prices; no fixture market data. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.LPPL_PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.LPPL_PREVIEW_URL || 'http://127.0.0.1:8796';
const output = process.env.LPPL_JOB_QA_OUTPUT;
assert.ok(output, 'Set a D-drive output directory');
fs.mkdirSync(output, {recursive:true});
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.LPPL_BROWSER_EXECUTABLE});
  const checks=[], errors=[], posts=[], jobs=[];
  try {
    for (const width of [1440,390]) {
      const context=await browser.newContext({viewport:{width,height:960}});
      await context.route('**/app/lppl-chart.js',async route => {
        const response=await route.fetch();
        await route.fulfill({response,body:await response.text()+
          '\n;const oldMount=LPPLChart.mount;LPPLChart.mount=function(...args){const c=oldMount(...args),oldSet=c.setData;c.setData=function(d){window.__qaData=d;return oldSet(d);};return c;};'});
      });
      const page=await context.newPage();
      page.on('pageerror',error=>errors.push(error.message));
      page.on('request',r=>{if(r.method()!=='GET')posts.push({url:r.url(),method:r.method()});});
      await page.goto(origin+'/chart.html?code=US_IXIC&kind=index#terminal-aftershock');
      await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
      await page.waitForFunction(()=>document.querySelector('#global-analysis')?.dataset.status==='available');
      const before=await page.evaluate(()=>window.__qaData.raw);
      assert.equal(before.research.aftershock.symbol,'US_IXIC');
      const submitted=page.waitForResponse(r=>r.url()===origin+'/api/global-analysis' && r.request().method()==='POST');
      await page.locator('#global-analysis-asof').fill('');
      await page.locator('#global-analysis-run').click();
      const queued=await (await submitted).json();
      assert.equal(queued.symbol,'US_IXIC');assert.equal(queued.requested_asof,null);
      assert.equal(await page.evaluate(()=>window.__qaData.raw.asof),before.asof,'Existing data stays available while queued');
      await page.waitForFunction(()=>document.querySelector('#global-analysis')?.dataset.status==='complete',null,{timeout:360000});
      const after=await page.evaluate(()=>window.__qaData.raw);
      assert.equal(after.job_id,queued.job_id);assert.equal(after.fit_counts.completed,27);
      assert.equal(after.research.aftershock.asof,after.asof);
      assert.equal(after.research.aftershock.source.mode,'verified_independent_research_archive');
      const result=await (await page.request.get(origin+'/api/global-analysis/'+queued.job_id)).json();
      assert.equal(result.cache_reused,27,'Same exact fit inputs reuse all 27 checkpoints');jobs.push(result);
      checks.push(width+': click -> real refreshed data -> 27 cached fits -> matched cards');
      await page.locator('#global-analysis-asof').fill('2099-01-01');
      await page.locator('#global-analysis-run').click();
      await page.waitForFunction(()=>document.querySelector('#global-analysis')?.dataset.status==='failed',null,{timeout:90000});
      assert.equal(await page.evaluate(()=>window.__qaData.raw.job_id),queued.job_id,'Failure preserves usable chart');
      assert.match(await page.locator('#global-analysis-status').innerText(),/没有完整交易日线/);
      checks.push(width+': invalid/unavailable date fails explicitly; prior chart remains usable');
      // Reconstruct one previously unarchived endpoint, then reload its exact URL.
      await page.locator('#global-analysis-asof').fill('2026-11-16');
      await page.locator('#global-analysis-run').click();
      await page.waitForFunction(()=>document.querySelector('#global-analysis')?.dataset.status==='complete',null,{timeout:360000});
      const historical=await page.evaluate(()=>window.__qaData.raw);
      assert.equal(historical.asof,'2026-11-16');assert.equal(historical.research.aftershock.asof,'2026-11-16');
      assert.equal(historical.research.aftershock.source.mode,'daily_recalculation');
      assert.equal(historical.research.market_events.mode,'historical');
      assert.ok(historical.research.market_events.items.every(item=>!item.after_model_asof));
      assert.match(page.url(),/asof=2026-11-16/);
      await page.reload();
      await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
      assert.equal(await page.evaluate(()=>window.__qaData.raw.asof),'2026-11-16');
      const history=await(await page.request.get(origin+'/lab/mock/data/global/US_IXIC_history.json')).json();
      assert.ok(history.frames.some(f=>f.asof==='2026-11-16'));
      assert.equal(history.asof,'2026-11-20');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      await page.locator('#terminal-aftershock').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(output,'jobs-'+width+'.png'),fullPage:true});
      checks.push(width+': new exact historical endpoint persists; reload and history list agree; no future news');
      await context.close();
    }
    assert.deepEqual(errors,[]);
    assert.ok(posts.every(r=>r.method==='POST' && r.url===origin+'/api/global-analysis'));
    const acceptance={checks,errors,posts,jobs,inspected_at:new Date().toISOString()};
    fs.writeFileSync(path.join(output,'acceptance.json'),JSON.stringify(acceptance,null,2));
    console.log(JSON.stringify(acceptance,null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
