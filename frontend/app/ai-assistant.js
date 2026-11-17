/* 研究助手（DeepSeek）：只把页面上已经显示的内容发给 Worker /ai；不读取、不计算业务数据。
   用法：<script src="app/ai-assistant.js" data-page="stock|index|backtest"></script>
   [data-ai-context="标题"] 标记要带上的页面区块（隐藏的不带）；[data-ai-anchor] 是窄屏时对话框插入的位置（其后）。 */
(function (root) {
  'use strict';
  var PRESETS = {
    stock: ['现在的顶部聚类区间是什么意思？', '主簇和次级簇有什么区别？', '占比为什么不是概率？',
      '各尺度的证据等级说明了什么？', '近期事件里哪些值得留意？', '抄底部分的历史回撤分布怎么看？'],
    index: ['现在的顶部聚类区间是什么意思？', '主簇和次级簇有什么区别？', '占比为什么不是概率？',
      '各尺度的证据等级说明了什么？', '拟合明细里的窗口数和合格拟合数是什么？', '历史背景这一块怎么看？'],
    backtest: ['这张回测图怎么读？', '提醒明细每一行是什么意思？', '“顶相对主簇”的早于、落在、晚于说明什么？',
      '为什么事后确认的顶不算命中率？', '开发段、校准段、测试段有什么区别？'],
  };
  var MAX_CONTEXT = 8000, MAX_KEEP = 12, MAX_SEND = 6, WIDE = 1100;
  var me = document.currentScript;
  var page = (me && me.dataset.page) || 'stock';

  function storeKey() {
    var q = new URLSearchParams(location.search);
    return 'lppl.ai.v1.' + page + ':' + (q.get('code') || q.get('sym') || q.get('s') || '');
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
      if (t) parts.push('【' + el.getAttribute('data-ai-context') + '】\n' + t);
    });
    var out = parts.join('\n\n');
    var marker = '\n（页面内容较长，已截断）';
    return out.length > MAX_CONTEXT ? out.slice(0, MAX_CONTEXT - marker.length) + marker : out;
  }

  var css = document.createElement('style');
  css.textContent =
    '.ai-btn{flex:none;height:32px;padding:0 12px;border-radius:8px;border:1px solid #d6dae3;background:#fff;color:#131722;font:600 13px sans-serif;cursor:pointer;white-space:nowrap}' +
    '.ai-btn[aria-expanded="true"]{background:#e9edf5}' +
    '.odn:not(.odn-light) .ai-btn{background:#1f1f1f;border-color:#333;color:#fff}' +
    '.ai-panel{box-sizing:border-box;background:#fff;color:#131722;border:1px solid #e3e7ee;display:flex;flex-direction:column;font:14px/1.6 sans-serif}' +
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
    '@media (min-width:' + WIDE + 'px){body.ai-open{padding-right:380px}' +
    '.ai-panel.ai-dock{position:fixed;top:0;right:0;bottom:0;width:380px;z-index:60;border-width:0 0 0 1px}}' +
    '@media (max-width:' + (WIDE - 1) + 'px){.ai-panel{margin:12px 0;border-radius:10px;max-height:72vh}.ai-panel .ai-log{min-height:120px}.ai-btn{padding:0 8px}}';
  document.head.appendChild(css);

  var panel = document.createElement('section');
  panel.className = 'ai-panel';
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
  btn.type = 'button'; btn.className = 'ai-btn'; btn.textContent = '研究助手';
  btn.setAttribute('aria-expanded', 'false');
  function wide() { return root.matchMedia('(min-width:' + WIDE + 'px)').matches; }
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
      }
    }
  }
  function toggle(open) {
    panel.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('ai-open', open && wide());
    if (open) {
      place(); render();
      if (!wide()) panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    root.dispatchEvent(new Event('resize'));
  }
  btn.addEventListener('click', function () { toggle(panel.hidden); });
  panel.querySelector('.ai-x').addEventListener('click', function () { toggle(false); });
  root.matchMedia('(min-width:' + WIDE + 'px)').addEventListener('change', function () {
    if (!panel.hidden) { place(); document.body.classList.toggle('ai-open', wide()); root.dispatchEvent(new Event('resize')); }
  });
  root.addEventListener('resize', function () { if (!panel.hidden) place(); });
  function mount() {
    var host = document.querySelector('.odn-r');
    if (host) host.insertBefore(btn, host.firstChild);
    else { btn.style.cssText = 'position:fixed;top:12px;right:12px;z-index:61'; document.body.appendChild(btn); }
    if (new URLSearchParams(location.search).get('ai') === '1') toggle(true);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})(typeof window !== 'undefined' ? window : globalThis);
