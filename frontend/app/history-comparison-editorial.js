/* Independent history comparison. Reads published frames supplied by the page; no model or data fetch. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.LPPLHistoryComparison = api;
    const start = () => {
      const host = root.document.getElementById('history-comparison');
      if (host) api.mount(host, root);
    };
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', start, { once: true });
    else start();
  }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const E = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
  const SPLIT = { dev: '开发段', cal: '校准段', test: '测试段' };
  const LABEL = { dev: '开发段证据', cal: '校准段证据', test: '测试段证据', cal_fragile: '校准段脆弱', dev_only: '仅开发段证据', dev_failed: '开发段未通过', none: '无证据', fail: '未通过', fail_i: '判据未通过', fail_i_iii: '判据未通过', pending_cal: '待校准', pending_test: '待测试', descriptive: '描述性' };
  const allowed = code => ['dev', 'cal', 'test', 'cal_fragile', 'descriptive'].includes(code);
  const sample = frame => Number.isInteger(frame.n) && frame.n >= 0 ? frame.n : null;
  const evidence = (frame, history) => typeof frame.evidence === 'string' ? frame.evidence : history.evidence || 'none';

  function interval(frame, scale) {
    const value = frame.w && frame.w[scale];
    return Array.isArray(value) && value.length === 2 && value.every(date) && value[0] <= value[1] ? value : null;
  }
  function records(history) {
    const rows = history && (history.fr || history.frames);
    if (!Array.isArray(rows)) return [];
    const unique = new Map();
    rows.forEach(row => { if (row && date(row.asof) && finite(row.close) && row.close > 0) unique.set(row.asof, row); });
    return [...unique.values()].sort((a, b) => a.asof.localeCompare(b.asof));
  }
  function defaults(frames, symbol) {
    const has = asof => frames.some(row => row.asof === asof);
    if (symbol === 'sh000001' && has('2007-10-12') && has('2015-06-12')) return ['2007-10-12', '2015-06-12'];
    const withWindow = frames.filter(frame => interval(frame, '6-12m') || interval(frame, '12-24m'));
    const available = withWindow.length >= 2 ? withWindow : frames;
    return available.length ? [available[0].asof, available[available.length - 1].asof] : ['', ''];
  }
  function fieldValues(frame, history) {
    const ev = evidence(frame, history), n = sample(frame);
    const numeric = allowed(ev) && (ev !== 'descriptive' || n > 0);
    const showInterval = ev === 'dev_only' || numeric;
    const windowText = scale => {
      if (!showInterval) return '当前证据等级不展示区间';
      const w = interval(frame, scale);
      return w ? w.join(' 至 ') : '该日未提供区间';
    };
    return [
      ['asof', '历史截止日', frame.asof],
      ['close', '当日收盘', frame.close.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })],
      ['split', '数据阶段', SPLIT[frame.split] || frame.split || '记录未提供'],
      ['evidence', '证据等级', LABEL[ev] || (/^fail/.test(ev) ? '未通过' : '未识别等级：不展示模型数字')],
      ['window6', '6–12 月档情景区间', windowText('6-12m')],
      ['window12', '12–24 月档情景区间', windowText('12-24m')],
      ['sample', '样本数', n == null ? '记录未提供' : numeric ? 'n=' + n : '当前证据等级不展示数字'],
      ['model', '模型版本', frame.model_version || history.model_version || '记录未提供'],
      ['data', '数据版本', frame.data_version || history.data_version || '记录未提供'],
      ['validation', '该截止日的校准／测试结果', '历史帧未提供独立验证结果'],
      ['interpretation', '阅读边界', ev === 'descriptive' ? '历史分位，不是预测' : '历史情景区间，不是峰值日预测']
    ];
  }
  function comparison(history, a, b) {
    const rows = records(history), left = rows.find(row => row.asof === a), right = rows.find(row => row.asof === b);
    if (!left || !right) return null;
    const A = fieldValues(left, history), B = fieldValues(right, history);
    return { left, right, same: a === b, rows: A.map((value, i) => ({ key: value[0], label: value[1], a: value[2], b: B[i][2], changed: value[2] !== B[i][2] })) };
  }
  function replayLink(symbol, asof, replays) {
    if (!((replays || {})[symbol] || []).includes(asof)) return null;
    return 'workstation-editorial.html?' + new URLSearchParams({ code: symbol, asof });
  }
  function createState() {
    const state = { symbol: '', H: null, frames: [], a: '', b: '', selected: '' };
    return {
      state,
      reset(symbol) { Object.assign(state, { symbol: symbol || '', H: null, frames: [], a: '', b: '', selected: '' }); },
      ready(detail, current) {
        if (!detail || !detail.H || !detail.symbol || (state.symbol && detail.symbol !== state.symbol)) return false;
        if (current && (current.symbol !== detail.symbol || current.H !== detail.H)) return false;
        if (detail.H.symbol && detail.H.symbol !== detail.symbol) return false;
        const frames = records(detail.H);
        if (!frames.length) return false;
        const [a, b] = defaults(frames, detail.symbol);
        Object.assign(state, { symbol: detail.symbol, H: detail.H, frames, a, b, selected: '' });
        return true;
      },
      select(detail) {
        if (!state.H || !detail || detail.symbol !== state.symbol || (detail.H && detail.H !== state.H)) return false;
        const asof = detail.frame && detail.frame.asof;
        if (!state.frames.some(frame => frame.asof === asof)) return false;
        state.selected = asof; return true;
      },
      set(slot, asof) {
        if (!['a', 'b'].includes(slot) || !state.frames.some(frame => frame.asof === asof)) return false;
        state[slot] = asof; return true;
      },
      swap() { const old = state.a; state.a = state.b; state.b = old; }
    };
  }

  function mount(host, win) {
    const controller = createState(), state = controller.state;
    host.classList.add('history-compare');
    host.innerHTML = `<div class="hc-heading"><div><p class="hc-eyebrow">时间对照</p><h2 id="hc-title">两个截止日，当时的记录并排看</h2></div><span class="hc-index" id="hc-index">等待历史记录</span></div>
      <p class="hc-intro">对照同一指数在两个已发布截止日的记录。只突出字段变化，不由此计算预测准确率。</p>
      <p id="hc-loading" role="status">历史记录载入后，可选择两个截止日。</p>
      <div id="hc-body" hidden>
        <div class="hc-controls"><div class="hc-date"><label for="hc-date-a"><span class="hc-letter">A</span> 截止日</label><select id="hc-date-a"></select></div><button id="hc-swap" class="hc-swap" type="button" aria-label="交换 A 和 B 的截止日">交换 ⇄</button><div class="hc-date"><label for="hc-date-b"><span class="hc-letter hc-letter-b">B</span> 截止日</label><select id="hc-date-b"></select></div></div>
        <div class="hc-pin"><p id="hc-selected">在图中查看一个历史截止日，可加入对照。</p><button type="button" id="hc-use-a" disabled>加入 A</button><button type="button" id="hc-use-b" disabled>加入 B</button></div>
        <p class="hc-status" id="hc-status" role="status" aria-live="polite"></p>
        <div class="hc-table-wrap"><table class="hc-table"><caption class="hc-sr">同一指数两个历史截止日的记录比较。标有“不同”的行表示字段内容不同。</caption><colgroup><col class="hc-col-label"><col><col></colgroup><thead><tr><th scope="col">记录字段</th><th scope="col" id="hc-head-a"></th><th scope="col" id="hc-head-b"></th></tr></thead><tbody id="hc-rows"></tbody></table></div>
        <div class="hc-actions"><div><button type="button" id="hc-show-a">在图中查看 A</button><span id="hc-replay-a"></span></div><div><button type="button" id="hc-show-b">在图中查看 B</button><span id="hc-replay-b"></span></div><button type="button" id="hc-show-both">显示两日所在范围</button></div>
        <p class="hc-footnote">区间按各截止日的数据计算；阶段划分与证据等级来自当前历史导出，不代表当时已完成校准或测试。历史帧没有独立验证结果时，不用最新模型的验证成绩代替。收盘为行情记录，不是模型输出。</p>
      </div>`;
    const $ = id => host.querySelector('#' + id);
    const context = () => win.LPPLHistoryPreview && win.LPPLHistoryPreview.getContext();
    const motion = () => win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
    function renderSelected() {
      $('hc-selected').textContent = state.selected ? '最近查看：' + state.selected : '在图中查看一个历史截止日，可加入对照。';
      $('hc-use-a').disabled = $('hc-use-b').disabled = !state.selected;
    }
    function render() {
      const value = comparison(state.H, state.a, state.b);
      if (!value) return;
      $('hc-date-a').value = state.a; $('hc-date-b').value = state.b;
      $('hc-head-a').innerHTML = '<span class="hc-letter">A</span><span>' + E(state.a) + '</span>';
      $('hc-head-b').innerHTML = '<span class="hc-letter hc-letter-b">B</span><span>' + E(state.b) + '</span>';
      const changes = value.rows.filter(row => row.changed).length;
      $('hc-status').textContent = value.same ? 'A、B 当前为同一截止日；选择另一个日期查看差异。' : changes + ' 项字段不同 · 暖金底色标出变化';
      $('hc-rows').innerHTML = value.rows.map(row => `<tr${row.changed ? ' class="hc-changed"' : ''}><th scope="row">${E(row.label)}${row.changed ? '<span class="hc-change-label">不同</span>' : ''}</th><td>${E(row.a).replace(/ 至 /g, '<span class="hc-until">至</span>')}</td><td>${E(row.b).replace(/ 至 /g, '<span class="hc-until">至</span>')}</td></tr>`).join('');
      for (const slot of ['a', 'b']) {
        const link = replayLink(state.symbol, state[slot], win.LPPL && win.LPPL.REPLAYS);
        $('hc-replay-' + slot).innerHTML = link ? '<a href="' + E(link) + '">打开该日工作站 ↗</a>' : '<span class="hc-unavailable">该日仅有历史区间记录，未发布完整工作站快照</span>';
      }
      renderSelected();
    }
    function reset(event) {
      const detail = event && event.detail;
      controller.reset(detail && detail.symbol || (context() || {}).symbol);
      $('hc-body').hidden = true; $('hc-loading').hidden = false;
      $('hc-loading').textContent = '当前没有已加载的历史记录；载入后可选择两个截止日。';
      $('hc-rows').innerHTML = ''; $('hc-date-a').innerHTML = ''; $('hc-date-b').innerHTML = '';
      const sym = win.LPPL && win.LPPL.resolve(state.symbol);
      $('hc-index').textContent = sym ? sym.name : '等待历史记录';
      renderSelected();
    }
    function ready(event) {
      if (!controller.ready(event.detail, context())) return;
      const sym = win.LPPL && win.LPPL.resolve(state.symbol);
      $('hc-index').textContent = sym ? sym.name : state.symbol;
      const options = state.frames.map(frame => '<option value="' + E(frame.asof) + '">' + E(frame.asof) + ((interval(frame, '6-12m') || interval(frame, '12-24m')) ? ' · 有区间' : ' · 无区间') + '</option>').join('');
      $('hc-date-a').innerHTML = options; $('hc-date-b').innerHTML = options;
      $('hc-body').hidden = false; $('hc-loading').hidden = true;
      render();
    }
    function selected(event) { if (controller.select(event.detail)) renderSelected(); }
    for (const slot of ['a', 'b']) {
      $('hc-date-' + slot).addEventListener('change', event => { if (controller.set(slot, event.target.value)) render(); });
      $('hc-use-' + slot).addEventListener('click', () => { if (controller.set(slot, state.selected)) render(); });
      $('hc-show-' + slot).addEventListener('click', event => {
        if (win.LPPLHistoryPreview && state.H) win.LPPLHistoryPreview.selectFrame(state[slot], event.currentTarget, true);
      });
    }
    $('hc-swap').addEventListener('click', () => { controller.swap(); render(); });
    $('hc-show-both').addEventListener('click', () => {
      if (!win.LPPLHistoryPreview || !state.H) return;
      win.LPPLHistoryPreview.showDates(state.a, state.b);
      const chart = win.document.getElementById('chart');
      if (chart) chart.scrollIntoView({ block: 'start', behavior: motion() });
    });
    win.addEventListener('lppl-history-reset', reset);
    win.addEventListener('lppl-history-ready', ready);
    win.addEventListener('lppl-history-select', selected);
    const initial = context();
    if (initial && initial.H) ready({ detail: initial });
    else if (initial) reset({ detail: initial });
    return { controller, destroy() {
      win.removeEventListener('lppl-history-reset', reset);
      win.removeEventListener('lppl-history-ready', ready);
      win.removeEventListener('lppl-history-select', selected);
      host.innerHTML = '';
    } };
  }
  return { E, date, interval, records, defaults, fieldValues, comparison, replayLink, createState, mount };
});
