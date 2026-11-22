(function (global) {
  'use strict';

  function escape(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (character) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character];
    });
  }

  function percent(value) {
    return value == null || !Number.isFinite(Number(value))
      ? '—'
      : (Number(value) * 100).toFixed(0) + '%';
  }

  function evidenceFor(status, levels) {
    var evidence = global.LPPL.ev(status, levels);
    if (/^fail/i.test(evidence.code)) evidence.show = false;
    return evidence;
  }

  function render(validation, levels) {
    var rows = Array.isArray(validation) ? validation : [];
    var body = rows.map(function (row) {
      var evidence = evidenceFor(row.status, levels);
      var show = evidence.show;
      var eventCount = row.n == null ? row.events : row.n;
      var eventText = evidence.code === 'descriptive'
        ? 'n=' + escape(eventCount)
        : escape(row.events);
      var note = show ? row.note || '' : '';
      if (evidence.code === 'descriptive') note = (note ? note + '；' : '') + '历史分位';
      return '<tr><td>' + escape(row.split) + '</td><td>' + (show ? eventText : '—') +
        '</td><td>' + (show ? percent(row.hit) : '—') +
        '</td><td>' + (show ? percent(row.false_alarm) : '—') +
        '</td><td>' + (show ? escape(row.brier == null ? '—' : row.brier) : '—') +
        '</td><td>' + escape(evidence.label) + '</td><td>' + escape(note) + '</td></tr>';
    }).join('');

    return '<div class="pn"><div class="scroll-x"><table><thead><tr><th>阶段</th><th>事件数</th><th>提前报警比例</th><th>报警后未见顶比例</th><th>ΔBrier</th><th>证据</th><th>说明</th></tr></thead><tbody>' +
      body + '</tbody></table></div><p class="honest">开发段有信号，校准段与测试段未通过；所以本站只描述，不给概率。</p></div>';
  }

  global.BacktestBenchView = { render: render };
})(window);
