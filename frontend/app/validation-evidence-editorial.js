/* Independent preview: show only evidence carried by the selected snapshot. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root && root.document) root.LPPLValidationEvidence = api.mount(root.document);
})(typeof window === 'undefined' ? null : window, function () {
  'use strict';
  const E = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const stages = [{ key: 'cal', title: '校准证据', subtitle: '规则在留出区间是否仍然成立' }, { key: 'test', title: '最终测试证据', subtitle: '冻结规则能否通过最终检验' }];
  const allowed = new Set(['dev', 'cal', 'test', 'cal_fragile', 'descriptive']);
  function stageOf(row) {
    const s = String(row.split || '').toLowerCase();
    if (/校准|calibration|^cal(?:\b|_)/.test(s)) return 'cal';
    if (/测试|test/.test(s)) return 'test';
    if (/开发|development|^dev(?:\b|_)/.test(s)) return 'dev';
    return '';
  }
  function showValues(row) {
    return allowed.has(row.status) && (row.status !== 'descriptive' || Number.isFinite(row.n) && row.n > 0);
  }
  function statusLabel(row, levels) {
    const s = row.status || 'none';
    if (/^fail/.test(s) || s === 'dev_failed') return '未通过';
    if (s === 'none') return '无有效证据';
    if (s === 'dev_only') return '仅开发段证据';
    if (s === 'pending_cal' || s === 'pending_test') return '等待验证';
    if (s === 'cal_fragile') return '证据脆弱';
    return levels[s] || ({ dev: '开发段证据', cal: '校准段记录', test: '测试段记录', descriptive: '描述性记录' })[s] || '证据等级未识别';
  }
  // Controlled, non-numeric explanations of the supplied validation notes.
  function reasons(row) {
    const note = String(row.note || ''), out = [];
    if (note.includes('不优于历史基率')) out.push('概率模型未显示优于历史基率的证据。');
    if (note.includes('LPPLS 置信度无组合通过')) out.push('LPPLS 置信度的被检验组合未通过。');
    if (/留出/.test(note) && /翻转|转正|不满足/.test(note)) out.push('稳健性检查未支持将结果升级为可靠的样本外证据。');
    if (note.includes('多重比较') || note.includes('Holm')) out.push('记录包含多重比较修正；名义结果不能直接视为稳健通过。');
    return out;
  }
  function metrics(row) {
    if (!showValues(row)) return [];
    const out = [];
    if (Number.isInteger(row.events) && row.events >= 0) out.push(['事件样本', 'n=' + row.events]);
    if (row.status === 'descriptive') out.push(['描述样本', 'n=' + row.n + ' · 历史分位，不是预测']);
    for (const [key, label] of [['hit', '提前报警比例'], ['false_alarm', '报警后未见顶比例']]) {
      if (Number.isFinite(row[key]) && row[key] >= 0 && row[key] <= 1) out.push([label, (row[key] * 100).toFixed(0) + '%']);
    }
    if (typeof row.brier === 'string' && row.brier) out.push(['Brier 记录', row.brier]);
    else if (Number.isFinite(row.brier)) out.push(['Brier 记录', String(row.brier)]);
    return out;
  }
  function buildView(R, conclusion) {
    const J = R.J || {}, validation = Array.isArray(J.validation) ? J.validation : [];
    const levels = J.evidence_levels || {};
    const results = stages.map(stage => {
      const rows = validation.map((row, index) => ({ row, index })).filter(x => stageOf(x.row) === stage.key);
      return { ...stage, rows: rows.map(({ row, index }) => ({
        split: row.split || '阶段未提供', status: row.status || 'none', label: statusLabel(row, levels),
        metrics: metrics(row), reasons: reasons(row), show: showValues(row),
        note: showValues(row) ? row.note || '' : '', source: 'validation[' + index + ']'
      })) };
    });
    const dev = validation.filter(row => stageOf(row) === 'dev');
    return { name: R.sym && R.sym.label || J.name || J.symbol || '当前标的', asof: R.asof || J.asof || '未提供',
      conclusion: conclusion || '当前记录未提供结论', model: J.model_version || '记录未提供', data: J.data_version || '记录未提供',
      evidence: (R.top && R.top.lppls_confidence || {}).evidence || 'none',
      historical: !R.latest, stages: results, dev: dev.map(row => ({ label: statusLabel(row, levels), split: row.split || '', metrics: metrics(row) })) };
  }
  function renderView(view) {
    const metricHTML = list => list.length ? '<dl class="validation-metrics">' + list.map(([k,v]) => '<div><dt>' + E(k) + '</dt><dd>' + E(v) + '</dd></div>').join('') + '</dl>' : '';
    return '<div class="validation-context"><p class="validation-symbol">' + E(view.name) + ' <span>· 截止 ' + E(view.asof) + '</span></p><p class="validation-conclusion">' + E(view.conclusion) + '</p><span class="evb">' + E(view.evidence) + '</span></div>' +
      '<p id="validation-scope" class="validation-scope">这里展示该快照附带的模型整体验证汇总，涉及多个指数；它不是这一条结论的单独检验成绩。' + (view.historical ? '<strong>这是回顾性验证：校准和测试可能晚于所选历史截止日，不属于当时已知信息。</strong>' : '验证结果用于说明模型的适用边界。') + '</p>' +
      '<div class="validation-grid">' + view.stages.map(stage => '<section class="validation-card"><p class="blk-k">' + E(stage.subtitle) + '</p><h3>' + E(stage.title) + '</h3>' +
        (stage.rows.length ? stage.rows.map(row => '<div class="validation-record"><span class="validation-status">' + E(row.label) + '</span><p class="validation-period">' + E(row.split) + '</p>' +
          (row.reasons.length ? '<ul class="validation-reasons">' + row.reasons.map(text => '<li>' + E(text) + '</li>').join('') + '</ul>' : '<p class="validation-empty">' + (row.show ? '以下为这份记录提供的验证指标。' : '当前等级不支持展示模型数值，不能据此认定验证通过。') + '</p>') +
          metricHTML(row.metrics) + (!row.show ? '<p class="validation-gate">命中比例、误报比例和 Brier 数值按证据等级隐藏。</p>' : '') +
          (row.note ? '<p class="validation-note">' + E(row.note) + '</p>' : '') + '<p class="validation-source">记录位置 · ' + E(row.source) + ' · ' + E(row.status) + '</p></div>').join('') : '<p class="validation-empty">当前快照没有提供这一阶段的验证记录。</p>') + '</section>').join('') + '</div>' +
      '<details class="validation-dev"><summary>开发段记录与数据版本</summary>' + (view.dev.length ? view.dev.map(row => '<p>' + E(row.split) + ' · ' + E(row.label) + '</p>' + metricHTML(row.metrics)).join('') : '<p>未提供开发段记录。</p>') +
      '<dl class="validation-meta"><div><dt>模型版本</dt><dd>' + E(view.model) + '</dd></div><div><dt>数据版本</dt><dd>' + E(view.data) + '</dd></div></dl></details>' +
      '<div class="validation-footer"><span>区间是情景描述，不是精确顶部日期。</span><button type="button" id="validation-table" class="bt">查看完整三段表 ↓</button></div>';
  }
  function mount(doc) {
    const trigger = doc.getElementById('conclusion-open'), dialog = doc.getElementById('validation-evidence');
    let current = null;
    function reset() { current = null; trigger.disabled = true; if (dialog.open) dialog.close(); }
    function update(R, conclusion) { current = buildView(R, conclusion); trigger.disabled = false; }
    trigger.addEventListener('click', () => {
      if (!current) return;
      doc.getElementById('validation-content').innerHTML = renderView(current);
      dialog.showModal();
      doc.getElementById('validation-title').focus({ preventScroll: true });
      dialog.scrollTop = 0;
      doc.getElementById('validation-table').addEventListener('click', () => {
        dialog.close();
        const tab = doc.getElementById('bt-1'); tab.click(); tab.focus({ preventScroll: true });
        tab.scrollIntoView({ block: 'start', behavior: 'auto' });
      });
    });
    doc.getElementById('validation-close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', e => {
      if (e.target !== dialog) return;
      const r = dialog.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close();
    });
    return { update, reset };
  }
  return { buildView, renderView, showValues, stageOf, mount };
});
