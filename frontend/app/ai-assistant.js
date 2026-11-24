/* 研究助手（DeepSeek）：只把页面上已经显示的内容发给 Worker /ai；不读取、不计算业务数据。
   用法：<script src="app/ai-assistant.js" data-page="home|stock|index|backtest|market|tools"></script>
   [data-ai-context="标题"] 标记要带上的页面区块（隐藏的不带）；[data-ai-anchor] 是窄屏时对话框插入的位置（其后）。 */
(function (root) {
  'use strict';
  var PRESETS = {
    home: ['7 个指数现在的风险状态怎么看？', '今日摘要里的几项分别表示什么？', '占比为什么不是概率？', '顶部聚类区间是什么意思？'],
    stock: ['现在的顶部聚类区间是什么意思？', '主簇和次级簇有什么区别？', '占比为什么不是概率？',
      '各尺度的证据等级说明了什么？', '近期事件里哪些值得留意？', '抄底部分的历史回撤分布怎么看？'],
    index: ['现在的顶部聚类区间是什么意思？', '主簇和次级簇有什么区别？', '占比为什么不是概率？',
      '各尺度的证据等级说明了什么？', '拟合明细里的窗口数和合格拟合数是什么？', '历史背景这一块怎么看？'],
    backtest: ['这张回测图怎么读？', '提醒明细每一行是什么意思？', '“顶相对主簇”的早于、落在、晚于说明什么？',
      '为什么事后确认的顶不算命中率？', '开发段、校准段、测试段有什么区别？'],
    market: ['今日摘要里的几项分别表示什么？', '自选相关快讯如何筛选？', '模型区间变化该如何理解？'],
    tools: ['这些工具的计算方式是什么？', '房贷等额本息和等额本金有什么区别？'],
  };
  var MAX_CONTEXT = 8000, MAX_KEEP = 12, MAX_SEND = 6, WIDE = 1200;
  var HOME_STORAGE_KEY = 'lppl.assistant.home';
  var me = document.currentScript;
  var page = (me && me.dataset.page) || 'stock';
  var defaultOpen = !!(me && me.dataset.default === 'open');

  function storeKey() {
    var q = new URLSearchParams(location.search);
    return 'lppl.ai.v1.' + page + ':' + (q.get('code') || q.get('sym') || q.get('s') || '');
  }
  function preferenceKey() {
    if (page === 'home') return HOME_STORAGE_KEY;
    var filename = root.location.pathname.split('/').pop() || 'index.html';
    return 'lppl.assistant.wide:' + filename;
  }
  function readPreference() {
    try {
      var value = root.localStorage.getItem(preferenceKey());
      if (value === '1') return true;
      if (value === '0') return false;
    } catch (e) { /* optional */ }
    return defaultOpen;
  }
  function writePreference(open) {
    try { root.localStorage.setItem(preferenceKey(), open ? '1' : '0'); } catch (e) { /* optional */ }
  }
  function loadHistory(key) {
    try { var v = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }
  function shown(el) {
    if (!el.isConnected || el.closest('[hidden]')) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  }
  function clean(text) { return String(text || '').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim(); }
  function collectContext() {
    var parts = ['页面：' + document.title];
    var asof = document.querySelector('.odn-asof');
    if (asof && clean(asof.innerText)) parts.push('页面日期：' + clean(asof.innerText));
    document.querySelectorAll('[data-ai-context]').forEach(function (el) {
      if (!shown(el)) return;
      var t = clean(el.innerText);
      el.querySelectorAll('[data-ai-exclude]').forEach(function (excluded) {
        var privateText = clean(excluded.innerText);
        if (privateText) t = t.replace(privateText, '').trim();
      });
      if (t) parts.push('【' + el.getAttribute('data-ai-context') + '】\n' + t);
    });
    var out = parts.join('\n\n');
    var marker = '\n（页面内容较长，已截断）';
    return out.length > MAX_CONTEXT ? out.slice(0, MAX_CONTEXT - marker.length) + marker : out;
  }

  var css = document.createElement('style');
  css.textContent =
    '.ai-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;flex:none;height:32px;padding:0 12px;border-radius:8px;border:1px solid transparent;background:#315CF5;color:#fff;font:600 13px sans-serif;cursor:pointer;white-space:nowrap}' +
    '.ai-btn:hover,.odn:not(.odn-light) .ai-btn:hover{background:#2447c9}' +
    '.ai-btn[aria-expanded="true"],.odn:not(.odn-light) .ai-btn[aria-expanded="true"]{background:#1d3aa8}' +
    '.ai-btn svg{width:14px;height:14px;flex:none}' +
    '.ai-switch{display:none;align-items:center;gap:7px;height:34px;padding:0 8px;border:1px solid #d6dae3;border-radius:999px;background:#fff;color:#4c525e;font:600 12px/1 sans-serif;cursor:pointer;white-space:nowrap}' +
    '.ai-switch:focus-visible{outline:3px solid rgba(49,92,245,.18);outline-offset:2px}' +
    '.ai-switch i{position:relative;display:block;width:30px;height:18px;border-radius:999px;background:#aeb6c4;transition:background .15s;flex:none}' +
    '.ai-switch i::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(19,23,34,.25);transition:transform .15s}' +
    '.ai-switch[aria-checked="true"]{border-color:#b9caff;background:#f5f8ff;color:#1f5fd6}' +
    '.ai-switch[aria-checked="true"] i{background:#315cf5}' +
    '.ai-switch[aria-checked="true"] i::after{transform:translateX(12px)}' +
    '.ai-ask-inline{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;height:28px;margin-left:8px;padding:0 9px;border:1px solid #315CF5;border-radius:6px;background:#fff;color:#315CF5;font:600 12px/1 sans-serif;white-space:nowrap;cursor:pointer}' +
    '.ai-ask-inline:hover{background:#f2f5ff}' +
    '.ai-panel{box-sizing:border-box;background:#fff;color:#131722;border:1px solid #e3e7ee;display:flex;flex-direction:column;font:14px/1.6 sans-serif;padding:0}' +
    '.ai-panel[hidden]{display:none}' +
    '.ai-btn,.ai-panel,.ai-panel *{font-family:inherit!important}' +
    '.ai-head{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid #e3e7ee}' +
    '.ai-head b{font-size:15px}.ai-head span{color:#6a6d78;font-size:12px}' +
    '.ai-x,.ai-clear{margin-left:auto;border:0;background:none;color:#4c525e;cursor:pointer;font:13px sans-serif;padding:4px 6px;border-radius:6px}' +
    '.ai-clear{margin-left:auto}.ai-clear+.ai-x{margin-left:0}.ai-x:hover,.ai-clear:hover{background:#f0f3fa}' +
    '.ai-log{flex:1;overflow-y:auto;padding:12px 14px;display:flex;flex-direction:column;gap:10px;min-height:0}' +
    '.ai-msg{white-space:pre-wrap;word-break:break-word;padding:8px 10px;border-radius:8px;max-width:100%}' +
    '.ai-u{align-self:flex-end;background:#e9edf5}.ai-a{background:#f6f8fb;border:1px solid #e3e7ee}' +
    '.ai-err{color:#b42318;background:#fef3f2;border:1px solid #fecdca}' +
    '.ai-presets{display:flex;flex-wrap:wrap;gap:6px;padding:0 14px 10px}' +
    '.ai-presets p{width:100%;margin:0 0 2px;color:#6a6d78;font-size:12px}' +
    '.ai-presets button{border:1px solid #d6dae3;background:#fff;border-radius:999px;padding:4px 10px;font:13px sans-serif;color:#131722;cursor:pointer;text-align:left}' +
    '.ai-presets button:hover{background:#f0f3fa}.ai-presets button:disabled{opacity:.5;cursor:default}' +
    '.ai-form{display:flex;gap:8px;padding:10px 14px 12px;border-top:1px solid #e3e7ee}' +
    '.ai-form textarea{flex:1;resize:none;height:44px;border:1px solid #d6dae3;border-radius:8px;padding:6px 8px;font:14px/1.5 sans-serif}' +
    '.ai-form button{flex:none;border:0;border-radius:8px;background:#2962ff;color:#fff;padding:0 14px;font:600 14px sans-serif;cursor:pointer}' +
    '.ai-form button:disabled{background:#9db3f5;cursor:default}' +
    '.ai-note{margin:0;padding:0 14px 10px;color:#6a6d78;font-size:12px}' +
    '.ai-panel.ai-theme-dark{background:#0f0f0f;color:#dbdbdb;border-color:#2a2a2a}' +
    '.ai-theme-dark .ai-head,.ai-theme-dark .ai-form{border-color:#2a2a2a}' +
    '.ai-theme-dark .ai-head span,.ai-theme-dark .ai-note{color:#8c8c8c}' +
    '.ai-theme-dark .ai-u{background:#2a2a2a;color:#dbdbdb}.ai-theme-dark .ai-a{background:#1a1a1a;border-color:#333;color:#dbdbdb}' +
    '.ai-theme-dark .ai-x,.ai-theme-dark .ai-clear{color:#b2b5be}.ai-theme-dark .ai-x:hover,.ai-theme-dark .ai-clear:hover{background:#2a2a2a}' +
    '.ai-theme-dark .ai-presets button,.ai-theme-dark .ai-form textarea{background:#1a1a1a;border-color:#444;color:#dbdbdb}' +
    '.ai-theme-dark .ai-presets button:hover{background:#2a2a2a}' +
    '@media (min-width:' + WIDE + 'px){.ai-switch{display:inline-flex}.ai-btn{display:none}' +
    '.ai-panel.ai-dock{position:fixed;top:0;left:208px;right:auto;bottom:0;width:340px;z-index:65;border-width:0 1px 0 0}}' +
    '@media (max-width:' + (WIDE - 1) + 'px){.ai-switch{display:none!important}.ai-panel{margin:12px 0;border-radius:10px;max-height:72vh}.ai-panel .ai-log{min-height:120px}.ai-btn{padding:0 8px}}' +
    '@media (max-width:760px){.ai-btn{display:none!important}.ai-panel:not([hidden]){position:fixed;top:52px;right:0;bottom:0;left:0;width:100vw;height:calc(100vh - 52px);height:calc(100dvh - 52px);max-height:none;margin:0;border:0;border-radius:0;z-index:120}.ai-panel .ai-log{min-height:0}}';
  document.head.appendChild(css);

  var panel = document.createElement('section');
  panel.className = 'ai-panel';
  var navHeader = document.querySelector('.odn');
  if (!navHeader || !navHeader.classList.contains('odn-light')) panel.classList.add('ai-theme-dark');
  panel.hidden = true;
  panel.setAttribute('aria-label', '研究助手');
  panel.innerHTML =
    '<div class="ai-head"><b>研究助手</b><span>DeepSeek · 只读本页数据</span>' +
    '<button type="button" class="ai-clear">清空</button><button type="button" class="ai-x" aria-label="关闭研究助手">关闭</button></div>' +
    '<div class="ai-log" aria-live="polite"></div>' +
    '<div class="ai-presets"><p>常用问题</p></div>' +
    '<form class="ai-form"><textarea maxlength="500" placeholder="问本页的模型结果，例如：主簇在哪个时间段？" aria-label="输入问题"></textarea><button type="submit">发送</button></form>' +
    '<p class="ai-note">只解释本页已显示的模型结果，不给买卖建议、目标价或止损价。对话只存在本浏览器。</p>';
  var log = panel.querySelector('.ai-log'), presets = panel.querySelector('.ai-presets');
  var form = panel.querySelector('.ai-form'), input = form.querySelector('textarea'), send = form.querySelector('button');
  var historyKey = storeKey(), history = loadHistory(historyKey), busy = false, controller = null;

  function syncHistory() {
    var key = storeKey();
    if (key === historyKey) return false;
    if (controller) controller.abort();
    historyKey = key;
    history = loadHistory(key);
    return true;
  }
  function saveHistory(expectedKey) {
    if (expectedKey && storeKey() !== expectedKey) {
      if (syncHistory()) render();
      return false;
    }
    syncHistory();
    try { localStorage.setItem(historyKey, JSON.stringify(history.slice(-MAX_KEEP))); } catch (e) { /* optional */ }
    return true;
  }

  function bubble(role, text, extra) {
    var d = document.createElement('div');
    d.className = 'ai-msg ' + (role === 'user' ? 'ai-u' : 'ai-a') + (extra ? ' ' + extra : '');
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }
  function tidy(text) { return String(text).replace(/\*\*/g, '').replace(/^#{1,6}\s*/gm, ''); }
  function render() {
    syncHistory();
    log.textContent = '';
    if (!history.length) bubble('assistant', '我可以解释本页显示的顶部聚类区间、占比、证据等级、事件等内容。点下面的常用问题，或者直接输入。');
    history.forEach(function (m) { bubble(m.role, m.role === 'assistant' ? tidy(m.content) : m.content); });
  }
  function setBusy(v) {
    busy = v; send.disabled = v;
    presets.querySelectorAll('button').forEach(function (b) { b.disabled = v; });
  }
  async function ask(question) {
    question = String(question || '').trim().slice(0, 500);
    if (syncHistory()) render();
    if (!question || busy) return;
    if (!root.LPPL || typeof root.LPPL.askAI !== 'function') { bubble('assistant', '研究助手未加载。', 'ai-err'); return; }
    if (!history.length) log.textContent = '';
    var requestKey = historyKey;
    var prior = history.slice(-MAX_SEND);
    var payload = { page: page, question: question, context: collectContext(), history: prior };
    var encoder = new TextEncoder();
    while (prior.length && encoder.encode(JSON.stringify(payload)).length > 60000) {
      prior.shift();
      payload.history = prior;
    }
    bubble('user', question);
    var out = bubble('assistant', '正在读取本页数据…');
    setBusy(true);
    controller = new AbortController();
    try {
      var r = await root.LPPL.askAI(payload,
        function (t) {
          if (storeKey() !== requestKey) {
            if (controller) controller.abort();
            if (syncHistory()) render();
            return;
          }
          out.textContent = tidy(t); log.scrollTop = log.scrollHeight;
        }, controller.signal);
      if (storeKey() !== requestKey) {
        if (syncHistory()) render();
        return;
      }
      if (r.blocked) {
        out.className = 'ai-msg ai-a ai-err';
        out.textContent = '这条回答涉及买卖建议或价格目标，已停止显示。本站只提供模型结果和证据说明，可以换个问法，例如问区间和证据等级的含义。';
        return;
      }
      if (!r.text) { out.className = 'ai-msg ai-a ai-err'; out.textContent = '没有收到回答，请稍后再试。'; return; }
      history.push({ role: 'user', content: question }, { role: 'assistant', content: r.text });
      history = history.slice(-MAX_KEEP);
      saveHistory(requestKey);
    } catch (e) {
      if (storeKey() !== requestKey) {
        if (syncHistory()) render();
        return;
      }
      out.className = 'ai-msg ai-a ai-err';
      out.textContent = (e && e.name === 'AbortError') ? '已停止。' : ((e && e.message) || '研究助手暂时不可用');
    } finally { setBusy(false); controller = null; }
  }
  (PRESETS[page] || PRESETS.stock).forEach(function (q) {
    var b = document.createElement('button'); b.type = 'button'; b.textContent = q;
    b.addEventListener('click', function () { ask(q); });
    presets.appendChild(b);
  });
  form.addEventListener('submit', function (e) { e.preventDefault(); var q = input.value; input.value = ''; ask(q); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  panel.querySelector('.ai-clear').addEventListener('click', function () {
    if (controller) controller.abort();
    syncHistory();
    history = []; saveHistory(historyKey); render();
  });

  var btn = document.createElement('button');
  btn.type = 'button'; btn.className = 'ai-btn';
  btn.innerHTML = '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H7l-3.5 2v-5.5A7.5 7.5 0 1 1 20 11.5Z"/><path d="M8 11h8M8 14h5"/></svg><span>研究助手</span>';
  btn.setAttribute('aria-label', '研究助手');
  btn.setAttribute('aria-expanded', 'false');
  function wide() { return root.matchMedia('(min-width:' + WIDE + 'px)').matches; }
  function mobile() { return root.matchMedia('(max-width:760px)').matches; }
  var switchButton = null;
  function syncSwitch(open) {
    if (switchButton) switchButton.setAttribute('aria-checked', String(open));
  }
  function placementVisible(el) {
    if (!el || !el.isConnected) return false;
    for (var node = el; node; node = node.parentElement) {
      if (node.hidden) return false;
      if (root.getComputedStyle) {
        var style = root.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
      }
    }
    var rect = el.getBoundingClientRect();
    return rect.width > 0 || rect.height > 0;
  }
  function place() {
    if (wide()) {
      panel.classList.add('ai-dock');
      if (panel.parentNode !== document.body) document.body.appendChild(panel);
    } else {
      panel.classList.remove('ai-dock');
      var anchor = document.querySelector('[data-ai-anchor]');
      if (placementVisible(anchor)) {
        if (panel.previousElementSibling !== anchor) anchor.insertAdjacentElement('afterend', panel);
        return;
      }
      var fallback = document.querySelector('[data-ai-fallback]');
      if (!placementVisible(fallback)) {
        var mains = document.querySelectorAll('main');
        fallback = null;
        for (var i = 0; i < mains.length; i += 1) {
          if (placementVisible(mains[i])) { fallback = mains[i]; break; }
        }
      }
      if (!placementVisible(fallback)) fallback = document.querySelector('.bt-views');
      if (placementVisible(fallback)) {
        if (fallback.tagName === 'MAIN') {
          if (panel.parentNode !== fallback || fallback.firstElementChild !== panel) fallback.insertBefore(panel, fallback.firstChild);
        } else if (panel.previousElementSibling !== fallback) {
          fallback.insertAdjacentElement('afterend', panel);
        }
      } else if (panel.parentNode !== document.body) document.body.appendChild(panel);
    }
  }
  function toggle(open, persist) {
    panel.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
    syncSwitch(open);
    if (persist) writePreference(open);
    document.body.classList.toggle('ai-open', open && wide());
    document.body.classList.toggle('ai-closed', !open && wide());
    document.body.classList.toggle('ai-mobile-open', open && mobile());
    document.dispatchEvent(new CustomEvent('lppl:assistant-state', { detail: { open: open } }));
    if (open) {
      place(); render();
      if (!wide() && !mobile()) panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    root.dispatchEvent(new Event('resize'));
  }
  btn.addEventListener('click', function () { toggle(panel.hidden, true); });
  root.LPPLAssistant = {
    open: function (question) {
      toggle(true, true);
      if (typeof question === 'string' && question.trim()) ask(question);
    },
    close: function () { toggle(false, true); },
    isOpen: function () { return !panel.hidden; },
  };
  document.addEventListener('lppl:assistant-open', function () { root.LPPLAssistant.open(); });
  document.addEventListener('lppl:assistant-close', function () { root.LPPLAssistant.close(); });
  document.addEventListener('click', function (e) {
    var target = e.target;
    var trigger = target && typeof target.closest === 'function' ? target.closest('[data-ai-ask]') : null;
    if (trigger) root.LPPLAssistant.open(trigger.dataset.aiAsk);
  });
  panel.querySelector('.ai-x').addEventListener('click', function () { toggle(false, true); });
  var lastWide = wide();
  root.matchMedia('(min-width:' + WIDE + 'px)').addEventListener('change', function (event) {
    if (event.matches) toggle(readPreference(), false);
    else if (lastWide) toggle(false, false);
    else if (!panel.hidden) { place(); root.dispatchEvent(new Event('resize')); }
    lastWide = event.matches;
  });
  root.matchMedia('(max-width:760px)').addEventListener('change', function (event) {
    document.body.classList.toggle('ai-mobile-open', !panel.hidden && event.matches);
    if (!panel.hidden) { place(); root.dispatchEvent(new Event('resize')); }
  });
  root.addEventListener('resize', function () { if (!panel.hidden) place(); });
  function mount() {
    var host = document.querySelector('.odn-r');
    if (host) {
      host.insertBefore(btn, host.firstChild);
      switchButton = document.createElement('button');
      switchButton.type = 'button';
      switchButton.className = 'ai-switch';
      switchButton.setAttribute('role', 'switch');
      switchButton.setAttribute('aria-checked', 'false');
      switchButton.innerHTML = '<span>研究助手</span><i aria-hidden="true"></i>';
      switchButton.addEventListener('click', function () { toggle(panel.hidden, true); });
      var help = host.querySelector('.odn-help');
      host.insertBefore(switchButton, help || null);
    }
    else { btn.style.cssText = 'position:fixed;top:12px;right:12px;z-index:61'; document.body.appendChild(btn); }
    var requested = new URLSearchParams(location.search).get('ai') === '1';
    if (wide()) toggle(readPreference(), false);
    else if (requested) toggle(true, false);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})(typeof window !== 'undefined' ? window : globalThis);
