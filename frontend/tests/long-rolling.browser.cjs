/* Read-only browser acceptance of actual daily sources and frozen long research.
 * Start the loopback preview with the new daily --long-results first.
 * LPPL_LONG_RESULTS points at global-daily-long; LPPL_SCREENSHOT_DIR stays on D:.
 * No source fetch, fit submission, historical reconstruction or publication here.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.LPPL_PLAYWRIGHT_MODULE || 'playwright');

const origin = process.env.LPPL_PREVIEW_URL || 'http://127.0.0.1:8796';
assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(new URL(origin).hostname), 'Only loopback preview is allowed');
const root = process.env.LPPL_LONG_RESULTS;
assert.ok(root && path.isAbsolute(root), 'LPPL_LONG_RESULTS must be an absolute directory of real daily results');
const summary = JSON.parse(fs.readFileSync(path.join(root, 'summary.json'), 'utf8'));
const output = process.env.LPPL_SCREENSHOT_DIR || path.join(root, 'browser-acceptance');
assert.ok(path.isAbsolute(output), 'Screenshot output must be absolute');
if (process.platform === 'win32') assert.match(output, /^D:[\\/]/i, 'Evidence belongs on D:');
const symbols = ['US_IXIC', 'US_NDX', 'KR_KOSPI', 'KR_KOSDAQ'];
const windows = [900, 925, 950, 6500, 6600, 6700];
const expectedHistory = Number(process.env.LPPL_EXPECT_HISTORY_COUNT || 51);
const widths = [1440, 390];
const checks = [], errors = [], writes = [], networkFailures = [], screenshots = [], archives = [], layoutChecks = [];
const pass = (width, symbol, description) => {
  checks.push({ width, symbol, description, status: 'VERIFIED' });
  console.log('PASS ' + width + ' ' + symbol + ': ' + description);
};
const serialize = value => JSON.stringify(value);

async function shot(page, name) {
  const target = path.join(output, name + '.png');
  await page.screenshot({ path: target, fullPage: false });
  screenshots.push(target);
}

async function loaded(page, symbol, asof) {
  await page.waitForFunction(() => document.querySelector('#chart-page')?.dataset.loaded === 'true', null, { timeout: 60000 });
  await page.waitForFunction(() => window.__qaData?.raw, null, { timeout: 20000 });
  const data = await page.evaluate(() => window.__qaData);
  assert.equal(data.symbol, symbol);
  if (asof) assert.equal(data.raw.asof, asof);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, 'No horizontal page overflow');
  return data;
}

async function checkHistoryReplay(page, width, symbol, current) {
  const response = await page.request.get(origin + '/lab/mock/data/global/' + symbol + '_history.json');
  assert.equal(response.ok(), true, 'Existing primary history must remain readable');
  const history = await response.json();
  const candidates = [...new Set((history.frames || []).map(row => row.asof))]
    .filter(date => date < current.asof).sort().reverse();
  assert.ok(candidates.length, symbol + ': need an actual earlier 27-fit archive for anti-leakage acceptance');
  let selected;
  // Choose actual retained records; never manufacture a historical endpoint.
  for (const asof of candidates) {
    const archived = await page.request.get(origin + '/lab/mock/data/global/' + symbol + '_' + asof + '.json');
    if (!archived.ok()) continue;
    const record = await archived.json();
    if (!record.price_history || record.symbol !== symbol || record.asof !== asof) continue;
    if (!selected || !record.research?.long_horizon) selected = { asof, record };
    if (!record.research?.long_horizon) break;
  }
  assert.ok(selected, symbol + ': no readable retained primary archive');
  const { asof, record } = selected;
  await page.goto(origin + '/chart.html?code=' + symbol + '&kind=index&asof=' + asof + '#long-horizon-card');
  let data = await loaded(page, symbol, asof);
  assert.ok(data.bars.every(bar => bar.date <= asof), 'Historical chart starts strictly at its own cutoff');
  const modelBefore = serialize(data.top);
  const longBefore = serialize(data.raw.research?.long_horizon);
  const long = data.raw.research?.long_horizon;
  if (long) {
    assert.equal(long.asof, asof);
    assert.notEqual(long.asof, current.asof);
    assert.ok((long.stability?.history || []).every(row => row.asof < asof));
    assert.ok(!long.profile_diagnostic || long.profile_diagnostic.asof === asof, 'Never inherit current profile into an earlier archive');
    const expected = current.history.find(row => row.asof === asof);
    assert.ok(expected, 'Attached historical result must exist in the retained research ledger');
    assert.deepEqual(long.windows, expected.windows);
  } else {
    assert.match(await page.locator('#long-horizon-card').innerText(), /本截止日没有长窗口研究结果|截止日.*不匹配/);
  }
  const count = data.bars.length;
  await page.locator('#terminal-show-future').check();
  await page.waitForFunction(n => window.__qaData.bars.length > n, count, { timeout: 30000 });
  data = await page.evaluate(() => window.__qaData);
  assert.equal(data.raw.asof, asof);
  assert.equal(serialize(data.top), modelBefore);
  assert.equal(serialize(data.raw.research?.long_horizon), longBefore);
  assert.ok(data.bars.some(bar => bar.date > asof), 'Later prices can be examined without moving the model');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
  archives.push({ width, symbol, asof, primaryDataVersion: record.data_version,
    longAttached: Boolean(long), laterPricesVisible: true, modelUnchanged: true });
  await shot(page, symbol + '-historical-' + width);
  pass(width, symbol, '真实旧档与后续行情回放：保留原顶部结果，未挪用当前长窗、profile或未来历史');
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  assert.equal(summary.status, 'complete');
  for (const symbol of symbols) {
    const asset = summary.assets[symbol];
    assert.ok(asset && asset.symbol === symbol);
    assert.ok(asset.source.rows >= 6700, symbol + ': full real daily history required');
    assert.equal(asset.history.length, expectedHistory);
  }
  const browser = await chromium.launch({ headless: true, executablePath: process.env.LPPL_BROWSER_EXECUTABLE });
  let activePage;
  let failure;
  try {
    for (const width of widths) {
      const context = await browser.newContext({ viewport: { width, height: 960 }, isMobile: width === 390, hasTouch: width === 390 });
      await context.route('**/*', route => ['GET', 'HEAD'].includes(route.request().method())
        ? route.continue() : route.abort('blockedbyclient'));
      // Observe the existing chart adapter without changing prices, fits or filters.
      await context.route('**/app/lppl-chart.js', async route => {
        const response = await route.fetch();
        await route.fulfill({ response, body: await response.text() +
          '\n;const qaOriginalMount=LPPLChart.mount;LPPLChart.mount=function(...args){const chart=qaOriginalMount(...args),originalSet=chart.setData;chart.setData=function(data){window.__qaData=data;return originalSet(data);};return chart;};' });
      });
      const page = await context.newPage();
      activePage = page;
      page.on('pageerror', error => errors.push({ width, url: page.url(), message: error.message }));
      page.on('request', request => {
        if (!['GET', 'HEAD'].includes(request.method())) writes.push({ width, method: request.method(), url: request.url() });
      });
      page.on('requestfailed', request => networkFailures.push({ width, url: request.url(), error: request.failure()?.errorText }));
      for (const symbol of symbols) {
        const expected = summary.assets[symbol];
        await page.goto(origin + '/chart.html?code=' + symbol + '&kind=index&from=home.html');
        const data = await loaded(page, symbol, expected.asof);
        assert.equal(await page.evaluate(() => innerWidth), width, 'Mobile viewport must not shrink a desktop layout');
        assert.equal(data.raw.fit_counts.expected, 27, 'Long study never replaces the current 27-fit model');
        assert.equal(data.raw.fit_counts.completed, 27);
        assert.equal(data.raw.price_history.dates.length, expected.source.rows);
        assert.equal(data.raw.price_history.dates[0], expected.source.first_date);
        const long = data.raw.research.long_horizon;
        assert.ok(long, symbol + ': preview must attach the new exact source-matched study');
        assert.equal(long.source.input_hash, expected.source.input_hash);
        assert.equal(long.source.data_version, expected.source.data_version);
        assert.equal(long.source.rows, expected.source.rows);
        assert.deepEqual(long.windows, expected.windows);
        assert.deepEqual(long.rules, expected.rules);
        assert.equal(long.counts.completed, 12);
        assert.equal(long.counts.expected, 12);
        assert.equal(long.g3_comparison, undefined, 'No legacy G3 comparison is manufactured for this study');
        await page.evaluate(() => scrollTo(0, 0));
        await shot(page, symbol + '-current-chart-' + width);
        pass(width, symbol, '完整真实源与当前27拟合保留；长窗六长度十二seed与冻结JSON一致');

        const card = page.locator('#long-horizon-card');
        if (!await card.evaluate(node => node.open)) await card.locator(':scope > summary').click();
        await card.evaluate(node => node.scrollIntoView({ block: 'start' }));
        await page.waitForFunction(() => document.querySelectorAll('.lh-window').length === 6);
        assert.equal(await card.locator('.lh-window').count(), 6);
        assert.doesNotMatch(await card.innerText(), /\[object Object\]|NaN|undefined/);
        const primary = serialize(data.top);
        for (const rule of ['cycles_1_5', 'cycles_2_5', 'cycles_1_5']) {
          await card.locator('[data-lh-rule="' + rule + '"]').click();
          assert.equal(await card.locator('[data-lh-rule="' + rule + '"]').getAttribute('aria-pressed'), 'true');
          for (let index = 0; index < windows.length; index++) {
            const window = expected.windows.find(row => row.n === windows[index]);
            const panel = card.locator('.lh-window').nth(index);
            assert.match(await panel.locator('h4').innerText(), new RegExp('^' + windows[index] + ' 日'));
            assert.equal(await panel.locator('.lh-window-state').innerText(), window.eligible[rule] ? '单窗研究候选' : '未形成该规则候选');
          }
          assert.equal(await page.evaluate(() => JSON.stringify(window.__qaData.top)), primary);
        }
        assert.equal(await card.locator('summary', { hasText: 'G3 对照' }).count(), 0);
        const profile = card.locator('.lh-profile');
        assert.equal(await profile.count(), 1);
        await profile.locator(':scope > summary').click();
        const expectedProfile = expected.profile_diagnostic;
        assert.equal(expectedProfile.asof, expected.asof);
        assert.equal(expectedProfile.counts.completed, expectedProfile.counts.expected);
        assert.deepEqual(long.profile_diagnostic, expectedProfile);
        assert.ok(Array.isArray(expectedProfile.points));
        assert.ok(expectedProfile.points.every(point => point.ahead >= 1 && point.ahead <= 90 && point.sse > 0 && point.delta_sse_pct >= -1e-9));
        const displayed = expectedProfile.points.filter((_, i, array) => i % 5 === 0 || i === array.length - 1).length;
        assert.equal(await profile.locator('.lh-profile-rows > p').count(), displayed);
        assert.match(await profile.innerText(), new RegExp('已完成 ' + expectedProfile.counts.completed + '/' + expectedProfile.counts.expected));
        assert.match(await profile.innerText(), /没有计算概率/);
        await card.locator('.lh-history > summary').click();
        assert.equal(await card.locator('.lh-history-date').count(), expectedHistory);
        assert.match(await card.locator('.lh-history').innerText(), new RegExp('加上当前截止日共 ' + (expectedHistory + 1) + ' 期'));
        if (await card.locator('.lh-history-earlier').count()) {
          await card.locator('.lh-history-earlier > summary').click();
        }
        assert.equal(await card.locator('.lh-history-date > summary').evaluateAll(nodes => nodes.filter(node => node.getClientRects().length).length), expectedHistory);
        assert.ok(long.stability.history.every(row => row.asof < long.asof));
        await card.locator('.lh-history-date').first().locator(':scope > summary').click();
        assert.match(await card.locator('.lh-history-date').first().innerText(), /12 \/ 12/);
        if (symbol === 'KR_KOSDAQ') {
          assert.equal(long.source.provider, 'naver');
          assert.equal(long.source.data_quality.status, 'unresolved_cross_source_discrepancy');
          assert.match(await card.innerText(), /来源核验待完成.*2001-11-01/);
          const evidence = card.locator('details').filter({ has: page.locator('summary', { hasText: '数据与证据说明' }) });
          await evidence.locator(':scope > summary').click();
          assert.match(await evidence.innerText(), /Naver 收盘 625\.5000/);
          assert.match(await evidence.innerText(), /Yahoo 收盘 636\.4000/);
          assert.match(await evidence.innerText(), /未将另一来源值拼接/);
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
        await card.evaluate(node => node.scrollIntoView({ block: 'start' }));
        const geometry = await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => {
          const heading = document.querySelector('#long-horizon-card > summary').getBoundingClientRect();
          const nav = document.querySelector('.odn')?.getBoundingClientRect();
          const stripNode = document.querySelector('#identity-strip');
          const strip = stripNode && !stripNode.hidden ? stripNode.getBoundingClientRect() : null;
          const obstructionBottom = Math.max(nav?.bottom || 0, strip && strip.top < innerHeight / 2 ? strip.bottom : 0);
          resolve({ headingTop: heading.top, obstructionBottom, clearance: heading.top - obstructionBottom });
        }))));
        layoutChecks.push({ width, symbol, ...geometry });
        assert.ok(geometry.clearance >= 4, 'Long-study heading must clear fixed navigation and asset identity');
        await shot(page, symbol + '-long-study-' + width);
        pass(width, symbol, '1.5/2.5分别核对、51历史加当前共52、profile按实际网格展示且不改变主图');
        await checkHistoryReplay(page, width, symbol, expected);
      }
      await context.close();
      activePage = null;
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, []);
  } catch (error) {
    failure = { name: error.name, message: error.message, stack: error.stack };
    if (activePage && !activePage.isClosed()) {
      try { await shot(activePage, 'failure'); } catch (_) { /* preserve original failure */ }
    }
  } finally {
    await browser.close();
    const result = { status: failure ? 'FAILED' : 'VERIFIED', inspected_at: new Date().toISOString(), widths,
      summary_report_version: summary.report_version, summary_generated_at: summary.generated_at,
      checks, errors, writes, networkFailures, archives, layoutChecks, screenshots, failure };
    fs.writeFileSync(path.join(output, 'acceptance.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  }
  if (failure) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
