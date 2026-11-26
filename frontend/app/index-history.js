/* 指数页完整历史：把冻结的早期日线接到最近行情前面，并生成“顶部预警记录 / 底分事件记录”两张表。
   只做拼接与展示；预警段来自 CPAlertLedger，底分与收益来自后端历史帧，不在前端重算。 */
(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CPIndexHistory = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  var SPLIT = { dev: '开发段', cal: '校准段', test: '测试段', live: '样本外延续' };
  var SEGMENTS = [['dev', '开发段 2000–2018'], ['cal', '校准段 2019–2021'], ['test', '测试段 2022–2025-08']];
  var SPLIT_HELP = '开发段用来设计规则，校准段只用来定门槛，测试段在前两段定完后才看。';

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function num(value) { return value != null && Number.isFinite(Number(value)) ? Number(value) : null; }
  function pct(value, digits) {
    var v = num(value);
    return v == null ? '—' : (v * 100).toFixed(digits == null ? 0 : digits) + '%';
  }
  function signedPct(value) {
    var v = num(value);
    return v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
  }
  function pp(value) {
    var v = num(value);
    return v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + ' 个百分点';
  }

  /* 早期日线只取早于现有第一根的部分；现有行情（含回放截止日）原样保留。 */
  function mergeBars(bars, payload) {
    if (!Array.isArray(bars) || !bars.length) return bars || [];
    if (!payload || payload.schema !== 'index_bars.v1' || !Array.isArray(payload.dates)) return bars;
    var close = payload.close;
    if (!Array.isArray(close) || close.length !== payload.dates.length) return bars;
    var first = bars[0].date, early = [];
    var pick = function (name, index, fallback) {
      var column = payload[name], value = Array.isArray(column) ? num(column[index]) : null;
      return value == null ? fallback : value;
    };
    /* 两个来源的成交量单位可能不同：用重叠日期的中位数比值把早期成交量换算到现有行情的单位 */
    var known = {}, ratios = [], scale = 1;
    bars.forEach(function (bar) { if (bar.volume > 0) known[bar.date] = bar.volume; });
    if (Array.isArray(payload.volume)) {
      payload.dates.forEach(function (date, index) {
        var v = num(payload.volume[index]);
        if (v > 0 && known[date]) ratios.push(known[date] / v);
      });
    }
    if (ratios.length >= 20) { ratios.sort(function (a, b) { return a - b; }); scale = ratios[ratios.length >> 1]; }
    for (var i = 0; i < payload.dates.length; i++) {
      var date = payload.dates[i], c = num(close[i]), volume = pick('volume', i, null);
      if (!date || date >= first) break;
      if (c == null || (early.length && date <= early[early.length - 1].date)) continue;
      early.push({
        date: date, open: pick('open', i, c), high: pick('high', i, c), low: pick('low', i, c), close: c,
        volume: volume == null ? null : volume * scale,
      });
    }
    return early.length ? early.concat(bars) : bars;
  }

  /* 事后顶要等 126 个交易日确认期结束才进入记录，与主图口径一致；bars 的最后一根就是截止日。 */
  var CONFIRM_SESSIONS = 126;
  function confirmedTops(history, bars) {
    var tops = history && Array.isArray(history.tops) ? history.tops : [];
    if (!Array.isArray(bars) || !bars.length) return [];
    var last = bars.length - 1;
    return tops.filter(function (top) {
      var lo = 0, hi = last + 1;
      while (lo < hi) { var mid = (lo + hi) >> 1; if (bars[mid].date < top.date) lo = mid + 1; else hi = mid; }
      return lo + CONFIRM_SESSIONS <= last;
    });
  }

  /* 截止日之后的帧、以及确认期未结束的事后顶都不进入记录。 */
  function topEpisodes(history, scale, asof, ledger, bars) {
    var api = ledger || (root && root.CPAlertLedger);
    if (!history || !Array.isArray(history.frames) || !api) return [];
    var frames = history.frames.filter(function (frame) { return frame.asof && (!asof || frame.asof <= asof); });
    return api.episodes(frames, confirmedTops(history, bars), scale).slice().reverse();
  }

  function bottomEvents(history, asof) {
    if (!history || !Array.isArray(history.frames)) return [];
    var summary = history.bottom_summary, byDate = {};
    if (summary && Array.isArray(summary.events)) {
      summary.events.forEach(function (event) { if (event && event.asof) byDate[event.asof] = event; });
    }
    /* 后端的 24/50 周收益取的是往后第 24/50 帧；那一帧不晚于截止日才显示 */
    var position = {};
    history.frames.forEach(function (frame, index) { if (frame.asof) position[frame.asof] = index; });
    /* 后端摘要只保留最近 12 个事件的收益；更早的事件按同一口径用已发布的帧收盘价相除 */
    var matured = function (date, weeks, value) {
      var frame = history.frames[position[date]], later = history.frames[position[date] + weeks];
      if (!later || !later.asof || (asof && later.asof > asof)) return null;
      if (num(value) != null) return num(value);
      var from = num(frame.close), to = num(later.close);
      return from > 0 && to != null ? to / from - 1 : null;
    };
    return history.frames.filter(function (frame) {
      return frame.bottom_first_alert_flag && frame.asof && (!asof || frame.asof <= asof);
    }).map(function (frame) {
      var event = byDate[frame.asof] || {};
      return {
        asof: frame.asof, split: frame.split, score: num(frame.fco_neg_intensity),
        factors: frame.bottom_factors || {},
        ret24: matured(frame.asof, 24, event.ret_24w), ret50: matured(frame.asof, 50, event.ret_50w),
      };
    }).reverse();
  }

  function badge(level, label, detail) {
    var maker = root && root.CPEvidenceBadge;
    return maker ? maker.html(level, { label: label, detail: detail }) : '';
  }

  function topSummary(history, scale, historical) {
    var summary = history && history.episode_summary && history.episode_summary[scale];
    if (historical || !summary || !summary.n_episodes) return '';
    var buffer = summary.buffer_days || 15;
    var line = '共 ' + summary.n_episodes + ' 轮预警；事后顶落在首次区间 ±' + buffer + ' 日内的占 ' +
      pct(summary.hit_rate_buffered, 1) + '，随机对照 ' + pct(summary.null_hit_rate_buffered, 1) +
      (num(summary.p_value_buffered) == null ? '' : '（p=' + Number(summary.p_value_buffered).toFixed(3) + '）') + '。';
    var rows = ['dev', 'cal', 'test', 'live'].filter(function (key) {
      return summary.by_split && summary.by_split[key] && summary.by_split[key].n_episodes > 0;
    }).map(function (key) {
      var part = summary.by_split[key];
      return '<tr><th scope="row">' + esc(SPLIT[key]) + '</th><td>' + esc(part.n_episodes) + '</td><td>' +
        esc(pct(part.hit_rate_buffered, 1)) + '</td></tr>';
    }).join('');
    var lead = num(summary.median_days_to_top);
    return '<p class="hl-sum">' + badge('dev', '开发段未显著', SPLIT_HELP + '顶部聚类在开发段未显著高于零对照。') +
      ' ' + esc(line) + '</p>' +
      '<details class="hl-more"><summary>分段明细</summary><table class="hl-mini"><thead><tr><th>数据段</th><th>预警轮数</th><th>±' +
      esc(buffer) + ' 日命中</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<p class="hl-note">精确落入首次区间 ' + esc(pct(summary.hit_rate_exact, 1)) +
      (lead == null ? '' : '；首次预警到事后顶中位 ' + Math.round(lead) + ' 天') + '。占比不是概率。</p></details>';
  }

  /* 历史帧是事后重算的：不是样本外证据，原登记的一次性检验结果不变 */
  function recomputeNote(history) {
    var data = history && history.recompute;
    if (!data || typeof data !== 'object') return '';
    return '<details class="hl-more"><summary>' + esc(typeof data.label === 'string' ? data.label : '事后重算，不是样本外') +
      '</summary><p class="hl-note">' + esc(typeof data.note === 'string' ? data.note : '') + '</p></details>';
  }

  function topTable(episodes, selected) {
    if (!episodes.length) return '<p class="hl-empty">该尺度没有出现过顶部聚类。</p>';
    var relation = { before: '早于区间', inside: '落在区间内', after: '晚于区间' };
    var body = episodes.map(function (episode) {
      var id = episode.scale + ':' + episode.first_asof;
      var main = Array.isArray(episode.clusters) ? episode.clusters[0] : null;
      var range = main ? [main.q20_date, main.q80_date] : (episode.window || []);
      var top = episode.next_top, dd = top ? num(top.max_dd) : null;
      var topText = !top ? '无' : esc(top.date) + (dd == null ? '' : ' · 回撤 ' + esc(pct(dd))) +
        (episode.days_to_top != null ? ' · 提前 ' + esc(episode.days_to_top) + ' 天' : '');
      var rel = relation[main ? episode.top_vs_main : episode.top_vs_window] || '无';
      return '<tr tabindex="0" data-hl-top="' + esc(id) + '" data-date="' + esc(episode.first_asof) +
        '" data-end="' + esc((top && top.date) || range[1] || episode.last_asof || episode.first_asof) +
        '" aria-selected="' + (selected === id) + '"><td>' + esc(episode.first_asof) + '</td><td>' + esc(episode.weeks) +
        ' 周</td><td>' + (range[0] ? esc(range[0]) + ' – ' + esc(range[1]) : '—') + '</td><td>' +
        esc(SPLIT[episode.split] || episode.split || '—') + '</td><td>' + topText + '</td><td>' + esc(rel) + '</td></tr>';
    }).join('');
    return '<div class="hl-scroll"><table class="hl-table"><thead><tr><th>首次预警日</th><th>持续</th><th>当时的聚类区间</th>' +
      '<th>所属段</th><th>事后确认顶</th><th>顶相对区间</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function renderTop(history, options) {
    var o = options || {}, scale = o.scale === '12-24m' ? '12-24m' : '6-12m';
    var episodes = topEpisodes(history, scale, o.asof, o.ledger, o.bars);
    var chips = [['6-12m', '6–12 月'], ['12-24m', '12–24 月']].map(function (item) {
      return '<button class="hl-chip" type="button" data-hl-scale="' + item[0] + '" aria-pressed="' + (item[0] === scale) + '">' +
        item[1] + '</button>';
    }).join('');
    return '<div class="hl-head"><p class="tp-d">每轮第一次出现顶部聚类记为一次预警，点一行定位到当时的图。</p>' +
      '<div class="hl-chips" role="group" aria-label="尺度">' + chips + '</div></div>' +
      topSummary(history, scale, o.historical) + recomputeNote(history) + topTable(episodes, o.selected);
  }

  function bottomSegments(history) {
    var meta = history && history.bottom_score, segments = meta && meta.segments;
    if (!segments || !segments.test) return '';
    var rows = SEGMENTS.filter(function (item) { return segments[item[0]]; }).map(function (item) {
      var row = segments[item[0]], p = num(row.shift_p);
      return '<tr><th scope="row">' + esc(item[1]) + '</th><td>' + esc(pp(row.lift_50w)) + '</td><td>' + esc(pp(row.old_lift_50w)) +
        '</td><td>' + esc(pp(row.relapse_24w)) + '</td><td>' + esc(pct(row.coverage)) + '</td><td>' +
        esc(row.n_events == null ? '—' : row.n_events) + '</td><td>' +
        esc(p == null ? '未计算' : p < 0.0005 ? '<0.0005' : p.toFixed(3)) + '</td></tr>';
    }).join('');
    return '<div class="hl-scroll"><table class="hl-mini"><thead><tr><th>数据段</th>' +
      '<th>50 周后上涨率 − 基准</th><th>旧底分同口径</th><th>24 周内再跌 10% − 基准</th><th>绿柱占回落周</th><th>独立事件</th>' +
      '<th>随机平移 p</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      '<p class="hl-note">7 个 A 股指数合并，事前登记。校准段新旧底分结果相同；测试段只有一个下跌—反弹周期，事件不是独立样本。</p>';
  }

  function bottomSummary(history, historical) {
    var meta = history && history.bottom_score, segments = meta && meta.segments;
    if (historical || !segments || !segments.test) return '';
    return '<p class="hl-sum">' +
      badge('passed', '测试段通过', SPLIT_HELP + '测试段只有一个下跌—反弹周期，各指数同涨同跌。') +
      ' 底分 ≥60：测试段 50 周后上涨率比基准高 ' + esc(pp(segments.test.lift_50w).replace(/^\+/, '')) + '。</p>' +
      '<details class="hl-more"><summary>三段明细</summary>' + bottomSegments(history) + '</details>';
  }

  function renderBottom(history, options) {
    var o = options || {}, events = bottomEvents(history, o.asof);
    var ret = function (value) {
      return value == null ? '<td class="hl-mute">未满期</td>'
        : '<td class="' + (value >= 0 ? 'hl-up' : 'hl-dn') + '">' + esc(signedPct(value)) + '</td>';
    };
    var body = events.map(function (event) {
      var f = event.factors, parts = [];
      if (num(f.dd_52w) != null) parts.push('回撤 ' + pct(f.dd_52w));
      if (num(f.erp_pct) != null) parts.push('股债利差分位 ' + pct(f.erp_pct));
      if (num(f.pbn_pct) != null) parts.push('破净率分位 ' + pct(f.pbn_pct));
      return '<tr tabindex="0" data-hl-bottom="' + esc(event.asof) + '" data-date="' + esc(event.asof) + '" aria-selected="' +
        (o.selected === event.asof) + '"><td>' + esc(event.asof) + '</td><td>' + esc(SPLIT[event.split] || event.split || '—') +
        '</td><td>' + (event.score == null ? '—' : Math.round(event.score * 100)) + '</td>' + ret(event.ret24) + ret(event.ret50) +
        '<td>' + esc(parts.join(' · ') || '—') + '</td></tr>';
    }).join('');
    var table = events.length
      ? '<div class="hl-scroll"><table class="hl-table"><thead><tr><th>事件日</th><th>所属段</th><th>底分</th><th>24 周后</th>' +
        '<th>50 周后</th><th>当时的分项</th></tr></thead><tbody>' + body + '</tbody></table></div>'
      : '<p class="hl-empty">该指数没有底分 ≥60 的事件。</p>';
    return '<div class="hl-head"><p class="tp-d">底分第一次达到 60（距上次至少 12 周）记为一次事件，点一行定位到当时的图。</p></div>' +
      bottomSummary(history, o.historical) + table;
  }

  return {
    mergeBars: mergeBars, confirmedTops: confirmedTops, topEpisodes: topEpisodes, bottomEvents: bottomEvents,
    renderTop: renderTop, renderBottom: renderBottom, bottomSegments: bottomSegments, SPLIT_HELP: SPLIT_HELP,
  };
});
