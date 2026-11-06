(function (root) {
  'use strict';
  const baseLabels = {
    idle: '尚未生成', loading: '读取中', submitting: '提交中', queued: '排队中',
    running: '计算中', publishing: '结果发布中', reconnecting: '连接恢复中',
    paused: '任务已保留', unconfirmed: '提交待确认', ready: '可查看',
    stale: '缓存可查看 · 刷新未完成', failed: '本次更新未完成',
  };
  const active = value => ['submitting', 'queued', 'running', 'publishing', 'reconnecting'].includes(value);
  const number = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';
  function mount(options) {
    const doc = options.document || root.document;
    const $ = id => doc.getElementById(id);
    const chart = root.CandleChart;
    const demo = options.api.isDemo === true;
    const labels = demo ? { ...baseLabels, queued: '演示排队中', running: '流程演示中',
      publishing: '演示整理中', ready: '演示已完成 · 未运行模型' } : baseLabels;
    let days = 120, prices = [], selected = -1, pointerY = null, layout = null;
    let lastCurrent, lastHistory, lastMarket, lastCode, state = null, drawFrame = null;
    let storage = options.storage;
    if (!storage) try {
      const native = root.localStorage;
      storage = demo ? {
        getItem: key => native.getItem('presentation.' + key),
        setItem: (key, value) => native.setItem('presentation.' + key, value),
      } : native;
    } catch { /* Storage is optional. */ }
    function readout(announce = false) {
      const bar = prices[selected];
      const text = chart.describe(bar, state?.market?.volume_unit);
      $('quote-readout').textContent = text;
      if (announce && $('quote-announcement')) $('quote-announcement').textContent = text;
      if (!bar) { $('chart-tooltip').hidden = true; return; }
      $('chart-tooltip').hidden = false;
      $('tooltip-date').textContent = bar.date;
      $('tooltip-ohlc').textContent = `开 ${number(bar.open)}  高 ${number(bar.high)}  低 ${number(bar.low)}  收 ${number(bar.close)}`;
      $('tooltip-volume').textContent = `量 ${chart.volume(bar.volume)}${bar.volume == null ? '' : ' · ' + chart.unitLabel(state?.market?.volume_unit)}`;
      $('quote-date').setAttribute('aria-valuetext', text);
    }
    function draw() {
      drawFrame = null;
      const canvas = $('market-plot');
      if (canvas.hidden || !prices.length) return;
      layout = chart.draw(canvas, prices, selected, { pointerY });
      readout();
    }
    function scheduleDraw() {
      if (drawFrame !== null) return;
      if (root.requestAnimationFrame) drawFrame = root.requestAnimationFrame(draw);
      else draw();
    }
    function marketCaption(market, status) {
      return `行情截至 ${market.asof} · ${chart.adjustmentLabel(market.adjustment)} · ${market.source || '日线数据'}` +
        (status === 'stale' || market.stale === true ? ' · 缓存日线，刷新未完成' : '') +
        (demo ? ' · 固定历史样本，不是实时行情' : '');
    }
    function showMarket(market) {
      prices = chart.normalize(market?.price).slice(-days);
      selected = prices.length - 1; pointerY = null;
      const exists = prices.length > 0;
      $('market-stats').hidden = !exists; $('chart-shell').hidden = !exists;
      $('market-plot').hidden = !exists; $('date-control').hidden = !exists;
      $('market-empty').hidden = exists; $('chart-legend').hidden = !exists;
      $('quote-date').max = String(Math.max(0, prices.length - 1));
      $('quote-date').value = String(Math.max(0, selected));
      if (exists) {
        const latest = prices.at(-1);
        for (const key of ['close', 'open', 'high', 'low']) $('quote-' + key).textContent = number(latest[key]);
        $('market-date').textContent = marketCaption(market, state?.marketStatus);
        $('market-basis').textContent = `${chart.adjustmentLabel(market.adjustment)}日线 · 成交量：${chart.unitLabel(market.volume_unit)}。` +
          '缺失OHLC只显示收盘标记；成交量0与缺失分别显示短刻线与×。';
        $('chart-source-note').textContent = demo
          ? '本地样本取自既有冻结文件。K线为真实历史行情；下方任务仅演示交互，不计算或展示预测。'
          : '行情与研究结果独立更新；模型历史若使用另一复权口径，将在下方单独标明，价格轴不混用。';
        $('market-plot').setAttribute('aria-label', `${chart.adjustmentLabel(market.adjustment)}日线K线与成交量，下方日期滑块可逐日读取OHLC和成交量`);
        draw();
      } else { $('market-date').textContent = ''; readout(); }
    }
    function update(next) {
      state = next;
      if (lastCode !== next.code) {
        lastCode = next.code; lastCurrent = null; lastHistory = null; lastMarket = null;
        $('results').hidden = true; $('demo-result').hidden = true; $('asof').textContent = '—'; showMarket(null);
      }
      $('welcome').hidden = true; doc.body.classList.add('has-stock');
      $('task-tools').hidden = false; $('market-panel').hidden = false; $('task-stages').hidden = false;
      $('market-name').textContent = (next.market?.name || next.current?.name || '股票') + ' · ' + next.code;
      if (next.market && next.market !== lastMarket) { lastMarket = next.market; showMarket(next.market); }
      if (next.market) $('market-date').textContent = marketCaption(next.market, next.marketStatus);
      if (!next.market) $('market-empty').textContent = next.issues.market || '正在读取已收盘日线；研究任务不会锁定行情。';
      const history = root.StockSession.compatible(next.current, next.history) ? next.history : null;
      if (next.current && (lastCurrent !== next.current || lastHistory !== history)) {
        lastCurrent = next.current; lastHistory = history;
        options.renderResult(next.current, history);
        if (!demo && next.history && !history) $('history-note').textContent =
          '已有历史回放与当前模型版本尚未匹配，可重新生成；当前分析仍可查看。';
      }
      $('analysis-pending').hidden = !!next.current;
      $('analysis-pending').textContent = demo
        ? '任务状态正在本机演示。你可以操作K线；没有请求线上计算，也不会生成预测值。'
        : next.currentStatus === 'failed' ? '本次分析暂未完成。行情仍可查看，也可以稍后重试。'
          : '当前研究结果在后台更新。你可以先看K线、切换股票，或稍后回来查看。';
      $('market-stage').textContent = '日线行情 · ' + (next.marketStatus === 'ready' ? demo ? '冻结样本已载入' : '可查看' : labels[next.marketStatus] || '读取中');
      $('current-stage').textContent = (demo ? '任务演示 · ' : '当前分析 · ') + (labels[next.currentStatus] || '等待中');
      $('history-stage').textContent = (demo ? '回放演示 · ' : '历史回放 · ') +
        (next.historyStatus === 'idle' ? '按需开启' : labels[next.historyStatus] || '等待中');
      const outdated = root.StockSession.stale(next.current, next.market), messages = [];
      if (demo) {
        const taskActive = active(next.currentStatus) || active(next.historyStatus);
        messages.push(taskActive
          ? next.current ? '上一轮演示记录保留；新任务正在演示，行情仍可操作。未运行模型。'
            : '任务正在本机演示，行情仍可操作。未运行模型。'
          : next.current ? '演示已完成 · 未运行模型。当前显示实际冻结日线，无顶部预测。'
            : '实际冻结行情与演示任务独立加载。');
      }
      else if (next.current) messages.push('分析截至 ' + next.current.asof + (outdated ?
        active(next.currentStatus) ? '，正在更新；已有结果仍可查看。' : '，已有结果较旧，可重新更新。' : '，已有结果可查看。'));
      else messages.push(next.market ? '日线已可查看；研究结果单独更新。' : '先读取日线；研究结果单独更新。');
      for (const key of ['market', 'current', 'history']) if (next.issues[key]) messages.push(next.issues[key]);
      $('query-status').textContent = [...new Set(messages)].join(' ');
      $('refresh-current').disabled = active(next.currentStatus); $('compute-history').disabled = active(next.historyStatus);
      $('refresh-current').textContent = active(next.currentStatus) ? labels[next.currentStatus] : demo ? '再演示一次后台任务' : '更新当前分析';
      $('compute-history').textContent = active(next.historyStatus) ? labels[next.historyStatus] : demo ? '演示独立回放任务' : next.history ? '更新历史回放' : '生成104周回放';
      $('resume-jobs').hidden = !['currentStatus', 'historyStatus'].some(key => next[key] === 'paused');
      const recent = [...new Set([...next.tasks.map(job => job.code), ...(next.recent || [])])].slice(0, 8);
      $('recent-stocks').replaceChildren(...recent.map(code => {
        const button = doc.createElement('button'); button.type = 'button';
        button.textContent = code + (next.tasks.some(job => job.code === code) ? ' · 有任务' : '');
        button.setAttribute('aria-current', String(code === next.code));
        button.addEventListener('click', () => select(code)); return button;
      }));
    }
    const session = root.StockSession.create({ api: options.api, storage, onChange: update,
      ...(demo ? { pollMs: 700 } : {}) });
    function searchError(message, code) {
      const retained = state?.code ? ` 当前仍显示 ${state.code}${code ? `，未切换至 ${code}` : ''}。` : '';
      $('search-error').textContent = message + retained;
      $('search-error').hidden = false;
      $('code').setAttribute('aria-invalid', 'true');
    }
    function select(code) {
      if (!/^(?:60|68|00|30|43|83|87|92)\d{4}$/.test(code)) {
        searchError('请输入支持的六位A股股票代码。', code); return;
      }
      if (demo && !options.api.codes.includes(code)) {
        searchError('离线演示仅包含600519的真实冻结行情。其他代码未接入，也没有请求线上服务。', code); return;
      }
      $('search-error').textContent = ''; $('search-error').hidden = true;
      $('code').setAttribute('aria-invalid', 'false');
      $('code').value = code;
      const url = new URL(root.location.href); url.searchParams.set('code', code);
      try { root.history.replaceState(null, '', url); } catch { /* file:// may restrict history writes. */ }
      void session.select(code);
    }
    $('search').addEventListener('submit', event => { event.preventDefault(); select($('code').value.trim()); });
    $('code').addEventListener('invalid', event => {
      event.preventDefault(); searchError('请输入支持的六位A股股票代码。', $('code').value.trim());
    });
    for (const button of doc.querySelectorAll('[data-stock-code]')) button.addEventListener('click', () => select(button.dataset.stockCode));
    $('refresh-current').addEventListener('click', () => { if (state) void session.request(state.code); });
    $('compute-history').addEventListener('click', () => { if (state) void session.request(state.code, 'history'); });
    $('resume-jobs').addEventListener('click', () => {
      if (state) for (const mode of ['current', 'history']) session.resume(state.code, mode);
    });
    for (const button of doc.querySelectorAll('[data-days]')) button.addEventListener('click', () => {
      days = Number(button.dataset.days);
      for (const other of doc.querySelectorAll('[data-days]')) other.setAttribute('aria-pressed', String(other === button));
      showMarket(state?.market);
    });
    $('quote-date').addEventListener('input', event => { selected = Number(event.target.value); pointerY = null; draw(); readout(true); });
    $('market-plot').addEventListener('pointermove', event => {
      if (!prices.length || !layout) return;
      const rect = event.currentTarget.getBoundingClientRect();
      selected = layout.indexAt(event.clientX - rect.left); pointerY = event.clientY - rect.top;
      $('quote-date').value = String(selected); scheduleDraw();
    });
    $('market-plot').addEventListener('pointerleave', () => { pointerY = null; scheduleDraw(); });
    const observer = root.ResizeObserver ? new root.ResizeObserver(scheduleDraw) : null;
    observer?.observe($('market-panel'));
    root.addEventListener('pagehide', event => {
      if (!event.persisted) { session.destroy(); observer?.disconnect(); if (drawFrame !== null) root.cancelAnimationFrame?.(drawFrame); }
    });
    root.addEventListener('pageshow', event => { if (event.persisted && state) void session.select(state.code); });
    const initial = new URLSearchParams(root.location.search).get('code');
    if (initial) select(initial);
    return session;
  }
  root.StockView = { mount };
})(window);
