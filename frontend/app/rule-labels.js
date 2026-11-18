(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RuleLabels = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  var RULES = Object.freeze({
    box: Object.freeze({
      id: 'box',
      name: '形态框',
      short: '区间与占比用“形态框”规则：只看拟合形状，不含振荡次数和阻尼条件',
      source: '区间来源：形态框规则（不含振荡/阻尼条件）',
    }),
    standard: Object.freeze({
      id: 'standard',
      name: 'FCO 标准过滤',
      short: '“合格拟合数”和“有合格拟合”用 FCO 标准过滤：另要求振荡约 0.8 个周期以上、阻尼与误差达标，比形态框严格',
    }),
  });
  var FOOTNOTE = '两者来自同一批拟合窗口、不同过滤规则；不是两套互相印证的结论。占比不是概率。';
  var EMPTY_REASONS = Object.freeze({
    not_computed: '这个尺度尚未计算',
    no_fit: '已计算，没有合格拟合（不代表风险较低）',
    no_cluster: '有合格拟合，但没有形成聚类区间',
    not_formal: '已形成候选区间，证据不足，不作正式提醒',
  });
  var EMPTY_SHORT = Object.freeze({
    not_computed: '未计算',
    no_fit: '无合格拟合',
    no_cluster: '未形成区间',
    not_formal: '证据不足',
  });

  function renderCaption(ruleIds) {
    var ids = Array.isArray(ruleIds) ? ruleIds.filter(function (id) { return RULES[id]; }) : [];
    var parts = ids.map(function (id) { return RULES[id].short; });
    if (ids.includes('box') && ids.includes('standard')) parts.push(FOOTNOTE);
    return parts.join('；');
  }

  function emptyReason(top, scale, hasCluster, evidenceSelectable) {
    var indicator = top && top.indicators && top.indicators[scale];
    var confidence = top && top.lppls_confidence && top.lppls_confidence[scale];
    if (!indicator || indicator.signal_status === 'not_computed' ||
        confidence == null || !Number.isFinite(confidence)) return 'not_computed';
    if (confidence === 0) return 'no_fit';
    var clusterExists = Array.isArray(hasCluster) ? hasCluster.length > 0 : hasCluster === true;
    if (confidence > 0 && !clusterExists) return 'no_cluster';
    if (clusterExists && evidenceSelectable !== true) return 'not_formal';
    return null;
  }

  function reasonText(reason) {
    return EMPTY_REASONS[reason] || '';
  }

  function shortText(reason) {
    return EMPTY_SHORT[reason] || '';
  }

  return {
    RULES: RULES,
    FOOTNOTE: FOOTNOTE,
    EMPTY_REASONS: EMPTY_REASONS,
    EMPTY_SHORT: EMPTY_SHORT,
    renderCaption: renderCaption,
    emptyReason: emptyReason,
    reasonText: reasonText,
    shortText: shortText,
  };
});
