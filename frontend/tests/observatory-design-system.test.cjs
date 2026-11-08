'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

test('phase 1 pages share the observatory visual system without touching data scripts', () => {
  const home = read('home.html');
  const stock = read('stock.html');
  const market = read('market.html');
  const css = read('app/observatory-phase1.css');

  for (const page of [home, stock, market]) assert.match(page, /app\/observatory-phase1\.css/);
  assert.match(home, /<body id="page-top" class="observatory-home">/);
  assert.match(stock, /<body class="observatory-page" data-page="stock">/);
  assert.match(market, /<body class="observatory-page" data-page="market">/);
  assert.match(home, /启<\/b>于青萍之末/);
  assert.match(home, /满<\/b>于狂澜之巅/);
  assert.match(stock, /app\/lppl-data\.js/);
  assert.match(css, /--obs-motion-control:\s*160ms/);
  assert.match(css, /--obs-motion-content:\s*360ms/);
  assert.match(css, /--obs-motion-chapter:\s*900ms/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
});

test('phase 1 responsive contract keeps the first action and data controls usable at 390px', () => {
  const css = read('app/observatory-phase1.css');
  assert.match(css, /@media \(max-width: 390px\)/);
  assert.match(css, /body\.observatory-home \.hero \.btn\.sun-sweep\s*\{[^}]*width:\s*100%/s);
  assert.match(css, /body\.observatory-page \.chip,[\s\S]*?min-height:\s*44px/);
  assert.match(css, /body\.observatory-home \.hero h1\s*\{[^}]*text-wrap:\s*balance/s);
});
