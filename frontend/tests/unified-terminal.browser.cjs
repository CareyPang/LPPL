/* Browser regression with captured real published responses, never synthetic prices.
 * LPPL_SAMPLE_DIR contains samples/, baseline/, maotai-market.json and provenance.json.
 * LPPL_PLAYWRIGHT_MODULE, LPPL_BROWSER_EXECUTABLE, LPPL_SCREENSHOT_DIR configure local QA.
 */
'use strict';
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.LPPL_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '../..'), sample = process.env.LPPL_SAMPLE_DIR;
assert.ok(sample, 'provide separately captured published responses');
const output = process.env.LPPL_SCREENSHOT_DIR;
const read = f => fs.readFileSync(path.join(sample, f), 'utf8');
const mime = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png'};
const checks = [], writes = [], errors = [];
const server = http.createServer((req,res) => {
  if(req.method !== 'GET') {writes.push(req.url);res.writeHead(405);return res.end();}
  let pathname = decodeURIComponent(new URL(req.url,'http://local').pathname);
  const before = pathname.startsWith('/before/'); if(before) pathname = pathname.slice(7);
  let file;
  if(pathname.startsWith('/lab/mock/data/')) {
    const relative = pathname.slice('/lab/mock/data/'.length);
    const live = path.join(sample,'samples',relative);
    file = fs.existsSync(live) ? live : path.join(sample,'baseline/web/mock/data',relative);
  } else if(pathname.startsWith('/lab/')) file=path.join(sample,'baseline/web',pathname.slice(5));
  else file = path.join(before ? path.join(sample,'baseline/frontend') : path.join(root,'frontend'),pathname);
  file = path.resolve(file);
  if(![root,sample].some(base=>file.startsWith(path.resolve(base)+path.sep)) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.writeHead(404);return res.end('{}');}
  res.writeHead(200, {'content-type':mime[path.extname(file)] || 'application/octet-stream'});
  if(pathname==='/app/lppl-chart.js' && !before) return res.end(fs.readFileSync(file,'utf8') + '\n;const mount=LPPLChart.mount;LPPLChart.mount=function(...a){const c=mount(...a),set=c.setData;c.setData=function(d){window.__qaData=d;return set(d);};window.__qaChart=c;return c;};');
  fs.createReadStream(file).pipe(res);
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const browser=await chromium.launch({headless:true,executablePath:process.env.LPPL_BROWSER_EXECUTABLE});
  if(output) fs.mkdirSync(output,{recursive:true});
  const pass=s=>{checks.push(s);console.log('PASS '+s);};
  const history=JSON.parse(read('samples/sh000001_history.json'));
  const asof=history.frames.filter(f=>f.asof<'2026-07-01' && f.w && f.w['6-12m']).at(-1).asof;
  const shot=async(p,name)=>{if(output)await p.screenshot({path:path.join(output,name+'.png'),fullPage:true});};
  try {
    for(const width of [1440,390]) {
      const ctx=await browser.newContext({viewport:{width,height:960}});
      await ctx.route('**/*',route=>{
        const req=route.request(),url=new URL(req.url());
        if(req.method()!=='GET') {writes.push(req.url());return route.abort();}
        if(url.origin===origin)return route.continue();
        if(url.pathname==='/market' && url.searchParams.get('code')==='600519')return route.fulfill({status:200,contentType:'application/json',body:read('maotai-market.json'),headers:{'access-control-allow-origin':'*'}});
        if(url.pathname==='/replay/result')return route.fulfill({status:404,contentType:'application/json',body:'{}',headers:{'access-control-allow-origin':'*'}});
        return route.fulfill({status:503,contentType:'application/json',body:'{}',headers:{'access-control-allow-origin':'*'}});
      });
      const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
      if(width===1440) {
        for(const [url,name] of [['home.html','home-before'],['chart.html?code=sh000001&kind=index','detail-before'],['index.html?code=sh000001&asof=2015-06-12','replay-before']]) {
          await page.goto(origin+'/before/'+url);await page.waitForTimeout(1600);await shot(page,name);
        }
        await page.goto(origin+'/chart.html?code=sh000001&kind=index&asof=2015-06-12&mode=replay');
        await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
        await shot(page,'replay-static-after-1440');
      }
      await page.goto(origin+'/home.html');
      const card=page.locator('a.row[data-sym="sh000001"]');await card.waitFor();
      await shot(page,'home-after-'+width);
      assert.match(await card.getAttribute('href'),/chart\.html/);
      await card.click();await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
      assert.equal(await page.locator('#terminal-asset').inputValue(),'sh000001');
      assert.match(await page.locator('#asset-name').innerText(),/上证/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      assert.equal(await page.locator('#return-link').getAttribute('href'),'home.html');
      await shot(page,'detail-after-'+width);pass(width+': home card → real index candles → evidence');
      await page.locator('#terminal-mode-replay').click();
      await page.locator('#terminal-asof').fill(asof);await page.locator('#terminal-asof').dispatchEvent('change');
      await page.waitForFunction(d=>document.querySelector('#chart-page')?.dataset.modelAsOf===d,asof);
      const frozen=await page.evaluate(()=>JSON.stringify(window.__qaData.top));
      assert.ok(await page.locator('#interval-list button').count()>0, 'real archive must contain visible interval bands');
      const beforeCount=await page.evaluate(()=>window.__qaData.bars.length);
      assert.ok(await page.evaluate(d=>window.__qaData.bars.every(b=>b.date<=d),asof));
      await page.locator('#terminal-show-future').check();
      await page.waitForFunction(n=>window.__qaData.bars.length>n,beforeCount);
      assert.equal(await page.evaluate(()=>JSON.stringify(window.__qaData.top)),frozen);
      assert.equal(await page.evaluate(()=>window.__qaData.asof),asof);
      await shot(page,'replay-after-'+width);
      await page.locator('#terminal-show-future').uncheck();
      assert.equal(await page.evaluate(()=>window.__qaData.bars.length),beforeCount);
      await page.locator('[data-scale="3-6m"]').click();
      assert.equal(new URL(page.url()).searchParams.get('asof'),asof);
      assert.ok(await page.locator('#terminal-history-list a').count()>0);
      pass(width+': exact history, later-price toggle leaves model unchanged, scale and ledger stay aligned');
      await page.locator('#terminal-latest').click();await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.loaded==='true');
      await page.locator('#terminal-asset').selectOption('sh000300');
      await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.code==='sh000300');
      assert.match(await page.locator('#asset-name').innerText(),/沪深300/);
      await page.locator('#terminal-asset').selectOption('600519');
      await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.code==='sh600519');
      assert.equal(await page.locator('#terminal-asset').inputValue(),'600519');
      assert.match(await page.locator('#asset-type').innerText(),/CNY/);
      pass(width+': switch index → Maotai with separately captured real Worker 200 response');
      await page.locator('#terminal-asset').selectOption('US_NVDA');
      await page.waitForFunction(()=>document.querySelector('#chart-page')?.dataset.code==='US_NVDA');
      assert.match(await page.locator('#asset-type').innerText(),/USD/);
      assert.equal(await page.locator('#period-selector').isVisible(),false);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      await shot(page,'nvda-'+width);
      await page.goto(origin+'/chart.html?code=US_ZZZZZZ&kind=stock&from=home.html');
      await page.locator('#error-panel').waitFor({state:'visible'});
      assert.equal(await page.locator('#chart-page').getAttribute('data-loaded'),null);
      await page.locator('#return-link').click();await page.waitForURL('**/home.html');
      pass(width+': US identity and unsupported symbol empty state; return to original list');
      await ctx.close();
    }
    assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
    const report={checks,pageErrors:errors,writes,asof,sources:JSON.parse(read('provenance.json'))};
    if(output)fs.writeFileSync(path.join(output,'acceptance.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({passed:checks.length,pageErrors:errors,writes}));
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
