'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const assistant = fs.readFileSync(path.join(root, 'app/ai-assistant.js'), 'utf8');
const drawing = fs.readFileSync(path.join(root, 'app/chart-drawing.js'), 'utf8');
const nav = fs.readFileSync(path.join(root, 'app/od-nav.js'), 'utf8');
const page = (name) => fs.readFileSync(path.join(root, name), 'utf8');

test('home and tools load the assistant with page context and designated presets', () => {
  const prompt = /class="ai-ask-inline"[^>]*data-ai-ask="现在的顶部聚类区间是什么意思？"/;
  for (const name of ['stock.html', 'index.html', 'backtest.html']) {
    assert.match(page(name), prompt, `${name} should have the cluster prompt`);
  }
  assert.equal([...page('backtest.html').matchAll(/data-ai-ask=/g)].length, 1);
  const home = page('home.html');
  assert.match(home, /app\/ai-assistant\.js" data-page="home"/);
  assert.match(home, /id="index-overview"[^>]*data-ai-context="指数风险概览"/);
  assert.match(home, /id="today" data-ai-context="今日摘要"/);
  assert.doesNotMatch(home, /data-ai-ask=/);
  const tools = page('tools.html');
  assert.match(tools, /app\/ai-assistant\.js" data-page="tools"/);
  assert.doesNotMatch(tools, /data-ai-ask=/);
  assert.match(assistant, /home: \['7 个指数现在的风险状态怎么看？', '今日摘要里的几项分别表示什么？', '占比为什么不是概率？', '顶部聚类区间是什么意思？'\]/);
  assert.match(assistant, /tools: \['这些工具的计算方式是什么？', '房贷等额本息和等额本金有什么区别？'\]/);
});

test('each tools card contributes named context without changing context limits', () => {
  const tools = page('tools.html');
  const contexts = [...tools.matchAll(/<article class="card" data-ai-context="([^"]+)"/g)]
    .map((match) => match[1]);
  assert.deepEqual(contexts, [
    '汇率换算',
    '时差与交易时钟',
    '单位换算',
    '金银价格换算',
    '金价汇率情景',
    '房贷计算器',
  ]);
  assert.match(assistant, /var MAX_CONTEXT = 8000/);
  assert.match(assistant, /if \(!shown\(el\)\) return;/);
});

test('assistant context excludes the private chart drawing toolbar', () => {
  assert.match(assistant, /querySelectorAll\('\[data-ai-exclude\]'\)/);
  assert.match(assistant, /clean\(excluded\.innerText\)/);
  assert.match(drawing, /toolbar\.dataset\.aiExclude = 'true'/);
});

test('assistant exports an idempotent public opener and delegates prompt clicks', () => {
  assert.match(assistant, /root\.LPPLAssistant\s*=\s*\{\s*open:\s*function \(question\) \{\s*toggle\(true, true\);/);
  assert.match(assistant, /if \(typeof question === 'string' && question\.trim\(\)\) ask\(question\);/);
  assert.match(assistant, /close:\s*function \(\) \{ toggle\(false, true\); \}/);
  assert.match(assistant, /isOpen:\s*function \(\) \{ return !panel\.hidden; \}/);
  assert.match(assistant, /document\.addEventListener\('click'/);
  assert.match(assistant, /root\.LPPLAssistant\.open\(trigger\.dataset\.aiAsk\)/);
});

test('wide assistant switch uses safe page-specific defaults and persistence', () => {
  const chart = page('chart.html');
  assert.match(assistant, /var HOME_STORAGE_KEY = 'lppl\.assistant\.home'/);
  assert.match(assistant, /var defaultOpen = !!\(me && me\.dataset\.default === 'open'\)/);
  assert.match(assistant, /return 'lppl\.assistant\.wide:' \+ filename/);
  assert.match(assistant, /if \(value === '1'\) return true;[\s\S]*?if \(value === '0'\) return false;[\s\S]*?return defaultOpen;/);
  assert.match(assistant, /root\.localStorage\.setItem\(preferenceKey\(\), open \? '1' : '0'\)/);
  assert.match(assistant, /switchButton\.setAttribute\('role', 'switch'\)/);
  assert.match(assistant, /switchButton\.setAttribute\('aria-checked', 'false'\)/);
  assert.match(assistant, /switchButton\.setAttribute\('aria-checked', String\(open\)\)/);
  assert.match(assistant, /if \(persist\) writePreference\(open\)/);
  assert.match(assistant, /\.ai-switch\[aria-checked="true"\] i\{background:#315cf5\}/);
  assert.doesNotMatch(assistant, /ai-home-switch/);
  assert.match(assistant, /document\.body\.classList\.toggle\('ai-closed', !open && wide\(\)\)/);
  assert.match(assistant, /if \(event\.matches\) toggle\(readPreference\(\), false\)/);
  assert.doesNotMatch(assistant, /\.ai-panel \.ai-x\{display:none\}/);
  assert.match(chart, /app\/ai-assistant\.js" data-page="stock" data-default="closed"/);
  assert.match(assistant, /if \(wide\(\)\) toggle\(readPreference\(\), false\)/);
  assert.match(nav, /body\.odn-sidebar-page\.vs-home:not\(\.ai-open\)\{padding-left:208px\}/);
  assert.match(nav, /@media \(min-width:1200px\)\{body\.odn-sidebar-page\.ai-closed\{padding-left:208px\}\}/);
});

test('assistant docks at the sidebar edge on wide screens and fills mobile screens', () => {
  assert.match(assistant, /btn\.setAttribute\('aria-label', '研究助手'\)/);
  assert.match(assistant, /<span>研究助手<\/span>/);
  assert.match(assistant, /WIDE = 1200/);
  assert.match(assistant, /left:208px;right:auto;bottom:0;width:340px/);
  assert.match(assistant, /\.ai-panel\{[^']*padding:0\}/);
  assert.match(assistant, /@media \(max-width:760px\)\{\.ai-btn\{display:none!important\}\.ai-panel:not\(\[hidden\]\)\{position:fixed;top:52px;right:0;bottom:0;left:0;width:100vw/);
  assert.match(assistant, /document\.dispatchEvent\(new CustomEvent\('lppl:assistant-state', \{ detail: \{ open: open \} \}\)\)/);
});

test('desktop top-bar search has the wide white input and blue focus ring', () => {
  assert.match(nav, /@media \(min-width:1200px\)\{body\.odn-sidebar-page\{padding-left:572px\}[\s\S]*?\.odn-q\{width:300px\}/);
  assert.match(nav, /background-color:#fff;border-color:#9aa3b2/);
  assert.match(nav, /rgba\(49,92,245,\.18\)/);
  assert.ok(nav.indexOf(".odn-light .odn-q input{background-color:#f0f3fa") < nav.lastIndexOf('@media (min-width:1200px)'));
});

test('compact navigation keeps help links in the hamburger menu', () => {
  assert.match(nav, /@media \(min-width:1200px\)\{body\.odn-sidebar-page\{padding-left:572px\}/);
  assert.match(nav, /@media \(min-width:761px\) and \(max-width:1199px\)\{body\.odn-sidebar-page\{padding-left:208px\}/);
  assert.match(nav, /@media \(max-width:760px\)\{body\.odn-sidebar-page\{padding-left:0\}/);
  assert.match(nav, /grid-template-columns:repeat\(5,minmax\(0,1fr\)\)/);
  assert.match(nav, /var menu = el\('details', 'odn-menu'\);[\s\S]*?HELP\.map/);
  assert.match(nav, /data-mode="assistant" aria-pressed="false">研究助手/);
});
