/* 临界点 · 标的页装配（Open Design 维护）：无 code 时挂标的目录，有 code 时挂吸顶头部；数据只经 window.LPPL。 */
(() => {
  const $ = (id) => document.getElementById(id);
  window.StockHeaderView = StockHeader.mount({ document });
  const results = $('results'), cat = $('catalog');
  const hasCode = !!new URLSearchParams(location.search).get('code');
  let mounted = false;
  const watch = {
    has: (row) => row.type === 'index'
      ? !!(window.IndexWatchlist && IndexWatchlist.has(row.watchKey))
      : StockWatchlist.read(localStorage).includes(row.watchKey),
    toggle: (row) => {
      if (row.type === 'index') { if (window.IndexWatchlist) IndexWatchlist.toggle(row.watchKey); return; }
      const list = StockWatchlist.read(localStorage);
      if (!list.includes(row.watchKey) && list.length >= StockWatchlist.MAX) {
        const st = $('query-status'); if (st) st.textContent = `自选最多 ${StockWatchlist.MAX} 只，请先移除一些。`;
        return;
      }
      const next = list.includes(row.watchKey) ? list.filter((c) => c !== row.watchKey) : [row.watchKey, ...list];
      StockWatchlist.write(localStorage, next);
      try { window.dispatchEvent(new CustomEvent('lppl-watch')); } catch (e) { /* 无事件环境 */ }
    },
  };
  async function mountCatalog() {
    if (mounted) return; mounted = true;
    cat.innerHTML = '<p class="muted">目录加载中…</p>';
    const [catalog, index] = await Promise.all([LPPL.catalog().catch(() => null), LPPL.stock.index().catch(() => ({}))]);
    if (!catalog) { cat.innerHTML = '<p class="muted">标的目录未发布。</p>'; return; }
    StockCatalog.mount({ el: cat, catalog, published: index && typeof index === 'object' ? Object.keys(index) : [], watch,
      onOpen: (row) => { $('code').value = row.code; $('search').requestSubmit(); } });
  }
  const sync = () => {
    const showing = !results.hidden;
    cat.hidden = showing;
    if (!showing) mountCatalog();
  };
  new MutationObserver(sync).observe(results, { attributes: true, attributeFilter: ['hidden'] });
  if (!hasCode) sync();
  const tab = (location.hash.match(/^#tab=(\w+)/) || [])[1];
  if (tab) {
    const t = StockHeader.TABS.find((x) => x[0] === tab);
    if (t) new MutationObserver((_, ob) => { if (!results.hidden) { ob.disconnect(); setTimeout(() => $('sh-tabs').querySelector('a[data-tab="' + tab + '"]')?.click(), 300); } }).observe(results, { attributes: true });
  }
})();
