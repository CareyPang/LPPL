(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LPPLMarketTrends = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const levels = { watch: '开始留意', strengthening: '迹象增强', invalidated: '此前判断已失效' };
  const kinds = { rebound_end: '反弹尾声', stage_top: '阶段高点', rebound: '短线反弹', reversal: '中期反转' };
  const text = value => typeof value === 'string' && value.trim().length > 0;
  function levelName(item) {
    if (item.level === 'invalidated' && item.closure_reason === 'expired') return '观察期结束';
    if (item.level === 'invalidated' && item.closure_reason === 'new_opposite_observation') return '已由新提醒接替';
    return levels[item.level];
  }
  function date(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
    const stamp = Date.parse(value + 'T00:00:00Z');
    return Number.isFinite(stamp) && new Date(stamp).toISOString().slice(0, 10) === value;
  }

  // The site's daily close is due at 06:00 Beijing time on the following day.
  // A server clock or a page visit never supplies the date an observation first qualified.
  function lastDueDate(now, calendar) {
    const due = new Date(now + (8 - 30) * 3600000);
    const key = () => due.toISOString().slice(0, 10);
    const closures = new Set(calendar?.holidays_through >= key() && Array.isArray(calendar.closures)
      ? calendar.closures : []);
    while ([0, 6].includes(due.getUTCDay()) || closures.has(key())) due.setUTCDate(due.getUTCDate() - 1);
    return key();
  }

  // All financial decisions and their original observation dates come from the snapshot.
  function view(snapshot, marketDate, now, calendar, selectedDate) {
    const assessment = snapshot?.trend_alerts;
    const result = { alerts: [], notice: '', asof: '', phase: '', historical: false, headline: '' };
    if (!assessment) {
      result.notice = '这份行情没有附带趋势评估。下方仍可查看当日涨跌和成交。';
      return result;
    }
    const { asof, phase, alerts, state, evidence } = assessment;
    if (assessment.schema !== 'breadth-alerts.v1' || !date(asof) ||
        asof !== snapshot.asof || asof !== snapshot.latest?.date ||
        !['experimental', 'research_replay'].includes(evidence)) {
      result.notice = '趋势评估的日期或版本与行情无法核对，请查看下方原始行情。';
      return result;
    }
    const today = new Date(now + 8 * 3600000).toISOString().slice(0, 10);
    if (selectedDate && (!date(selectedDate) || asof > selectedDate)) {
      result.notice = '所选日期尚无这份趋势记录。更晚出现的提醒已隐藏。';
      return result;
    }
    if (asof > today) {
      result.notice = '这份评估的日期晚于当前交易日期，请核对数据时间。';
      return result;
    }
    result.asof = asof;
    result.historical = Boolean(selectedDate) || evidence === 'research_replay' || snapshot.stale === true ||
      (date(marketDate) && marketDate > asof) || asof < lastDueDate(now, calendar);
    result.context = evidence === 'research_replay' || selectedDate ? '历史回放' :
      result.historical ? '上次收盘记录' : '试行观察';
    if (text(phase?.label) && date(phase.asof) && phase.asof < asof) {
      result.phase = '截至 ' + phase.asof + '：' + [phase.label, phase.maturity_label].filter(text).join(' · ');
    }
    if (state === 'unavailable') {
      result.notice = text(assessment.reason) ? assessment.reason : '这一天缺少判断趋势所需的数据。';
      return result;
    }
    if ((state === 'quiet' || state === 'watch') && text(assessment.context_note)) {
      result.contextNote = assessment.context_note;
    }
    if (state === 'quiet' && Array.isArray(alerts) && alerts.length === 0) {
      result.notice = text(assessment.reason) ? assessment.reason : '这次收盘没有触发转折提醒。';
      return result;
    }
    if (state !== 'watch' || !Array.isArray(alerts) || !alerts.length) {
      result.notice = '这份记录的提醒状态不完整，暂时无法判断。';
      return result;
    }
    result.alerts = alerts.filter(item => item && Object.hasOwn(kinds, item.kind) && Object.hasOwn(levels, item.level) &&
      item.evidence === evidence && text(item.title) && text(item.message) &&
      Array.isArray(item.reasons) && item.reasons.some(text) && text(item.next_check) &&
      date(item.trigger_date) && date(item.update_date) &&
      item.trigger_date <= item.update_date && item.update_date <= asof &&
      item.active === (item.level !== 'invalidated'));
    const priority = item => item.active ? (item.update_date === asof ? 0 : 1) : 2;
    result.alerts.sort((left, right) => priority(left) - priority(right));
    if (result.alerts.length < alerts.length) result.notice = '部分提醒缺少完整依据，暂未展示。';
    if (!result.historical && marketDate === asof) {
      result.headline = result.alerts.filter(item => item.active && item.update_date === asof)
        .map(item => item.title + '（' + levels[item.level] + '）').join('、');
    }
    return result;
  }

  function markup(model, escape) {
    const stamp = model.asof ? `<p class="trend-meta">${escape(model.context)} · ${escape(model.asof)} 收盘</p>` : '';
    const cards = model.alerts.map(item => `<article class="trend-card" data-level="${item.level}">
      <header><h4>${escape(item.title)}</h4><span>${kinds[item.kind]} · ${levelName(item)}</span></header>
      <p>${escape(item.message)}</p>
      <ul aria-label="提醒依据">${item.reasons.filter(text).map(reason => '<li>' + escape(reason) + '</li>').join('')}</ul>
      <p class="trend-next"><strong>接下来看</strong> ${escape(item.next_check)}</p>
      <p class="trend-meta">首次符合条件 ${escape(item.trigger_date)}${item.update_date === item.trigger_date ? '' : ' · 判断更新 ' + escape(item.update_date)}</p>
    </article>`).join('');
    return `<div class="trend-heading"><h3>上证走势提醒</h3>${stamp}</div>
      ${model.phase ? '<p class="trend-phase">' + escape(model.phase) + '</p>' : ''}
      ${model.contextNote ? '<p class="trend-context"><strong>成交观察</strong> ' + escape(model.contextNote) + '</p>' : ''}
      ${cards ? '<div class="trend-cards">' + cards + '</div>' : ''}
      ${model.notice ? '<p class="note">' + escape(model.notice) + '</p>' : ''}`;
  }

  return { view, markup };
});
