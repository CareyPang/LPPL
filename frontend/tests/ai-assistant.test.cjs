'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const assistant = fs.readFileSync(path.join(root, 'app/ai-assistant.js'), 'utf8');
const nav = fs.readFileSync(path.join(root, 'app/od-nav.js'), 'utf8');
const page = (name) => fs.readFileSync(path.join(root, name), 'utf8');

test('cluster pages expose inline assistant prompts, but home and tools do not', () => {
  const prompt = /class="ai-ask-inline"[^>]*data-ai-ask="现在的顶部聚类区间是什么意思？"/;
  for (const name of ['stock.html', 'index.html', 'backtest.html']) {
    assert.match(page(name), prompt, `${name} should have the cluster prompt`);
  }
  assert.equal([...page('backtest.html').matchAll(/data-ai-ask=/g)].length, 1);
  for (const name of ['home.html', 'tools.html']) {
    assert.doesNotMatch(page(name), /data-ai-ask=/, `${name} should not have an assistant prompt`);
  }
});

test('assistant exports an idempotent public opener and delegates prompt clicks', () => {
  assert.match(assistant, /root\.LPPLAssistant\s*=\s*\{\s*open:\s*function \(question\) \{\s*toggle\(true\);/);
  assert.match(assistant, /if \(typeof question === 'string' && question\.trim\(\)\) ask\(question\);/);
  assert.match(assistant, /document\.addEventListener\('click'/);
  assert.match(assistant, /root\.LPPLAssistant\.open\(trigger\.dataset\.aiAsk\)/);
});

test('assistant button stays accessible when its label is hidden on narrow screens', () => {
  assert.match(assistant, /btn\.setAttribute\('aria-label', '研究助手'\)/);
  assert.match(assistant, /<span>研究助手<\/span>/);
  assert.match(assistant, /@media \(max-width:520px\)\{\.ai-btn\{box-sizing:border-box;width:34px;height:34px;padding:0;gap:0\}\.ai-btn span\{display:none\}\}/);
});

test('desktop top-bar search has the wide white input and blue focus ring', () => {
  assert.match(nav, /@media \(min-width:1200px\)\{\.odn-q\{width:300px\}/);
  assert.match(nav, /background-color:#fff;border-color:#9aa3b2/);
  assert.match(nav, /rgba\(49,92,245,\.18\)/);
  assert.ok(nav.indexOf(".odn-light .odn-q input{background-color:#f0f3fa") < nav.indexOf('@media (min-width:1200px)'));
});

test('compact navigation keeps help links in the hamburger menu', () => {
  assert.match(nav, /@media \(max-width:520px\)\{\.odn-main\{display:none\}\.odn-menu\{display:block\}\.odn-help\{display:none\}\.odn-r\{gap:3px;padding-left:0\}/);
  assert.match(nav, /\.odn-q input\{box-sizing:border-box;width:clamp\(138px,calc\(100vw - 222px\),168px\);padding-right:12px\}/);
  assert.match(nav, /var menu = el\('details', 'odn-menu'\);[\s\S]*?odn-menu-sep[\s\S]*?HELP\.map/);
});
