/* Run manually with Playwright available; no production endpoint is contacted.
 * LPPL_PLAYWRIGHT_MODULE may point to an existing playwright or playwright-core installation.
 * LPPL_BROWSER_EXECUTABLE is optional when the package's Chromium is installed.
 * LPPL_SCREENSHOT_DIR must point outside the repository for disposable QA captures.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.env.LPPL_PLAYWRIGHT_MODULE || 'playwright');
const Core = require('../app/research-workspace-core.js');
const ROOT = path.resolve(__dirname, '../..');
const FRONT = path.join(ROOT, 'frontend');
const FIX = path.join(__dirname, 'fixtures');
const requests = [], failures = [];
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.woff2': 'font/woff2' };
const fixturePaths = {
  '/lab/mock/data/sh000001_latest.json': 'sh000001_latest.json',
  '/lab/mock/data/stock/600519.json': 'stock_600519.json'
};
let failStock = false;
let delayFirstIndex = true;
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  requests.push({ method: req.method, path: url.pathname });
  if (req.method !== 'GET') { res.writeHead(405); res.end(); return; }
  if (url.pathname === '/lab/mock/data/stock/index.json') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ '600519': { name: '贵州茅台', asof: '2026-11-17' }, '000001': { name: '平安银行', asof: '2026-11-17' } })); return;
  }
  if (failStock && url.pathname === '/lab/mock/data/stock/600519.json') { res.writeHead(503); res.end('{}'); return; }
  let file;
  if (fixturePaths[url.pathname]) file = path.join(process.env.LPPL_PUBLISHED_SAMPLE_DIR || FIX, fixturePaths[url.pathname]);
  else if (url.pathname.startsWith('/lab/')) file = path.resolve(ROOT, 'web', '.' + url.pathname.slice(4));
  else file = path.resolve(FRONT, '.' + url.pathname);
  if ((!fixturePaths[url.pathname] && !file.startsWith(ROOT + path.sep)) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404); res.end(); return;
  }
  const send = () => {
    res.writeHead(200, { 'content-type': mime[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
    fs.createReadStream(file).pipe(res);
  };
  if (url.pathname === '/lab/mock/data/sh000001_latest.json' && delayFirstIndex) {
    delayFirstIndex = false;
    setTimeout(send, 1200); // Adding the second asset must survive an in-flight refresh.
  } else send();
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ headless: true, ...(process.env.LPPL_BROWSER_EXECUTABLE ? { executablePath: process.env.LPPL_BROWSER_EXECUTABLE } : {}) });
  const checks = [];
  const check = (name) => { checks.push(name); console.log('PASS ' + name); };
  async function context(options = {}) {
    const ctx = await browser.newContext(options);
    await ctx.route('**/*', route => {
      if (route.request().url().startsWith(origin + '/')) return route.continue();
      return route.fulfill({ status: 503, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: '{"error":"offline browser test"}' });
    });
    return ctx;
  }
  async function noOverflow(page) {
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true, 'page must not overflow horizontally');
  }
  async function screenshot(page, name) {
    if (!process.env.LPPL_SCREENSHOT_DIR) return;
    fs.mkdirSync(process.env.LPPL_SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: path.join(process.env.LPPL_SCREENSHOT_DIR, name + '.png'), fullPage: true });
  }
  try {
    const ctx = await context({ viewport: { width: 1440, height: 1000 } });
    const page = await ctx.newPage();
    page.on('pageerror', e => failures.push(e.message));
    await page.goto(origin + '/research-workspace.html');
    await page.locator('#empty-watch').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#watch-count').innerText(), '0');
    await noOverflow(page);
    check('first visit has no invented watchlist or model results');

    await page.locator('[data-add-sample="index:sh000001"]').click();
    await page.locator('#watch-list .asset-select').first().waitFor();
    const ruleDisclosure = page.locator('.detail-panel details.record-details').filter({ hasText: '结果口径说明' }).first();
    await ruleDisclosure.waitFor();
    await ruleDisclosure.locator('summary').click();
    assert.match(await ruleDisclosure.locator('.record-caption').innerText(), /占比不是概率/);
    check('proportion definition is not presented as a probability');
    await page.locator('#open-add').click();
    await page.locator('#add-code').fill('600519');
    await page.locator('#add-form button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('#watch-count').textContent.trim() === '2');
    await page.waitForFunction(() => document.querySelector('#watch-list').textContent.includes('贵州茅台')).catch(async error => {
      console.error(JSON.stringify({ list: await page.locator('#watch-list').innerText(), refresh: await page.locator('#refresh-state').innerText(), detail: await page.locator('#detail-summary').innerText(), requests }, null, 2));
      await screenshot(page, 'workspace-load-failure');
      throw error;
    });
    assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('lppl.watchlist.v1'))), ['600519']);
    assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('lppl.watchlist.idx.v1'))), ['sh000001']);
    check('adding a second asset during an in-flight refresh loads both shared watchlist items');

    await page.locator('#watch-list .asset-select').filter({ hasText: '贵州茅台' }).click();
    await page.locator('#open-group').click();
    await page.locator('#group-name').fill('消费观察');
    await page.locator('#group-form button[type="submit"]').click();
    await page.locator('#asset-group').selectOption({ label: '消费观察' });
    const text = '关注理由：观察区间与证据。<img src=x onerror=alert(1)>';
    await page.locator('#research-note').fill(text);
    await page.locator('#save-note').click();
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#watch-count').textContent.trim() === '2');
    await page.locator('#watch-list .asset-select').filter({ hasText: '贵州茅台' }).click();
    assert.equal(await page.locator('#research-note').inputValue(), text);
    assert.equal(await page.locator('#asset-group option:checked').innerText(), '消费观察');
    assert.equal(await page.locator('#note-history img').count(), 0);
    check('groups and plain-text notes survive reload without HTML execution');

    await page.locator('#research-note').fill('第二版：保留第一版依据。');
    await page.locator('#save-note').click();
    assert.ok(Number(await page.locator('#note-version-count').innerText()) >= 2);
    const unchangedTab = await ctx.newPage();
    await unchangedTab.goto(origin + '/research-workspace.html');
    await unchangedTab.waitForFunction(() => !document.getElementById('refresh-results').disabled);
    assert.equal(await page.evaluate(() => document.getElementById('storage-warning').hidden), true);
    await page.locator('#research-note').fill('第二标签打开后仍可保存。');
    await page.locator('#save-note').click();
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('lppl.research-workspace.v1')).notes.some(n => n.text === '第二标签打开后仍可保存。')), true);
    await unchangedTab.close();
    check('opening a second workspace tab with unchanged data does not block note saves');
    await page.locator('#list-search').fill('茅台');
    await page.waitForFunction(() => document.querySelectorAll('#watch-list .asset-select').length === 1);
    await page.reload();
    assert.equal(await page.locator('#list-search').inputValue(), '茅台');
    await page.locator('#list-search').fill('');
    await page.waitForFunction(() => document.querySelectorAll('#watch-list .asset-select').length === 2);
    check('note versions and list filters are retained');

    await page.locator('#watch-list input[type="checkbox"]').nth(0).check();
    await page.locator('#watch-list input[type="checkbox"]').nth(1).check();
    await page.locator('.compare-table').waitFor();
    assert.match(await page.locator('#compare-content').innerText(), /日期|截止/);
    await noOverflow(page);
    await screenshot(page, 'workspace-desktop');
    check('structured comparison renders distinct dated results');
    const keyboardRow = page.locator('#watch-list .asset-select').filter({ hasText: '贵州茅台' });
    await keyboardRow.focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.select), 'stock:600519');
    check('keyboard selection retains focus after list redraw');

    assert.match(await page.locator('#detail-code').innerText(), /上交所 SSE.*CNY.*交易状态未提供/);
    const publicDownload = page.waitForEvent('download');
    await page.locator('#share-summary').click();
    const publicFile = await publicDownload, publicCard = JSON.parse(fs.readFileSync(await publicFile.path(), 'utf8'));
    assert.equal(publicCard.asset.code, '600519');
    for (const key of ['asof', 'source', 'modelVersion', 'evidence', 'firstPublicAt']) assert.ok(Object.hasOwn(publicCard, key));
    assert.equal(publicCard.firstPublicAt, null);
    assert.equal(['notes', 'holdings', 'groups', 'account'].some(key => Object.hasOwn(publicCard, key)), false);
    assert.equal(JSON.stringify(publicCard).includes('第二版'), false);
    check('anonymous card includes provenance and excludes private notes and positions');

    await page.locator('#remove-asset').click();
    assert.equal(await page.locator('#watch-count').innerText(), '1');
    await page.locator('#undo-remove').click();
    assert.equal(await page.locator('#watch-count').innerText(), '2');
    await page.waitForFunction(() => !document.getElementById('refresh-results').disabled);
    assert.equal(await page.locator('#research-note').inputValue(), '第二标签打开后仍可保存。');
    check('remove and undo preserve notes and groups');

    const other = await ctx.newPage();
    await other.goto(origin + '/app/research-workspace.css');
    const previouslySaved = await page.locator('#research-note').inputValue();
    await other.evaluate(() => {
      const key = 'lppl.research-workspace.v1', s = JSON.parse(localStorage.getItem(key));
      s.revision += 1;
      s.notes.at(-1).text = '另一标签页的新保存内容';
      s.notes.at(-1).version += 1;
      localStorage.setItem(key, JSON.stringify(s));
    });
    await page.locator('#restore-saved').waitFor({ state: 'visible' });
    await page.locator('#restore-saved').click();
    assert.notEqual(previouslySaved, '另一标签页的新保存内容');
    assert.equal(await page.locator('#research-note').inputValue(), '另一标签页的新保存内容');
    check('restoring newer saved notes discards unchanged editor text while preserving real drafts');
    await page.locator('#research-note').fill('此标签页未保存草稿');
    await other.evaluate(() => {
      const key = 'lppl.research-workspace.v1', s = JSON.parse(localStorage.getItem(key));
      s.revision += 1;
      s.notes.push({ ...s.notes.at(-1), id: 'other-tab-note', text: '其他标签页保存内容', version: s.notes.at(-1).version + 1 });
      localStorage.setItem(key, JSON.stringify(s));
    });
    await page.locator('#restore-saved').waitFor({ state: 'visible' });
    await page.locator('#save-note').click();
    assert.match(await page.locator('#note-state').innerText(), /失败/);
    await page.locator('#restore-saved').click();
    assert.equal(await page.locator('#research-note').inputValue(), '此标签页未保存草稿');
    await page.locator('#save-note').click();
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('lppl.research-workspace.v1')).notes.some(n => n.text === '其他标签页保存内容')), true);
    await other.close();
    check('real cross-tab conflict refuses overwrite and restores saved state without losing draft');

    await page.waitForFunction(() => !document.getElementById('refresh-results').disabled);
    const privateDownload = page.waitForEvent('download');
    await page.locator('#export-private').click();
    const privateFile = await privateDownload, privatePath = await privateFile.path();
    const privateBundle = JSON.parse(fs.readFileSync(privatePath, 'utf8'));
    assert.equal(privateBundle.privacy, 'PRIVATE_BACKUP');
    assert.ok(privateBundle.sections[Core.KEY].notes.some(n => n.text === '其他标签页保存内容'));
    await page.locator('#import-private').setInputFiles(privatePath);
    await page.locator('#portable-preview').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#portable-sections input:checked').count(), 0);
    await page.locator('#portable-sections input').filter({ visible: true }).first().check();
    const beforeImport = page.waitForEvent('download');
    await page.locator('#apply-private').click();
    await beforeImport;
    await page.waitForFunction(() => document.getElementById('portable-status').textContent.includes('已导入 1'));
    check('private backup preview defaults to keep local and exports pre-import recovery file');

    await page.locator('#open-discovery').click();
    await page.locator('#discovery-query').fill('平安');
    await page.locator('#discovery-results [data-discover="000001"]').waitFor();
    assert.match(await page.locator('#discovery-results').innerText(), /000001.*SZ/);
    await page.keyboard.press('Escape');
    await page.locator('#discovery-dialog').waitFor({ state: 'hidden' });
    assert.equal(await page.evaluate(() => document.activeElement.id), 'open-discovery');
    check('published catalog discovery distinguishes stock codes and returns keyboard focus');

    const href = await page.locator('#open-analysis').getAttribute('href');
    assert.match(href, /from=research-workspace/);
    assert.doesNotMatch(href, /asof=/);
    const currentFullChart = new URL(await page.locator('#open-full-chart').getAttribute('href'), origin);
    const currentResultAsOf = await page.evaluate(() => {
      const state = JSON.parse(localStorage.getItem('lppl.research-workspace.v1'));
      return state.observations['stock:600519'].at(-1).asof;
    });
    assert.ok(currentResultAsOf);
    assert.equal(currentFullChart.searchParams.has('asof'), false);
    assert.equal(new URL(currentFullChart.searchParams.get('from'), origin).searchParams.has('asof'), false);
    check('current published result opens the full chart without a historical cutoff');
    assert.equal(requests.some(r => r.method === 'POST'), false);
    await page.locator('#open-analysis').click();
    await page.locator('a[href="research-workspace.html"]').filter({ hasText: '返回我的研究' }).waitFor();
    await page.locator('a[href="research-workspace.html"]').filter({ hasText: '返回我的研究' }).click();
    await page.locator('#watch-list .asset-select').filter({ hasText: '贵州茅台' }).waitFor();
    check('analysis has an explicit same-origin return path');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#watch-list .asset-select').filter({ hasText: '贵州茅台' }).click();
    await noOverflow(page);
    await screenshot(page, 'workspace-mobile');
    await page.locator('#open-add').click();
    await page.locator('#add-dialog').waitFor({ state: 'visible' });
    await noOverflow(page);
    await page.keyboard.press('Escape');
    await page.locator('#add-dialog').waitFor({ state: 'hidden' });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await noOverflow(page);
    check('390px and reduced motion keep list, details, and dialog usable');

    const blocked = await context({ viewport: { width: 390, height: 844 } });
    await blocked.addInitScript(() => { Storage.prototype.setItem = function () { throw new DOMException('Quota exceeded', 'QuotaExceededError'); }; });
    const blockedPage = await blocked.newPage();
    await blockedPage.goto(origin + '/research-workspace.html');
    await blockedPage.locator('[data-add-sample="stock:600519"]').click();
    await blockedPage.locator('#storage-warning').waitFor({ state: 'visible' });
    check('storage write failure is visible');

    failStock = true;
    const missing = await context();
    await missing.addInitScript(() => localStorage.setItem('lppl.watchlist.v1', '["600519"]'));
    const missingPage = await missing.newPage();
    await missingPage.goto(origin + '/research-workspace.html');
    await missingPage.locator('#watch-list .asset-select').first().click();
    await missingPage.waitForFunction(() => /未取得|失败|不可用|未加载/.test(document.querySelector('#detail-summary').textContent));
    assert.equal(await missingPage.locator('#save-note').isEnabled(), true);
    await missingPage.locator('#research-note').fill('尚无分析，先记录关注理由。');
    await missingPage.locator('#save-note').click();
    await missingPage.reload();
    await missingPage.locator('#watch-list .asset-select').first().click();
    assert.equal(await missingPage.locator('#research-note').inputValue(), '尚无分析，先记录关注理由。');
    check('missing result retains usable watchlist and notes');
    failStock = false;

    const seeded = Core.initial();
    const a = Core.asset('stock', '600519', '贵州茅台');
    const raw = JSON.parse(fs.readFileSync(path.join(FIX, 'stock_600519.json'), 'utf8'));
    const first = { ...Core.summarize(a, raw), modelVersion: 'fixture-v1', predictionId: 'fixture-A' };
    const second = { ...first, modelVersion: 'fixture-v2', predictionId: 'fixture-B' };
    const identityOnly = { ...second, predictionId: 'fixture-C' };
    for (const [i, summary] of [first, second, identityOnly].entries()) {
      const stamp = '2026-11-18T01:0' + i + ':00.000Z';
      Core.observe(seeded, summary, stamp);
      Core.recordVisit(seeded, summary, stamp);
    }
    assert.equal(seeded.observations[a.id].length, 2);
    const restored = await context();
    await restored.addInitScript(({ key, data }) => {
      localStorage.setItem('lppl.watchlist.v1', '["600519"]');
      localStorage.setItem(key, JSON.stringify(data));
    }, { key: Core.KEY, data: seeded });
    const restoredPage = await restored.newPage();
    await restoredPage.goto(origin + '/research-workspace.html');
    await restoredPage.locator('#resume-items button').nth(2).click();
    assert.match(await restoredPage.locator('#detail-summary').innerText(), /fixture-v1/);
    await restoredPage.locator('#resume-items button').nth(0).click();
    assert.match(await restoredPage.locator('#detail-summary').innerText(), /fixture-C/);
    check('resume restores the exact model and prediction identity without inventing another alert');

    const skipContext = await context({ viewport: { width: 1024, height: 768 } });
    const skipPage = await skipContext.newPage();
    await skipPage.goto(origin + '/research-workspace.html');
    await skipPage.keyboard.press('Tab');
    assert.equal(await skipPage.evaluate(() => document.activeElement.classList.contains('skip-link')), true);
    check('first keyboard Tab reaches the visible workspace skip link');
    await skipContext.close();

    const tabletContext = await context({ viewport: { width: 820, height: 1000 } });
    await tabletContext.addInitScript(() => localStorage.setItem('lppl.watchlist.v1', '["600519"]'));
    const tabletPage = await tabletContext.newPage();
    await tabletPage.goto(origin + '/research-workspace.html');
    await tabletPage.waitForFunction(() => !document.getElementById('refresh-results').disabled);
    const overlap = await tabletPage.evaluate(() => {
      const checkbox = document.querySelector('.compare-check input').getBoundingClientRect();
      const detail = document.querySelector('.detail-panel').getBoundingClientRect();
      return checkbox.left < detail.right && checkbox.right > detail.left &&
        checkbox.top < detail.bottom && checkbox.bottom > detail.top;
    });
    assert.equal(overlap, false);
    check('tablet comparison checkbox remains clear of the detail pane');
    await tabletContext.close();

    const drawerContext = await context({ viewport: { width: 1024, height: 768 } });
    await drawerContext.addInitScript(() => localStorage.setItem('lppl.watchlist.v1', '["600519"]'));
    const drawerPage = await drawerContext.newPage();
    await drawerPage.goto(origin + '/research-workspace.html');
    await drawerPage.waitForFunction(() => !document.getElementById('refresh-results').disabled);
    await drawerPage.locator('button[aria-label="打开自选"]').click();
    await drawerPage.locator('#odw-b button[data-rm="600519"]').click();
    await drawerPage.waitForFunction(() => document.getElementById('watch-count').textContent.trim() === '0');
    assert.equal(await drawerPage.locator('#watch-list [data-row="stock:600519"]').count(), 0);
    check('removing a stock in the shared sidebar immediately removes its workspace row');
    await drawerContext.close();

    const replayRaw = JSON.parse(fs.readFileSync(path.join(FIX, 'stock_600519_2025-05-23.json'), 'utf8'));
    const replayAsset = Core.asset('stock', '600519', '贵州茅台');
    const replayState = Core.initial();
    replayState.selectedId = replayAsset.id;
    const replaySummary = Core.summarize(replayAsset, replayRaw, '2025-05-24T00:00:00.000Z');
    Core.observe(replayState, replaySummary, '2025-05-24T00:00:00.000Z');
    Core.saveNote(replayState, replaySummary, '回放日的研究依据', '2025-05-24T00:00:00.000Z');
    const alternateSummary = Core.summarize(replayAsset, { ...replayRaw, asof: '2025-06-01',
      prediction_id: 'replay-fixture-20250601' }, '2025-06-02T00:00:00.000Z');
    Core.observe(replayState, alternateSummary, '2025-06-02T00:00:00.000Z');
    const replayStore = { value: null, getItem(key) { return key === Core.KEY ? this.value : null; },
      setItem(key, value) { if (key === Core.KEY) this.value = value; } };
    Core.save(replayStore, replayState);
    const replayContext = await context({ viewport: { width: 1280, height: 900 } });
    await replayContext.addInitScript(({ key, data }) => {
      localStorage.setItem('lppl.watchlist.v1', '["600519"]');
      localStorage.setItem(key, data);
    }, { key: Core.KEY, data: replayStore.value });
    const replayPage = await replayContext.newPage();
    await replayPage.goto(origin + '/research-workspace.html?kind=stock&code=600519&asof=2025-05-23');
    await replayPage.waitForFunction(() => !document.getElementById('refresh-results').disabled);
    assert.match(await replayPage.locator('#detail-summary').innerText(), /2025-05-23|2025-06-02/);
    await replayPage.locator('#note-history').evaluate(el => { el.closest('details').open = true; });
    assert.match(await replayPage.locator('#note-history').innerText(), /回放日的研究依据/);
    assert.equal(await replayPage.evaluate(() => JSON.parse(localStorage.getItem('lppl.research-workspace.v1')).observations['stock:600519'].find(r => r.asof === '2025-05-23').windows[0].evidence), 'research_candidate');
    await replayPage.evaluate(() => window.scrollTo(0, Math.floor(document.documentElement.scrollHeight / 3)));
    const savedScroll = await replayPage.evaluate(() => window.scrollY);
    await replayPage.locator('#open-full-chart').click();
    await replayPage.waitForURL(/chart\.html/);
    assert.match(replayPage.url(), /asof=2025-05-23/);
    assert.match(decodeURIComponent(new URL(replayPage.url()).searchParams.get('from')), /kind=stock.*code=600519.*asof=2025-05-23/);
    await replayPage.locator('#return-link').waitFor();
    assert.match(await replayPage.locator('body').innerText(), /该日封存未就绪；未触发计算/);
    await replayPage.locator('#return-link').click();
    await replayPage.waitForURL(/research-workspace\.html.*asof=2025-05-23/);
    await replayPage.waitForFunction(() => !document.getElementById('refresh-results').disabled);
    assert.match(await replayPage.locator('#detail-summary').innerText(), /2025-06-02/);
    await replayPage.locator('#note-history').evaluate(el => { el.closest('details').open = true; });
    assert.match(await replayPage.locator('#note-history').innerText(), /回放日的研究依据/);
    assert.equal(await replayPage.evaluate(() => JSON.parse(localStorage.getItem('lppl.research-workspace.v1')).observations['stock:600519'].find(r => r.asof === '2025-05-23').windows[0].evidence), 'research_candidate');
    assert.ok(Math.abs(await replayPage.evaluate(() => window.scrollY) - savedScroll) <= 2);
    await replayPage.locator('#observation-history').evaluate(el => { el.closest('details').open = true; });
    await replayPage.locator('#observation-history button[data-inspect="1"]').click();
    assert.equal(new URL(replayPage.url()).searchParams.get('asof'), '2025-06-01');
    assert.match(await replayPage.locator('#detail-summary').innerText(), /2025-06-02/);
    assert.doesNotMatch(await replayPage.locator('#detail-summary').innerText(), /本机未保存截至/);
    await replayPage.locator('#observation-history #show-current').click();
    assert.equal(new URL(replayPage.url()).searchParams.has('asof'), false);
    assert.match(await replayPage.locator('#detail-summary').innerText(), new RegExp(raw.asof));
    assert.doesNotMatch(await replayPage.locator('#detail-summary').innerText(), /本机未保存截至/);
    check('selecting another saved date updates the URL; returning to current clears the replay cutoff');
    check('full-chart return preserves the archived workspace date, evidence, note and list position without latest fallback');
    await replayContext.close();

    const missingReplayState = Core.initial();
    const latestSummary = Core.summarize(replayAsset, raw, '2026-11-18T00:00:00.000Z');
    Core.observe(missingReplayState, latestSummary, '2026-11-18T00:00:00.000Z');
    Core.saveNote(missingReplayState, latestSummary, '最新结果笔记', '2026-11-18T00:00:00.000Z');
    const missingReplayStore = { value: null, getItem(key) { return key === Core.KEY ? this.value : null; },
      setItem(key, value) { if (key === Core.KEY) this.value = value; } };
    Core.save(missingReplayStore, missingReplayState);
    const missingReplayContext = await context();
    await missingReplayContext.addInitScript(({ key, data }) => {
      localStorage.setItem('lppl.watchlist.v1', '["600519"]');
      localStorage.setItem(key, data);
    }, { key: Core.KEY, data: missingReplayStore.value });
    const missingReplayPage = await missingReplayContext.newPage();
    await missingReplayPage.goto(origin + '/research-workspace.html?kind=stock&code=600519&asof=2025-05-23');
    await missingReplayPage.waitForFunction(() => !document.getElementById('refresh-results').disabled);
    assert.equal(await missingReplayPage.locator('#save-note').isEnabled(), false);
    await missingReplayPage.locator('#research-note').fill('缺少摘要时误绑定');
    await missingReplayPage.locator('#save-note').click({ force: true });
    const misbound = await missingReplayPage.evaluate(() => JSON.parse(localStorage.getItem('lppl.research-workspace.v1')).notes);
    assert.equal(misbound.some(note => note.text === '缺少摘要时误绑定'), false);
    assert.ok(misbound.some(note => note.text === '最新结果笔记' && note.asof === latestSummary.asof));
    check('replay without an exact local summary cannot save a note against another date');
    await missingReplayContext.close();

    assert.deepEqual(failures, []);
    check('no uncaught browser exceptions');
    console.log(JSON.stringify({ checks: checks.length, names: checks, fixture_mode: !process.env.LPPL_PUBLISHED_SAMPLE_DIR, archived_published_samples: !!process.env.LPPL_PUBLISHED_SAMPLE_DIR, external_requests_fulfilled_offline: true }, null, 2));
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
