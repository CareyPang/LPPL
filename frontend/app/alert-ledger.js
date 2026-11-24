(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CPAlertLedger = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var DAY = 86400000;

  function dateValue(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    var time = Date.parse(value + 'T00:00:00Z');
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value ? time : null;
  }

  function frameWindow(frame, scale) {
    var value = frame && frame.w && frame.w[scale];
    if (Array.isArray(value) && value.length >= 2) return [value[0], value[1]];
    var clusters = frameClusters(frame, scale);
    return clusters && clusters.length
      ? [clusters[0].q20_date, clusters[0].q80_date]
      : null;
  }

  function frameClusters(frame, scale) {
    var collection = frame && frame.clusters;
    if (!collection || !Object.prototype.hasOwnProperty.call(collection, scale) ||
        !Array.isArray(collection[scale])) return null;
    return collection[scale]
      .map(function (cluster, index) {
        if (!cluster || dateValue(cluster.q20_date) === null ||
            dateValue(cluster.q80_date) === null || cluster.share == null ||
            !Number.isFinite(Number(cluster.share))) return null;
        var safe = {
          rank: 'secondary',
          share: Number(cluster.share),
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
        if (Object.prototype.hasOwnProperty.call(cluster, 'n')) safe.n = cluster.n;
        if (Object.prototype.hasOwnProperty.call(cluster, 'n_scale')) safe.n_scale = cluster.n_scale;
        return safe;
      });
  }

  function isoFromTime(ms) {
    if (!Number.isFinite(ms)) return null;
    return new Date(ms).toISOString().slice(0, 10);
  }

  /**
   * 估算单个主簇/区间的临界时间中位数日期（q50_date）：
   * 若后端已提供 q50_date 则直接采用，否则取 [q20_date, q80_date] 的对称中点日期。
   */
  function clusterMedianDate(cluster, fallbackWindow) {
    if (cluster && dateValue(cluster.q50_date) !== null) return cluster.q50_date;
    var lo = cluster && cluster.q20_date ? cluster.q20_date : (fallbackWindow && fallbackWindow[0]);
    var hi = cluster && cluster.q80_date ? cluster.q80_date : (fallbackWindow && fallbackWindow[1]);
    var t0 = dateValue(lo), t1 = dateValue(hi);
    if (t0 === null || t1 === null) return null;
    return isoFromTime(Math.round((t0 + t1) / 2));
  }

  /**
   * 连续 as-of 顶部区间不漂移检验（t_c Convergence / Non-Drifting Test）：
   * 追踪一个连续顶部聚类轮次中每一周的主簇中位数 t_c_med：
   * - drift_ratio = Δ(t_c_med) / Δ(asof)：
   *   * 若连续 ≥ 3 周且 drift_ratio ≤ 0.35（且中位数总漂移 ≤ 21 自然日），判定为「高危锁定（locked）」——真顶部概率大幅提高；
   *   * 若连续 ≥ 2 周但 drift_ratio > 0.55（预测顶部随截止日同步后移），判定为「漂移观察（drifting）」——大概率是趋势追涨伪信号；
   *   * 其余为「观察收敛中（forming）」。
   */
  function analyzeRunConvergence(run, scale) {
    if (!Array.isArray(run) || !run.length) return null;
    var points = run.map(function (item) {
      var cls = frameClusters(item.frame, scale);
      var main = cls && cls[0] ? cls[0] : null;
      var q20 = main ? main.q20_date : item.window[0];
      var q80 = main ? main.q80_date : item.window[1];
      var med = clusterMedianDate(main, item.window);
      var t0 = dateValue(q20), t1 = dateValue(q80), tm = dateValue(med), ta = dateValue(item.frame.asof);
      return {
        asof: item.frame.asof,
        asof_ms: ta,
        q20_date: q20,
        q80_date: q80,
        median_date: med,
        median_ms: tm,
        width_days: (t0 !== null && t1 !== null) ? Math.max(0, Math.round((t1 - t0) / DAY)) : null,
        share: main ? main.share : null,
      };
    }).filter(function (p) { return p.asof_ms !== null && p.median_ms !== null; });

    if (!points.length) return null;
    var first = points[0], last = points[points.length - 1];
    // 稳健时间中位数：取本轮所有有效周主簇中位数的中位数（抗单周离群）
    var sortedMed = points.map(function (p) { return p.median_ms; }).sort(function (a, b) { return a - b; });
    var midIdx = Math.floor(sortedMed.length / 2);
    var clusterMedMs = sortedMed.length % 2
      ? sortedMed[midIdx]
      : Math.round((sortedMed[midIdx - 1] + sortedMed[midIdx]) / 2);
    var clusterMedianDateStr = isoFromTime(clusterMedMs);

    var elapsedDays = Math.max(0, Math.round((last.asof_ms - first.asof_ms) / DAY));
    var medianShiftDays = Math.round((last.median_ms - first.median_ms) / DAY);
    var driftRatio = elapsedDays >= 7 ? Number((medianShiftDays / elapsedDays).toFixed(2)) : null;

    // 统计从最近一帧往回看，连续多少周中位数落在一个 ±18 自然日窄带内（不往后漂移）
    var anchorMs = last.median_ms;
    var stableWeeks = 1;
    for (var i = points.length - 2; i >= 0; i -= 1) {
      if (Math.abs(points[i].median_ms - anchorMs) <= 18 * DAY) stableWeeks += 1;
      else break;
    }

    var widthNarrowing = first.width_days != null && last.width_days != null
      ? (last.width_days - first.width_days)
      : null;

    var status = 'forming';
    var label = '观察收敛中';
    var highConfidence = false;
    if (points.length === 1) {
      status = 'single';
      label = '单周初现';
    } else if (stableWeeks >= 3 && (driftRatio === null || driftRatio <= 0.35)) {
      status = 'locked';
      label = '高危锁定（连续 ' + stableWeeks + ' 周未漂移）';
      highConfidence = true;
    } else if (driftRatio !== null && driftRatio > 0.55) {
      status = 'drifting';
      label = '漂移观察（随时间后移）';
    } else if (stableWeeks >= 2) {
      status = 'converging';
      label = '初步锚定（连续 ' + stableWeeks + ' 周）';
    }

    return {
      status: status,
      label: label,
      high_confidence: highConfidence,
      weeks: points.length,
      stable_weeks: stableWeeks,
      median_date: clusterMedianDateStr,
      latest_median_date: last.median_date,
      median_shift_days: medianShiftDays,
      elapsed_days: elapsedDays,
      drift_ratio: driftRatio,
      width_days_first: first.width_days,
      width_days_last: last.width_days,
      width_delta_days: widthNarrowing,
    };
  }

  function episodes(frames, tops, scale) {
    var ordered = (Array.isArray(frames) ? frames : [])
      .map(function (frame, index) { return { frame: frame, index: index }; })
      .filter(function (item) { return item.frame && dateValue(item.frame.asof) !== null; })
      .sort(function (a, b) {
        return a.frame.asof < b.frame.asof ? -1 : a.frame.asof > b.frame.asof ? 1 : a.index - b.index;
      });
    var orderedTops = (Array.isArray(tops) ? tops : [])
      .filter(function (top) { return top && dateValue(top.date) !== null; })
      .slice()
      .sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; });
    var result = [], run = [];

    function flush() {
      if (!run.length) return;
      var first = run[0], last = run[run.length - 1];
      var firstWindow = first.window, lastWindow = last.window;
      var clusters = frameClusters(first.frame, scale);
      var lastClusters = frameClusters(last.frame, scale);
      var top = orderedTops.find(function (item) { return item.date > first.frame.asof; }) || null;
      var relation = null;
      if (top && dateValue(firstWindow[0]) !== null && dateValue(firstWindow[1]) !== null) {
        relation = top.date < firstWindow[0] ? 'before' :
          top.date <= firstWindow[1] ? 'inside' : 'after';
      }
      var main = clusters && clusters[0];
      var mainRelation = null;
      if (top && main) {
        mainRelation = top.date < main.q20_date ? 'before' :
          top.date <= main.q80_date ? 'inside' : 'after';
      }
      var convergence = analyzeRunConvergence(run, scale);
      var ep = {
        scale: scale,
        first_asof: first.frame.asof,
        last_asof: last.frame.asof,
        weeks: run.length,
        split: first.frame.split,
        window: firstWindow.slice(),
        last_window: lastWindow.slice(),
        clusters: clusters,
        last_clusters: lastClusters,
        next_top: top ? { date: top.date, max_dd: top.max_dd } : null,
        top_vs_window: relation,
        top_vs_main: mainRelation,
        days_to_top: top ? Math.round((dateValue(top.date) - dateValue(first.frame.asof)) / DAY) : null,
      };
      // 以非枚举属性附加收敛与时间中位数，严格保持 episodes() 原有可枚举字段向后兼容
      Object.defineProperty(ep, 'median_date', {
        value: convergence ? convergence.median_date : clusterMedianDate(main, firstWindow),
        enumerable: false,
      });
      Object.defineProperty(ep, 'convergence', {
        value: convergence,
        enumerable: false,
      });
      result.push(ep);
      run = [];
    }

    ordered.forEach(function (item) {
      var frame = item.frame, window = frameWindow(frame, scale);
      if (window) run.push({ frame: frame, window: window });
      else flush();
    });
    flush();
    return result;
  }

  /**
   * 返回「正在进行中（截至最后一帧仍活跃）」或最近一轮的高置信顶部收敛摘要，
   * 供指数/个股回测结论栏用文字直接提醒。
   */
  function latestConvergence(frames, tops, scale) {
    var eps = episodes(frames, tops, scale || '6-12m');
    if (!eps.length) return { active: null, latest: null, lockedCount: 0, total: 0 };
    var ordered = (Array.isArray(frames) ? frames : []).filter(function (f) { return f && f.asof; });
    var lastAsof = ordered.length ? ordered[ordered.length - 1].asof : null;
    var latest = eps[eps.length - 1];
    var active = (lastAsof && latest.last_asof === lastAsof) ? latest : null;
    var lockedCount = eps.filter(function (e) { return e.convergence && e.convergence.high_confidence; }).length;
    return { active: active, latest: latest, lockedCount: lockedCount, total: eps.length };
  }

  function lockedAsOf(frames, tops, scale) {
    scale = scale || '6-12m';
    var ordered = (Array.isArray(frames) ? frames : [])
      .filter(function (frame) { return frame && dateValue(frame.asof) !== null; })
      .slice()
      .sort(function (a, b) { return a.asof < b.asof ? -1 : a.asof > b.asof ? 1 : 0; });
    var result = new Map();
    ordered.forEach(function (frame) { result.set(frame.asof, null); });

    episodes(ordered, tops, scale).forEach(function (episode) {
      var run = [];
      ordered.forEach(function (frame) {
        if (frame.asof < episode.first_asof || frame.asof > episode.last_asof) return;
        var window = frameWindow(frame, scale);
        if (!window) return;
        run.push({ frame: frame, window: window });
        result.set(frame.asof, analyzeRunConvergence(run, scale));
      });
    });
    return result;
  }

  return {
    episodes: episodes,
    clusterMedianDate: clusterMedianDate,
    analyzeRunConvergence: analyzeRunConvergence,
    latestConvergence: latestConvergence,
    lockedAsOf: lockedAsOf,
  };
});
