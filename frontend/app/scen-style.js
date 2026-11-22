/* 临界点 · 历史情景区间的统一绘制样式（backtest.html 与 index.html 共用）
   只负责画法，不含任何数据或模型计算。输入全部来自 window.LPPL 取回的静态 JSON。 */
(function (G) {
  'use strict';
  const WARN = '#9A5B00', REAL = '#1F5FD6', FCO = '#D6303A', FCO_BOT = '#11845A';
  const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')'; };
  const CPSCN = {
    WARN, REAL, FCO, FCO_BOT, rgba,
    /* 同屏截止日多于该数量时进入"密集模式"：不画连接线，区间线更细，重叠处自然叠亮 */
    DENSE_PER_PX: 0.5,
    isDense(n, w) { return w > 0 && n / w > CPSCN.DENSE_PER_PX; },
    /* 一条历史情景区间：截止日收盘价 y 处，从 x0 向右连到区间 [xa, xb]。
       o = { x0, xa, xb, y, hot, dense, secondary } */
    drawRange(ctx, o) {
      const y = Math.round(o.y) + 0.5, hot = !!o.hot, dense = !!o.dense, secondary = !!o.secondary;
      if (!dense || hot) {
        ctx.strokeStyle = rgba(WARN, secondary ? hot ? 0.38 : 0.08 : hot ? 0.75 : 0.2); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(o.x0, y); ctx.lineTo(o.xa, y); ctx.stroke();
        ctx.fillStyle = rgba(WARN, secondary ? hot ? 0.55 : 0.2 : hot ? 1 : 0.5);
        ctx.fillRect(Math.round(o.x0) - 1, Math.round(o.y) - 1, 3, 3);
      }
      ctx.strokeStyle = rgba(WARN, secondary ? hot ? 0.7 : 0.28 : hot ? 1 : dense ? 0.38 : 0.6);
      ctx.lineWidth = secondary ? hot ? 2 : 1.5 : hot ? 4 : dense ? 1.5 : 3;
      if (secondary) ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(o.xa, y); ctx.lineTo(Math.max(o.xa + 2, o.xb), y); ctx.stroke();
      if (secondary) ctx.setLineDash([]);
      ctx.lineWidth = 1;
    },
    /* FCO 风格红色泡沫强度柱状图（底部向上，自动降噪分级）：
       o = { x, w, bottom, maxH, intensity, hot, locked, highThreshold }，intensity ∈ [0, 1]
       低于高置信门槛（默认 0.40）且未锁定的弱红柱自动淡化为背景参考，避免视觉噪音。 */
    TOP_HIGH_THRESHOLD: 0.40,
    BOT_HIGH_THRESHOLD: 0.50,
    drawFcoBar(ctx, o) {
      const v = Math.max(0, Math.min(1, Number(o.intensity) || 0));
      if (v <= 0) return;
      const thr = o.highThreshold != null ? Number(o.highThreshold) : CPSCN.TOP_HIGH_THRESHOLD;
      const highConf = Boolean(o.locked) || v >= thr;
      const h = Math.max(highConf ? 4 : 2, Math.round(v * o.maxH * (highConf ? 1 : 0.72)));
      const bw = Math.max(2, Math.round((o.w || 4) * (highConf ? 1 : 0.75)));
      const x = Math.round(o.x - bw / 2);
      const y = Math.round(o.bottom - h);
      const alpha = o.hot ? 0.85 : (highConf ? (0.36 + v * 0.44) : (0.07 + v * 0.14));
      ctx.fillStyle = rgba(FCO, alpha);
      ctx.fillRect(x, y, bw, h);
      if (o.locked) {
        ctx.fillStyle = FCO;
        ctx.fillRect(x, y - 2, bw, 2);
      }
    },
    /* FCO 风格绿色底部/负泡沫强度柱状图（底部向上，红顶绿底，自动降噪分级）：
       o = { x, w, bottom, maxH, intensity, hot, highThreshold }，intensity ∈ [0, 1]
       低于 0.50 共振门槛的弱绿柱降级为极淡背景参考，≥ 0.50 共振区高亮突出。 */
    drawFcoBottomBar(ctx, o) {
      const v = Math.max(0, Math.min(1, Number(o.intensity) || 0));
      if (v <= 0) return;
      const thr = o.highThreshold != null ? Number(o.highThreshold) : CPSCN.BOT_HIGH_THRESHOLD;
      const highConf = v >= thr;
      const h = Math.max(highConf ? 4 : 2, Math.round(v * o.maxH * (highConf ? 1 : 0.65)));
      const bw = Math.max(2, Math.round((o.w || 4) * (highConf ? 1 : 0.75)));
      const x = Math.round(o.x - bw / 2);
      const y = Math.round(o.bottom - h);
      const alpha = o.hot ? 0.85 : (highConf ? (0.36 + v * 0.44) : (0.06 + v * 0.12));
      ctx.fillStyle = rgba(FCO_BOT, alpha);
      ctx.fillRect(x, y, bw, h);
    },
    /* 严格 as-of 首次预警旗标（每轮泡沫第一次出现顶部聚类的截止日）：
       o = { x, y, top, bottom, label, active } */
    drawFirstAlert(ctx, o) {
      const x = Math.round(o.x) + 0.5;
      ctx.save();
      ctx.strokeStyle = rgba(FCO, o.active ? 0.92 : 0.52);
      ctx.lineWidth = o.active ? 1.6 : 1;
      ctx.setLineDash(o.active ? [] : [3, 3]);
      ctx.beginPath(); ctx.moveTo(x, o.top); ctx.lineTo(x, o.bottom); ctx.stroke();
      ctx.setLineDash([]);
      // 价格点圆环标记
      if (Number.isFinite(o.y)) {
        ctx.fillStyle = '#FFFFFF';
        ctx.strokeStyle = FCO;
        ctx.lineWidth = o.active ? 2.2 : 1.6;
        ctx.beginPath(); ctx.arc(x, o.y, o.active ? 4.5 : 3.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      }
      // 顶部红色旗标胶囊
      if (o.label) {
        ctx.font = '600 10px "JetBrains Mono","PingFang SC","Microsoft YaHei",sans-serif';
        const tw = ctx.measureText(o.label).width;
        const pw = tw + 10, ph = 16;
        const bx = Math.round(x - pw / 2), by = Math.round(o.top + 3);
        ctx.fillStyle = o.active ? FCO : rgba(FCO, 0.9);
        ctx.fillRect(bx, by, pw, ph);
        ctx.fillStyle = '#FFFFFF';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(o.label, x, by + ph / 2 + 0.5);
      }
      ctx.restore();
    },
    /* 事后确认顶的三角标记，(x, y) 为三角尖端 */
    drawTop(ctx, x, y) {
      ctx.fillStyle = REAL; ctx.beginPath();
      ctx.moveTo(x, y); ctx.lineTo(x - 5, y - 8); ctx.lineTo(x + 5, y - 8); ctx.closePath(); ctx.fill();
    },
  };
  G.CPSCN = CPSCN;
})(window);
