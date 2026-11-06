/* Homepage presentation only: no market data, model output, or navigation delay. */
(function (root) {
  'use strict';
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const smooth = (low, high, value) => {
    const t = clamp((value - low) / (high - low), 0, 1);
    return t * t * (3 - 2 * t);
  };
  function motionPolicy({ reducedMotion = false, saveData = false, stored = null, protocol = '' } = {}) {
    if (protocol === 'file:') return { enabled: false, locked: true, reason: 'local-still' };
    if (reducedMotion) return { enabled: false, locked: true, reason: 'reduced-motion' };
    if (stored === 'off') return { enabled: false, locked: false, reason: 'user-paused' };
    if (saveData && stored !== 'on') return { enabled: false, locked: false, reason: 'save-data' };
    return { enabled: true, locked: false, reason: 'motion' };
  }
  function introRunway(introHeight, viewportHeight) {
    // Finish the fixed story before the next section enters the viewport.
    return Math.max(1, introHeight - viewportHeight * 1.1);
  }
  function scene(progress, layout = {}) {
    const p = clamp(Number(progress) || 0, 0, 1);
    const clearance = smooth(.85, 1.05, layout.contentTopRatio ?? 2);
    return {
      hero: (1 - smooth(.13, .28, p)) * clearance,
      waterline: smooth(.32, .40, p) * (1 - smooth(.52, .60, p)) * clearance,
      underwater: smooth(.64, .72, p) * (1 - smooth(.87, .96, p)) * clearance,
      chapter: p < .30 ? '海面' : p < .58 ? '入水' : '水线以下'
    };
  }
  function workstationHref(search = '') {
    const params = new URLSearchParams(search);
    return params.get('demo') === '1' ? 'stock.html?demo=1' : 'stock.html';
  }
  function prepareLinks(document, search) {
    const href = workstationHref(search);
    document.querySelectorAll('[data-workstation]').forEach(link => { link.href = href; });
    return href;
  }
  const scales = {
    stage: {
      title: '阶段性高点',
      description: '关注约 1–6 个月上涨阶段的高点。它可能同时也是局部高点；更长的观察尺度，并不代表更远的预测日期。',
      note: '阶段提示优先呈现，局部提示独立保留。'
    },
    local: {
      title: '短期局部高点',
      description: '观察数周行情中的局部起伏。一个局部高点，并不自动意味着这段上涨已经结束。',
      note: '局部与阶段可以重合，也可以分别出现。'
    },
    pending: {
      title: '尺度尚待判断',
      description: '只有一段上涨或一次合格拟合，仍不足以确定高点层级。证据不够时，保留待判状态。',
      note: '这里切换的是讲解，不是在给某只股票分类。'
    }
  };
  function scaleCopy(name) { return scales[name] || scales.stage; }
  function bindScales(document) {
    const panel = document.getElementById('scale-study');
    if (!panel) return;
    const buttons = [...panel.querySelectorAll('[data-scale]')];
    function choose(name) {
      const copy = scaleCopy(name);
      panel.dataset.selected = Object.hasOwn(scales, name) ? name : 'stage';
      buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.scale === panel.dataset.selected)));
      document.getElementById('scale-title').textContent = copy.title;
      document.getElementById('scale-description').textContent = copy.description;
      document.getElementById('scale-note').textContent = copy.note;
    }
    buttons.forEach(button => button.addEventListener('click', () => choose(button.dataset.scale)));
    choose('stage');
  }
  const api = { motionPolicy, introRunway, scene, workstationHref, prepareLinks, scaleCopy, bindScales };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.HomeJourney = api;
})(typeof window === 'object' ? window : globalThis);
