/* Public archive observations are independent of this browser's local inbox. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.WatchlistArchive = api;
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  const labels = {
    baseline: '收录起点', window_appeared: '出现观察区间', window_revised: '观察区间修订',
    window_ended: '原观察区间不再列出', state_changed: '研究状态变化'
  };
  const validDay = value => {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(value + 'T00:00:00Z');
    return Number.isFinite(+date) && date.toISOString().slice(0, 10) === value;
  };
  const sourceLink = value => typeof value === 'string' &&
    /^https:\/\/github\.com\/CareyPang\/LPPL\/blob\/[a-f0-9]{40}\/[A-Za-z0-9_./-]+$/i.test(value) &&
    !value.split('/').includes('..') ? value : null;

  function archiveView(doc, day, byClose) {
    const cutoff = byClose && validDay(day) ? Date.parse(day + 'T15:00:00+08:00') : NaN;
    const eligible = row => !!row && (!byClose || (
      validDay(row.asof) && row.asof <= day && typeof row.sealed_at === 'string' &&
      /(?:Z|[+-]\d{2}:\d{2})$/i.test(row.sealed_at) && Date.parse(row.sealed_at) <= cutoff
    ));
    const observations = doc.observations.filter(eligible);
    const events = [];
    for (const event of doc.events) {
      const current = doc.observations[event.current];
      const previous = event.previous == null ? null : doc.observations[event.previous];
      if (eligible(current) && (!previous || eligible(previous))) events.push({ kind: event.kind, current, previous });
    }
    return { observations, events: events.reverse() };
  }

  function bind(document, api) {
    const el = id => document.getElementById('archive-' + id);
    const controls = el('controls'), mode = el('mode'), day = el('cutoff'), state = el('state');
    const records = el('records'), more = el('more'), retry = el('retry');
    let assetId, replayDay, doc, version = 0, shown = 3;
    const location = document.defaultView.location;
    const saved = new URLSearchParams(location.search);
    function append(parent, tag, value) {
      const child = document.createElement(tag);
      child.textContent = value;
      parent.append(child);
      return child;
    }
    function link(parent, row, label) {
      const url = sourceLink(row.source_url);
      if (!url) return;
      const node = append(parent, 'a', label);
      node.href = url;
      node.target = '_blank';
      node.rel = 'noopener noreferrer';
    }
    function bands(row) {
      if (!row.windows.length) return rootStatus(row.status);
      return row.windows.map(w => (w.scale || '综合') + ' · ' + w.start + ' 至 ' + w.end +
        (w.evidence === 'descriptive' ? '（n=' + w.n + '，历史分位，不是预测）' : '')).join('；');
    }
    function rootStatus(status) {
      return document.defaultView.ResearchWorkspaceCore.STATUS[status] || '无可展示的区间';
    }
    function chartLink(parent, row) {
      if (!row.chart_path || !/^[0-9a-f]{64}$/.test(row.sha256)) return;
      const [kind, code] = assetId.split(':');
      const back = new URLSearchParams({ kind, code });
      if (replayDay) back.set('asof', replayDay);
      if (mode.value === 'close') back.set('archiveThrough', day.value);
      const args = new URLSearchParams({ kind, code, asof: row.asof, archive: row.sha256,
        from: 'research-workspace.html?' + back.toString() });
      append(parent, 'a', '看此原档图表 ↗').href = 'chart.html?' + args;
    }
    function draw() {
      records.replaceChildren();
      more.hidden = true;
      if (!doc) return;
      const byClose = mode.value === 'close';
      el('cutoff-label').hidden = !byClose;
      const { observations, events } = archiveView(doc, day.value, byClose);
      const gaps = doc.gaps.filter(g => !byClose || !g.asof || g.asof <= day.value);
      state.textContent = '已核对 ' + observations.length + ' 份原档' +
        (gaps.length ? ' · 有缺档或未通过核验的记录，覆盖不完整。' : '。') +
        (byClose ? '按北京时间 15:00 及有凭据的封存时间筛选。' : '按已收录原档比较，公开首发时间未知。');
      if (!observations.length) {
        append(records, 'p', byClose ? '所选收盘时点没有可核对的封存记录。生成时间不足以证明当时已封存。' : '暂无已核对的原档。');
        return;
      }
      const last = observations.at(-1);
      link(records, last, '查看此范围最后一份原档 · ' + last.asof + ' ↗');
      chartLink(records, last);
      for (const item of events.slice(0, shown)) {
        const card = append(records, 'article', '');
        append(card, 'strong', item.current.asof + ' · ' + (labels[item.kind] || '归档变化'));
        if (item.previous) append(card, 'p', '此前（' + item.previous.asof + '）' + bands(item.previous));
        append(card, 'p', '本档 · ' + bands(item.current));
        if (item.kind === 'state_changed' && item.previous) {
          if (item.previous.evidence !== item.current.evidence)
            append(card, 'p', '证据等级 · ' + item.previous.evidence + ' → ' + item.current.evidence);
          if (item.previous.model_version !== item.current.model_version)
            append(card, 'p', '模型版本 · ' + item.previous.model_version + ' → ' + item.current.model_version);
        }
        append(card, 'small', (item.current.provenance === 'stock_job' ? '个股作业归档' : '指数封存') +
          ' · ' + (item.current.model_version || '模型版本未提供'));
        const sources = append(card, 'div', '');
        if (item.previous) link(sources, item.previous, '前一原档 ↗');
        link(sources, item.current, '本次原档 ↗');
        chartLink(sources, item.current);
      }
      more.hidden = events.length <= shown;
    }
    async function read() {
      const current = ++version, id = assetId;
      retry.hidden = true;
      if (!id) return;
      state.textContent = '正在核对封存目录…';
      try {
        const index = await api.fetchResult('watchlist-archive/index.json');
        if (current !== version) return;
        if (index.reason || index.data?.schema_version !== 1 || !index.data.assets) throw Error();
        const entry = index.data.assets[id];
        if (!entry) {
          controls.hidden = true;
          doc = null;
          records.replaceChildren(); more.hidden = true;
          state.textContent = id.startsWith('stock:') && !index.data.stock_jobs_available
            ? '本次构建未取得个股归档目录。已有行情和本机记录仍可查看。'
            : '该标的暂无已核对原档。已有行情和本机记录仍可查看。';
          return;
        }
        const path = 'watchlist-archive/' + id.replace(':', '-') + '.json';
        if (entry.path !== path) throw Error();
        const result = await api.fetchResult(path);
        if (current !== version) return;
        const candidate = result.data;
        if (result.reason || candidate?.schema_version !== 1 || candidate.asset_id !== id ||
            !Array.isArray(candidate.events) || !Array.isArray(candidate.observations) || !Array.isArray(candidate.gaps)) throw Error();
        doc = candidate;
        if (!day.value) day.value = doc.observations.at(-1)?.asof || '';
        controls.hidden = false;
        draw();
      } catch {
        if (current !== version) return;
        state.textContent = '封存记录读取失败。' + (doc ? '保留上次读取的原档。' : '仍可查看行情与本机记录。');
        retry.hidden = false;
      }
    }
    function select(id, asof) {
      const pinned = validDay(asof) ? asof : '';
      if (id === assetId && pinned === replayDay) return;
      assetId = id; replayDay = pinned; doc = null; shown = 3;
      controls.hidden = true; more.hidden = true; records.replaceChildren();
      const returnedDay = id === saved.get('kind') + ':' + saved.get('code') && validDay(saved.get('archiveThrough'))
        ? saved.get('archiveThrough') : '';
      mode.value = pinned || returnedDay ? 'close' : 'all'; day.value = pinned || returnedDay;
      mode.disabled = !!pinned;
      day.disabled = !!pinned;
      read();
    }
    mode.addEventListener('change', () => { shown = 3; draw(); });
    day.addEventListener('input', () => { shown = 3; draw(); });
    more.addEventListener('click', () => { shown += 10; draw(); });
    retry.addEventListener('click', read);
    return { select, read };
  }
  return { bind, archiveView, sourceLink };
});
