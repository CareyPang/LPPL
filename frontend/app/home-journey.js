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
      // Keep the same words visible through the ivory-to-white transition
      // (.26–.42), then clear them before the functional section arrives.
      hero: (1 - smooth(.43, .58, p)) * clearance,
      waterline: 0,
      underwater: 0,
      chapter: p < .30 ? '海面' : p < .58 ? '入水' : '水线以下'
    };
  }
  function assetCode(value = '') {
    const code = String(value).normalize('NFKC').trim();
    const aliases = { '上证指数': 'sh000001', '上证': 'sh000001', '沪指': 'sh000001', '贵州茅台': 'sh600519', '茅台': 'sh600519' };
    if (aliases[code]) return aliases[code];
    if (/^(?:sh|sz|bj)\d{6}$/i.test(code)) return code.toLowerCase();
    if (/^(?:60|68)\d{4}$/.test(code)) return 'sh' + code;
    if (/^(?:00|30)\d{4}$/.test(code)) return 'sz' + code;
    if (/^(?:43|83|87|92)\d{4}$/.test(code)) return 'bj' + code;
    return code;
  }
  function workstationHref(search = '', selectedCode) {
    const params = new URLSearchParams(search);
    const next = new URLSearchParams();
    if (params.get('demo') === '1') next.set('demo', '1');
    const code = assetCode(selectedCode ?? params.get('code') ?? '');
    if (code) next.set('code', code);
    return 'stock.html' + (next.size ? '?' + next.toString() : '');
  }
  function prepareLinks(document, search) {
    const href = workstationHref(search);
    document.querySelectorAll('[data-workstation]').forEach(link => {
      link.href = workstationHref(search, link.dataset?.workstationCode);
    });
    return href;
  }
  function bindAssetEntry(document, search, navigate = href => root.location.assign(href)) {
    const form = document.getElementById('home-asset-search');
    if (!form) return;
    const input = document.getElementById('home-asset-code');
    const initial = new URLSearchParams(search).get('code');
    if (initial) input.value = initial;
    form.addEventListener('submit', event => {
      event.preventDefault();
      const code = input.value.trim();
      if (!code) { input.focus(); return; }
      navigate(workstationHref(search, code));
    });
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
  const api = { motionPolicy, introRunway, scene, assetCode, workstationHref, prepareLinks, bindAssetEntry, scaleCopy, bindScales };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.HomeJourney = api;
})(typeof window === 'object' ? window : globalThis);
