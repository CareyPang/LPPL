(function (root) {
  'use strict';

  var own = function (value, key) {
    return value != null && Object.prototype.hasOwnProperty.call(value, key);
  };

  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    var time = Date.parse(value + 'T00:00:00Z');
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
  }

  function forScale(source, scale) {
    var entries;
    if (own(source, 'scale_clusters')) entries = source.scale_clusters;
    else if (own(source, 'clusters')) entries = source.clusters;
    else return null;
    if (!entries || !own(entries, scale) || !Array.isArray(entries[scale])) return null;

    return entries[scale]
      .map(function (cluster, index) {
        if (!cluster) return null;
        if (cluster.share == null) return null;
        var share = Number(cluster.share);
        if (!validDate(cluster.q20_date) || !validDate(cluster.q80_date) || !Number.isFinite(share)) return null;
        var safe = {
          rank: 'secondary',
          share: share,
          q20_date: cluster.q20_date,
          q80_date: cluster.q80_date,
          _index: index,
        };
        if (cluster.n != null && Number.isFinite(Number(cluster.n))) safe.n = Number(cluster.n);
        if (cluster.n_scale != null && Number.isFinite(Number(cluster.n_scale))) safe.n_scale = Number(cluster.n_scale);
        return safe;
      })
      .filter(Boolean)
      .sort(function (a, b) { return b.share - a.share || a._index - b._index; })
      .map(function (cluster, index) {
        var safe = {
          rank: index === 0 ? 'main' : 'secondary',
          share: cluster.share,
          q20_date: cluster.q20_date,
          q80_date: cluster.q80_date,
        };
        if (own(cluster, 'n')) safe.n = cluster.n;
        if (own(cluster, 'n_scale')) safe.n_scale = cluster.n_scale;
        return safe;
      });
  }

  function label(cluster) {
    return cluster && cluster.rank === 'main' ? '主簇' : '次级簇';
  }

  function shareText(cluster) {
    return cluster && Number.isFinite(Number(cluster.share))
      ? '占 ' + Math.round(Number(cluster.share) * 100) + '%'
      : '';
  }

  var api = {
    NOTE: '占比 = 占该尺度合格拟合的比例，不是概率；区间为簇内 t_c 的 20–80% 分位，不是顶部日期；未校准，仅供参考。',
    forScale: forScale,
    label: label,
    shareText: shareText,
  };
  root.CPTopClusters = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
