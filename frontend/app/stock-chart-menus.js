/* 个股页图表头部：时间 / 尺度 / 图层三个下拉菜单的开合与当前尺度文字 */
(function () {
  const menus = [...document.querySelectorAll('#market-panel .cmenu')];
  const scales = document.getElementById('stock-scales');
  const scaleMenu = document.getElementById('menu-scale');
  const cur = document.getElementById('menu-scale-cur');
  const syncScale = () => {
    scaleMenu.hidden = scales.hidden;
    const on = scales.querySelector('[aria-checked="true"]');
    cur.textContent = on ? on.textContent.split('\n')[0] : '—';
  };
  new MutationObserver(syncScale).observe(scales, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden', 'aria-checked'] });
  syncScale();
  for (const menu of menus) {
    menu.addEventListener('toggle', () => { if (menu.open) for (const other of menus) if (other !== menu) other.open = false; });
  }
  document.addEventListener('click', (event) => {
    for (const menu of menus) {
      if (!menu.contains(event.target) || (event.target.closest('.cmenu-pop button') && menu.id !== 'menu-layers')) menu.open = false;
    }
  });
})();
