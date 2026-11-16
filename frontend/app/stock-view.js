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
  function mapScenarioBands(bars, windows, states, closures) {
    if (!bars.length || !root.CPTradingDays) return [];
    const selectable = new Set((states || [])
      .filter(state => state.selectable && state.hasWindow)
      .map(state => state.scale));
    return (windows || []).filter(window => window && selectable.has(window.scale) &&
      typeof window.q20_date === 'string' && typeof window.q80_date === 'string')
      .map(window => {
        const first = root.CPTradingDays.idxOf(bars, window.q20_date, closures);
        const last = root.CPTradingDays.idxOf(bars, window.q80_date, closures);
        return {
          scale: window.scale,
          lo: Math.min(first, last),
          hi: Math.max(first, last),
          q20_date: window.q20_date,
          q80_date: window.q80_date,
        };
      });
  }
  function futureSlots(length, bands, atLatest) {
    if (!atLatest || !length || !bands.length) return 0;
    const furthest = Math.max(...bands.map(band => band.hi - (length - 1)));
    return furthest > 0 ? Math.min(260, furthest + 3) : 0;
  }
  function domainSlots(start, end, future) {
    return Math.max(0, end - start) + Math.max(0, future);
  }
  root.StockChartWindow = { zoom, pan, mapScenarioBands, futureSlots, domainSlots };

  const SCALE_NAMES = {
    '2-4w': '2–4 周',
    '1-3m': '1–3 月',
    '3-6m': '3–6 月',
    '6-12m': '6–12 月',
    '12-24m': '12–24 月',
    '2-6y': '2–6 年',
  };

  function mount(options) {
    const doc = options.document || root.document;
    const $ = id => doc.getElementById(id);
    let days = 120, allPrices = [], prices = [], windowStart = 0, windowEnd = 0;
    let selected = -1, lastCurrent, lastHistory, lastMarket, lastCode, shownMarketCode;
    let scenario = null, scenarioCode = null, selectedScale = root.ScaleBar?.DEFAULT_SCALE || '6-12m';
    let hoveredScale = null, hoveredFutureDate = null, scaleInitialized = false;
    let historyMode = false, historyFrame = null, historyCutoffIndex = -1;
    let events = [], focusEvent = null;
    let state = null, staticCode = null, staticGeneration = 0, closed = false;
    const initialParams = new URLSearchParams(root.location?.search || '');
    let pendingInitialAsOf = initialParams.get('asof');
    let pendingInitialFocus = initialParams.get('focus');
    let initialAsOfHandled = !pendingInitialAsOf;
    let initialFocusHandled = !pendingInitialFocus;
    let storage;
    try { storage = root.localStorage; } catch { /* Storage is optional. */ }

    const visibility = root.StockVisibility?.create({ document: doc, storage,
      onVisible: observation => {
        $('first-visible-note').textContent = '本浏览器首次看到此结果：' + observation.first_visible_at_client +
          ' · 本机时钟未校验；不作为真实提前公开发布的证据。';
      },
    });

    function normalizedCode(value) {
      const text = String(value || '').toUpperCase();
      if (/^US_/.test(text)) return text;
      const match = text.match(/(\d{6})$/);
      return match ? match[1] : text;
    }
    function shortDate(value) {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
      return match ? Number(match[2]) + '/' + Number(match[3]) : String(value || '—');
    }
    function visibleLength() {
      return historyMode ? Math.max(0, historyCutoffIndex + 1) : allPrices.length;
    }
    function lastIndexAtOrBefore(bars, date) {
      let index = -1;
      for (let i = 0; i < bars.length && bars[i].date <= date; i++) index = i;
      return index;
    }
    function frameAtOrBefore(date) {
      let frame = null;
      for (const candidate of lastHistory?.frames || []) {
        if (candidate?.asof <= date && (!frame || candidate.asof > frame.asof)) frame = candidate;
      }
      return frame;
    }
    function closuresFor(current = lastCurrent) {
      return new Set(Array.isArray(current?.future_calendar?.closures)
        ? current.future_calendar.closures : []);
    }
    function writeQueryParam(name, value) {
      if (!root.history?.replaceState || !root.location?.href) return;
      const url = new URL(root.location.href);
      if (value == null) url.searchParams.delete(name);
      else url.searchParams.set(name, value);
      root.history.replaceState(null, '', url);
    }
    function historyAvailability(date) {
      if (!lastHistory) return { ok: false, reason: '本股暂无历史补算' };
      if (date > lastCurrent?.asof) return { ok: false, reason: '事件日在模型截止日之后，没有对应补算' };
      const frame = frameAtOrBefore(date);
      if (!frame) return { ok: false, reason: '事件日早于最早一次补算' };
      if (!allPrices.length || frame.asof < allPrices[0].date) {
        return { ok: false, reason: '行情历史不够，无法显示当时 K 线' };
      }
      return { ok: true, reason: '' };
    }
    function updateMarketDate(market, current, code, marketStatus) {
      if (historyMode) {
        $('market-date').textContent = '历史补算截至 ' + historyFrame.asof;
        return;
      }
      const text = [];
      if (market?.asof) text.push('行情截至 ' + market.asof);
      if (current?.asof && normalizedCode(current.symbol) === normalizedCode(code)) {
        text.push('模型截至 ' + current.asof);
      }
      if (market) {
        text.push('未复权');
        text.push(market.source || '日线数据');
      }
      if (marketStatus === 'stale' || market?.stale === true) text.push('缓存日线，刷新未完成');
      $('market-date').textContent = text.join(' · ');
    }
    function renderHistoryBanner() {
      const banner = $('stock-history-banner');
      if (!banner) return;
      banner.hidden = !historyMode;
      if (historyMode) {
        $('stock-history-banner-text').textContent =
          '历史补算 · 截至 ' + historyFrame.asof + '（历史补算，不是当时发布）';
      }
    }
    function renderScaleBar(focusScale) {
      const container = $('stock-scales');
      if (!container) return;
      const scaleNote = $('stock-scale-note');
      const calendarNote = $('stock-calendar-note');
      if (historyMode) {
        container.hidden = true;
        if (scaleNote) scaleNote.hidden = true;
        if (calendarNote) calendarNote.hidden = true;
        return;
      }
      if (!scenario) {
        container.hidden = true;
        container.replaceChildren();
        if (scaleNote) scaleNote.hidden = true;
        if (calendarNote) calendarNote.hidden = true;
        return;
      }
      const focusedScale = focusScale || doc.activeElement?.dataset?.scale;
      const enabled = scenario.states.filter(state => state.selectable);
      const tabStopScale = enabled.some(state => state.scale === selectedScale)
        ? selectedScale : enabled[0]?.scale;
      const buttons = scenario.states.map(state => {
        const window = scenario.windows.find(item => item.scale === state.scale);
        const status = !state.selectable ? '无证据'
          : state.hasWindow && window?.q20_date && window?.q80_date
            ? shortDate(window.q20_date) + '–' + shortDate(window.q80_date)
            : '无合格拟合';
        const button = doc.createElement('button');
        button.type = 'button';
        button.className = 'stock-scale-button';
        button.dataset.scale = state.scale;
        button.setAttribute('role', 'radio');
        button.setAttribute('aria-checked', String(state.scale === selectedScale));
        button.setAttribute('aria-label', SCALE_NAMES[state.scale] + ' ' + status);
        button.setAttribute('tabindex', String(state.selectable && state.scale === tabStopScale ? 0 : -1));
        button.disabled = !state.selectable;
        button.textContent = SCALE_NAMES[state.scale] + '\n' + status;
        button.addEventListener('click', () => selectScale(state.scale, true));
        button.addEventListener('pointerenter', () => {
          hoveredScale = state.scale;
          draw();
        });
        button.addEventListener('pointerleave', () => {
          if (hoveredScale === state.scale) {
            hoveredScale = null;
            draw();
          }
        });
        button.addEventListener('keydown', event => {
          const index = enabled.findIndex(item => item.scale === state.scale);
          if (event.key === 'ArrowRight' || event.key === 'ArrowDown' ||
              event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
            if (!enabled.length) return;
            event.preventDefault();
            const direction = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1;
            const next = enabled[(index + direction + enabled.length) % enabled.length];
            selectScale(next.scale, true);
          } else if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
            event.preventDefault();
            selectScale(state.scale, true);
          }
        });
        return button;
      });
      container.replaceChildren(...buttons);
      container.hidden = false;
      if (focusedScale) {
        const target = container.querySelector('[data-scale="' + focusedScale + '"]');
        target?.focus();
      }
      if (scaleNote) {
        scaleNote.hidden = false;
        scaleNote.textContent = scenario.states.find(state => state.scale === selectedScale)?.hasWindow
          ? '情景区间是未校准的时间区间，不是顶部日期；只有 6–12 月、12–24 月有开发段证据。'
          : '该尺度本次无合格拟合；这不代表风险较低。';
      }
      if (calendarNote) {
        calendarNote.hidden = !scenario.missingCalendar;
        calendarNote.textContent = scenario.missingCalendar
          ? '该结果未附休市日表，未来日期按工作日估算'
          : '';
      }
    }
    function writeScaleQuery(scale) {
      if (!root.history?.replaceState || !root.location?.href) return;
      const url = new URL(root.location.href);
      url.searchParams.set('scale', scale);
      root.history.replaceState(null, '', url);
    }
    function selectScale(scale, focus = false) {
      if (historyMode || !scenario || !scenario.states.some(state => state.scale === scale && state.selectable)) return;
      selectedScale = scale;
      const band = scenario.bands.find(item => item.scale === scale);
      const future = root.StockChartWindow.futureSlots(
        allPrices.length, scenario.bands, windowEnd === allPrices.length,
      );
      const visibleEnd = windowEnd + future;
      if (band && (band.hi < windowStart || band.lo >= visibleEnd)) {
        const span = Math.max(1, windowEnd - windowStart);
        windowEnd = allPrices.length;
        windowStart = Math.max(0, windowEnd - span);
        setWindow(windowStart, windowEnd, selected);
      }
      renderScaleBar(focus ? scale : undefined);
      updateChartAriaLabel();
      draw();
      writeScaleQuery(scale);
      options.onScaleSelected?.(scale);
    }
    function historyScenario(frame, current) {
      const calendar = current?.future_calendar;
      const closures = closuresFor(current);
      const evidence = lastHistory?.evidence || lastHistory?.evidence_levels?.scenarios;
      const hiddenEvidence = !evidence || typeof evidence !== 'string' || evidence === 'none'
        || evidence.startsWith('fail') || evidence === 'dev_only' || evidence === 'dev_failed';
      const bands = hiddenEvidence ? [] : (frame.scenarios || [])
        .filter(item => typeof item?.q20_date === 'string' && typeof item?.q80_date === 'string')
        .map((item, index) => {
          const first = root.CPTradingDays.idxOf(allPrices, item.q20_date, closures);
          const last = root.CPTradingDays.idxOf(allPrices, item.q80_date, closures);
          return {
            scale: 'history-' + index,
            lo: Math.min(first, last),
            hi: Math.max(first, last),
            q20_date: item.q20_date,
            q80_date: item.q80_date,
          };
        });
      return { history: true, frame, closures, bands, missingCalendar: !calendar || typeof calendar !== 'object' };
    }
    function updateScenario(next) {
      if (historyMode) {
        scenario = historyScenario(historyFrame, next.current);
        renderScaleBar();
        updateChartAriaLabel();
        draw();
        return;
      }
      const code = normalizedCode(next.code);
      if (scenarioCode !== code) {
        scenarioCode = code;
        scaleInitialized = false;
        selectedScale = root.ScaleBar?.DEFAULT_SCALE || '6-12m';
      }
      const current = next.current;
      const market = next.market;
      const currentCode = normalizedCode(current?.symbol);
      const marketCode = normalizedCode(market?.code || next.code);
      if (!root.ScaleBar || !root.CPTradingDays || !market ||
          !current || !code || currentCode !== code || marketCode !== code || shownMarketCode !== code) {
        scenario = null;
        hoveredScale = null;
        renderScaleBar();
        updateChartAriaLabel();
        draw();
        return;
      }
      const top = current.top || {};
      const confidence = top.lppls_confidence || {};
      const windows = Array.isArray(top.scale_windows) ? top.scale_windows : [];
      const states = root.ScaleBar.classify(confidence.scale_evidence, confidence, windows);
      if (!scaleInitialized) {
        const requested = new URLSearchParams(root.location.search).get('scale');
        selectedScale = root.ScaleBar.parseHash(
          'scale=' + encodeURIComponent(requested || ''), states,
        );
        scaleInitialized = true;
      } else if (!states.some(state => state.scale === selectedScale && state.selectable)) {
        selectedScale = root.ScaleBar.DEFAULT_SCALE;
      }
      const calendar = current.future_calendar;
      const closures = new Set(Array.isArray(calendar?.closures) ? calendar.closures : []);
      const bands = root.StockChartWindow.mapScenarioBands(allPrices, windows, states, closures);
      scenario = {
        current,
        states,
        windows,
        closures,
        bands,
        missingCalendar: !calendar || typeof calendar !== 'object',
      };
      renderScaleBar();
      updateChartAriaLabel();
      draw();
    }
    function updateChartAriaLabel() {
      const canvas = $('market-plot');
      if (!canvas) return;
      if (historyMode) {
        canvas.setAttribute('aria-label', '历史补算截至 ' + historyFrame.asof + ' 的未复权日K线和成交量');
        return;
      }
      const band = scenario?.bands.find(item => item.scale === selectedScale);
      const summary = band
        ? '情景区间：' + SCALE_NAMES[band.scale] + ' ' + band.q20_date + ' 至 ' + band.q80_date + '（未校准）'
        : '本次无合格情景区间';
      canvas.setAttribute('aria-label',
        '未复权日K线和成交量；使用下方日期滑块逐日查看开高低收及成交量；' + summary);
    }
    function setEvents(items) {
      events = Array.isArray(items) ? items.filter(item =>
        item && typeof item.id === 'string' && typeof item.date === 'string') : [];
      draw();
    }
    function focusDate(date, eventId) {
      if (!allPrices.length || date < allPrices[0].date) {
        return { ok: false, reason: '行情历史不够，图上无此日期' };
      }
      if (historyMode && date > historyFrame.asof) {
        return { ok: false, reason: '该日期在补算截止日之后，返回最新后可查看' };
      }
      const closures = scenario?.closures || closuresFor();
      const index = root.CPTradingDays.idxOf(allPrices, date, closures);
      if (index < visibleLength()) {
        const span = Math.max(1, windowEnd - windowStart);
        const end = visibleLength();
        const start = clamp(index - Math.floor(span / 2), 0, Math.max(0, end - span));
        focusEvent = { date, eventId };
        setWindow(start, Math.min(end, start + span), index);
      } else {
        const span = Math.max(1, windowEnd - windowStart);
        const end = visibleLength();
        setWindow(Math.max(0, end - span), end, selected);
        const future = currentFutureSlots();
        if (index >= windowEnd + future) return { ok: false, reason: '该日期超出图上范围' };
        focusEvent = { date, eventId };
        hoveredFutureDate = date;
        draw();
      }
      writeQueryParam('focus', date);
      return { ok: true };
    }
    function activateHistory(frame, eventDate, eventId) {
      const cutoffIndex = lastIndexAtOrBefore(allPrices, frame.asof);
      if (cutoffIndex < 0) return { ok: false, reason: '行情历史不够，无法显示当时 K 线' };
      const span = Math.max(1, windowEnd - windowStart);
      historyMode = true;
      historyFrame = frame;
      historyCutoffIndex = cutoffIndex;
      focusEvent = null;
      scenario = historyScenario(frame, lastCurrent);
      renderHistoryBanner();
      renderScaleBar();
      updateChartAriaLabel();
      updateMarketDate(state?.market, state?.current, state?.code, state?.marketStatus);
      const end = cutoffIndex + 1;
      setWindow(Math.max(0, end - span), end, end - 1);
      writeQueryParam('asof', frame.asof);
      if (eventDate && eventDate <= frame.asof) focusDate(eventDate, eventId);
      return { ok: true };
    }
    function enterHistory(eventDate, eventId) {
      const available = historyAvailability(eventDate);
      if (!available.ok) return available;
      return activateHistory(frameAtOrBefore(eventDate), eventDate, eventId);
    }
    function exitHistory() {
      if (!historyMode) return { ok: true };
      const span = Math.max(1, windowEnd - windowStart);
      historyMode = false;
      historyFrame = null;
      historyCutoffIndex = -1;
      renderHistoryBanner();
      writeQueryParam('asof', null);
      updateScenario(state || {});
      updateMarketDate(state?.market, state?.current, state?.code, state?.marketStatus);
      const end = allPrices.length;
      setWindow(Math.max(0, end - span), end, selected);
      return { ok: true };
    }
    function applyInitialUrl(next, history) {
      if (!initialAsOfHandled && next.market && next.current &&
          (history || next.history || next.historyStatus !== 'loading')) {
        const frame = history?.frames?.find(item => item.asof === pendingInitialAsOf);
        initialAsOfHandled = true;
        if (frame && lastIndexAtOrBefore(allPrices, frame.asof) >= 0) activateHistory(frame, null, null);
        else writeQueryParam('asof', null);
      }
      if (!initialFocusHandled && next.market && initialAsOfHandled) {
        initialFocusHandled = true;
        focusDate(pendingInitialFocus, null);
      }
    }

    function readout() {
      if (hoveredFutureDate) {
        for (const key of ['close', 'open', 'high', 'low']) $('quote-' + key).textContent = '—';
        $('quote-selected-date').textContent = hoveredFutureDate + ' · 未来交易日，无行情';
        $('quote-readout').textContent = hoveredFutureDate + ' · 未来交易日，无行情';
        return;
      }
      const bar = allPrices[selected];
      if (!bar) {
        $('quote-selected-date').textContent = '';
        $('quote-readout').textContent = '';
        for (const key of ['close', 'open', 'high', 'low']) $('quote-' + key).textContent = '—';
        return;
      }
      for (const key of ['close', 'open', 'high', 'low']) $('quote-' + key).textContent = number(bar[key]);
      $('quote-selected-date').textContent = bar.date + (selected === visibleLength() - 1
        ? historyMode ? '（补算截止）' : '（最新）' : '');
      $('quote-readout').textContent = bar.date + '  开 ' + number(bar.open) +
        '  高 ' + number(bar.high) + '  低 ' + number(bar.low) + '  收 ' + number(bar.close) + '  量 ' + number(bar.volume) + '（供应商原始单位）';
      $('quote-date').setAttribute('aria-valuetext', bar.date + '，收盘 ' + number(bar.close));
    }
    function setRangePreset(button) {
      for (const other of doc.querySelectorAll('[data-days]')) {
        other.setAttribute('aria-pressed', String(other === button));
      }
      $('range-mode').textContent = button ? button.textContent : '自定义';
    }
    function setWindow(start, end, nextSelected = selected, custom = false) {
      const bounds = normalizedWindow(start, end, visibleLength());
      const changed = bounds.start !== windowStart || bounds.end !== windowEnd;
      windowStart = bounds.start;
      windowEnd = bounds.end;
      hoveredFutureDate = null;
      prices = allPrices.slice(windowStart, windowEnd);
      selected = prices.length
        ? clamp(Number.isFinite(Number(nextSelected)) ? Math.round(Number(nextSelected)) : windowStart, windowStart, windowEnd - 1)
        : -1;
      const slider = $('quote-date');
      slider.min = String(windowStart);
      slider.max = String(Math.max(windowStart, windowEnd - 1));
      slider.value = String(Math.max(0, selected));
      if (custom && changed) setRangePreset(null);
      if (prices.length) draw();
      else readout();
    }
    function draw() {
      const canvas = $('market-plot');
      if (canvas.hidden || !prices.length) return;
      const width = canvas.clientWidth, height = canvas.clientHeight;
      if (!width || !height) return;
      const fontFamily = root.getComputedStyle?.(doc.body)?.fontFamily || 'sans-serif';
      const cjkFont = '11px ' + fontFamily;
      const ratio = Math.min(root.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
      const ctx = canvas.getContext('2d');
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      const left = 10, right = 58, top = 20, bottom = 32;
      const low = Math.min(...prices.map(x => x.low)), high = Math.max(...prices.map(x => x.high));
      const pad = Math.max((high - low) * .12, Math.abs(high) * .01, .01);
      const min = low - pad, max = high + pad;
      const plotWidth = Math.max(1, width - left - right);
      const future = currentFutureSlots();
      const domain = Math.max(1, root.StockChartWindow.domainSlots(windowStart, windowEnd, future));
      const candleWidth = Math.max(.8, Math.min(9, plotWidth / domain * .65));
      const xEdge = index => left + (index - windowStart) / domain * plotWidth;
      const x = index => left + (index - windowStart + .5) / domain * plotWidth;
      const priceBottom = height * .69, volumeTop = height * .77, volumeBottom = height - bottom;
      const maxVolume = Math.max(1, ...prices.map(bar => bar.volume));
      const y = p => top + (max - p) / (max - min) * (priceBottom - top);
      ctx.clearRect(0, 0, width, height); ctx.lineWidth = 1; ctx.textAlign = 'left';
      if (future) {
        const divider = xEdge(windowEnd);
        ctx.fillStyle = '#F8FAFC';
        ctx.fillRect(divider, top, Math.max(0, width - right - divider), height - top - bottom);
      }
      ctx.font = '11px Consolas, monospace';
      for (let i = 0; i <= 4; i++) {
        const p = min + (max - min) * i / 4;
        ctx.strokeStyle = '#E3E7EE'; ctx.beginPath(); ctx.moveTo(left, y(p)); ctx.lineTo(width - right, y(p)); ctx.stroke();
        ctx.fillStyle = '#6A6D78'; ctx.fillText(number(p), width - right + 8, y(p) + 4);
      }
      ctx.font = cjkFont;
      ctx.fillStyle = '#6A6D78'; ctx.fillText('成交量', left, volumeTop - 6);
      const bandLabels = [];
      for (const band of scenario?.bands || []) {
        const first = Math.max(windowStart, band.lo);
        const afterLast = Math.min(windowEnd + future, band.hi + 1);
        if (afterLast <= first) continue;
        const x1 = xEdge(first), x2 = xEdge(afterLast);
        const selectedBand = historyMode || band.scale === selectedScale;
        const hoveredBand = !historyMode && band.scale === hoveredScale;
        ctx.fillStyle = selectedBand ? 'rgba(31,95,214,.16)'
          : hoveredBand ? 'rgba(31,95,214,.10)' : 'rgba(31,95,214,.045)';
        ctx.fillRect(x1, top, x2 - x1, priceBottom - top);
        ctx.strokeStyle = selectedBand ? '#1F5FD6'
          : hoveredBand ? 'rgba(31,95,214,.65)' : 'rgba(31,95,214,.25)';
        ctx.lineWidth = selectedBand ? 2 : hoveredBand ? 1.5 : 1;
        ctx.beginPath();
        ctx.moveTo(x1, top); ctx.lineTo(x2, top);
        ctx.lineTo(x2, priceBottom); ctx.lineTo(x1, priceBottom);
        ctx.lineTo(x1, top); ctx.stroke();
        if (selectedBand) {
          bandLabels.push({ band, x1, x2 });
        }
      }
      for (const [i, bar] of prices.entries()) {
        const globalIndex = windowStart + i;
        ctx.strokeStyle = ctx.fillStyle = bar.close >= bar.open ? '#D6303A' : '#11845A';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x(globalIndex), y(bar.high)); ctx.lineTo(x(globalIndex), y(bar.low)); ctx.stroke();
        ctx.fillRect(x(globalIndex) - candleWidth / 2, Math.min(y(bar.open), y(bar.close)),
          candleWidth, Math.max(1, Math.abs(y(bar.open) - y(bar.close))));
        const volumeHeight = bar.volume / maxVolume * (volumeBottom - volumeTop);
        ctx.globalAlpha = .55;
        ctx.fillRect(x(globalIndex) - candleWidth / 2, volumeBottom - volumeHeight, candleWidth, volumeHeight);
        ctx.globalAlpha = 1;
      }
      const selectedVisible = selected - windowStart;
      if (prices[selectedVisible]) {
        ctx.lineWidth = 1; ctx.strokeStyle = '#9AA1AD'; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(x(selected), top); ctx.lineTo(x(selected), height - bottom); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = '#131722'; ctx.beginPath(); ctx.arc(x(selected), y(prices[selectedVisible].close), 3, 0, Math.PI * 2); ctx.fill();
      }
      for (const { band, x1, x2 } of bandLabels) {
        const fullLabel = historyMode
          ? '补算情景 ' + shortDate(band.q20_date) + '–' + shortDate(band.q80_date)
          : SCALE_NAMES[band.scale] + ' 情景区间 ' +
            shortDate(band.q20_date) + '–' + shortDate(band.q80_date);
        const shortLabel = historyMode
          ? '补算情景 ' + shortDate(band.q20_date) + '–' + shortDate(band.q80_date)
          : shortDate(band.q20_date) + '–' + shortDate(band.q80_date);
        const plotRight = width - right;
        const labelX = Math.max(left, x1 + 3);
        const labelY = top + 13;
        let label = fullLabel;
        let labelWidth;
        let textX = labelX;
        let textAlign = 'left';
        ctx.font = cjkFont;
        labelWidth = ctx.measureText(label).width;
        if (labelX + labelWidth > plotRight) {
          label = shortLabel;
          labelWidth = ctx.measureText(label).width;
          textX = Math.max(left, Math.min(x2, plotRight) - 3);
          textAlign = 'right';
        }
        const textLeft = textAlign === 'right' ? textX - labelWidth : textX;
        const backgroundLeft = Math.max(left, textLeft - 3);
        const backgroundRight = Math.min(plotRight, textLeft + labelWidth + 3);
        ctx.fillStyle = 'rgba(255,255,255,.88)';
        ctx.fillRect(backgroundLeft, labelY - 12,
          Math.max(0, backgroundRight - backgroundLeft), 16);
        ctx.fillStyle = '#1F5FD6';
        ctx.textAlign = textAlign;
        ctx.fillText(label, textX, labelY);
        ctx.textAlign = 'left';
      }
      const cutoffDate = historyFrame?.asof;
      for (const event of events) {
        if (event.date < allPrices[0]?.date) continue;
        if (historyMode && event.date > cutoffDate) continue;
        const index = root.CPTradingDays.idxOf(allPrices, event.date, scenario?.closures);
        if (index < windowStart || index >= windowEnd + future) continue;
        const focused = focusEvent &&
          (focusEvent.eventId ? event.id === focusEvent.eventId : event.date === focusEvent.date);
        const markerX = x(index), markerY = priceBottom - 1;
        ctx.fillStyle = focused ? '#1F5FD6' : '#9AA1AD';
        ctx.beginPath();
        ctx.moveTo(markerX, markerY - 6);
        ctx.lineTo(markerX - 3, markerY);
        ctx.lineTo(markerX + 3, markerY);
        ctx.fill();
      }
      ctx.fillStyle = '#6A6D78';
      ctx.font = '11px Consolas, monospace';
      ctx.textAlign = 'left';
      ctx.fillText(prices[0].date, left, height - 9);
      const endLabelX = future ? xEdge(windowEnd) - 3 : width - right;
      ctx.textAlign = 'right'; ctx.fillText(prices[prices.length - 1].date, endLabelX, height - 9); ctx.textAlign = 'left';
      if (future) {
        const divider = xEdge(windowEnd);
        ctx.strokeStyle = '#AAB3C2'; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(divider, top); ctx.lineTo(divider, height - bottom); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = '#7B8492'; ctx.font = cjkFont;
        ctx.textAlign = 'left';
        ctx.fillText('未来交易日 · 无行情', divider + 4, volumeTop + 12,
          Math.max(0, width - right - divider - 6));
      }
      readout();
    }
    function showMarket(market, code, preserve = false) {
      const previous = {
        bars: allPrices,
        start: windowStart,
        end: windowEnd,
        startDate: allPrices[windowStart]?.date,
        endDate: allPrices[windowEnd - 1]?.date,
        selectedDate: allPrices[selected]?.date,
      };
      const previousSpan = Math.max(1, previous.end - previous.start);
      const wasAtLatest = previous.end === previous.bars.length;
      const bars = market?.price || [];
      allPrices = bars.filter(bar => bar && typeof bar.date === 'string' &&
        ['open', 'high', 'low', 'close', 'volume'].every(key => Number.isFinite(bar[key])) &&
        Math.min(bar.open, bar.high, bar.low, bar.close) > 0 && bar.volume >= 0 &&
        bar.high >= Math.max(bar.open, bar.close, bar.low) && bar.low <= Math.min(bar.open, bar.close));
      const exists = allPrices.length > 0;
      shownMarketCode = exists ? normalizedCode(code || market?.code) : null;
      $('market-stats').hidden = !exists;
      $('market-plot').hidden = !exists;
      $('date-control').hidden = !exists;
      $('market-empty').hidden = exists;
      $('quote-selected-date').hidden = !exists;
      if (exists) {
        if (historyMode) {
          historyCutoffIndex = lastIndexAtOrBefore(allPrices, historyFrame.asof);
          const end = Math.min(previous.end, historyCutoffIndex + 1);
          const start = Math.min(previous.start, Math.max(0, end - previousSpan));
          setWindow(start, end, selected);
        } else if (preserve && previous.bars.length && !wasAtLatest) {
          const findDate = (date, fallback) => {
            if (!date) return fallback;
            const exact = allPrices.findIndex(bar => bar.date === date);
            if (exact >= 0) return exact;
            const next = allPrices.findIndex(bar => bar.date > date);
            return next >= 0 ? next : allPrices.length - 1;
          };
          const start = findDate(previous.startDate, Math.max(0, allPrices.length - days));
          const last = findDate(previous.endDate, Math.min(allPrices.length - 1, start + previousSpan - 1));
          const selectedIndex = findDate(previous.selectedDate, last);
          windowStart = Math.min(start, last);
          windowEnd = Math.max(windowStart + 1, last + 1);
          setWindow(windowStart, windowEnd, selectedIndex);
        } else {
          windowEnd = allPrices.length;
          windowStart = Math.max(0, windowEnd - previousSpan);
          if (!preserve || !previous.bars.length) windowStart = Math.max(0, windowEnd - days);
          setWindow(windowStart, windowEnd, windowEnd - 1);
        }
      } else {
        $('market-date').textContent = '';
        setWindow(0, 0, -1);
      }
      setRangePreset([...doc.querySelectorAll('[data-days]')].find(button => Number(button.dataset.days) === days));
      $('market-zoom-hint').hidden = !exists;
    }
    function update(next) {
      if (staticCode) return;
      state = next;
      const changed = lastCode !== next.code;
      if (changed) {
        if (historyMode) {
          historyMode = false; historyFrame = null; historyCutoffIndex = -1;
          writeQueryParam('asof', null);
          focusEvent = null;
          renderHistoryBanner();
        }
        lastCode = next.code; lastCurrent = null; lastHistory = null; lastMarket = null;
        $('results').hidden = true; $('asof').textContent = '—'; $('first-visible-note').textContent = ''; visibility?.observe(null, null); showMarket(null, next.code, false);
      }
      $('market-panel').hidden = false; $('task-stages').hidden = false;
      $('market-name').textContent = (next.market?.name || next.current?.name || '股票') + ' · ' + next.code;
      if (next.market && next.market !== lastMarket) {
        lastMarket = next.market;
        showMarket(next.market, next.code, !changed);
        if (next.current && next.current === lastCurrent) options.renderMarket?.(next.current, next.market);
      }
      if (!next.market) $('market-empty').textContent = next.issues.market ||
        '正在读取已收盘日线；模型计算不会阻塞行情。';
      const history = root.StockSession.compatible(next.current, next.history) ? next.history : null;
      if (next.current && (lastCurrent !== next.current || lastHistory !== history)) {
        lastCurrent = next.current; lastHistory = history;
        options.renderResult(next.current, history, next.market);
        $('first-visible-note').textContent = '尚未记录此结果在本浏览器的可见时间。';
        visibility?.observe($('summary').querySelector('.top') || $('risk'), next.current);
        if (next.history && !history) $('history-note').textContent =
          '已有历史回放与当前模型版本尚未匹配，可重新生成；当前分析仍可查看。';
      }
      updateScenario(next);
      updateMarketDate(next.market, next.current, next.code, next.marketStatus);
      applyInitialUrl(next, history);
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
    $('stock-history-exit')?.addEventListener('click', exitHistory);
    for (const button of doc.querySelectorAll('[data-days]')) button.addEventListener('click', () => {
      days = Number(button.dataset.days);
      setRangePreset(button);
      const end = visibleLength();
      setWindow(Math.max(0, end - days), end, end - 1);
    });
    $('quote-date').addEventListener('input', event => {
      selected = clamp(Number(event.target.value), windowStart, windowEnd - 1);
      draw();
    });
    const canvas = $('market-plot');
    const pointers = new Map();
    const touchStarts = new Map();
    let drag = null, pinch = null, touchPinching = false;
    function currentFutureSlots() {
      const atLatest = windowEnd === visibleLength();
      const projected = scenario
        ? root.StockChartWindow.futureSlots(visibleLength(), scenario.bands, atLatest)
        : 0;
      const replayFuture = historyMode && atLatest ? Math.max(0, allPrices.length - visibleLength()) : 0;
      return Math.max(projected, replayFuture);
    }
    function plotMetrics(clientX) {
      const rect = canvas.getBoundingClientRect();
      const plotWidth = Math.max(rect.width - 68, 1);
      const future = currentFutureSlots();
      const domain = Math.max(1, root.StockChartWindow.domainSlots(windowStart, windowEnd, future));
      const x = clientX - rect.left - 10;
      const inPlot = x >= 0 && x <= plotWidth;
      const slot = clamp(x / plotWidth * domain, 0, domain);
      return {
        rect,
        plotWidth,
        anchor: clamp(slot / Math.max(1, windowEnd - windowStart), 0, 1),
        slot,
        domain,
        future,
        inPlot,
      };
    }
    function selectAt(clientX) {
      if (!prices.length) return;
      const { slot } = plotMetrics(clientX);
      selected = windowStart + clamp(Math.floor(slot), 0, prices.length - 1);
      hoveredFutureDate = null;
      $('quote-date').value = String(selected);
      draw();
    }
    function inspectAt(clientX) {
      if (!prices.length) return;
      const point = plotMetrics(clientX);
      if (point.inPlot && point.future && point.slot >= prices.length) {
        const offset = Math.min(point.future - 1, Math.floor(point.slot - prices.length));
        const index = windowEnd + offset;
        hoveredFutureDate = root.CPTradingDays.dateAt(allPrices, index, scenario?.closures);
        readout();
      } else {
        hoveredFutureDate = null;
        selectAt(clientX);
      }
    }
    function bandAt(clientX, clientY) {
      if (!scenario?.bands.length) return null;
      const point = plotMetrics(clientX);
      const y = clientY - point.rect.top;
      if (!point.inPlot || y < 20 || y > canvas.clientHeight * .69) return null;
      const position = windowStart + point.slot;
      return scenario.bands
        .filter(band => position >= band.lo && position <= band.hi + 1)
        .sort((a, b) =>
          Math.abs(position - (a.lo + a.hi + 1) / 2) -
          Math.abs(position - (b.lo + b.hi + 1) / 2))[0] || null;
    }
    function activateAt(clientX, clientY) {
      inspectAt(clientX);
      const band = bandAt(clientX, clientY);
      if (band) selectScale(band.scale);
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
        if (!pointers.size) touchPinching = false;
        pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        touchStarts.set(event.pointerId, { x: event.clientX, y: event.clientY });
        canvas.setPointerCapture?.(event.pointerId);
        if (pointers.size === 2) {
          touchPinching = true;
          startPinch();
        }
      } else if ((event.pointerType === 'mouse' || event.pointerType === 'pen') && event.button === 0) {
        drag = { x: event.clientX, start: windowStart, end: windowEnd, moved: false };
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
          const scaled = zoom(pinch.start, pinch.end, visibleLength(), distance / pinch.distance, pinch.anchor);
          const deltaBars = -(midpoint - pinch.midpoint) / pinch.plotWidth * (scaled.end - scaled.start);
          const moved = pan(scaled.start, scaled.end, visibleLength(), deltaBars);
          setWindow(moved.start, moved.end, selected, true);
        } else if (pointers.size === 1) {
          const start = touchStarts.get(event.pointerId);
          if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) {
            touchStarts.set(event.pointerId, null);
          }
          inspectAt(event.clientX);
        }
        return;
      }
      if (event.pointerType !== 'mouse' && event.pointerType !== 'pen') return;
      if (drag && event.buttons) {
        if (Math.abs(drag.x - event.clientX) > 5) drag.moved = true;
        if (drag.moved) {
          const { plotWidth } = plotMetrics(event.clientX);
          const deltaBars = (drag.x - event.clientX) / plotWidth * (drag.end - drag.start);
          const moved = pan(drag.start, drag.end, visibleLength(), deltaBars);
          setWindow(moved.start, moved.end, selected, true);
        }
      } else if (!drag) {
        inspectAt(event.clientX);
      }
    });
    const endPointer = (event, activate) => {
      if (event.pointerType === 'touch') {
        const start = touchStarts.get(event.pointerId);
        if (activate && start && !touchPinching && pointers.size === 1) {
          activateAt(event.clientX, event.clientY);
        }
        pointers.delete(event.pointerId);
        touchStarts.delete(event.pointerId);
        if (pointers.size < 2) pinch = null;
        if (!pointers.size) touchPinching = false;
      } else {
        const previous = drag;
        drag = null;
        if (activate && previous && !previous.moved) activateAt(event.clientX, event.clientY);
      }
    };
    canvas.addEventListener('pointerup', event => endPointer(event, true));
    canvas.addEventListener('pointercancel', event => endPointer(event, false));
    canvas.addEventListener('pointerleave', event => {
      if (event?.pointerType === 'touch') return;
      hoveredFutureDate = null;
      readout();
    });
    canvas.addEventListener('wheel', event => {
      if (!allPrices.length || (!event.ctrlKey && !event.metaKey)) return;
      event.preventDefault();
      const { anchor } = plotMetrics(event.clientX);
      const bounds = zoom(windowStart, windowEnd, visibleLength(), Math.exp(-event.deltaY * .002), anchor);
      setWindow(bounds.start, bounds.end, selected, true);
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
    renderHistoryBanner();
    const initial = new URLSearchParams(root.location.search).get('code');
    if (initial) select(initial);
    return Object.assign(session, { focusDate, historyAvailability, enterHistory, exitHistory, setEvents });
  }
  root.StockView = { mount };
})(window);
