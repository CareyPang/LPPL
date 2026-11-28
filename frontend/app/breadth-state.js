/* 宽度状态解释：只渲染后端发布的状态与标记（breadth.state），不在前端重算，不作买卖信号。 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CPBreadthState = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  var MEANING = {
    panic_low: '绝大多数股票下跌、跌停超过 100 家且成交放大，同时上证收在 60 日新低、站上 20 日线的股票不到 13%：卖盘在已经下跌一段之后集中释放。',
    panic_first: '绝大多数股票下跌、跌停超过 100 家且成交放大，但上证没有收在 60 日新低：卖盘集中释放发生在下跌的前段或反弹途中。',
    panic: '绝大多数股票下跌、跌停超过 100 家且成交放大：卖盘集中释放。',
    down_heavy: '多数股票下跌且成交放大：卖出意愿强。',
    down_light: '多数股票下跌但成交萎缩：卖盘没有集中释放，买盘也没有进场。',
    down: '多数股票下跌，成交量在常见范围内。',
    up_heavy: '绝大多数股票上涨且成交放大：买盘广泛进场。',
    up_light: '多数股票上涨但成交萎缩：上涨缺少增量资金。',
    up: '多数股票上涨，成交量在常见范围内。',
    mixed: '涨跌家数接近，没有一致方向。',
  };
  var FLAG_MEANING = {
    top_div: '上证收在 60 日新高，但上涨的股票不到一半，站上 20 日线的比例比近 20 日高点低 10 个百分点以上：指数由少数股票带动。',
    bottom_div: '上证收在 60 日新低，但站上 20 日线的比例比近 60 日低点高 5 个百分点以上：多数股票没有跟随指数创新低。',
    oversold: '站上 20 日线的股票不到 13%，处于有记录以来最低的 5%。',
    overheat: '站上 20 日线的股票超过 86%，处于有记录以来最高的 5%。',
  };
  var TONE = {
    panic_low: 'dn2', panic_first: 'dn2', panic: 'dn2', down_heavy: 'dn2', down_light: 'dn1', down: 'dn1',
    up_heavy: 'up2', up_light: 'up1', up: 'up1', mixed: 'mid',
  };
  var MARKS = ['panic', 'top_div', 'bottom_div', 'oversold', 'overheat'];

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function num(value) { return value != null && Number.isFinite(Number(value)) ? Number(value) : null; }
  function pct(value, digits) {
    var v = num(value);
    return v == null ? '—' : (v * 100).toFixed(digits == null ? 1 : digits) + '%';
  }

  function rows(state) {
    var h = state && state.history;
    if (!h || !Array.isArray(h.date)) return [];
    return h.date.map(function (date, i) {
      return {
        date: date, sh: num(h.sh && h.sh[i]), red: num(h.red && h.red[i]), ratio: num(h.ratio && h.ratio[i]),
        P20: num(h.P20 && h.P20[i]), ld: num(h.ld && h.ld[i]), state: h.state && h.state[i],
        flags: (h.flags && h.flags[i]) || [],
      };
    });
  }

  function label(state, key) {
    return (state.labels && state.labels[key]) || (state.flag_labels && state.flag_labels[key]) || key;
  }

  /* 一天的读数说明：只复述当日数值。 */
  function describe(row) {
    var parts = ['上涨 ' + pct(row.red)];
    if (row.ratio != null) parts.push('成交额为前 20 日均量的 ' + row.ratio.toFixed(2) + ' 倍');
    if (row.ld != null) parts.push('跌停 ' + row.ld + ' 家');
    if (row.P20 != null) parts.push('站上 20 日线 ' + pct(row.P20));
    return parts.join('，') + '。';
  }

  function isPanic(key) { return typeof key === 'string' && key.indexOf('panic') === 0; }

  /* 连续出现同一标记的交易日合并成一段；恐慌出清的两种类型分开成段。 */
  function episodes(list, mark) {
    var out = [], open = null;
    list.forEach(function (row, i) {
      var on = mark === 'panic' ? isPanic(row.state) : row.flags.indexOf(mark) >= 0;
      if (on) {
        if (!open || (mark === 'panic' && open.state !== row.state)) {
          open = { mark: mark, state: row.state, start: row.date, startSh: row.sh, days: 0 }; out.push(open);
        }
        open.end = row.date; open.endSh = row.sh; open.days += 1; open.last = i;
      } else {
        open = null;
      }
    });
    return out;
  }

  function render(state, options) {
    if (!state || !state.latest || !state.history) return '';
    var o = options || {}, list = rows(state), last = list[list.length - 1];
    if (!last) return '';
    var mark = MARKS.indexOf(o.mark) >= 0 ? o.mark : 'bottom_div';
    var latest = state.latest, flags = latest.flags || {};
    var flagKeys = Object.keys(flags);
    var head = '<div class="bs-now"><span class="bs-tag bs-' + TONE[latest.state] + '">' + esc(label(state, latest.state)) + '</span>' +
      (latest.streak > 1 ? '<span class="bs-streak">连续 ' + latest.streak + ' 个交易日</span>' : '') +
      flagKeys.map(function (key) {
        return '<span class="bs-flag">' + esc(label(state, key)) + (flags[key] > 1 ? ' · 连续 ' + flags[key] + ' 日' : '') + '</span>';
      }).join('') + '</div>';
    var meaning = '<p class="bs-mean">' + esc(MEANING[latest.state] || '') + '</p>' +
      flagKeys.map(function (key) { return '<p class="bs-mean"><b>' + esc(label(state, key)) + '</b>：' + esc(FLAG_MEANING[key] || '') + '</p>'; }).join('') +
      '<p class="note">' + esc(latest.date) + ' 读数：' + esc(describe(last)) + '</p>';

    var recent = list.slice(-20).reverse().map(function (row) {
      return '<tr><td>' + esc(row.date) + '</td><td><span class="bs-tag bs-' + TONE[row.state] + '">' + esc(label(state, row.state)) + '</span>' +
        row.flags.map(function (key) { return '<span class="bs-flag">' + esc(label(state, key)) + '</span>'; }).join('') +
        '</td><td class="r">' + (row.sh == null ? '—' : row.sh.toFixed(2)) + '</td><td class="r">' + pct(row.red) + '</td><td class="r">' +
        (row.ratio == null ? '—' : row.ratio.toFixed(2) + '×') + '</td><td class="r">' + (row.ld == null ? '—' : row.ld) + '</td><td class="r">' + pct(row.P20) + '</td></tr>';
    }).join('');

    var chips = MARKS.map(function (key) {
      var count = key === 'panic'
        ? Object.keys(state.counts || {}).filter(isPanic).reduce(function (sum, k) { return sum + (num(state.counts[k]) || 0); }, 0)
        : (state.flag_counts || {})[key];
      return '<button class="bs-chip" type="button" data-bs-mark="' + key + '" aria-pressed="' + (key === mark) + '">' +
        esc(label(state, key)) + ' <span class="m">' + (num(count) == null ? '—' : count) + ' 天</span></button>';
    }).join('');
    var eps = episodes(list, mark).reverse().slice(0, 40).map(function (ep) {
      return '<tr><td>' + esc(ep.start) + (ep.end !== ep.start ? ' 至 ' + esc(ep.end) : '') + '</td>' +
        (mark === 'panic' ? '<td>' + esc(ep.state === 'panic' ? '其他' : label(state, ep.state).replace('恐慌出清 · ', '')) + '</td>' : '') + '<td class="r">' + ep.days +
        '</td><td class="r">' + (ep.startSh == null ? '—' : ep.startSh.toFixed(2)) + '</td><td class="r">' + (ep.endSh == null ? '—' : ep.endSh.toFixed(2)) + '</td></tr>';
    }).join('');
    var markMeaning = mark === 'panic'
      ? MEANING.panic + '按上证当日位置分两种：“超卖新低”指同时收在 60 日新低且站上 20 日线的股票不到 13%；“指数未破位”指没有收在 60 日新低；“其他”指收在 60 日新低但不到极端超卖。'
      : FLAG_MEANING[mark];

    var total = num(state.n_days) || list.length;
    var freq = Object.keys(state.labels || {}).map(function (key) {
      var count = num((state.counts || {})[key]) || 0;
      return '<tr><td><span class="bs-tag bs-' + TONE[key] + '">' + esc(label(state, key)) + '</span></td><td>' + esc(MEANING[key] || '') +
        '</td><td class="r">' + count + '</td><td class="r">' + pct(total ? count / total : null) + '</td></tr>';
    }).join('');

    return '<section class="bs" aria-label="宽度状态">' +
      '<h3>今日宽度状态</h3>' + head + meaning + (o.after || '') +
      '<details class="bs-more"' + (o.open ? ' open' : '') + '><summary>最近 20 日状态与标记记录</summary>' +
      '<div class="bs-cols"><div><h3>最近 20 日状态</h3><div class="table-scroll"><table class="bs-recent"><thead><tr>' +
      '<th>日期</th><th>状态</th><th class="r">上证</th><th class="r">上涨占比</th><th class="r">量比</th><th class="r">跌停</th><th class="r">站上 20 日线</th>' +
      '</tr></thead><tbody>' + recent + '</tbody></table></div></div>' +
      '<div><h3>标记记录（' + esc(state.since) + ' 起）</h3><div class="bs-chips" role="group" aria-label="标记">' + chips + '</div>' +
      '<p class="note">' + esc(markMeaning) + '</p>' +
      (eps ? '<div class="table-scroll"><table class="bs-eps"><thead><tr><th>日期</th>' + (mark === 'panic' ? '<th>类型</th>' : '') + '<th class="r">天数</th><th class="r">起始日上证</th><th class="r">结束日上证</th></tr></thead><tbody>' +
        eps + '</tbody></table></div>' : '<p class="note">有记录以来没有出现。</p>') + '</div></div></details>' +
      '<details class="breadth-method"><summary>状态怎么分的</summary>' +
      '<p class="note">每个交易日按当日及之前的数据归入一类；阈值取自 ' + esc(state.since) + ' 以来 ' + total +
      ' 个交易日各指标自身的分位，没有参考之后的涨跌。状态和标记只描述当日市场，不是买卖信号；它们之后的涨跌尚未检验。</p>' +
      '<div class="table-scroll"><table class="bs-freq"><thead><tr><th>状态</th><th>含义</th><th class="r">天数</th><th class="r">占比</th></tr></thead><tbody>' + freq + '</tbody></table></div>' +
      '<p class="note">A 股普跌日的 TRIN 通常低于 1（上涨占比越低 TRIN 越低），所以恐慌出清不按 TRIN 判定，按跌停家数和成交量判定。</p>' +
      '</details></section>';
  }

  return { render: render, rows: rows, episodes: episodes, describe: describe, MEANING: MEANING, FLAG_MEANING: FLAG_MEANING, MARKS: MARKS };
});
