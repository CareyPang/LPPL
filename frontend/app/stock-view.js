(function (root) {
  'use strict';
  const labels = {
    idle: '尚未生成', loading: '读取中', submitting: '提交中', queued: '排队中',
    running: '计算中', current_running: '计算中', history_running: '计算中', current_ready: '可查看', history_ready: '可查看', publishing: '结果发布中', reconnecting: '连接恢复中',
    reconciliation_required: '待核对', paused: '任务已保留', unconfirmed: '提交待确认', ready: '可查看',
    stale: '缓存可查看 · 刷新未完成', failed: '本次更新未完成',
  };
  const active = value => ['submitting', 'queued', 'running', 'current_running', 'history_running', 'publishing', 'reconnecting', 'reconciliation_required'].includes(value);
  const number = value => value != null && Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '—';
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  function normalizedWindow(start, end, total) {
    const count = Number.isFinite(Number(total)) ? Math.max(0, Math.floor(Number(total))) : 0;
    if (!count) return { start: 0, end: 0 };
    let first = clamp(Number.isFinite(Number(start)) ? Math.floor(Number(start)) : 0, 0, count);
    let last = clamp(Number.isFinite(Number(end)) ? Math.floor(Number(end)) : 0, 0, count);
    if (last < first) [first, last] = [last, first];
    const size = Math.min(count, Math.max(Math.min(count, 20), last - first));
    first = Math.min(first, count - size);
    return { start: first, end: first + size };
  }
  function zoom(start, end, total, factor, anchorFrac) {
    const base = normalizedWindow(start, end, total);
    const count = Number.isFinite(Number(total)) ? Math.max(0, Math.floor(Number(total))) : 0;
    if (!count) return base;
    const scale = Number.isFinite(Number(factor)) && Number(factor) > 0 ? Number(factor) : 1;
    const size = base.end - base.start;
    const minSize = Math.min(count, 20);
    const nextSize = clamp(Math.round(size / scale), minSize, count);
    const anchor = clamp(Number.isFinite(Number(anchorFrac)) ? Number(anchorFrac) : .5, 0, 1);
    const anchorIndex = base.start + size * anchor;
    const nextStart = clamp(Math.round(anchorIndex - nextSize * anchor), 0, count - nextSize);
    return { start: nextStart, end: nextStart + nextSize };
  }
  function pan(start, end, total, deltaBars) {
    const base = normalizedWindow(start, end, total);
    const count = Number.isFinite(Number(total)) ? Math.max(0, Math.floor(Number(total))) : 0;
    if (!count) return base;
    const size = base.end - base.start;
    const delta = Number.isFinite(Number(deltaBars)) ? Math.round(Number(deltaBars)) : 0;
    const nextStart = clamp(base.start + delta, 0, count - size);
    return { start: nextStart, end: nextStart + size };
  }
  root.StockChartWindow = { zoom, pan };

  function mount(options) {
    const doc = options.document || root.document;
    const $ = id => doc.getElementById(id);
    let days = 120, allPrices = [], prices = [], windowStart = 0, windowEnd = 0;
    let selected = -1, lastCurrent, lastHistory, lastMarket, lastCode;
    let state = null, staticCode = null, staticGeneration = 0, closed = false;
    let storage;
    try { storage = root.localStorage; } catch { /* Storage is optional. */ }

    const visibility = root.StockVisibility?.create({ document: doc, storage,
      onVisible: observation => {
        $('first-visible-note').textContent = '本浏览器首次看到此结果：' + observation.first_visible_at_client +
          ' · 本机时钟未校验；不作为真实提前公开发布的证据。';
      },
    });

    function readout() {
      const bar = allPrices[selected];
      if (!bar) {
        $('quote-selected-date').textContent = '';
        $('quote-readout').textContent = '';
        for (const key of ['close', 'open', 'high', 'low']) $('quote-' + key).textContent = '—';
        return;
      }
      for (const key of ['close', 'open', 'high', 'low']) $('quote-' + key).textContent = number(bar[key]);
      $('quote-selected-date').textContent = bar.date + (selected === allPrices.length - 1 ? '（最新）' : '');
      $('quote-readout').textContent = bar.date + '  开 ' + number(bar.open) +
        '  高 ' + number(bar.high) + '  低 ' + number(bar.low) + '  收 ' + number(bar.close) + '  量 ' + number(bar.volume) + '（供应商原始单位）';
      $('quote-date').setAttribute('aria-valuetext', bar.date + '，收盘 ' + number(bar.close));
    }
    function setWindow(start, end, nextSelected = selected) {
      const bounds = normalizedWindow(start, end, allPrices.length);
      windowStart = bounds.start;
      windowEnd = bounds.end;
      prices = allPrices.slice(windowStart, windowEnd);
      selected = prices.length
        ? clamp(Number.isFinite(Number(nextSelected)) ? Math.round(Number(nextSelected)) : windowStart, windowStart, windowEnd - 1)
        : -1;
      const slider = $('quote-date');
      slider.min = String(windowStart);
      slider.max = String(Math.max(windowStart, windowEnd - 1));
      slider.value = String(Math.max(0, selected));
      if (prices.length) draw();
      else readout();
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
      const low = Math.min(...prices.map(x => x.low)), high = Math.max(...prices.map(x => x.high));
      const pad = Math.max((high - low) * .12, Math.abs(high) * .01, .01);
      const min = low - pad, max = high + pad;
      const plotWidth = width - left - right;
      const candleWidth = Math.max(.8, Math.min(9, plotWidth / Math.max(prices.length, 1) * .65));
      const x = i => left + (i + .5) / Math.max(prices.length, 1) * plotWidth;
      const priceBottom = height * .69, volumeTop = height * .77, volumeBottom = height - bottom;
      const maxVolume = Math.max(1, ...prices.map(bar => bar.volume));
      const y = p => top + (max - p) / (max - min) * (priceBottom - top);
      ctx.clearRect(0, 0, width, height); ctx.lineWidth = 1;
      ctx.font = '11px Consolas, monospace';
      for (let i = 0; i <= 4; i++) {
        const p = min + (max - min) * i / 4;
        ctx.strokeStyle = '#E3E7EE'; ctx.beginPath(); ctx.moveTo(left, y(p)); ctx.lineTo(width - right, y(p)); ctx.stroke();
        ctx.fillStyle = '#6A6D78'; ctx.fillText(number(p), width - right + 8, y(p) + 4);
      }
      ctx.fillStyle = '#6A6D78'; ctx.fillText('成交量', left, volumeTop - 6);
      for (const [i, bar] of prices.entries()) {
        ctx.strokeStyle = ctx.fillStyle = bar.close >= bar.open ? '#D6303A' : '#11845A';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x(i), y(bar.high)); ctx.lineTo(x(i), y(bar.low)); ctx.stroke();
        ctx.fillRect(x(i) - candleWidth / 2, Math.min(y(bar.open), y(bar.close)),
          candleWidth, Math.max(1, Math.abs(y(bar.open) - y(bar.close))));
        const volumeHeight = bar.volume / maxVolume * (volumeBottom - volumeTop);
        ctx.globalAlpha = .55;
        ctx.fillRect(x(i) - candleWidth / 2, volumeBottom - volumeHeight, candleWidth, volumeHeight);
        ctx.globalAlpha = 1;
      }
      const selectedVisible = selected - windowStart;
      if (prices[selectedVisible]) {
        ctx.lineWidth = 1; ctx.strokeStyle = '#9AA1AD'; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(x(selectedVisible), top); ctx.lineTo(x(selectedVisible), height - bottom); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = '#131722'; ctx.beginPath(); ctx.arc(x(selectedVisible), y(prices[selectedVisible].close), 3, 0, Math.PI * 2); ctx.fill();
      }
      ctx.fillStyle = '#6A6D78';
      ctx.fillText(prices[0].date, left, height - 9);
      ctx.textAlign = 'right'; ctx.fillText(prices[prices.length - 1].date, width - right, height - 9); ctx.textAlign = 'left';
      readout();
    }
    function showMarket(market) {
      const bars = market?.price || [];
      allPrices = bars.filter(bar => bar && typeof bar.date === 'string' &&
        ['open', 'high', 'low', 'close', 'volume'].every(key => Number.isFinite(bar[key])) &&
        Math.min(bar.open, bar.high, bar.low, bar.close) > 0 && bar.volume >= 0 &&
        bar.high >= Math.max(bar.open, bar.close, bar.low) && bar.low <= Math.min(bar.open, bar.close));
      const exists = allPrices.length > 0;
      $('market-stats').hidden = !exists;
      $('market-plot').hidden = !exists;
      $('date-control').hidden = !exists;
      $('market-empty').hidden = exists;
      $('quote-selected-date').hidden = !exists;
      if (exists) {
        $('market-date').textContent = '行情截至 ' + market.asof + ' · 未复权 · ' + (market.source || '日线数据');
        windowEnd = allPrices.length;
        windowStart = Math.max(0, windowEnd - days);
        setWindow(windowStart, windowEnd, windowEnd - 1);
      } else {
        $('market-date').textContent = '';
        setWindow(0, 0, -1);
      }
    }
    function update(next) {
      if (staticCode) return;
      state = next;
      const changed = lastCode !== next.code;
      if (changed) {
        lastCode = next.code; lastCurrent = null; lastHistory = null; lastMarket = null;
        $('results').hidden = true; $('asof').textContent = '—'; $('first-visible-note').textContent = ''; visibility?.observe(null, null); showMarket(null);
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
        $('first-visible-note').textContent = '尚未记录此结果在本浏览器的可见时间。';
        visibility?.observe($('summary').querySelector('.top') || $('risk'), next.current);
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
      const outdated = next.stale || root.StockSession.stale(next.current, next.market);
      const messages = [];
      if (next.current) messages.push('分析截至 ' + next.current.asof + (outdated ?
        active(next.currentStatus) ? '，正在更新；已有结果仍可查看。' : '，已有结果较旧，可重新更新。' : '，已有结果可查看。'));
      else messages.push(next.market ? '日线行情已可查看；当前分析单独更新。' : '先读取行情；当前分析单独更新。');
      const staleReasons = {
        analysis_asof_behind_market: '分析截至日早于行情截至日。',
        source_revision_changed: '已有结果与当前计算代码版本不同。',
        analysis_asof_or_source_behind_market: '结果截至日或计算代码版本尚未与当前行情核对一致。',
        refresh_failed_previous_result_retained: '本次刷新失败，保留上次成功结果及原始截止日。',
      };
      if (outdated && staleReasons[next.stale_reason]) messages.push(staleReasons[next.stale_reason]);
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
    function select(input) {
      let code = options.normalizeCode ? options.normalizeCode(input) : input;
      if (!code) {
        $('query-status').textContent = '请输入六位 A 股股票代码或观察清单中的美股代码。';
        return;
      }
      if (options.isStaticCode?.(code)) {
        const generation = ++staticGeneration;
        staticCode = code;
        $('code').value = code;
        const url = new URL(root.location.href); url.searchParams.set('code', code);
        root.history.replaceState(null, '', url);
        lastCode = null; lastCurrent = null; lastHistory = null; lastMarket = null;
        state = null;
        $('asof').textContent = '—';
        $('results').hidden = true;
        $('market-panel').hidden = true;
        $('task-stages').hidden = true;
        $('analysis-pending').hidden = true;
        $('refresh-current').disabled = true;
        $('compute-history').disabled = true;
        $('resume-jobs').hidden = true;
        $('first-visible-note').textContent = '';
        visibility?.observe(null, null);
        $('query-status').textContent = '读取已发布美股结果…';
        void Promise.resolve().then(() => options.loadStaticCode(code)).then(result => {
          if (closed || generation !== staticGeneration || staticCode !== code) return;
          if (!result?.current) throw Error('该美股的预计算结果暂不可用。');
          options.renderResult(result.current, result.history || null);
          $('query-status').textContent = result.refreshFailed
            ? `已加载 ${result.current.asof || '—'} 的预计算结果；最近一次夜间刷新失败，结果未更新。`
            : result.history
              ? '已加载预计算的当前结果和历史回测。'
              : '已加载预计算的当前结果；历史回测文件暂不可用。';
        }).catch(error => {
          if (closed || generation !== staticGeneration || staticCode !== code) return;
          $('query-status').textContent = error.message || '美股预计算结果暂不可用。';
        });
        return;
      }
      staticCode = null;
      staticGeneration += 1;
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
      const end = allPrices.length;
      setWindow(Math.max(0, end - days), end, end - 1);
    });
    $('quote-date').addEventListener('input', event => {
      selected = clamp(Number(event.target.value), windowStart, windowEnd - 1);
      draw();
    });
    const canvas = $('market-plot');
    const pointers = new Map();
    let drag = null, pinch = null;
    function plotMetrics(clientX) {
      const rect = canvas.getBoundingClientRect();
      const plotWidth = Math.max(rect.width - 68, 1);
      return {
        rect,
        plotWidth,
        anchor: clamp((clientX - rect.left - 10) / plotWidth, 0, 1),
      };
    }
    function selectAt(clientX) {
      if (!prices.length) return;
      const { anchor } = plotMetrics(clientX);
      selected = windowStart + Math.round(anchor * (prices.length - 1));
      $('quote-date').value = String(selected);
      draw();
    }
    function startPinch() {
      const points = [...pointers.values()];
      if (points.length < 2) { pinch = null; return; }
      const midpoint = (points[0].x + points[1].x) / 2;
      const { anchor, plotWidth } = plotMetrics(midpoint);
      pinch = {
        start: windowStart,
        end: windowEnd,
        distance: Math.max(1, Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y)),
        midpoint,
        anchor,
        plotWidth,
      };
    }
    canvas.addEventListener('pointerdown', event => {
      if (event.pointerType === 'touch') {
        pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        canvas.setPointerCapture?.(event.pointerId);
        if (pointers.size === 2) startPinch();
      } else if ((event.pointerType === 'mouse' || event.pointerType === 'pen') && event.button === 0) {
        drag = { x: event.clientX, start: windowStart, end: windowEnd };
        canvas.setPointerCapture?.(event.pointerId);
      }
    });
    canvas.addEventListener('pointermove', event => {
      if (event.pointerType === 'touch') {
        if (!pointers.has(event.pointerId)) return;
        pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        if (pointers.size >= 2 && pinch) {
          const points = [...pointers.values()];
          const midpoint = (points[0].x + points[1].x) / 2;
          const distance = Math.max(1, Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y));
          const scaled = zoom(pinch.start, pinch.end, allPrices.length, distance / pinch.distance, pinch.anchor);
          const deltaBars = -(midpoint - pinch.midpoint) / pinch.plotWidth * (pinch.end - pinch.start);
          const moved = pan(scaled.start, scaled.end, allPrices.length, deltaBars);
          setWindow(moved.start, moved.end, selected);
        } else if (pointers.size === 1) {
          selectAt(event.clientX);
        }
        return;
      }
      if (event.pointerType !== 'mouse' && event.pointerType !== 'pen') return;
      if (drag && event.buttons) {
        const { plotWidth } = plotMetrics(event.clientX);
        const deltaBars = (drag.x - event.clientX) / plotWidth * (drag.end - drag.start);
        const moved = pan(drag.start, drag.end, allPrices.length, deltaBars);
        setWindow(moved.start, moved.end, selected);
      } else if (!drag) {
        selectAt(event.clientX);
      }
    });
    const endPointer = event => {
      if (event.pointerType === 'touch') {
        pointers.delete(event.pointerId);
        if (pointers.size < 2) pinch = null;
      } else {
        drag = null;
      }
    };
    canvas.addEventListener('pointerup', endPointer);
    canvas.addEventListener('pointercancel', endPointer);
    canvas.addEventListener('wheel', event => {
      if (!allPrices.length) return;
      event.preventDefault();
      const { anchor } = plotMetrics(event.clientX);
      const bounds = zoom(windowStart, windowEnd, allPrices.length, Math.exp(-event.deltaY * .002), anchor);
      setWindow(bounds.start, bounds.end, selected);
    }, { passive: false });
    const observer = root.ResizeObserver ? new root.ResizeObserver(draw) : null;
    observer?.observe($('market-panel'));
    root.addEventListener('pagehide', event => {
      if (!event.persisted) {
        closed = true;
        session.destroy();
        observer?.disconnect();
        visibility?.destroy();
      }
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
