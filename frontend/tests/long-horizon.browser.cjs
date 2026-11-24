/* Actual local research output, with no browser-side fitting or write requests. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.LPPL_PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.LPPL_PREVIEW_URL || 'http://127.0.0.1:8796';
const root = process.env.LPPL_LONG_RESULTS;
assert.ok(root, 'LPPL_LONG_RESULTS must point to actual completed research');
const summary = JSON.parse(fs.readFileSync(path.join(root, 'summary.json'), 'utf8'));
const output = path.join(root, 'browser');
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.LPPL_BROWSER_EXECUTABLE });
  const checks = [], errors = [], writes = [];
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 960 } });
      await context.route('**/app/lppl-chart.js', async route => {
        const response = await route.fetch();
        await route.fulfill({ response, body: await response.text() +
          '\n;const oldMount=LPPLChart.mount;LPPLChart.mount=function(...args){const c=oldMount(...args),oldSet=c.setData;c.setData=function(d){window.__qaData=d;return oldSet(d);};return c;};' });
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      page.on('request', request => { if (request.method() !== 'GET') writes.push(request.url()); });
      for (const symbol of ['US_IXIC', 'US_NDX']) {
        await page.goto(origin + '/chart.html?code=' + symbol + '&kind=index&from=home.html%3Fmarket%3Dus#long-horizon-card');
        await page.waitForFunction(() => document.querySelector('#chart-page')?.dataset.loaded === 'true');
        const card = page.locator('#long-horizon-card');
        assert.equal(await card.isVisible(), true);
        assert.equal(await card.getAttribute('open'), '', 'direct link opens long-window study');
        await page.waitForFunction(() => document.querySelectorAll('.lh-window').length === 6);
        const data = await page.evaluate(() => window.__qaData);
        assert.equal(data.raw.research.long_horizon.asof, summary.assets[symbol].asof);
        assert.deepEqual(data.raw.research.long_horizon.windows, summary.assets[symbol].windows);
        assert.equal(data.raw.fit_counts.expected, 27, 'original short-window result is not replaced');
        const frozen = JSON.stringify(data.top);
        assert.equal(await card.locator('.lh-window').count(), 6);
        assert.match(await card.innerText(), /单窗研究候选/);
        assert.doesNotMatch(await card.innerText(), /\[object Object\]|NaN|undefined/);
        await card.locator('[data-lh-rule="cycles_2_5"]').click();
        assert.equal(await card.locator('[data-lh-rule="cycles_2_5"]').getAttribute('aria-pressed'), 'true');
        assert.equal(await page.evaluate(() => JSON.stringify(window.__qaData.top)), frozen);
        await card.locator('[data-lh-rule="cycles_1_5"]').click();
        const g3 = card.locator('details').filter({ has: page.locator('summary', { hasText: 'G3 对照' }) });
        assert.match(await g3.locator('summary').innerText(), /合格 0\/6/);
        await g3.locator('summary').click();
        assert.match(await g3.innerText(), /搜索域与预算不同/);
        const profile = card.locator('details').filter({ has: page.locator('summary', { hasText: '把顶部放在不同时间' }) });
        await profile.locator('summary').click();
        assert.match(await profile.innerText(), /SSE|误差/);
        assert.match(await profile.innerText(), /16/);
        assert.match(await profile.innerText(), /46/);
        assert.ok(data.raw.research.long_horizon.profile_diagnostic.points.length === 31);
        assert.ok(data.raw.research.long_horizon.profile_diagnostic.points.every(p => p.sse === null || p.delta_sse_pct >= 0));
        await card.locator('.lh-history > summary').click();
        if (symbol === 'US_NDX') assert.match(await card.locator('.lh-history').innerText(), /未取得|不可复用|缺档/);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
        await page.screenshot({ path: path.join(output, symbol + '-' + width + '.png'), fullPage: true });
        checks.push(width + ': ' + symbol + ' actual 24-seed study, rule isolation, G3 and exact history');

        await page.goto(origin + '/chart.html?code=' + symbol + '&kind=index&asof=2026-11-13#long-horizon-card');
        await page.waitForFunction(() => document.querySelector('#chart-page')?.dataset.loaded === 'true');
        assert.equal(await page.evaluate(() => window.__qaData.raw.research.long_horizon), undefined);
        assert.match(await card.innerText(), /本截止日没有长窗口研究结果/);
        const historicTop = await page.evaluate(() => JSON.stringify(window.__qaData.top));
        const historicBars = await page.evaluate(() => window.__qaData.bars.length);
        await page.locator('#terminal-show-future').check();
        await page.waitForFunction(n => window.__qaData.bars.length > n, historicBars);
        assert.equal(await page.evaluate(() => JSON.stringify(window.__qaData.top)), historicTop);
        assert.equal(await page.evaluate(() => window.__qaData.raw.research.long_horizon), undefined);
        checks.push(width + ': ' + symbol + ' no latest long-window leakage during historic/later-price replay');
      }
      await page.goto(origin + '/chart.html?code=US_MRVL&kind=stock');
      await page.waitForFunction(() => document.querySelector('#chart-page')?.dataset.loaded === 'true');
      assert.equal(await page.locator('#long-horizon-card').isVisible(), false);
      checks.push(width + ': unrelated asset remains unchanged');
      await context.close();
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, []);
    const result = { checks, errors, writes, inspected_at: new Date().toISOString(), widths: [1440, 390],
      study_counts: summary.counts, study_generated_at: summary.generated_at };
    fs.writeFileSync(path.join(output, 'acceptance.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
