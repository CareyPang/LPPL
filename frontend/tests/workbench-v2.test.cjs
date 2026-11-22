const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '..');

test('EvidenceBadge renders compact tone-coded badge with tooltip detail', () => {
  const code = fs.readFileSync(path.join(ROOT, 'app', 'evidence-badge.js'), 'utf8');
  const ctx = { window: {} };
  ctx.globalThis = ctx;
  vm.runInNewContext(code, ctx);
  const EB = ctx.window.CPEvidenceBadge;
  assert.ok(EB);
  const okHtml = EB.html('passed', { n: 24 });
  assert.match(okHtml, /data-tone="ok"/);
  assert.match(okHtml, /样本外通过/);
  assert.match(okHtml, /样本 n = 24/);

  const warnHtml = EB.html('fail_i_iii');
  assert.match(warnHtml, /data-tone="warn"/);
  assert.match(warnHtml, /未过样本外/);
});

test('CPSCN exposes FCO red bar and first-alert flag renderers', () => {
  const code = fs.readFileSync(path.join(ROOT, 'app', 'scen-style.js'), 'utf8');
  const ctx = { window: {} };
  vm.runInNewContext(code, ctx);
  const S = ctx.window.CPSCN;
  assert.equal(S.FCO, '#D6303A');
  assert.equal(typeof S.drawFcoBar, 'function');
  assert.equal(typeof S.drawFirstAlert, 'function');

  const ops = [];
  const fakeCtx = {
    save() { ops.push('save'); },
    restore() { ops.push('restore'); },
    beginPath() {},
    moveTo() {},
    lineTo() {},
    arc() { ops.push('arc'); },
    stroke() { ops.push('stroke'); },
    fill() { ops.push('fill'); },
    setLineDash() {},
    measureText() { return { width: 42 }; },
    fillRect(x, y, w, h) { ops.push(['rect', x, y, w, h]); },
    fillText(t) { ops.push(['text', t]); },
  };
  S.drawFcoBar(fakeCtx, { x: 100, w: 6, bottom: 300, maxH: 80, intensity: 0.8, hot: false });
  assert.ok(ops.some((o) => Array.isArray(o) && o[0] === 'rect' && o[4] >= 60));

  S.drawFirstAlert(fakeCtx, { x: 120, y: 150, top: 20, bottom: 300, label: '首警 15-05', active: true });
  assert.ok(ops.some((o) => Array.isArray(o) && o[0] === 'text' && o[1] === '首警 15-05'));
});
