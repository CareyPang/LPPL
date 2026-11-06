(function (root) {
  'use strict';
  const labels = {
    idle: '尚未生成', loading: '读取中', submitting: '提交中', queued: '排队中',
    running: '计算中', publishing: '结果发布中', reconnecting: '连接恢复中',
    paused: '任务已保留', unconfirmed: '提交待确认', ready: '可查看',
    stale: '缓存可查看 · 刷新未完成', failed: '本次更新未完成',
  };
  const active = value => ['submitting', 'queued', 'running', 'publishing', 'reconnecting'].includes(value);
  const number = value => value != null && Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '—';
  function mount(options) {
    const doc = options.document || root.document;
    const $ = id => doc.getElementById(id);
    let days = 120, prices = [], selected = -1, lastCurrent, lastHistory, lastMarket, lastCode;
    let state = null;
    let storage;
    try { storage = root.localStorage; } catch { /* Storage is optional. */ }

    function readout() {
      const bar = prices[selected];
      if (!bar) { $('quote-readout').textContent = ''; return; }
      $('quote-readout').textContent = bar.date + '  开 ' + number(bar.open) +
        '  高 ' + number(bar.high) + '  低 ' + number(bar.low) + '  收 ' + number(bar.close);
      $('quote-date').setAttribute('aria-valuetext', bar.date + '，收盘 ' + number(bar.close));
    }
    function draw() {
      const canvas = $('market-plot');
      if (canvas.hidden || !prices.length) return;
      const width = canvas.clientWidth, height = canvas.clientHeight;
      if (!width || !height) return;
      const ratio = Math.min(root.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
      const ctx = canvas.getContext('2d');
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      const left = 10, right = 58, top = 20, bottom = 32;
      const low = Math.min(...prices.map(x => x.close)), high = Math.max(...prices.map(x => x.close));
      const pad = Math.max((high - low) * .12, Math.abs(high) * .01, .01);
      const min = low - pad, max = high + pad;
      const x = i => left + i / Math.max(prices.length - 1, 1) * (width - left - right);
      const y = p => top + (max - p) / (max - min) * (height - top - bottom);
      ctx.clearRect(0, 0, width, height); ctx.lineWidth = 1;
      ctx.font = '11px Consolas, monospace';
      for (let i = 0; i <= 4; i++) {
        const p = min + (max - min) * i / 4;
        ctx.strokeStyle = '#28332F'; ctx.beginPath(); ctx.moveTo(left, y(p)); ctx.lineTo(width - right, y(p)); ctx.stroke();
        ctx.fillStyle = '#A7B4AF'; ctx.fillText(number(p), width - right + 8, y(p) + 4);
      }
      ctx.strokeStyle = '#91C7BC'; ctx.lineWidth = 1.8; ctx.beginPath();
      prices.forEach((bar, i) => { if (i === 0) ctx.moveTo(x(i), y(bar.close)); else ctx.lineTo(x(i), y(bar.close)); });
      ctx.stroke();
      if (prices[selected]) {
        ctx.lineWidth = 1; ctx.strokeStyle = '#6D8680'; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(x(selected), top); ctx.lineTo(x(selected), height - bottom); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = '#E8F3EE'; ctx.beginPath(); ctx.arc(x(selected), y(prices[selected].close), 3, 0, Math.PI * 2); ctx.fill();
      }
      ctx.fillStyle = '#A7B4AF';
      ctx.fillText(prices[0].date, left, height - 9);
      ctx.textAlign = 'right'; ctx.fillText(prices[prices.length - 1].date, width - right, height - 9); ctx.textAlign = 'left';
      readout();
    }
    function showMarket(market) {
      const bars = market?.price || [];
      prices = bars.filter(bar => bar && typeof bar.date === 'string' && Number.isFinite(bar.close) && bar.close > 0).slice(-days);
      selected = prices.length - 1;
      const exists = prices.length > 0;
      $('market-stats').hidden = !exists;
      $('market-plot').hidden = !exists;
      $('date-control').hidden = !exists;
      $('market-empty').hidden = exists;
      $('quote-date').max = String(Math.max(0, prices.length - 1));
      $('quote-date').value = String(Math.max(0, selected));
      if (exists) {
        const latest = prices[prices.length - 1];
        for (const key of ['close', 'open', 'high', 'low']) $('quote-' + key).textContent = number(latest[key]);
        $('market-date').textContent = '行情截至 ' + market.asof + ' · 未复权 · ' + (market.source || '日线数据');
        draw();
      } else { $('market-date').textContent = ''; readout(); }
    }
    function update(next) {
      state = next;
      const changed = lastCode !== next.code;
      if (changed) {
        lastCode = next.code; lastCurrent = null; lastHistory = null; lastMarket = null;
        $('results').hidden = true; $('asof').textContent = '—'; showMarket(null);
      }
      $('market-panel').hidden = false; $('task-stages').hidden = false;
      $('market-name').textContent = (next.market?.name || next.current?.name || '股票') + ' · ' + next.code;
      if (next.market && next.market !== lastMarket) { lastMarket = next.market; showMarket(next.market); }
      if (next.market) $('market-date').textContent = '行情截至 ' + next.market.asof +
        ' · 未复权 · ' + (next.market.source || '日线数据') +
        (next.marketStatus === 'stale' || next.market.stale === true ? ' · 缓存日线，刷新未完成' : '');
      if (!next.market) $('market-empty').textContent = next.issues.market ||
        '正在读取已收盘日线；模型计算不会阻塞行情。';
      const history = root.StockSession.compatible(next.current, next.history) ? next.history : null;
      if (next.current && (lastCurrent !== next.current || lastHistory !== history)) {
        lastCurrent = next.current; lastHistory = history;
        options.renderResult(next.current, history);
        if (next.history && !history) $('history-note').textContent =
          '已有历史回放与当前模型版本尚未匹配，可重新生成；当前分析仍可查看。';
      }
      $('analysis-pending').hidden = !!next.current;
      $('analysis-pending').textContent = next.currentStatus === 'failed'
        ? '本次分析暂未完成。行情仍可查看，也可以稍后重试。'
        : '当前分析在后台更新。你可以先看行情、切换股票，或稍后回来查看。';
      $('market-stage').textContent = '日线行情 · ' + (labels[next.marketStatus] || '读取中');
      $('current-stage').textContent = '当前分析 · ' + (labels[next.currentStatus] || '等待中');
      $('history-stage').textContent = '历史回放 · ' + (next.historyStatus === 'idle' ? '按需生成' : labels[next.historyStatus] || '等待中');
      const outdated = root.StockSession.stale(next.current, next.market);
      const messages = [];
      if (next.current) messages.push('分析截至 ' + next.current.asof + (outdated ?
        active(next.currentStatus) ? '，正在更新；已有结果仍可查看。' : '，已有结果较旧，可重新更新。' : '，已有结果可查看。'));
      else messages.push(next.market ? '日线行情已可查看；当前分析单独更新。' : '先读取行情；当前分析单独更新。');
      for (const key of ['market', 'current', 'history']) if (next.issues[key]) messages.push(next.issues[key]);
      $('query-status').textContent = [...new Set(messages)].join(' ');
      $('refresh-current').disabled = active(next.currentStatus);
      $('compute-history').disabled = active(next.historyStatus);
      $('refresh-current').textContent = active(next.currentStatus) ? '当前分析' + labels[next.currentStatus] : '更新当前分析';
      $('compute-history').textContent = active(next.historyStatus) ? '历史回放' + labels[next.historyStatus] :
        next.history ? '更新历史回放' : '生成104周回放';
      $('resume-jobs').hidden = !['currentStatus', 'historyStatus'].some(key => next[key] === 'paused');
      const recent = [...new Set([...next.tasks.map(job => job.code), ...(next.recent || [])])].slice(0, 8);
      const container = $('recent-stocks');
      container.replaceChildren(...recent.map(code => {
        const button = doc.createElement('button');
        button.type = 'button';
        button.textContent = code + (next.tasks.some(job => job.code === code) ? ' · 有任务' : '');
        button.setAttribute('aria-current', String(code === next.code));
        button.addEventListener('click', () => select(code));
        return button;
      }));
    }
    const session = root.StockSession.create({ api: options.api, storage, onChange: update });
    function select(code) {
      if (!/^(?:60|68|00|30|43|83|87|92)\d{4}$/.test(code)) {
        $('query-status').textContent = '请输入支持的六位 A 股股票代码。';
        return;
      }
      $('code').value = code;
      const url = new URL(root.location.href); url.searchParams.set('code', code);
      root.history.replaceState(null, '', url);
      void session.select(code);
    }
    $('search').addEventListener('submit', event => { event.preventDefault(); select($('code').value.trim()); });
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
    $('quote-date').addEventListener('input', event => { selected = Number(event.target.value); draw(); });
    $('market-plot').addEventListener('pointermove', event => {
      if (!prices.length) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const p = (event.clientX - rect.left - 10) / Math.max(rect.width - 68, 1);
      selected = Math.max(0, Math.min(prices.length - 1, Math.round(p * (prices.length - 1))));
      $('quote-date').value = String(selected); draw();
    });
    const observer = root.ResizeObserver ? new root.ResizeObserver(draw) : null;
    observer?.observe($('market-panel'));
    root.addEventListener('pagehide', event => {
      if (!event.persisted) { session.destroy(); observer?.disconnect(); }
    });
    root.addEventListener('pageshow', event => {
      if (event.persisted && state) void session.select(state.code);
    });
    const initial = new URLSearchParams(root.location.search).get('code');
    if (initial) select(initial);
    return session;
  }
  root.StockView = { mount };
})(window);
