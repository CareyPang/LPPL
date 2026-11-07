/* Decorative brand motion only: it never reads model or market values. */
(function () {
  'use strict';
  const root = document.documentElement;
  const control = document.getElementById('workspace-motion');
  if (!control) return;
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  let stored = null;
  try { stored = localStorage.getItem('cp_home_motion'); } catch (_) { /* Session-only fallback. */ }
  function render() {
    const locked = preference.matches || Boolean(navigator.connection && navigator.connection.saveData);
    const enabled = !locked && stored !== 'off';
    root.classList.toggle('workspace-static', !enabled);
    control.disabled = locked;
    control.setAttribute('aria-pressed', String(enabled));
    control.setAttribute('aria-label', locked ? '静态画面，遵循系统减少动效或节省流量设置' : enabled ? '关闭工作站装饰动效' : '开启工作站装饰动效');
    control.textContent = locked ? '装饰动画 · 系统关闭' : enabled ? '装饰动画 · 开' : '装饰动画 · 关';
    control.title = locked ? '遵循系统减少动态效果或省流设置；不影响行情与分析' : '仅控制徽章扫光，不影响行情与分析';
  }
  control.addEventListener('click', function () {
    stored = root.classList.contains('workspace-static') ? 'on' : 'off';
    try { localStorage.setItem('cp_home_motion', stored); } catch (_) { /* The current page still responds. */ }
    render();
  });
  if (preference.addEventListener) preference.addEventListener('change', render);
  window.addEventListener('storage', function (event) {
    if (event.key === 'cp_home_motion' || event.key === null) { stored = event.newValue; render(); }
  });
  render();
})();
