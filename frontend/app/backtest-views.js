/* 临界点 · 回测页双页签装配（Open Design 维护）：情景区间（原页面全部不动）/ 策略回测（StrategyPanel）。数据只经 window.LPPL。 */
(function () {
  'use strict';
  var views = document.querySelector('.bt-views'), sv = document.getElementById('strategy-view'), app = document.querySelector('main.app');
  if (!views || !sv || !app) return;
  var panel = window.StrategyPanel ? StrategyPanel.mount({ el: document.getElementById('strategy-panel') }) : null;
  var loadedFor = '';
  function currentSym() {
    var q = new URLSearchParams(location.search).get('code') || new URLSearchParams(location.search).get('sym');
    var S = window.LPPL && q ? LPPL.resolve(q) : null;
    if (S) return S;
    var name = (document.getElementById('sym-n') || {}).textContent || '';
    var hit = (window.LPPL && LPPL.SYMS || []).filter(function (x) { return x.name === name.trim(); })[0];
    return hit || (window.LPPL && LPPL.SYMS && LPPL.SYMS[0]) || null;
  }
  function loadStrategy() {
    var S = currentSym();
    if (!S || !panel) return;
    document.getElementById('sv-title').textContent = S.name + ' · 策略回放';
    document.getElementById('sv-sub').textContent = S.sym + ' · 事前登记规则的历史回放 · 不是预测';
    if (loadedFor === S.sym) return;
    loadedFor = S.sym;
    panel.set(null);
    LPPL.strategy(S.sym).then(function (J) { if (loadedFor === S.sym) panel.set(J); });
  }
  function show(view, push) {
    var strat = view === 'strategy';
    sv.hidden = !strat; app.hidden = strat;
    views.querySelectorAll('a[data-view]').forEach(function (a) { if (a.dataset.view === view) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current'); });
    if (strat) loadStrategy();
    if (push && history.replaceState) { var u = new URL(location.href); u.hash = 'view=' + view; history.replaceState(null, '', u); }
    setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 0);
  }
  views.addEventListener('click', function (e) { var a = e.target.closest('a[data-view]'); if (!a) return; e.preventDefault(); show(a.dataset.view, true); });
  var symN = document.getElementById('sym-n');
  if (symN && window.MutationObserver) new MutationObserver(function () { if (!sv.hidden) { loadedFor = ''; loadStrategy(); } }).observe(symN, { childList: true, characterData: true, subtree: true });
  var v = (location.hash.match(/view=(\w+)/) || [])[1];
  show(v === 'strategy' ? 'strategy' : 'scenario', false);
})();
