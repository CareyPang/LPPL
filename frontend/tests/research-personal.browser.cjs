/* Offline interaction check. No production requests, fitting or writes.
 * Use LPPL_PLAYWRIGHT_MODULE / LPPL_BROWSER_EXECUTABLE for an existing installation.
 * Optional screenshots belong in LPPL_SCREENSHOT_DIR outside the repository. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.LPPL_PLAYWRIGHT_MODULE || 'playwright');
const FRONT = path.resolve(__dirname, '..');
const calls = [], errors = [];
let failEvents = true;
const eventPayload = { asof: '2026-11-17', generated: '2026-11-18T01:00:00Z', window: { lift: ['2026-11-17', '2026-12-17'], dividend: ['2026-11-17', '2026-12-17'], forecast: ['2026-10-18', '2026-11-17'] }, sources: { lift: { provider: 'test.source', ok: true, stale: false, fetched_at: '2026-11-18T01:00:00Z' }, dividend: { provider: 'test.source', ok: true }, forecast: { provider: 'test.source', ok: true } }, lift: [{ code: '600519', name: '贵州茅台', free_date: '2026-11-25', free_shares_type: '测试事件，并非真实公告', first_seen_at: '2026-11-18T01:00:00Z' }], dividend: [{ code: '600519', name: '<img src=x onerror=alert(1)>', ex_dividend_date: '2026-11-18', plan_text: '测试分配方案' }], forecast: [] };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1'); calls.push({ method: req.method, path: url.pathname });
  if (req.method !== 'GET') { res.writeHead(405); res.end(); return; }
  if (url.pathname === '/lab/mock/data/events/events_latest.json') { res.writeHead(failEvents ? 503 : 200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(eventPayload)); return; }
  let file = url.pathname === '/lab/mock/data/stock/600519.json' ? path.join(__dirname, 'fixtures/stock_600519.json') : path.resolve(FRONT, '.' + url.pathname);
  if (!file.startsWith(FRONT + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end('{}'); return; }
  res.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' })[path.extname(file)] || 'application/octet-stream' }); fs.createReadStream(file).pipe(res);
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ headless: true, ...(process.env.LPPL_BROWSER_EXECUTABLE ? { executablePath: process.env.LPPL_BROWSER_EXECUTABLE } : {}) });
  try {
    for (const width of [1440, 390]) {
      const ctx = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 } });
      await ctx.route('**/*', route => route.request().url().startsWith(origin + '/') ? route.continue() : route.fulfill({ status: 503, body: '{}' }));
      await ctx.addInitScript(() => localStorage.setItem('lppl.watchlist.v1', '["600519"]'));
      const page = await ctx.newPage(); page.on('pageerror', err => errors.push(String(err)));
      failEvents = true;
      await page.goto(origin + '/research-workspace.html', { waitUntil: 'networkidle' });
      assert.equal(await page.locator('#personal-events').isVisible(), false);
      // The personal calendar starts only when explicitly opened.
      const previousEventCalls = calls.filter(r => r.path.endsWith('events_latest.json')).length;
      await page.locator('#personal-calendar > summary').click();
      await page.getByText('未取得可用的事件快照。', { exact: false }).waitFor();
      assert.equal(calls.filter(r => r.path.endsWith('events_latest.json')).length, previousEventCalls + 1);
      failEvents = false; await page.locator('#events-retry').click();
      await page.locator('#calendar-clear').click();
      await page.getByText('测试事件，并非真实公告', { exact: true }).waitFor();
      assert.equal(await page.locator('#personal-events img').count(), 0);
      await page.locator('#calendar-day').fill('2026-11-25');
      assert.equal(await page.locator('#personal-events .personal-event').count(), 1);
      assert.match(await page.locator('#personal-events').textContent(), /发布日期未知/);
      await page.locator('#calendar-month').fill('2026-12');
      assert.match(await page.locator('#personal-events').textContent(), /没有匹配的自选事件/);
      await page.locator('#calendar-clear').click();
      // Zero cost is a valid record, whereas an absent holding is an em dash.
      await page.locator('#personal-portfolio > summary').click();
      assert.equal(await page.locator('#holdings-total').textContent(), '—');
      await page.locator('#holding-form-details > summary').click();
      await page.locator('#holding-code').fill('600519'); await page.locator('#holding-name').fill('贵州茅台');
      await page.locator('#holding-shares').fill('100'); await page.locator('#holding-cost').fill('0');
      await page.locator('#holding-form [type=submit]').click();
      assert.equal(await page.locator('#holdings-total').textContent(), '0.00 元');
      await page.getByRole('button', { name: '编辑', exact: true }).click();
      await page.locator('#holding-cost').fill('1500'); await page.locator('#holding-form [type=submit]').click();
      await page.locator('#holding-unit').selectOption('wan');
      assert.equal(await page.locator('#holdings-total').textContent(), '15.00 万元');
      await page.getByRole('button', { name: '删除记录', exact: true }).click();
      assert.equal(await page.locator('#holdings-total').textContent(), '—');
      await page.locator('#holding-undo').click();
      assert.equal(await page.locator('#holdings-total').textContent(), '15.00 万元');
      // Inject a real schema result change; metadata-only update must not create a new item.
      await page.evaluate(() => {
        const C = ResearchWorkspaceCore, state = C.load(localStorage), list = state.observations['stock:600519'], base = list[list.length - 1];
        state.observations['stock:600519'] = [{ ...base, id: 'test-base' }, { ...base, id: 'test-metadata', modelVersion: 'other' }, { ...base, id: 'test-change', modelVersion: 'other', status: base.status === 'no_cluster' ? 'unavailable' : 'no_cluster' }];
        localStorage.setItem(C.KEY, JSON.stringify(state)); window.dispatchEvent(new CustomEvent('workspace-change'));
      });
      await page.locator('#personal-inbox > summary').click();
      assert.equal(await page.locator('#personal-unread').textContent(), '1 条未读');
      await page.locator('#changes-mark-all').click();
      assert.equal(await page.locator('#personal-unread').textContent(), '0 条未读');
      assert.equal(await page.evaluate(() => ResearchPersonalCore.load(localStorage).readChanges.length), 1);
      await page.getByRole('button', { name: '编辑', exact: true }).click();
      await page.locator('#holding-cost').fill('1600');
      const other = await ctx.newPage();
      await other.goto(origin + '/app/research-personal.css');
      await other.evaluate(() => {
        const key = 'lppl.research-personal.v1', value = JSON.parse(localStorage.getItem(key));
        value.revision += 1; value.holdings[0].cost = 1550; localStorage.setItem(key, JSON.stringify(value));
      });
      await page.waitForFunction(() => document.getElementById('personal-message').textContent.includes('另一页'));
      await page.locator('#holding-form [type=submit]').click();
      assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('lppl.research-personal.v1')).holdings[0].cost), 1550);
      assert.equal(await page.locator('#holding-cost').inputValue(), '1600');
      await page.locator('#personal-reload').click();
      assert.equal(await page.locator('#holding-cost').inputValue(), '1600');
      await page.locator('#holding-form [type=submit]').click();
      assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('lppl.research-personal.v1')).holdings[0].cost), 1600);
      await other.close();
      // Failed writes must leave both storage and UI data intact.
      await page.evaluate(() => { const original = Storage.prototype.setItem; Storage.prototype.setItem = function (key, value) { if (key === ResearchPersonalCore.KEY) throw new Error('simulated quota'); return original.call(this, key, value); }; });
      await page.getByRole('button', { name: '删除记录', exact: true }).click();
      assert.match(await page.locator('#personal-message').textContent(), /未保存/);
      assert.equal(await page.locator('#personal-holdings .personal-holding').count(), 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true);
      const small = await page.locator('#research-personal button:visible,#research-personal input:visible,#research-personal select:visible').evaluateAll(els => els.filter(el => el.getBoundingClientRect().height < 43.5).map(el => el.id));
      assert.deepEqual(small, []);
      if (process.env.LPPL_SCREENSHOT_DIR) { fs.mkdirSync(process.env.LPPL_SCREENSHOT_DIR, { recursive: true }); await page.locator('#research-personal').screenshot({ path: path.join(process.env.LPPL_SCREENSHOT_DIR, 'personal-' + width + '.png') }); }
      console.log('PASS personal modules ' + width + 'px: lazy events/retry/history boundaries/XSS/holdings units/undo/inbox/storage failure/no overflow/44px');
      await ctx.close();
    }
    assert.deepEqual(errors, []); assert.equal(calls.some(r => r.method !== 'GET'), false);
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; server.close(); });
