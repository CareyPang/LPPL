/* A fixed same-origin return destination; never trust a return URL from the query. */
(function () {
  'use strict';
  if (new URLSearchParams(location.search).get('from') !== 'research-workspace') return;
  var nav = document.createElement('nav');
  nav.setAttribute('aria-label', '返回研究清单');
  nav.style.cssText = 'margin:12px 16px;padding:10px 14px;border:1px solid #dbe3ef;border-radius:10px;background:#f5f7ff;display:flex;align-items:center;flex-wrap:wrap;gap:12px;font:14px/1.5 system-ui;color:#263b66';
  var link = document.createElement('a');
  link.href = 'research-workspace.html';
  link.textContent = '← 返回我的研究';
  link.style.cssText = 'display:inline-flex;align-items:center;min-height:44px;color:#3155d9;font-weight:600';
  var text = document.createElement('span');
  text.textContent = '清单筛选、分组和研究笔记保留在此浏览器。';
  nav.append(link, text);
  var main = document.querySelector('main');
  if (main) main.prepend(nav); else document.body.prepend(nav);
})();
