/* Read only the site's published archives through its shared data client. */
(function (root) {
  'use strict';
  const assets = [
    { id: 'sh000001', name: '上证指数', code: '000001', exchange: '上交所', type: '指数' },
    { id: 'sh600519', name: '贵州茅台', code: '600519', exchange: '上交所', type: '股票' },
    { id: 'sh600320', name: '振华重工', code: '600320', exchange: '上交所', type: '股票' },
  ];
  const scaleNames = { '2-4w': '2–4 周', '1-3m': '1–3 月', '3-6m': '3–6 月', '6-12m': '6–12 月', '12-24m': '12–24 月', '2-6y': '2–6 年' };
  const evidenceNames = { dev: '开发段证据', cal: '校准段记录', test: '最终测试段记录', research_candidate: '个股研究候选' };
  const allowed = new Set(['dev', 'cal', 'test', 'research_candidate']);
  const rawQuotePath = 'market/archives/sh600519_2026-11-17.json';
  const recentQuotes = new WeakMap();
  function iso(date) {
    if (typeof date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return false;
    const parsed = new Date(date + 'T00:00:00Z');
    return Number.isFinite(+parsed) && parsed.toISOString().slice(0, 10) === date;
  }

  function barsOf(raw) {
    const ph = raw?.price_history;
    if (!Array.isArray(ph?.dates) || !iso(raw.asof)) return [];
    const rows = new Map();
    ph.dates.forEach((date, i) => {
      if (!iso(date) || date > raw.asof || !Number.isFinite(ph.close?.[i]) || ph.close[i] <= 0) return;
      const row = { date, close: ph.close[i], volume: Number.isFinite(ph.volume?.[i]) && ph.volume[i] >= 0 ? ph.volume[i] : null };
      for (const key of ['open', 'high', 'low']) row[key] = Number.isFinite(ph[key]?.[i]) && ph[key][i] > 0 ? ph[key][i] : null;
      rows.set(date, row);
    });
    return [...rows.values()].sort((a, b) => a.date.localeCompare(b.date));
  }

  function windowRows(rows, asof) {
    const windows = [];
    let withheld = false;
    for (const row of rows) {
      if (row.start == null && row.end == null) continue;
      if (!iso(row.start) || !iso(row.end) || row.start <= asof || row.start >= row.end ||
          !allowed.has(row.level) || !(row.scale in scaleNames)) {
        withheld = true;
        continue;
      }
      windows.push({ start: row.start, end: row.end, label: scaleNames[row.scale] + '拟合', level: row.level });
    }
    return { windows, withheld };
  }

  function historyWindows(history, frame) {
    const rows = [];
    for (const [scale, pair] of Object.entries(frame?.w || {})) {
      if (!pair) continue;
      const level = history.scale_evidence?.[scale] || history.evidence;
      rows.push({ scale, level, start: pair[0], end: pair[1] });
    }
    return windowRows(rows, frame.asof);
  }

  function latestWindows(raw) {
    const top = raw.top || {}, codes = top.lppls_confidence?.scale_evidence || {};
    const rows = (top.scale_windows || []).map(w => {
      const scaleLevel = codes[w.scale];
      // Individual stocks never inherit the index's development validation.
      const level = top.evidence_override && allowed.has(scaleLevel) ? top.evidence_override : scaleLevel;
      return { scale: w.scale, level, start: w.q20_date, end: w.q80_date };
    });
    return windowRows(rows, raw.asof);
  }

  function archiveFrame(dataset, frame, modelPrices) {
    if (!iso(frame?.asof) || !frame.w || !dataset.barsByDate.has(frame.asof)) return false;
    // History closes are rounded to two decimals, OHLC to three. Reject incompatible
    // vintages / adjustment bases rather than put a model over a different price.
    const modelClose = modelPrices.get(frame.asof);
    return Number.isFinite(modelClose) && Number.isFinite(frame.close) && Math.abs(frame.close - modelClose) <= 0.006;
  }

  function quoteBars(asset, quote) {
    if (quote?.symbol !== asset.id || quote.adjustment !== 'none' || quote.frequency !== '1d' ||
        quote.closed_only !== true || !iso(quote.asof) || !Array.isArray(quote.price)) return [];
    const rows = quote.price.filter(bar => iso(bar.date) && bar.date <= quote.asof && Number.isFinite(bar.close) && bar.close > 0);
    return rows.map(bar => ({ date: bar.date, close: bar.close, open: bar.open, high: bar.high, low: bar.low, volume: bar.volume }));
  }

  function decodeSeals(asset, result, issues) {
    const seals = new Map();
    if (asset.type !== '指数' || !result) return seals;
    const list = result.data;
    if (list?.symbol !== asset.id || !Array.isArray(list.records)) {
      issues.push('逐日封存目录暂不可读。');
      return seals;
    }
    for (const entry of list.records) {
      const record = entry?.record;
      const time = entry?.sealed_at;
      if (record?.symbol !== asset.id || !iso(entry.asof) || record.asof !== entry.asof ||
          !record.top || typeof time !== 'string' || !/(?:Z|[+-]\d\d:\d\d)$/i.test(time) ||
          !Number.isFinite(Date.parse(time)) || !/^[a-f0-9]{64}$/.test(entry.sha256) ||
          typeof entry.path !== 'string') continue;
      const bars = barsOf(record);
      if (!bars.length || bars.at(-1).date !== entry.asof) continue;
      seals.set(entry.asof, { ...entry, bars });
    }
    return seals;
  }

  function datasetOf(asset, latest, history, quote, catalog, base) {
    const paths = asset.type === '指数'
      ? { latest: asset.id + '_latest.json', history: asset.id + '_history.json' }
      : { latest: 'stock/' + asset.code + '.json', history: 'stock/' + asset.code + '_history.json' };
    const issues = [];
    function read(record, name, key) {
      if (record?.reason === 'unavailable') issues.push(name + '读取失败，可重试。');
      if (!record?.data) return null;
      if (record.data.symbol !== asset.id || (key === 'latest' && !iso(record.data.asof)) ||
          (key === 'history' && !Array.isArray(record.data.frames))) {
        issues.push(name + '的标的或结构不匹配。');
        return null;
      }
      return record.data;
    }
    const current = read(latest, '当前归档', 'latest'), historic = read(history, '回放归档', 'history');
    const modelBars = barsOf(current);
    const separateQuote = asset.id === 'sh600519';
    const seals = decodeSeals(asset, catalog, issues);
    const allBars = separateQuote ? quoteBars(asset, quote?.data) : modelBars;
    const quoteSource = base + (separateQuote ? rawQuotePath : paths.latest);
    const modelPrices = new Map(modelBars.map(bar => [bar.date, bar.close]));
    const dataset = { asset, current, historic, allBars, barsByDate: new Map(allBars.map(bar => [bar.date, bar])),
      frames: new Map(), source: base + paths.latest, historySource: base + paths.history,
      quoteSource, seals, separateQuote, issues,
      uncovered: latest?.reason === 'unpublished' && history?.reason === 'unpublished', exampleDate: null };
    const recentQuote = separateQuote && recentQuotes.get(root.LPPL);
    if (recentQuote && recentQuote.asof > (allBars.at(-1)?.date || '')) dataset.currentQuote = recentQuote;
    dataset.researchPending = !latest || !history || (asset.type === '指数' && !catalog);
    if ((separateQuote ? quote : current) && !allBars.length) issues.push('行情归档缺少可读取的日线，可重试。');
    if (historic) {
      for (const frame of historic.frames) {
        if (archiveFrame(dataset, frame, modelPrices)) dataset.frames.set(frame.asof, frame);
      }
      if (current && allBars.length && historic.frames.length && !dataset.frames.size) issues.push('历史记录与本次行情日期或模型输入价格口径不匹配。');
    }
    dataset.dates = [...new Set([...seals.keys(), ...dataset.frames.keys(), current?.asof, allBars.at(-1)?.date].filter(Boolean))].sort().reverse();
    dataset.exampleDate = dataset.dates.find(date => date !== current?.asof && date < allBars.at(-1)?.date &&
      dataset.frames.has(date) && historyWindows(historic, dataset.frames.get(date)).windows.length) || null;
    return dataset;
  }

  async function load(id, onPartial) {
    const asset = assets.find(item => item.id === id);
    if (!asset) throw new Error('未知标的');
    const api = root.LPPL, base = api.BASE;
    const prefix = asset.type === '指数' ? asset.id : 'stock/' + asset.code;
    const latestPath = prefix + (asset.type === '指数' ? '_latest.json' : '.json');
    let latest, history, quote, seals;
    const update = () => {
      if (onPartial && (latest?.data || quote?.data || seals?.data)) onPartial(datasetOf(asset, latest, history, quote, seals, base));
    };
    const latestTask = api.fetchResult(latestPath).then(result => { latest = result; update(); });
    const historyTask = api.fetchResult(prefix + '_history.json').then(result => { history = result; update(); });
    const quoteTask = asset.id === 'sh600519' && api.fetchResult(rawQuotePath).then(result => { quote = result; update(); });
    const sealTask = asset.type === '指数' && api.fetchResult('guanshi/' + id + '_seals.json').then(result => { seals = result; update(); });
    await Promise.all([latestTask, historyTask, quoteTask, sealTask]);
    return datasetOf(asset, latest, history, quote, seals, base);
  }

  async function refreshQuote(dataset, now = Date.now()) {
    const keep = (status, message) => ({ dataset, status, message });
    if (!dataset.separateQuote) return keep('unavailable', '该标的没有按需日线接口。');
    try {
      const api = root.LPPL.stock;
      const q = await api.market(dataset.asset.code);
      if (q?.stale || q?.stale_reason) return keep('unchanged', '行情服务返回了过期缓存，已保留现有日线。');
      const stamp = Date.parse(q?.generated_at);
      // Use the same China close + 30-minute settlement policy as the quote endpoint.
      const lastClosedDate = clock => new Date(clock - 7.5 * 3600000).toISOString().slice(0, 10);
      if (q?.code !== dataset.asset.code || q?.source !== 'tencent_fqkline' || q?.volume_unit !== 'vendor_native' ||
          q?.model_computed !== false || q?.evidence !== 'observed' || !iso(q.cutoff) || !iso(q.asof) ||
          !Number.isFinite(stamp) || stamp > now || q.asof > q.cutoff || q.cutoff > lastClosedDate(stamp) ||
          !Array.isArray(q.price)) return keep('unavailable', '日线来源、数据口径或截止时间未通过核对，已保留现有行情。');
      const bars = quoteBars(dataset.asset, q);
      if (!bars.length || bars.length !== q.price.length || bars.at(-1).date !== q.asof ||
          bars.some((bar, i) => (i && bars[i - 1].date >= bar.date) ||
            [0, 6].includes(new Date(bar.date + 'T00:00:00Z').getUTCDay()) ||
            ![bar.open, bar.high, bar.low, bar.close, bar.volume].every(Number.isFinite) ||
            bar.low <= 0 || bar.volume < 0 || bar.high < Math.max(bar.open, bar.close, bar.low) ||
            bar.low > Math.min(bar.open, bar.close))) return keep('unavailable', '日线记录不完整，已保留现有行情。');
      const previous = [dataset.currentQuote?.asof, dataset.allBars.at(-1)?.date, recentQuotes.get(root.LPPL)?.asof].filter(Boolean).sort().at(-1);
      if (previous && q.asof <= previous) return keep('unchanged', '已读取的行情截至 ' + previous + '，暂未取得更晚的收盘日线。');
      const source = api.api() + '/market?code=' + encodeURIComponent(dataset.asset.code);
      const currentQuote = { asof: q.asof, bars, source };
      recentQuotes.set(root.LPPL, currentQuote);
      return { dataset: { ...dataset, currentQuote }, status: 'updated',
        message: '已读取截至 ' + q.asof + ' 的不复权收盘日线。' };
    } catch {
      return keep('unavailable', '行情服务暂不可用，可继续查看原有档案。');
    }
  }

  function view(dataset, requested, revealLater = false) {
    const { asset, current, historic, exampleDate, issues } = dataset;
    const dates = dataset.currentQuote ? [...new Set([dataset.currentQuote.asof, ...dataset.dates])].sort().reverse() : dataset.dates;
    const asof = iso(requested) ? requested : dates[0] || null;
    // A manual refresh is a session-local current view. Historical charts, including
    // their later-price reveal, keep the original files and revisions.
    const live = dataset.currentQuote && (!requested || asof === dataset.currentQuote.asof && !dataset.dates.includes(asof))
      ? dataset.currentQuote : null;
    const allBars = live?.bars || dataset.allBars;
    const seal = dataset.seals.get(asof);
    const currentMatch = current && (asof === current.asof || (live || asof === dataset.dates[0]) && asof > current.asof);
    const snapshot = seal?.record || (currentMatch ? current : null);
    const frame = snapshot ? null : dataset.frames.get(asof);
    const record = snapshot || (frame ? historic : null);
    // Replay the original price vintage. Each later segment comes from exactly
    // one overlapping archive. October's index native volume can differ 100x
    // from November's native volume on the same day, despite equal prices.
    let laterBars = allBars, laterSource = live?.source || dataset.quoteSource;
    if (seal) {
      const alternatives = [...dataset.seals.values()].map(s => ({ bars: s.bars, source: s.path }));
      alternatives.push({ bars: allBars, source: dataset.quoteSource });
      const later = alternatives.filter(s => s.bars.at(-1)?.date > asof && s.bars.some(b => b.date === asof))
        .sort((a, b) => b.bars.at(-1).date.localeCompare(a.bars.at(-1).date))[0];
      laterBars = later?.bars || [];
      laterSource = later?.source || null;
    }
    const hasLater = !!asof && laterBars.some(bar => bar.date > asof);
    const isStock = asset.type === '股票';
    const hfq = /(?:^|_)hfq(?:_|$)/.test(current?.data_version || '');
    const knownBars = seal?.bars || (asof ? allBars.filter(bar => bar.date <= asof) : []);
    const laterBoundaryVolume = seal && laterBars.find(b => b.date === asof)?.volume;
    const originalBoundaryVolume = seal?.bars.at(-1)?.volume;
    const incompatibleVolume = Number.isFinite(originalBoundaryVolume) && Number.isFinite(laterBoundaryVolume) &&
      laterBoundaryVolume !== originalBoundaryVolume;
    const laterSegment = hasLater && revealLater ? laterBars.filter(bar => bar.date > asof) : [];
    const result = { asset, asof, dates, exampleDate, hasLater, issues, modelAsOf: snapshot?.asof || frame?.asof || null,
      bars: laterSegment.length ? [...knownBars, ...laterSegment.map(bar => incompatibleVolume ? { ...bar, volume: null } : bar)] : knownBars,
      sealedAt: seal?.sealed_at || null,
      windows: [], evidence: [], firstVisible: null, modelVersion: record?.model_version || null,
      dataVersion: record?.data_version || null, quoteSource: seal?.path || live?.source || (allBars.length ? dataset.quoteSource : null),
      quoteAsOf: knownBars.at(-1)?.date || null, quoteStatus: live ? '按需读取 · 日线时效未独立核验' : '归档日线',
      laterSource: hasLater ? laterSource : null,
      laterVolumeNote: incompatibleVolume ? '两份归档的重叠日成交量口径存在差异，后续成交量留空。' : '',
      source: seal?.path || (record ? (snapshot ? dataset.source : dataset.historySource) : null),
      priceBasis: dataset.separateQuote ? '不复权收盘日线 · 腾讯行情' : isStock ? (hfq ? '后复权模型输入，非实际成交价' : '模型输入，复权口径未记录') : '指数点位',
      priceUnit: dataset.separateQuote ? '元' : isStock ? (hfq ? '后复权值' : '模型输入值') : '点', volumeUnit: '源单位',
      provenance: seal ? '当日封存' : record ? (snapshot ? '当前归档' : '历史重算') : '无可核对记录' };
    if (!record) {
      result.state = dataset.researchPending ? 'loading' : dataset.uncovered ? 'uncovered' : issues.length && !current ? 'unavailable' : 'no_record';
      result.headline = { loading: '正在读取顶部研究记录…', uncovered: '暂无已归档的顶部研究', unavailable: '研究数据暂未读取', no_record: '该日期没有可核对的研究记录' }[result.state];
      result.evidence.push(result.state === 'loading' ? '正在核对该标的的归档来源。'
        : dataset.uncovered ? '当前归档与历史归档均未发布。' : '没有对应截止日的可用模型记录。');
      return result;
    }
    const bands = snapshot ? latestWindows(snapshot) : historyWindows(historic, frame);
    result.windows = bands.windows;
    const indicators = snapshot?.top?.indicators;
    const counts = indicators ? Object.entries(indicators).filter(([scale]) => scale in scaleNames) : [];
    const computed = counts.filter(([, value]) => value && value.signal_status && value.signal_status !== 'not_computed');
    const noFit = computed.length && computed.every(([, value]) => value.signal_status === 'no_qualified_fit');
    const missing = snapshot ? !snapshot.top || (!counts.length && !snapshot.top.signal_status && !snapshot.top.scale_windows) : false;
    result.state = bands.windows.length ? 'window' : bands.withheld ? 'restricted' : missing ? 'no_record' : 'no_window';
    result.headline = result.state === 'window' ? '有候选顶部时间区间'
      : result.state === 'restricted' ? '现有记录未形成可展示的日期区间'
      : result.state === 'no_record' ? '这份归档缺少顶部研究字段'
      : noFit ? '已计算的 ' + computed.length + ' 个尺度均未形成合格拟合' : '该记录没有给出候选顶部区间';
    if (counts.length) result.evidence.push('已计算 ' + computed.length + ' / ' + counts.length + ' 个拟合尺度。');
    if (bands.windows.length) {
      for (const w of bands.windows) result.evidence.push(w.label + ' · ' + evidenceNames[w.level] + '。');
      const rule = frame ? historic.rule : snapshot?.top?.window?.rule;
      if (typeof rule === 'string' && rule.trim()) result.evidence.push('归档规则：' + rule);
    }
    if (bands.withheld) result.evidence.push('部分原始日期未通过证据、完整区间或未来日期检查。');
    result.evidence.push(isStock ? '个股研究候选，尚未经样本外验证。' : '研究尺度仅描述拟合区间，尚无经验证的阶段顶提醒。');
    if (dataset.separateQuote && hfq) result.evidence.push('图上是未复权真实成交日线，模型使用独立的后复权输入。');
    if (snapshot && snapshot.asof < asof) result.evidence.push('行情已更新至所选日期，现有模型记录仍截至 ' + snapshot.asof + '。');
    if (seal) result.evidence.push('原档封存于 ' + seal.sealed_at + '。封存时点与首次通知送达分别记录。');
    if (frame) result.evidence.push('这是用历史数据重算的记录。行情来自当前存档的数据版本。');
    result.evidence.push('原始记录未提供可核对的首次公开时间。');
    return result;
  }

  const api = { assets, load, view, refreshQuote };
  root.GuanshiData = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
