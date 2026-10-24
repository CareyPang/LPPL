/* 临界点 2.0 · 共用界面组件（桌面版与手机版共用）
   - 白话文案：见顶窗口、回落区、二波计划
   - SVG：未来路线图、信号带
   主题颜色从容器的 CSS 变量读取：--c-ink --c-ink-3 --c-line --c-top --c-bot --c-wave --c-real --c-bg */
(function (G) {
  'use strict';
  const CP = G.CP;
  const U = {};
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  U.esc = esc;
  const pct = (v, d) => (isFinite(v) ? (v * 100).toFixed(d === undefined ? 1 : d) + '%' : '—');
  const sp = (v, d) => (isFinite(v) ? (v >= 0 ? '+' : '') + (v * 100).toFixed(d === undefined ? 1 : d) + '%' : '—');
  U.pct = pct; U.sp = sp;
  const px = (v) => (isFinite(v) ? (v >= 1000 ? v.toFixed(0) : v >= 100 ? v.toFixed(1) : v.toFixed(2)) : '—');
  U.px = px;
  U.md = function (d, ref) {
    if (!d) return '—';
    const y = d.slice(0, 4), m = +d.slice(5, 7), dd = +d.slice(8, 10);
    return (ref && ref.slice(0, 4) !== y ? y + '年' : '') + m + '月' + dd + '日';
  };
  U.range = function (a, b, ref, lastDate) {
    const est = lastDate && b > lastDate ? '约 ' : '';
    return est + U.md(a, ref) + ' – ' + U.md(b, ref);
  };

  U.LEVEL = { high: '高', mid: '中', low: '低', none: '无' };

  /* ---------------- 白话结论 ---------------- */
  U.verdict = function (R) {
    const rm = R.rm, ph = R.phase.k, last = R.bars[R.bars.length - 1].date;
    const P = CP.PHASES.find((p) => p.k === ph);
    let head = '', sub = '';
    if (ph === 'crit') { head = '临界区：准备逃顶'; sub = '多个时间尺度同时指向 ' + U.range(rm.topW.loDate, rm.topW.hiDate, R.asof, last) + ' 见顶。'; }
    else if (ph === 'accel') { head = rm.topW ? '加速期：顶部结构正在形成' : '加速期：上涨在加速'; sub = rm.topW ? '已有少数尺度指向 ' + U.range(rm.topW.loDate, rm.topW.hiDate, R.asof, last) + '，一致度还不够高，先不动。' : '暂未出现合格的见顶窗口，持有并每周复查。'; }
    else if (ph === 'crash') { head = '破裂期：不要抄底'; sub = '自近期高点已回撤 ' + pct(1 - R.rm.close / R.rm.hi60) + '，底部条件尚未共振。'; }
    else if (ph === 'base') { head = '筑底期：分批进场'; sub = '底部多条件共振通过，按三批计划建仓。'; }
    else if (ph === 'wave2') { head = '二波：持有'; sub = '已收复一半以上跌幅，持有并重新监测下一个顶部。'; }
    else { head = '平稳期：无临界结构'; sub = '各尺度都没有合格的泡沫结构，没有逃顶信号。'; }
    return { head, sub, phase: P };
  };

  /* ---------------- 三段计划 ---------------- */
  U.plans = function (R) {
    const rm = R.rm, s = rm.sigma, last = R.bars[R.bars.length - 1].date;
    const trail = 1 - Math.exp(-1.5 * s * Math.sqrt(3));
    const crashTh = 2 * s * Math.sqrt(10);
    const st = rm.stats;
    const exit = { title: '逃顶计划', tone: 'top', rows: [] };
    if (rm.topW) {
      exit.lead = '见顶窗口 ' + U.range(rm.topW.loDate, rm.topW.hiDate, R.asof, last);
      exit.meta = rm.topW.n + ' 个时间尺度指向同一窗口 · 一致度 ' + pct(rm.conf, 0) + ' · 可信度' + U.LEVEL[rm.level];
      exit.rows.push(['窗口开启前 10 个交易日内', rm.conf >= CP.RULES.alertConf ? '先卖出一半仓位' : '一致度未到 15%，暂不减仓，继续观察']);
      exit.rows.push(['剩余一半', '移动止盈：从预警后的最高收盘回落 ' + pct(trail) + ' 就全部卖出']);
      exit.rows.push(['窗口结束 5 日后仍未破位', '视为误报，买回减掉的仓位']);
      if (rm.topPx) exit.rows.push(['窗口内的参考价位', px(rm.topPx[0]) + ' – ' + px(rm.topPx[1]) + '（按当前波动估算，不是目标价）']);
    } else {
      exit.lead = '暂无见顶窗口';
      exit.meta = '合格窗口 ' + R.scan.nq + '/' + R.scan.total + '，没有形成一致的临界时间';
      exit.rows.push(['当前', '不发逃顶信号；持有并每周复查一次']);
      exit.rows.push(['已在下跌中', '自 60 日高点回撤 ≥ ' + pct(crashTh) + ' 视为破位，清仓等待底部']);
    }
    const bot = { title: '抄底计划', tone: 'bot', rows: [] };
    if (rm.crash) {
      bot.lead = '预计回落区 ' + px(rm.crash.pxLo) + ' – ' + px(rm.crash.pxHi);
      bot.meta = '时间 ' + U.range(rm.crash.botLoDate, rm.crash.botHiDate, R.asof, last) + ' · 依据该标的过去 ' + st.n + ' 次同类回撤（幅度 ' + pct(st.depth[0], 0) + '–' + pct(st.depth[2], 0) + '，用时 ' + Math.round(st.days[0]) + '–' + Math.round(st.days[2]) + ' 个交易日）';
    } else {
      bot.lead = st.n >= 3 ? '历史同类回撤 ' + pct(st.depth[0], 0) + ' – ' + pct(st.depth[2], 0) : '历史回撤样本不足';
      bot.meta = st.n >= 3 ? '用时 ' + Math.round(st.days[0]) + '–' + Math.round(st.days[2]) + ' 个交易日（过去 ' + st.n + ' 次）。没有见顶窗口时不推算底部日期。' : '';
    }
    bot.rows.push(['不抄的情况', '跌幅不足 ' + pct(2.5 * s * Math.sqrt(10)) + '、调整不满 10 日、仍在创新低：一律不买']);
    bot.rows.push(['第一批 1/3', '跌幅、时间、止跌三项必要条件全满足，且总共 6 项里至少 4 项通过']);
    bot.rows.push(['第二批 1/3', '首批后 5 日不破低点，或较首批价上涨 ' + pct(Math.exp(s * Math.sqrt(5)) - 1)]);
    bot.rows.push(['止损', '收盘跌破调整低点 ' + pct(1 - Math.exp(-1.5 * s)) + ' 以上：全部卖出，重新等待']);
    const w2 = { title: '二波计划', tone: 'wave', rows: [] };
    if (rm.crash) {
      w2.lead = '二波参考 ' + px(rm.crash.wave2);
      w2.meta = '历史反弹中位数收复跌幅的 ' + pct(st.rebound[1], 0) + '（四分位 ' + pct(st.rebound[0], 0) + '–' + pct(st.rebound[2], 0) + '）';
    } else { w2.lead = '收复一半跌幅后满仓'; w2.meta = '二波目标需要先有见顶窗口和回落区'; }
    w2.rows.push(['第三批 1/3', '价格收复本轮跌幅的一半：补足仓位，进入二波']);
    w2.rows.push(['二波中', '重新运行顶部引擎；下一个见顶窗口出现时重复逃顶计划']);
    return [exit, bot, w2];
  };

  /* ---------------- SVG 工具 ---------------- */
  function sc(d0, d1, r0, r1) { const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0); return (v) => r0 + (v - d0) * k; }
  function niceStep(span, n) { const raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p; return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p; }
  function pathOf(pts) { let s = ''; pts.forEach((p, i) => { s += (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }); return s; }

  /* ---------------- 未来路线图 ---------------- */
  U.roadmapSVG = function (R, o) {
    o = o || {};
    const W = o.w || 1100, H = o.h || 440, padL = o.compact ? 8 : 16, padR = o.compact ? 46 : 64, padT = 28, padB = 30;
    const bars = R.bars, T = R.T, rm = R.rm, N = bars.length;
    const back = o.back || 150;
    const a = Math.max(0, T - back);
    let b = T + 40;
    if (rm.topW) b = Math.max(b, rm.topW.hi + 12);
    if (rm.crash) b = Math.max(b, rm.crash.botHi + 18);
    if (R.replay) b = Math.max(b, Math.min(N - 1, R.replay.wave2.i + 8));
    b = Math.min(b, T + (o.compact ? 110 : 140));
    const x = sc(a, b, padL, W - padR);
    let lo = Infinity, hi = -Infinity;
    for (let i = a; i <= Math.min(b, N - 1); i++) { if (i <= T || R.replay) { lo = Math.min(lo, bars[i].close); hi = Math.max(hi, bars[i].close); } }
    if (rm.crash) { lo = Math.min(lo, rm.crash.pxLo); hi = Math.max(hi, rm.crash.wave2); }
    if (rm.topPx) hi = Math.max(hi, rm.topPx[1]);
    const pad = (hi - lo) * 0.08;
    lo -= pad; hi += pad;
    const y = sc(Math.log(lo), Math.log(hi), H - padB, padT);
    const Y = (v) => y(Math.log(v));
    let s = '<svg class="rm-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(o.label || '未来路线图') + '" preserveAspectRatio="none">';
    // 网格与价格刻度
    const st = niceStep(hi - lo, o.compact ? 4 : 6);
    for (let v = Math.ceil(lo / st) * st; v <= hi; v += st) {
      s += '<line x1="' + padL + '" x2="' + (W - padR) + '" y1="' + Y(v).toFixed(1) + '" y2="' + Y(v).toFixed(1) + '" class="rm-grid"/>';
      s += '<text x="' + (W - padR + 6) + '" y="' + (Y(v) + 4).toFixed(1) + '" class="rm-tick">' + px(v) + '</text>';
    }
    // 月份刻度
    let lastM = '';
    for (let i = a; i <= b; i++) {
      const d = CP.dateAt(bars, i), m = d.slice(0, 7);
      if (m !== lastM) {
        if (lastM) {
          s += '<line x1="' + x(i).toFixed(1) + '" x2="' + x(i).toFixed(1) + '" y1="' + padT + '" y2="' + (H - padB) + '" class="rm-grid rm-grid-v"/>';
          s += '<text x="' + (x(i) + 4).toFixed(1) + '" y="' + (H - 10) + '" class="rm-tick">' + (+d.slice(5, 7)) + '月' + (d.slice(5, 7) === '01' ? ' ' + d.slice(0, 4) : '') + '</text>';
        }
        lastM = m;
      }
    }
    // 见顶窗口
    if (rm.topW) {
      const x0 = x(Math.max(a, rm.topW.lo)), x1 = x(Math.min(b, rm.topW.hi));
      s += '<rect x="' + x0.toFixed(1) + '" y="' + padT + '" width="' + Math.max(3, x1 - x0).toFixed(1) + '" height="' + (H - padT - padB) + '" class="rm-topband"/>';
      s += '<text x="' + ((x0 + x1) / 2).toFixed(1) + '" y="' + (padT - 10) + '" class="rm-lbl rm-lbl-top" text-anchor="middle">见顶窗口</text>';
      if (rm.topPx) {
        const yy0 = Y(rm.topPx[1]), yy1 = Y(rm.topPx[0]);
        s += '<rect x="' + x0.toFixed(1) + '" y="' + yy0.toFixed(1) + '" width="' + Math.max(3, x1 - x0).toFixed(1) + '" height="' + Math.max(2, yy1 - yy0).toFixed(1) + '" class="rm-toppx"/>';
      }
    }
    if (rm.altW && rm.altW.lo <= b) {
      const x0 = x(Math.max(a, rm.altW.lo)), x1 = x(Math.min(b, rm.altW.hi));
      s += '<rect x="' + x0.toFixed(1) + '" y="' + padT + '" width="' + Math.max(2, x1 - x0).toFixed(1) + '" height="' + (H - padT - padB) + '" class="rm-altband"/>';
    }
    // 回落区
    if (rm.crash) {
      const c = rm.crash;
      const x0 = x(Math.min(b, c.botLo)), x1 = x(Math.min(b, c.botHi));
      s += '<rect x="' + x0.toFixed(1) + '" y="' + Y(c.pxHi).toFixed(1) + '" width="' + Math.max(3, x1 - x0).toFixed(1) + '" height="' + (Y(c.pxLo) - Y(c.pxHi)).toFixed(1) + '" class="rm-botbox" rx="4"/>';
      s += '<text x="' + ((x0 + x1) / 2).toFixed(1) + '" y="' + (Y(c.pxLo) + 16).toFixed(1) + '" class="rm-lbl rm-lbl-bot" text-anchor="middle">预计回落区</text>';
      const tx = x(Math.max(a, rm.topW.mid)), ty = Y(c.ref);
      s += '<path d="M' + tx.toFixed(1) + ' ' + ty.toFixed(1) + ' Q ' + ((tx + x0) / 2).toFixed(1) + ' ' + (ty).toFixed(1) + ' ' + ((x0 + x1) / 2).toFixed(1) + ' ' + Y(c.pxMid).toFixed(1) + '" class="rm-arrow rm-arrow-dn"/>';
      const wx = Math.min(W - padR - 4, x1 + (x1 - x0) * 0.6 + 30);
      s += '<path d="M' + ((x0 + x1) / 2).toFixed(1) + ' ' + Y(c.pxMid).toFixed(1) + ' Q ' + wx.toFixed(1) + ' ' + Y(c.pxMid).toFixed(1) + ' ' + wx.toFixed(1) + ' ' + Y(c.wave2).toFixed(1) + '" class="rm-arrow rm-arrow-up"/>';
      s += '<line x1="' + (wx - 26).toFixed(1) + '" x2="' + (wx + 6).toFixed(1) + '" y1="' + Y(c.wave2).toFixed(1) + '" y2="' + Y(c.wave2).toFixed(1) + '" class="rm-w2"/>';
      s += '<text x="' + (wx - 2).toFixed(1) + '" y="' + (Y(c.wave2) - 8).toFixed(1) + '" class="rm-lbl rm-lbl-wave" text-anchor="end">二波参考</text>';
    }
    // 历史价格
    const hp = [];
    for (let i = a; i <= T; i++) hp.push([x(i), Y(bars[i].close)]);
    s += '<path d="' + pathOf(hp) + '" class="rm-px"/>';
    // 真实后续
    if (R.replay) {
      const rp = [];
      for (let i = T; i <= Math.min(b, N - 1); i++) rp.push([x(i), Y(bars[i].close)]);
      s += '<path d="' + pathOf(rp) + '" class="rm-real"/>';
      const mk = (i, t, cls, dy) => {
        if (i > b) return '';
        const cx = x(i), cy = Y(bars[i].close);
        return '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="4.5" class="rm-dot ' + cls + '"/><text x="' + cx.toFixed(1) + '" y="' + (cy + dy).toFixed(1) + '" class="rm-lbl rm-lbl-real" text-anchor="middle">' + t + '</text>';
      };
      s += mk(R.replay.peak.i, '真实顶 ' + U.md(R.replay.peak.date), 'rm-dot-top', -12);
      if (R.replay.bottom.i > R.replay.peak.i) s += mk(R.replay.bottom.i, '真实底 ' + U.md(R.replay.bottom.date), 'rm-dot-bot', 20);
      if (o.acts !== false && R.replay.sim) {
        R.replay.sim.acts.forEach((ac) => {
          if (ac.i > b) return;
          const cx = x(ac.i), cy = Y(ac.px), up = ac.to > ac.from;
          s += '<path d="' + (up ? 'M' + cx + ' ' + (cy + 6) + 'l-5 9h10z' : 'M' + cx + ' ' + (cy - 6) + 'l-5 -9h10z') + '" class="' + (up ? 'rm-buy' : 'rm-sell') + '"><title>' + esc(ac.date + ' ' + ac.why) + '</title></path>';
        });
      }
    }
    // 截止日
    const xt = x(T);
    s += '<line x1="' + xt.toFixed(1) + '" x2="' + xt.toFixed(1) + '" y1="' + (padT - 4) + '" y2="' + (H - padB) + '" class="rm-now"/>';
    s += '<circle cx="' + xt.toFixed(1) + '" cy="' + Y(bars[T].close).toFixed(1) + '" r="5" class="rm-nowdot"/>';
    s += '<text x="' + (xt - 6).toFixed(1) + '" y="' + (padT + 12) + '" class="rm-lbl rm-lbl-now" text-anchor="end">' + (R.latest ? '今天' : '截止日') + ' ' + U.md(R.asof) + '</text>';
    if (R.replay) s += '<text x="' + (xt + 6).toFixed(1) + '" y="' + (padT + 12) + '" class="rm-lbl rm-lbl-real">之后的真实走势（模型未见）</text>';
    s += '</svg>';
    return s;
  };

  /* ---------------- 信号带：每个截止日的主窗口一致度 + 真实顶部 ---------------- */
  U.tapeSVG = function (R, o) {
    o = o || {};
    const W = o.w || 1100, H = o.h || 200, padL = 8, padR = 48, padT = 14, padB = 26;
    const bars = R.bars, tape = R.tape, N = bars.length;
    const from = o.from !== undefined ? o.from : Math.max(tape[0][0], N - 1 - (o.span || 500));
    const tp = tape.filter((e) => e[0] >= from);
    if (!tp.length) return '';
    const a = from, b = N - 1;
    const x = sc(a, b, padL, W - padR);
    const hH = (H - padT - padB) * 0.55;
    let lo = Infinity, hi = -Infinity;
    for (let i = a; i <= b; i++) { lo = Math.min(lo, bars[i].close); hi = Math.max(hi, bars[i].close); }
    const y = sc(Math.log(lo), Math.log(hi), padT + hH, padT);
    const yb = sc(0, 0.7, H - padB, padT + hH + 8);
    let s = '<svg class="tp-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="顶部信号带" preserveAspectRatio="none">';
    s += '<line x1="' + padL + '" x2="' + (W - padR) + '" y1="' + yb(CP.RULES.alertConf).toFixed(1) + '" y2="' + yb(CP.RULES.alertConf).toFixed(1) + '" class="tp-th"/>';
    s += '<text x="' + (W - padR + 4) + '" y="' + (yb(CP.RULES.alertConf) + 4).toFixed(1) + '" class="rm-tick">15%</text>';
    const bw = Math.max(1.5, (W - padL - padR) / ((b - a) / 5) * 0.7);
    tp.forEach((e) => {
      const c = e[3]; if (!c) return;
      const v = c[3] / e[1];
      const near = c[0] <= CP.RULES.alertLead;
      s += '<rect x="' + (x(e[0]) - bw / 2).toFixed(1) + '" y="' + yb(Math.min(0.7, v)).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + (yb(0) - yb(Math.min(0.7, v))).toFixed(1) + '" class="' + (v >= CP.RULES.alertConf && near ? 'tp-bar-hot' : 'tp-bar') + '"><title>' + esc(bars[e[0]].date + '：一致度 ' + pct(v, 0) + '，指向 ' + CP.dateAt(bars, e[0] + c[0]) + ' – ' + CP.dateAt(bars, e[0] + c[1])) + '</title></rect>';
    });
    const pp = [];
    for (let i = a; i <= b; i++) pp.push([x(i), y(bars[i].close)]);
    s += '<path d="' + pathOf(pp) + '" class="tp-px"/>';
    R.evalr.events.filter((e) => e.i >= a).forEach((e) => {
      s += '<circle cx="' + x(e.i).toFixed(1) + '" cy="' + y(bars[e.i].close).toFixed(1) + '" r="4" class="' + (e.hit ? 'tp-hit' : 'tp-miss') + '"><title>' + esc(bars[e.i].date + ' 真实顶部 ' + (e.hit ? '（提前命中）' : '（未提前命中）')) + '</title></circle>';
    });
    let lastY = '';
    for (let i = a; i <= b; i++) { const yy = bars[i].date.slice(0, 7); if (yy !== lastY) { if (lastY && /-(01|04|07|10)$/.test(yy)) s += '<text x="' + x(i).toFixed(1) + '" y="' + (H - 8) + '" class="rm-tick">' + yy.replace('-', '.') + '</text>'; lastY = yy; } }
    if (R.T < N - 1) s += '<line x1="' + x(R.T).toFixed(1) + '" x2="' + x(R.T).toFixed(1) + '" y1="' + padT + '" y2="' + (H - padB) + '" class="rm-now"/>';
    s += '</svg>';
    return s;
  };

  U.phaseHTML = function (k) {
    const i = CP.PHASES.findIndex((p) => p.k === k);
    return CP.PHASES.map((p, j) => '<li class="ph' + (j === i ? ' ph-on' : j < i ? ' ph-past' : '') + ' ph-' + p.k + '"' + (j === i ? ' aria-current="step"' : '') + '><span class="ph-n">' + (j + 1) + '</span><span class="ph-name">' + p.name + '</span><span class="ph-tip">' + p.tip + '</span></li>').join('');
  };

  // 回放打分
  U.score = function (R) {
    const rp = R.replay, rm = R.rm, last = R.bars[R.bars.length - 1].date;
    if (!rp) return null;
    const rows = [];
    if (rm.topW) rows.push({ k: '见顶时间', pred: U.range(rm.topW.loDate, rm.topW.hiDate, R.asof, last), real: U.md(rp.peak.date) + ' · ' + px(rp.peak.px), ok: rp.topHit, note: rp.topHit ? '命中' : (rp.topErr > 0 ? '真实顶晚 ' + rp.topErr + ' 个交易日' : '真实顶早 ' + (-rp.topErr) + ' 个交易日') });
    else rows.push({ k: '见顶时间', pred: '无见顶窗口', real: U.md(rp.peak.date) + ' · ' + px(rp.peak.px), ok: false, note: rp.firstSig ? (rp.firstSig.lead > 0 ? '漏报；截止日后 ' + U.md(rp.firstSig.date) + ' 才指向，仅提前 ' + rp.firstSig.lead + ' 日' : '漏报；见顶当天才出现结构') : '漏报' });
    if (rm.crash) {
      rows.push({ k: '底部时间', pred: U.range(rm.crash.botLoDate, rm.crash.botHiDate, R.asof, last), real: U.md(rp.bottom.date), ok: rp.botTimeHit, note: rp.botTimeHit ? '命中' : '未命中' });
      rows.push({ k: '底部价格', pred: px(rm.crash.pxLo) + ' – ' + px(rm.crash.pxHi), real: px(rp.bottom.px) + '（回撤 ' + pct(rp.bottom.dd) + '）', ok: rp.botPxHit, note: rp.botPxHit ? '命中' : '未命中' });
      rows.push({ k: '二波高点', pred: px(rm.crash.wave2), real: px(rp.wave2.px) + ' · ' + U.md(rp.wave2.date), ok: Math.abs(rp.wave2.px / rm.crash.wave2 - 1) < 0.03, note: '误差 ' + sp(rp.wave2.px / rm.crash.wave2 - 1) });
    }
    return rows;
  };

  G.CPUI = U;
})(typeof window !== 'undefined' ? window : globalThis);
