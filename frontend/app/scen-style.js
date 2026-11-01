/* 临界点 · 历史情景区间的统一绘制样式（backtest.html 与 index.html 共用）
   只负责画法，不含任何数据或模型计算。输入全部来自 window.LPPL 取回的静态 JSON。 */
(function (G) {
  'use strict';
  const WARN = '#FFB800', REAL = '#4DA3FF';
  const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')'; };
  const SCN = {
    WARN, REAL, rgba,
    /* 同屏截止日多于该数量时进入"密集模式"：不画连接线，区间线更细，重叠处自然叠亮 */
    DENSE: 60,
    /* 一条历史情景区间：截止日收盘价 y 处，从 x0 向右连到区间 [xa, xb]。
       o = { x0, xa, xb, y, hot, dense } */
    drawRange(ctx, o) {
      const y = Math.round(o.y) + 0.5, hot = !!o.hot, dense = !!o.dense;
      if (!dense || hot) {
        ctx.strokeStyle = rgba(WARN, hot ? 0.75 : 0.2); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(o.x0, y); ctx.lineTo(o.xa, y); ctx.stroke();
        ctx.fillStyle = rgba(WARN, hot ? 1 : 0.5);
        ctx.fillRect(Math.round(o.x0) - 1, Math.round(o.y) - 1, 3, 3);
      }
      ctx.strokeStyle = rgba(WARN, hot ? 1 : dense ? 0.38 : 0.6);
      ctx.lineWidth = hot ? 4 : dense ? 1.5 : 3;
      ctx.beginPath(); ctx.moveTo(o.xa, y); ctx.lineTo(Math.max(o.xa + 2, o.xb), y); ctx.stroke();
      ctx.lineWidth = 1;
    },
    /* 事后确认顶的三角标记，(x, y) 为三角尖端 */
    drawTop(ctx, x, y) {
      ctx.fillStyle = REAL; ctx.beginPath();
      ctx.moveTo(x, y); ctx.lineTo(x - 5, y - 8); ctx.lineTo(x + 5, y - 8); ctx.closePath(); ctx.fill();
    },
  };
  G.SCN = SCN;
})(window);
