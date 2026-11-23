/* 临界点 · 回测页视图装配（Open Design 维护）。数据只经 window.LPPL。 */
(function () {
  'use strict';
  var views = document.querySelector('.bt-views'), sv = document.getElementById('strategy-view'),
    benchView = document.getElementById('bench-view'), benchPanel = document.getElementById('bench-panel'),
    app = document.querySelector('main.app');
  if (!views || !sv || !benchView || !benchPanel || !app) return;
  if (document.getElementById('ld')?.dataset.assetUnavailable === 'true') return;
  var panel = window.StrategyPanel ? StrategyPanel.mount({ el: document.getElementById('strategy-panel') }) : null;
  var loadedFor = '', benchLoadedFor = '', benchRequest = 0;
  function currentSym() {
    /* 先看页面当前选中的标的，地址参数只作初始值 */
    var name = (document.getElementById('sym-n') || {}).textContent || '';
    var hit = (window.LPPL && LPPL.SYMS || []).filter(function (x) { return x.name === name.trim(); })[0];
    if (hit) return !hit.market || hit.market === 'cn' ? hit : null;
    var params = new URLSearchParams(location.search);
    var q = params.get('sym') || params.get('code');
    var query = String(q || '').trim().toUpperCase();
    var S = window.LPPL && q ? LPPL.resolve(q) || (LPPL.GLOBAL_SYMS || []).find(function (asset) {
      return [asset.sym, asset.code, asset.name].concat(asset.alias || []).some(function (value) { return String(value).toUpperCase() === query; });
    }) : null;
    if (S && S.market && S.market !== 'cn') return null;
    if (q && !S) return null;
    return S || (window.LPPL && LPPL.SYMS && LPPL.SYMS[0]) || null;
  }
  function loadStrategy() {
    var S = currentSym();
    if (!S || !panel) return;
    document.getElementById('sv-title').textContent = S.name + ' · 策略回放';
    document.getElementById('sv-sub').textContent = S.sym + ' · 事前登记规则的历史回放';
    if (loadedFor === S.sym) return;
    loadedFor = S.sym;
    panel.set(null);
    LPPL.strategy(S.sym).then(function (J) { if (loadedFor === S.sym) panel.set(J); }).catch(function () {
      if (loadedFor !== S.sym) return;
      loadedFor = '';
      document.getElementById('strategy-panel').innerHTML = '<p class="sp-gate">策略数据读取失败（网络或服务器错误），不是“未发布”。请稍后重试。</p>';
    });
  }
  function loadBench() {
    var S = currentSym();
    if (!S || !window.LPPL || !window.BacktestBenchView || benchLoadedFor === S.sym) return;
    benchLoadedFor = S.sym;
    var request = ++benchRequest;
    benchPanel.innerHTML = '<p class="sp-empty">三段验证加载中…</p>';
    LPPL.load(S.sym).then(function (data) {
      if (request !== benchRequest || benchLoadedFor !== S.sym) return;
      var result = data.raw || {};
      benchPanel.innerHTML = BacktestBenchView.render(result.validation, result.evidence_levels);
    }).catch(function () {
      if (request !== benchRequest || benchLoadedFor !== S.sym) return;
      benchLoadedFor = '';
      benchPanel.innerHTML = '<p class="sp-gate">三段验证数据读取失败，请稍后重试。</p>';
    });
  }
  function show(view, push) {
    var selected = view === 'strategy' || view === 'bench' ? view : 'scenario';
    var strat = selected === 'strategy', bench = selected === 'bench';
    sv.hidden = !strat; benchView.hidden = !bench; app.hidden = strat || bench;
    views.querySelectorAll('a[data-view]').forEach(function (a) { if (a.dataset.view === selected) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current'); });
    if (strat) loadStrategy();
    if (bench) loadBench();
    if (push && history.replaceState) {
      var u = new URL(location.href); u.hash = 'view=' + selected; history.replaceState(null, '', u);
      window.dispatchEvent(new Event('hashchange'));
    }
    setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 0);
  }
  function showLocationView() {
    var v = (location.hash.match(/view=(\w+)/) || [])[1];
    show(v === 'strategy' || v === 'bench' ? v : 'scenario', false);
  }
  views.addEventListener('click', function (e) { var a = e.target.closest('a[data-view]'); if (!a) return; e.preventDefault(); show(a.dataset.view, true); });
  var sidebar = document.querySelector('.odn-sidebar');
  if (sidebar) sidebar.addEventListener('click', function (e) {
    var a = e.target.closest('.odn-side-link');
    if (!a) return;
    var target = new URL(a.href);
    if (target.pathname !== location.pathname) return;
    var view = (target.hash.match(/view=(\w+)/) || [])[1];
    if (view !== 'scenario' && view !== 'strategy' && view !== 'bench') return;
    e.preventDefault();
    show(view, true);
  });
  window.addEventListener('hashchange', showLocationView);
  var symN = document.getElementById('sym-n');
  if (symN && window.MutationObserver) new MutationObserver(function () {
    if (!sv.hidden) { loadedFor = ''; loadStrategy(); }
    if (!benchView.hidden) { benchLoadedFor = ''; loadBench(); }
  }).observe(symN, { childList: true, characterData: true, subtree: true });
  showLocationView();
})();
