/* Discover the published-result catalog, not an exchange-wide stock screener. */
(function () {
  'use strict';
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'button button-quiet'; button.id = 'open-discovery'; button.textContent = '发现已收录标的';
  document.querySelector('.heading-actions').prepend(button);
  const dialog = document.createElement('dialog'); dialog.id = 'discovery-dialog'; dialog.setAttribute('aria-labelledby', 'discovery-title');
  dialog.innerHTML = '<div class="dialog-head"><h2 id="discovery-title">发现已收录标的</h2><button type="button" id="close-discovery" class="icon-button" aria-label="关闭发现窗口">×</button></div><p class="discovery-feedback">来自站点已发布目录，不代表全市场。目录存在不代表有顶部信号；加入自选后再核对区间和证据。</p><label>名称或代码<input type="search" id="discovery-query" placeholder="例如 茅台 / 600519" maxlength="80"></label><label>交易所<select id="discovery-exchange"><option value="all">全部交易所</option><option value="sh">上交所</option><option value="sz">深交所</option><option value="bj">北交所</option></select></label><div id="discovery-status" class="discovery-feedback" role="status"></div><button id="discovery-retry" type="button" class="text-button" hidden>重试读取目录</button><div id="discovery-results" class="discovery-list"></div>';
  document.body.append(dialog);
  const $ = id => document.getElementById(id), escape = v => String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  let rows = null, loading = false;
  function render() {
    const q = $('discovery-query').value.trim().toLowerCase(), exchange = $('discovery-exchange').value;
    const matches = (rows || []).filter(row => (exchange === 'all' || row.exchange === exchange) && (!q || (row.name + row.code).toLowerCase().includes(q)));
    $('discovery-results').innerHTML = matches.slice(0, 40).map(row => '<div class="discovery-row"><div><strong>' + escape(row.name) + '</strong><small>' + escape(row.code + ' · ' + row.exchange.toUpperCase() + (row.asof ? ' · 截至 ' + row.asof : '')) + '</small></div><button type="button" class="button button-quiet" data-discover="' + row.code + '">加入研究</button></div>').join('');
    if (rows) $('discovery-status').textContent = matches.length ? '匹配 ' + matches.length + ' 个，按截止日排序显示前 40 个。目录来源：站点已发布结果索引。' : '没有匹配项。可以清除条件，或用“添加标的”输入代码查看覆盖状态。';
  }
  async function load() {
    if (loading) return; loading = true; $('discovery-status').textContent = '正在读取发布目录…'; $('discovery-retry').hidden = true;
    try {
      const data = await window.LPPL.stock.index();
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error();
      rows = Object.entries(data).filter(([code, item]) => /^(?:60|68|00|30|43|83|87|92)\d{4}$/.test(code) && item && typeof item === 'object').map(([code, item]) => ({ code, name: typeof item.name === 'string' ? item.name.slice(0, 80) : code, asof: window.ResearchWorkspaceCore.date(item.asof), exchange: /^(60|68)/.test(code) ? 'sh' : /^(00|30)/.test(code) ? 'sz' : 'bj' })).sort((a, b) => String(b.asof || '').localeCompare(String(a.asof || '')) || a.code.localeCompare(b.code));
      render();
    } catch { $('discovery-status').textContent = '发布目录暂时无法读取。现有自选和研究结果仍可使用。'; $('discovery-retry').hidden = false; }
    finally { loading = false; }
  }
  button.addEventListener('click', () => { dialog.showModal(); $('discovery-query').focus(); if (!rows) load(); else render(); });
  $('close-discovery').addEventListener('click', () => dialog.close()); dialog.addEventListener('close', () => button.focus());
  dialog.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); dialog.close(); } });
  $('discovery-query').addEventListener('input', render); $('discovery-exchange').addEventListener('change', render); $('discovery-retry').addEventListener('click', load);
  $('discovery-results').addEventListener('click', event => {
    const target = event.target.closest('[data-discover]'); if (!target) return;
    window.dispatchEvent(new CustomEvent('workspace-select', { detail: { assetId: 'stock:' + target.dataset.discover } })); dialog.close();
  });
})();
