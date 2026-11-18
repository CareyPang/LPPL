/* Offline integration: uses the production adapter and real Lightweight Charts.
 * Set LPPL_PLAYWRIGHT_MODULE, LPPL_BROWSER_EXECUTABLE and LPPL_SCREENSHOT_DIR.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.env.LPPL_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '../..'), front = path.join(root, 'frontend'), fixtures = path.join(__dirname, 'fixtures');
const read = f => fs.readFileSync(path.join(fixtures, f), 'utf8');
const indexRaw = JSON.parse(read('sh000001_latest.json'));
const requests = [], errors = [], checks = [];
let modelDelay = 1500, modelMissing = false, replayReady = true, closeOnlyReplay = false;
const mime = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.json':'application/json', '.svg':'image/svg+xml' };
const files = { '/lab/mock/data/sh000001_latest.json':'sh000001_latest.json', '/lab/mock/data/sh000001_history.json':'sh000001_history.json', '/lab/mock/data/stock/600519.json':'stock_600519.json' };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost'); requests.push({ method:req.method, path:url.pathname });
  if (req.method !== 'GET') { res.writeHead(405); return res.end(); }
  if (url.pathname === '/lab/mock/data/events/events_latest.json') { res.writeHead(503); return res.end('{}'); }
  if (modelMissing && url.pathname === '/lab/mock/data/stock/600519.json') { res.writeHead(404); return res.end('{}'); }
  let file = files[url.pathname] ? path.join(fixtures, files[url.pathname]) : path.resolve(front, '.' + url.pathname);
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); return res.end('{}'); }
  const send = () => {
    res.writeHead(200, { 'content-type':mime[path.extname(file)] || 'application/octet-stream', 'cache-control':'no-store' });
    if (url.pathname === '/app/lppl-chart.js') {
      // Expose only in this local QA response, not in shipped app code.
      return res.end(fs.readFileSync(file, 'utf8') + '\n;const originalMount=LPPLChart.mount;LPPLChart.mount=function(...args){window.__qaChart=originalMount(...args);return window.__qaChart;};');
    }
    fs.createReadStream(file).pipe(res);
  };
  if (url.pathname === '/lab/mock/data/stock/600519.json') setTimeout(send, modelDelay); else send();
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ headless:true, ...(process.env.LPPL_BROWSER_EXECUTABLE ? { executablePath:process.env.LPPL_BROWSER_EXECUTABLE } : {}) });
  const output = process.env.LPPL_SCREENSHOT_DIR;
  if (output) fs.mkdirSync(output, { recursive:true });
  const pass = text => { checks.push(text); console.log('PASS ' + text); };
  async function make(width) {
    const ctx = await browser.newContext({ viewport:{ width, height:900 }, acceptDownloads:true });
    await ctx.route('**/*', route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin === origin) return route.continue();
      requests.push({ method:req.method(), path:url.pathname });
      if (url.pathname === '/market') return route.fulfill({ status:200, contentType:'application/json', body:read('stock_600519_market.json'), headers:{ 'access-control-allow-origin':'*' } });
      if (url.pathname === '/replay/result') {
        const result = closeOnlyReplay ? { ...indexRaw, price_history:{ dates:indexRaw.price_history.dates, close:indexRaw.price_history.close } } : indexRaw;
        return route.fulfill({ status:200, contentType:'application/json',
          body:JSON.stringify(replayReady ? { status:'ready', result } : { status:'missing' }), headers:{ 'access-control-allow-origin':'*' } });
      }
      return route.fulfill({ status:503, contentType:'application/json', body:'{}', headers:{ 'access-control-allow-origin':'*' } });
    });
    const page = await ctx.newPage(); page.on('pageerror', e => errors.push(e.message)); return { ctx, page };
  }
  async function overflow(page) { assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true); }
  try {
    const desktop = await make(1440), page = desktop.page;
    await page.goto(origin + '/chart.html?code=600519&kind=stock&scale=3-6m&from=research-workspace.html');
    await page.waitForFunction(() => document.querySelector('#chart-page').dataset.loaded === 'true');
    assert.equal(await page.locator('#chart-page').getAttribute('data-model-status'), 'loading');
    assert.match(await page.locator('#asset-type').innerText(), /CNY/);
    assert.equal(await page.locator('#return-link').getAttribute('href'), 'research-workspace.html');
    const marketClose = await page.locator('#chart-page').getAttribute('data-last-close');
    await page.evaluate(() => window.__qaChart.setVisibleRange({ from:100, to:150 }));
    await page.waitForFunction(() => window.__qaChart.getVisibleRange().from === 100);
    const view = await page.evaluate(() => window.__qaChart.getVisibleRange());
    await page.waitForFunction(() => document.querySelector('#chart-page').dataset.modelStatus === 'ok');
    assert.deepEqual(await page.evaluate(() => window.__qaChart.getVisibleRange()), view);
    assert.equal(await page.locator('#chart-page').getAttribute('data-last-close'), marketClose);
    pass('market renders before delayed model; model completion preserves candles and user zoom');
    await overflow(page);
    if (output) await page.screenshot({ path:path.join(output, 'chart-desktop.png'), fullPage:true });
    const download = page.waitForEvent('download'); await page.locator('#share-card').click();
    const card = await download; const cardPath = await card.path(); const svg = fs.readFileSync(cardPath, 'utf8');
    assert.match(svg, /贵州茅台/); assert.match(svg, /模型/); assert.match(svg, /首次可见时间/);
    if (output) await card.saveAs(path.join(output, 'chart-research-card.svg'));
    const pngDownload = page.waitForEvent('download'); await page.locator('#share-screenshot').click();
    const png = await pngDownload;
    if (output) await png.saveAs(path.join(output, 'chart-with-evidence.png'));
    assert.ok(fs.statSync(await png.path()).size > 10000);
    pass('anonymous SVG card and actual chart PNG download with evidence metadata');
    await page.locator('#evidence-close').click(); assert.equal(await page.locator('#evidence-panel').isVisible(), false);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'evidence-toggle');
    await page.locator('#evidence-toggle').click(); pass('desktop auxiliary evidence can close and restores focus');

    modelMissing = true; modelDelay = 0;
    await page.reload(); await page.waitForFunction(() => document.querySelector('#chart-page').dataset.modelStatus === 'missing');
    assert.equal(await page.locator('#chart-page').getAttribute('data-last-close'), marketClose);
    assert.match(await page.locator('#evidence-state').innerText(), /尚未发布，或读取失败/);
    assert.equal(await page.locator('#interval-list button').count(), 0);
    pass('missing model and failed events keep market candles without invented intervals');

    const phone = await make(390), mobile = phone.page;
    await mobile.goto(origin + '/chart.html?code=600519&kind=stock');
    await mobile.waitForFunction(() => document.querySelector('#chart-page').dataset.loaded === 'true');
    await overflow(mobile); assert.equal(await mobile.locator('#evidence-panel').isVisible(), false);
    await mobile.locator('#evidence-toggle').click();
    assert.equal(await mobile.locator('#evidence-panel').getAttribute('aria-modal'), 'true');
    if (output) await mobile.screenshot({ path:path.join(output, 'chart-mobile-evidence.png'), fullPage:true });
    await mobile.keyboard.press('Escape');
    assert.equal(await mobile.locator('#evidence-panel').isVisible(), false);
    assert.equal(await mobile.evaluate(() => document.activeElement.id), 'evidence-toggle');
    await mobile.locator('#chart-fullscreen').click();
    await mobile.locator('#fullscreen-exit').waitFor({ state:'visible' });
    await mobile.locator('#fullscreen-exit').click();
    assert.equal(await mobile.locator('#chart-fullscreen').getAttribute('aria-pressed'), 'false');
    await overflow(mobile);
    if (output) await mobile.screenshot({ path:path.join(output, 'chart-mobile.png'), fullPage:true });
    pass('390px has no overflow; evidence drawer Escape and chart fullscreen exit restore usable page');

    await page.goto(origin + '/chart.html?code=sh000001&asof=' + indexRaw.asof + '&scale=6-12m&from=research-workspace.html');
    await page.waitForFunction(() => document.querySelector('#chart-page').dataset.loaded === 'true');
    assert.equal(await page.locator('#chart-page').getAttribute('data-model-as-of'), indexRaw.asof);
    await page.locator('[data-scale="3-6m"]').click();
    assert.equal(new URL(page.url()).searchParams.get('asof'), indexRaw.asof);
    assert.match(await page.locator('#asof-notice').innerText(), /真实提前发布分开/);
    if (output) await page.screenshot({ path:path.join(output, 'chart-index-archive.png'), fullPage:true });
    pass('exact historical archive keeps cutoff and source context across scale changes');
    closeOnlyReplay = true;
    await page.reload(); await page.waitForFunction(() => document.querySelector('#chart-page').dataset.loaded === 'true');
    assert.equal(await page.locator('#chart-page').getAttribute('data-price-mode'), 'close');
    assert.match(await page.locator('#price-mode-note').innerText(), /真实收盘线，不补造 K 线/);
    if (output) await page.screenshot({ path:path.join(output, 'chart-close-only.png'), fullPage:true });
    pass('close-only historical source renders a labelled line without synthetic candle OHLC');
    replayReady = false;
    await page.goto(origin + '/chart.html?code=sh000001&asof=2025-08-11');
    await page.waitForFunction(() => document.querySelector('#chart-page').dataset.loaded === 'true');
    assert.equal(await page.locator('#chart-page').getAttribute('data-model-as-of'), '2025-08-11');
    assert.ok((await page.locator('#chart-page').getAttribute('data-last-bar-date')) <= '2025-08-11');
    assert.match(await page.locator('#asof-notice').innerText(), /修订时点未记录/);
    pass('exact published history frame fallback clips market bars and labels revision limits');
    await page.goto(origin + '/chart.html?code=sh000001&asof=2026-06-26');
    await page.locator('#error-panel').waitFor({ state:'visible' });
    assert.match(await page.locator('#error-message').innerText(), /只读访问未发起计算/);
    assert.notEqual(await page.locator('#chart-page').getAttribute('data-loaded'), 'true');
    await page.goto(origin + '/chart.html?code=sh000001&asof=2026-02-29');
    await page.locator('#error-panel').waitFor({ state:'visible' });
    assert.match(await page.locator('#error-message').innerText(), /历史截止日无效/);
    assert.deepEqual(requests.filter(r => r.method !== 'GET'), []);
    pass('missing/invalid historical dates never display latest or issue POST');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed:checks.length, pageErrors:errors, writes:requests.filter(r => r.method !== 'GET').length }));
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); process.exitCode=1; server.close(); });
