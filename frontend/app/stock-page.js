/* 临界点 · 标的页装配（Open Design 维护）：无 code 时挂标的目录，有 code 时挂吸顶头部；数据只经 window.LPPL。 */
(() => {
  const $ = (id) => document.getElementById(id);
  window.StockHeaderView = StockHeader.mount({ document });
  const results = $('results'), cat = $('catalog');
  const hasCode = !!new URLSearchParams(location.search).get('code');
  let mounted = false, catalogView = null;
  const watch = {
    has: (row) => {
      try {
        return row.type === 'index'
          ? !!(window.IndexWatchlist && IndexWatchlist.has(row.watchKey))
          : StockWatchlist.read(localStorage).includes(row.watchKey);
      } catch (e) { return false; } /* 浏览器禁用本地存储时目录仍可浏览，只是不能收藏 */
    },
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
    if (mounted) { catalogView?.restoreScroll(); return; }
    mounted = true;
    cat.innerHTML = '<p class="muted">目录加载中…</p>';
    const indexPromise = new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value && typeof value === 'object' ? value : {});
      };
      const timer = setTimeout(() => finish({}), 2000);
      Promise.resolve().then(() => LPPL.stock.index()).then(finish, () => finish({}));
    });
    const [catalogResult, index] = await Promise.all([
      LPPL.fetchResult('catalog.json', { empty: (data) => !Array.isArray(data?.rows) || data.rows.length === 0 }),
      indexPromise,
    ]);
    const catalog = catalogResult.data;
    if (!catalog || catalogResult.reason === 'empty') {
      const reason = catalogResult.reason || 'unpublished';
      const labels = { unpublished: '未发布', unavailable: '暂时无法读取', empty: '目录数据为空', not_applicable: '不适用' };
      cat.innerHTML = `<p class="${reason === 'unavailable' ? 'fail' : 'muted'}" data-reason="${reason}">标的目录：${labels[reason] || '状态未知'}</p>` +
        (reason === 'unavailable' ? '<button type="button" class="chip" data-retry-catalog>重试</button>' : '');
      mounted = false;
      return;
    }
    const params = new URLSearchParams(location.search);
    catalogView = StockCatalog.mount({ el: cat, catalog, published: index && typeof index === 'object' ? Object.keys(index) : [], watch,
      query: params.has('q') ? params.get('q') : undefined,
      onOpen: (row) => { location.href = 'stock.html?code=' + encodeURIComponent(row.code); } });
  }
  cat.addEventListener('click', (event) => {
    if (event.target.closest('[data-retry-catalog]')) mountCatalog();
  });
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
