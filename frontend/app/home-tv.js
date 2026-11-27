/* 临界点 · 首页（TradingView 式）展示逻辑（Open Design 维护）
   - 业务数据只经 window.LPPL 读取（overview / history），不读数据文件、不在前端重算模型。
   - 指数列表、实时报价、自选仍由 home.html 内联脚本负责；本文件只补主图、今日结论与底部卡片，
     并通过 home:rows / home:quotes 事件复用内联脚本已取到的行情，不额外请求。
   - 只展示已发布的首次预警标记与 52 周回撤，不显示精确顶部日期、目标价或任何合成分数。 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root && root.document) {
    root.HomeTV = api;
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', function () { api.mount(root); });
    else api.mount(root);
  }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var DAY = 86400000;
  var WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  var BADGES = {
    sh000001: ['上', '#e03c31'], sh000016: ['50', '#2962ff'], sh000300: ['300', '#00897b'],
    sh000905: ['500', '#f57c00'], sh000688: ['科', '#6a1b9a'], sz399001: ['深', '#0277bd'], sz399006: ['创', '#c2185b'],
  };
  var RANGES = { '52': '近 1 年', '260': '近 5 年', all: '' };
  var RANGE_KEY = 'lppl.home.mainRange';
  var MAIN_SYM = 'sh000001';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function isDate(v) {
    return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) &&
      Number.isFinite(Date.parse(v + 'T00:00:00Z')) && new Date(v + 'T00:00:00Z').toISOString().slice(0, 10) === v;
  }
  function dayValue(v) { return isDate(v) ? Date.parse(v + 'T00:00:00Z') : null; }
  function finite(v) { return v != null && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null; }

  function badgeFor(sym, name) {
    var key = String(sym || '').toLowerCase(), b = BADGES[key];
    if (b) return { text: b[0], color: b[1] };
    var text = String(name || sym || '?').replace(/\s+/g, '').charAt(0) || '?';
    var h = 0, s = String(sym || name || '');
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return { text: text, color: 'hsl(' + h + ',52%,40%)' };
  }

  /* 已发布的周度帧 → [{d, c, a, dd}]，按日期升序；缺日期或收盘的帧跳过 */
  function weeklySeries(history) {
    var frames = history && Array.isArray(history.frames) ? history.frames : [];
    var out = [];
    frames.forEach(function (f) {
      if (!f || !isDate(f.asof)) return;
      var c = finite(f.close);
      if (c == null || c <= 0) return;
      out.push({ d: f.asof, c: c, a: f.first_alert_flag === true, dd: finite(f.dd_52w) });
    });
    out.sort(function (a, b) { return a.d < b.d ? -1 : a.d > b.d ? 1 : 0; });
    return out;
  }
  function normRange(v) { var s = String(v); return Object.prototype.hasOwnProperty.call(RANGES, s) ? s : 'all'; }
  function sliceRange(series, range) {
    var r = normRange(range);
    if (r === 'all') return series.slice();
    /* 已发布帧会跳周，按日期截取，不按帧数 */
    var last = series.length ? dayValue(series[series.length - 1].d) : null;
    if (last == null) return series.slice();
    var from = new Date(last);
    from.setUTCFullYear(from.getUTCFullYear() - Math.round(Number(r) / 52));
    var cut = from.getTime(), i = 0;
    while (i < series.length - 2 && dayValue(series[i].d) < cut) i += 1;
    return series.slice(i);
  }
  function change(series) {
    if (!series || series.length < 2) return null;
    var a = series[0].c, b = series[series.length - 1].c;
    return a > 0 ? b / a - 1 : null;
  }
  function rangeLabel(series, range) {
    var r = normRange(range);
    if (r !== 'all') return RANGES[r];
    return series && series.length ? series[0].d.slice(0, 4) + ' 年以来' : '';
  }
  function niceTicks(min, max, count) {
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [];
    var raw = (max - min) / Math.max(1, count || 5), p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p;
    var step = (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p, out = [];
    for (var v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(Number(v.toFixed(10)));
    return out;
  }
  function lastAlert(series) {
    for (var i = series.length - 1; i >= 0; i--) if (series[i].a) return series[i].d;
    return null;
  }
  function alertCount(series) { return series.reduce(function (n, p) { return n + (p.a ? 1 : 0); }, 0); }
  function weeksBetween(from, to) {
    var a = dayValue(from), b = dayValue(to);
    if (a == null || b == null || b < a) return null;
    return Math.floor((b - a) / (7 * DAY));
  }
  /* 每个指数最近一次首次预警，按日期倒序 */
  function recentAlerts(items, asof, limit) {
    return (items || []).map(function (it) {
      var d = lastAlert(it.series || []);
      return d ? { sym: it.sym, name: it.name, date: d, weeks: weeksBetween(d, asof) } : null;
    }).filter(Boolean).sort(function (x, y) { return x.date < y.date ? 1 : x.date > y.date ? -1 : 0; }).slice(0, limit || 5);
  }
  /* 最新一帧的 52 周回撤（已发布字段 dd_52w），回撤从大到小 */
  function drawdowns(items) {
    return (items || []).map(function (it) {
      var s = it.series || [], last = s[s.length - 1];
      return last && last.dd != null ? { sym: it.sym, name: it.name, dd: last.dd, asof: last.d } : null;
    }).filter(Boolean).sort(function (a, b) { return a.dd - b.dd; });
  }
  /* 今日结论：只看已发布的 has_top，不另设阈值 */
  function answer(overview) {
    var list = overview && Array.isArray(overview.indices) ? overview.indices.filter(function (x) { return x && x.sym; }) : [];
    if (!list.length) return null;
    var tops = list.filter(function (x) { return x.has_top === true; });
    var names = tops.map(function (x) { return x.name || x.sym; });
    return {
      total: list.length, count: tops.length, names: names, tone: tops.length ? 'on' : 'off',
      asof: isDate(overview.asof) ? overview.asof : null,
      text: tops.length ? '今天：' + names.join('、') + ' 出现顶部区间' : '今天：' + list.length + ' 个主要指数都未出现顶部区间',
    };
  }
  function longDate(v) {
    var t = dayValue(v);
    if (t == null) return '';
    var d = new Date(t);
    return (d.getUTCMonth() + 1) + ' 月 ' + d.getUTCDate() + ' 日 ' + WEEKDAYS[d.getUTCDay()];
  }
  function pct(x, digits) {
    if (!Number.isFinite(x)) return '—';
    return (x >= 0 ? '+' : '') + (x * 100).toFixed(digits == null ? 2 : digits) + '%';
  }
  function fmt(v) {
    return Number.isFinite(v) ? v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
  }
  function fmtAxis(v) {
    return v >= 1000 ? Math.round(v).toLocaleString('en-US') : v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  function query(obj) {
    return Object.keys(obj).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(obj[k]); }).join('&');
  }
  function chartHref(sym) { return 'chart.html?' + query({ kind: 'index', from: 'home.html', code: sym }); }

  /* ---------- 主图：纯 SVG 字符串，便于测试 ---------- */
  function xLabels(series, plotWidth) {
    if (!series || series.length < 2) return [];
    var first = dayValue(series[0].d), last = dayValue(series[series.length - 1].d);
    var years = (last - first) / (365.25 * DAY), out = [];
    if (years <= 1.6) {
      var stepM = plotWidth < 420 ? 3 : 2, seenM = {};
      series.forEach(function (p, i) {
        var key = p.d.slice(0, 7);
        if (seenM[key]) return;
        seenM[key] = 1;
        var mm = Number(p.d.slice(5, 7));
        if (i > 0 && (mm - 1) % stepM === 0) out.push({ i: i, label: mm === 1 ? p.d.slice(0, 4) : mm + ' 月' });
      });
      return out;
    }
    var maxLabels = Math.max(2, Math.floor(plotWidth / 72));
    var step = [1, 2, 4, 5, 10].filter(function (s) { return Math.ceil(years) / s <= maxLabels; })[0] || 10, seenY = {};
    series.forEach(function (p, i) {
      var y = Number(p.d.slice(0, 4));
      if (seenY[y]) return;
      seenY[y] = 1;
      if (i > 0 && y % step === 0) out.push({ i: i, label: String(y) });
    });
    return out;
  }
  function chartModel(series, width, height) {
    var W = Math.max(160, Math.round(width)), H = Math.max(140, Math.round(height));
    var padR = 58, padT = 12, padB = 26, pw = W - padR, ph = H - padT - padB;
    var lo = Infinity, hi = -Infinity;
    series.forEach(function (p) { if (p.c < lo) lo = p.c; if (p.c > hi) hi = p.c; });
    var pad = (hi - lo) * 0.06 || hi * 0.02 || 1;
    lo -= pad; hi += pad;
    var n = series.length;
    var x = function (i) { return n < 2 ? pw / 2 : i * pw / (n - 1); };
    var y = function (v) { return padT + (hi - v) / (hi - lo) * ph; };
    return { W: W, H: H, pw: pw, ph: ph, padT: padT, padR: padR, lo: lo, hi: hi, x: x, y: y,
      pts: series.map(function (p, i) { return [x(i), y(p.c)]; }) };
  }
  function renderChart(series, width, height) {
    if (!series || series.length < 2) return { html: '', model: null };
    var m = chartModel(series, width, height), base = (m.padT + m.ph).toFixed(1), f = function (v) { return v.toFixed(1); };
    var line = 'M' + m.pts.map(function (p) { return f(p[0]) + ' ' + f(p[1]); }).join(' L');
    var area = line + ' L' + f(m.pts[m.pts.length - 1][0]) + ' ' + base + ' L' + f(m.pts[0][0]) + ' ' + base + ' Z';
    var s = '<svg class="hm-svg" width="' + m.W + '" height="' + m.H + '" viewBox="0 0 ' + m.W + ' ' + m.H + '" aria-hidden="true">' +
      '<defs><linearGradient id="hm-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#2962ff" stop-opacity=".16"/>' +
      '<stop offset="1" stop-color="#2962ff" stop-opacity="0"/></linearGradient></defs>';
    niceTicks(m.lo, m.hi, m.H < 260 ? 4 : m.H < 380 ? 5 : 6).forEach(function (t) {
      var yy = m.y(t);
      s += '<line class="g" x1="0" x2="' + m.pw + '" y1="' + f(yy) + '" y2="' + f(yy) + '"/>' +
        '<text class="ya" x="' + (m.pw + 8) + '" y="' + f(yy + 4) + '">' + esc(fmtAxis(t)) + '</text>';
    });
    xLabels(series, m.pw).forEach(function (l) {
      s += '<text class="xa" x="' + f(m.x(l.i)) + '" y="' + (m.H - 8) + '" text-anchor="middle">' + esc(l.label) + '</text>';
    });
    s += '<line class="base" x1="0" x2="' + m.pw + '" y1="' + base + '" y2="' + base + '"/>' +
      '<path class="area" d="' + area + '" fill="url(#hm-fill)"/><path class="line" d="' + line + '"/>';
    series.forEach(function (p, i) {
      if (p.a) s += '<circle class="al" cx="' + f(m.pts[i][0]) + '" cy="' + f(m.pts[i][1]) + '" r="3.6"/>';
    });
    var lp = m.pts[m.pts.length - 1], last = series[series.length - 1], tw = m.padR - 4;
    s += '<line class="lastl" x1="' + f(lp[0]) + '" x2="' + m.pw + '" y1="' + f(lp[1]) + '" y2="' + f(lp[1]) + '"/>' +
      '<g class="tag"><rect x="' + (m.pw + 2) + '" y="' + f(lp[1] - 10) + '" width="' + tw + '" height="20" rx="4"/>' +
      '<text x="' + f(m.pw + 2 + tw / 2) + '" y="' + f(lp[1] + 4) + '" text-anchor="middle">' + esc(fmtAxis(last.c)) + '</text></g>' +
      '<g class="xh" visibility="hidden"><line class="xl" x1="0" x2="0" y1="' + m.padT + '" y2="' + base + '"/><circle class="xc" cx="0" cy="0" r="4"/></g>' +
      '</svg>';
    return { html: s, model: m };
  }

  /* ---------- 页面挂载 ---------- */
  function mount(win) {
    var doc = win.document;
    if (!doc.body || !doc.body.classList.contains('home-tv')) return;
    var $ = function (id) { return doc.getElementById(id); };
    var reduce = win.matchMedia ? win.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
    pressFeel(doc, reduce);
    rowBadges(win);
    var L = win.LPPL;
    if (!L) return;

    var state = { range: readRange(win), full: [], view: [], model: null, row: null, quote: null };
    var plot = $('hm-plot');

    /* 今日结论 */
    var overviewP = (L.overview ? Promise.resolve(L.overview()) : Promise.resolve(null)).catch(function () { return null; });
    overviewP.then(function (ov) {
      var a = answer(ov), box = $('hm-answer'), date = $('hm-date');
      if (!box) return;
      if (!a) { box.className = 'hm-answer'; box.querySelector('span').textContent = '今日结论暂未发布'; return; }
      box.className = 'hm-answer ' + a.tone;
      box.querySelector('span').innerHTML = esc(a.text) + (a.asof ? ' <small>' + esc(a.asof) + ' 收盘</small>' : '');
      if (date && a.asof) date.textContent = longDate(a.asof) + ' · 收盘数据';
    });

    /* 历史帧：与内联脚本同一路径，LPPL 的请求缓存会合并为一次下载 */
    var syms = (L.SYMS || []).filter(function (s) { return (s.market || 'cn') === 'cn'; });
    var loads = syms.map(function (s) {
      return Promise.resolve(L.history ? L.history(s.sym) : null).then(function (h) {
        return { sym: s.sym, name: s.name, history: h, series: weeklySeries(h) };
      }, function () { return { sym: s.sym, name: s.name, history: null, series: [], failed: true }; });
    });
    var mainIdx = syms.map(function (s) { return s.sym; }).indexOf(MAIN_SYM);
    if (mainIdx >= 0) loads[mainIdx].then(function (it) {
      state.full = it.series;
      if (!state.full.length) { if (plot) plot.innerHTML = '<p class="hm-empty">走势暂未加载，可打开图表查看</p>'; return; }
      var n = alertCount(state.full), last = lastAlert(state.full), sum = $('hm-alert-sum');
      if (sum) sum.textContent = state.full[0].d.slice(0, 4) + ' 年以来 ' + n + ' 次' + (last ? ' · 最近一次 ' + last : '');
      draw();
      var ver = $('hm-ver');
      if (ver && it.history) ver.textContent = '模型 ' + (it.history.model_version || '—') + ' · 数据截至 ' + state.full[state.full.length - 1].d;
    });
    Promise.all(loads).then(function (items) {
      return overviewP.then(function (ov) {
        var asof = ov && isDate(ov.asof) ? ov.asof : items.reduce(function (m, it) {
          var s = it.series, d = s.length ? s[s.length - 1].d : '';
          return d > m ? d : m;
        }, '');
        paintAlerts($('hm-alerts'), recentAlerts(items, asof, 5), items.every(function (it) { return it.failed; }));
        paintDrawdowns($('hm-dd'), drawdowns(items));
      });
    });

    /* 复用内联脚本已取到的日线和实时报价 */
    function onRows(d) {
      d = d || {};
      if (d.market && d.market !== 'cn') return;
      state.row = (d.rows || []).filter(function (r) { return r && r.sym === MAIN_SYM && !r.error; })[0] || state.row;
      paintHeader();
    }
    function onQuotes(quotes) {
      var q = quotes && quotes[MAIN_SYM];
      state.quote = q && Number.isFinite(q.price) ? q : null;
      paintHeader();
    }
    doc.addEventListener('home:rows', function (e) { onRows(e.detail); });
    doc.addEventListener('home:quotes', function (e) { onQuotes(e.detail); });
    /* 事件可能先于本脚本挂载触发：读取内联脚本留下的最近一次结果 */
    if (win.__homeRows) onRows(win.__homeRows);
    if (win.__homeQuotes) onQuotes(win.__homeQuotes);

    /* 区间切换 */
    var seg = $('hm-range');
    if (seg) {
      syncRange();
      seg.addEventListener('click', function (e) {
        var b = e.target.closest('button[data-range]');
        if (!b) return;
        state.range = normRange(b.dataset.range);
        try { win.localStorage.setItem(RANGE_KEY, state.range); } catch (err) { /* 存储不可用 */ }
        syncRange();
        draw();
      });
    }
    function syncRange() {
      if (!seg) return;
      seg.querySelectorAll('button[data-range]').forEach(function (b) {
        b.setAttribute('aria-pressed', String(normRange(b.dataset.range) === state.range));
      });
    }

    function draw() {
      if (!plot || !state.full.length) return;
      state.view = sliceRange(state.full, state.range);
      var w = plot.clientWidth || 600, h = plot.clientHeight || 300, out = renderChart(state.view, w, h);
      state.model = out.model;
      plot.innerHTML = out.html + '<div class="hm-tip" hidden></div>';
      var first = state.view[0], last = state.view[state.view.length - 1];
      plot.setAttribute('aria-label', '上证指数周收盘，' + first.d + ' 至 ' + last.d + '，' + rangeLabel(state.view, state.range) +
        ' ' + pct(change(state.view), 1) + '，区间内首次预警 ' + alertCount(state.view) + ' 次');
      paintHeader();
    }
    function paintHeader() {
      var px = $('hm-px'), day = $('hm-day'), note = $('hm-px-note'), chg = $('hm-chg');
      if (!px) return;
      var q = state.quote, r = state.row, s = state.full, d = null, text = '';
      if (q) {
        px.textContent = fmt(q.price);
        d = Number.isFinite(q.pct) ? q.pct / 100 : null;
        var t = L.quoteTimeLabel ? L.quoteTimeLabel(q.time, q.tz) : null;
        text = t && t.time !== '—' ? '报价 ' + t.time : '实时报价';
      } else if (r && r.last && Number.isFinite(r.last.close)) {
        px.textContent = fmt(r.last.close);
        d = r.prev && r.prev.close ? r.last.close / r.prev.close - 1 : null;
        text = '收盘 ' + String(r.last.date || '').slice(5);
      } else if (s.length) {
        px.textContent = fmt(s[s.length - 1].c);
        text = '周收盘 ' + s[s.length - 1].d.slice(5);
      }
      if (day) { day.className = 'chg num ' + (d == null ? '' : d >= 0 ? 'up' : 'dn'); day.textContent = d == null ? '' : pct(d); }
      if (note) note.textContent = text;
      if (chg && state.view.length) {
        var c = change(state.view);
        chg.className = 'num ' + (c >= 0 ? 'up' : 'dn');
        chg.textContent = pct(c);
        var lab = $('hm-chg-l');
        if (lab) lab.textContent = rangeLabel(state.view, state.range);
      }
    }

    /* 十字线与提示 */
    if (plot) {
      plot.addEventListener('pointermove', function (e) {
        var m = state.model, svg = plot.querySelector('svg'), tip = plot.querySelector('.hm-tip');
        if (!m || !svg || !tip) return;
        var rect = svg.getBoundingClientRect(), x = e.clientX - rect.left;
        if (x < 0 || x > m.pw) { hideTip(); return; }
        var n = state.view.length, i = Math.max(0, Math.min(n - 1, Math.round(x / m.pw * (n - 1)))), p = state.view[i], pt = m.pts[i];
        var xh = svg.querySelector('.xh');
        xh.setAttribute('visibility', 'visible');
        xh.querySelector('.xl').setAttribute('x1', pt[0].toFixed(1));
        xh.querySelector('.xl').setAttribute('x2', pt[0].toFixed(1));
        xh.querySelector('.xc').setAttribute('cx', pt[0].toFixed(1));
        xh.querySelector('.xc').setAttribute('cy', pt[1].toFixed(1));
        tip.innerHTML = '<b class="num">' + esc(fmt(p.c)) + '</b><span>' + esc(p.d) + ' 周收盘</span>' + (p.a ? '<em>首次预警</em>' : '');
        tip.hidden = false;
        var left = pt[0] + 14;
        if (left + 150 > m.pw) left = pt[0] - 14 - tip.offsetWidth;
        tip.style.left = Math.max(0, left) + 'px';
      });
      plot.addEventListener('pointerleave', hideTip);
      if (win.ResizeObserver) {
        var lastW = 0, lastH = 0, raf = 0;
        new win.ResizeObserver(function () {
          var w = plot.clientWidth, h = plot.clientHeight;
          if (Math.abs(w - lastW) < 2 && Math.abs(h - lastH) < 2) return;
          lastW = w; lastH = h;
          win.cancelAnimationFrame(raf);
          raf = win.requestAnimationFrame(draw);
        }).observe(plot);
      }
    }
    function hideTip() {
      var svg = plot && plot.querySelector('svg'), tip = plot && plot.querySelector('.hm-tip');
      if (svg) svg.querySelector('.xh').setAttribute('visibility', 'hidden');
      if (tip) tip.hidden = true;
    }
  }

  function readRange(win) {
    try { return normRange(win.localStorage.getItem(RANGE_KEY) || 'all'); } catch (e) { return 'all'; }
  }
  function paintAlerts(box, list, failed) {
    if (!box) return;
    if (failed) { box.innerHTML = '<p class="hm-empty">首次预警记录暂未加载</p>'; return; }
    if (!list.length) { box.innerHTML = '<p class="hm-empty">已发布记录里还没有首次预警</p>'; return; }
    box.innerHTML = list.map(function (a) {
      var b = badgeFor(a.sym, a.name);
      return '<a class="hm-ar" href="' + esc(chartHref(a.sym)) + '"><i class="hm-bd hm-bd-sm" style="background:' + b.color + '" aria-hidden="true">' +
        esc(b.text) + '</i><span class="an">' + esc(a.name) + '</span><span class="ad num">' + esc(a.date) +
        (a.weeks != null ? '<em>' + (a.weeks === 0 ? '本周' : a.weeks + ' 周前') + '</em>' : '') + '</span></a>';
    }).join('');
  }
  function paintDrawdowns(box, list) {
    if (!box) return;
    if (!list.length) { box.innerHTML = '<p class="hm-empty">回撤数据暂未加载</p>'; return; }
    var max = Math.max.apply(null, list.map(function (x) { return Math.abs(x.dd); }).concat([0.0001]));
    box.innerHTML = list.map(function (x) {
      return '<div class="hm-dr"><span class="nm">' + esc(x.name) + '</span><span class="bar" aria-hidden="true"><i style="width:' +
        (Math.abs(x.dd) / max * 100).toFixed(1) + '%"></i></span><b class="num ' + (x.dd < 0 ? 'dn' : '') + '">' +
        (x.dd * 100).toFixed(1) + '%</b></div>';
    }).join('');
  }
  /* 胶囊松开时的回弹（按下的下沉由 CSS :active 完成） */
  function pressFeel(doc, reduce) {
    doc.addEventListener('pointerup', function (e) {
      if (reduce.matches || !e.target.closest) return;
      var t = e.target.closest('.btn,.hm-seg button');
      if (!t) return;
      t.classList.remove('hm-rel');
      void t.offsetWidth;
      t.classList.add('hm-rel');
      setTimeout(function () { t.classList.remove('hm-rel'); }, 300);
    });
  }
  /* 给内联脚本渲染的指数行补上彩色徽标；只监听 #rows 的直接子节点，避免循环触发 */
  function rowBadges(win) {
    var doc = win.document, rows = doc.getElementById('rows');
    if (!rows) return;
    function paint() {
      rows.querySelectorAll('a.row').forEach(function (a) {
        if (a.firstElementChild && a.firstElementChild.classList.contains('hm-bd')) return;
        var n = a.querySelector('.n'), b = badgeFor(a.dataset.sym || '', a.dataset.name || (n ? n.textContent : ''));
        var i = doc.createElement('i');
        i.className = 'hm-bd';
        i.setAttribute('aria-hidden', 'true');
        i.style.background = b.color;
        i.textContent = b.text;
        a.insertBefore(i, a.firstChild);
      });
    }
    if (win.MutationObserver) new win.MutationObserver(paint).observe(rows, { childList: true });
    paint();
  }

  return {
    badgeFor: badgeFor, weeklySeries: weeklySeries, sliceRange: sliceRange, normRange: normRange, change: change,
    rangeLabel: rangeLabel, niceTicks: niceTicks, lastAlert: lastAlert, alertCount: alertCount, weeksBetween: weeksBetween,
    recentAlerts: recentAlerts, drawdowns: drawdowns, answer: answer, longDate: longDate, pct: pct, chartHref: chartHref,
    xLabels: xLabels, renderChart: renderChart, mount: mount,
  };
});
