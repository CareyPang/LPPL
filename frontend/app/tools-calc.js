/* 工具页纯函数：汇率、时区、单位、贵金属、房贷。不读业务数据，不调用模型。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LPPLTools = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  var G_PER_OZT = 31.1034768;
  var MASS = { g: 1, kg: 1000, ozt: G_PER_OZT, oz: 28.349523125, tael_hk: 37.429, liang: 50, jin: 500 };
  var MASS_NAME = { g: '克', kg: '千克', ozt: '金衡盎司', oz: '常衡盎司', tael_hk: '香港金衡两', liang: '市两', jin: '市斤' };

  function num(v) { if (v == null || String(v).trim() === '') return NaN; var n = Number(v); return Number.isFinite(n) ? n : NaN; }
  function bad(msg) { return { status: 'invalid_input', error: msg }; }

  /* rate 的单位是「报价货币 / 基础货币」；per=100 表示银行牌价按每 100 基础货币报价 */
  function fx(amount, rate, per) {
    amount = num(amount); rate = num(rate); per = num(per || 1);
    if (!(rate > 0) || !(per > 0)) return bad('汇率必须大于 0');
    if (!Number.isFinite(amount)) return bad('金额不是数字');
    var unit = rate / per;
    return { status: 'ready', unitRate: unit, inverseRate: 1 / unit, converted: amount * unit, back: amount / unit };
  }
  /* 共同基准货币 C：qCA = A/C，qCB = B/C → A→B = B/A = qCB / qCA */
  function crossRate(qCA, qCB) {
    qCA = num(qCA); qCB = num(qCB);
    if (!(qCA > 0) || !(qCB > 0)) return bad('两个汇率都必须大于 0');
    return { status: 'ready', rate: qCB / qCA };
  }

  function mass(value, from, to) {
    value = num(value);
    if (!MASS[from] || !MASS[to]) return bad('未知单位');
    if (!Number.isFinite(value)) return bad('数值不是数字');
    return { status: 'ready', value: value * MASS[from] / MASS[to] };
  }
  function temperature(value, from, to) {
    value = num(value);
    if (!Number.isFinite(value)) return bad('数值不是数字');
    var c = from === 'C' ? value : from === 'F' ? (value - 32) * 5 / 9 : from === 'K' ? value - 273.15 : NaN;
    if (!Number.isFinite(c)) return bad('未知单位');
    if (c < -273.15) return bad('低于绝对零度');
    var out = to === 'C' ? c : to === 'F' ? c * 9 / 5 + 32 : to === 'K' ? c + 273.15 : NaN;
    return Number.isFinite(out) ? { status: 'ready', value: out } : bad('未知单位');
  }

  /* usdPerOzt：美元/金衡盎司；cnyPerUsd：人民币/美元；domestic 可选，人民币/克 */
  function metal(usdPerOzt, cnyPerUsd, domestic) {
    var G = num(usdPerOzt), X = num(cnyPerUsd);
    if (!(G > 0) || !(X > 0)) return bad('价格和汇率都必须大于 0');
    var perG = G * X / G_PER_OZT;
    var r = { status: 'ready', cnyPerGram: perG, cnyPerKg: perG * 1000, usdPerGram: G / G_PER_OZT };
    var d = num(domestic);
    if (domestic !== '' && domestic != null && d > 0) {
      r.premium = d - perG; r.premiumPct = d / perG - 1;
    }
    return r;
  }
  function fxScenario(usdPerOzt, rateA, rateB) {
    var a = metal(usdPerOzt, rateA), b = metal(usdPerOzt, rateB);
    if (a.status !== 'ready' || b.status !== 'ready') return bad('价格和汇率都必须大于 0');
    return { status: 'ready', a: a.cnyPerGram, b: b.cnyPerGram, diff: b.cnyPerGram - a.cnyPerGram, diffPct: b.cnyPerGram / a.cnyPerGram - 1 };
  }

  /* 等额本息 annuity / 等额本金 linear；annualPct 年利率百分数，months 期数 */
  function mortgage(principal, annualPct, months, method) {
    var P = num(principal), y = num(annualPct), n = Math.round(num(months));
    if (!(P > 0) || !(n > 0) || !(y >= 0) || n > 600) return bad('本金、期数须大于 0，年利率不小于 0，期数不超过 600');
    var r = y / 100 / 12, rows = [], bal = P, total = 0;
    for (var k = 1; k <= n; k += 1) {
      var interest = bal * r, principalPart, pay;
      if (method === 'linear') { principalPart = P / n; pay = principalPart + interest; }
      else {
        pay = r === 0 ? P / n : P * r * Math.pow(1 + r, n) / (Math.pow(1 + r, n) - 1);
        principalPart = pay - interest;
      }
      bal = k === n ? 0 : bal - principalPart;
      total += pay;
      rows.push({ k: k, pay: pay, principal: principalPart, interest: interest, balance: bal });
    }
    return { status: 'ready', rows: rows, first: rows[0].pay, last: rows[n - 1].pay, total: total, interest: total - P };
  }

  /* 时区：offsetMinutes(zone, ms) = 该时刻在 zone 的墙上时间 − UTC */
  var fmtCache = {};
  function parts(zone, ms) {
    var f = fmtCache[zone] || (fmtCache[zone] = new Intl.DateTimeFormat('en-US', {
      timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', weekday: 'short'
    }));
    var o = {};
    f.formatToParts(new Date(ms)).forEach(function (p) { o[p.type] = p.value; });
    return { y: +o.year, mo: +o.month, d: +o.day, h: +o.hour, mi: +o.minute, s: +o.second, wd: o.weekday };
  }
  function offsetMinutes(zone, ms) {
    var p = parts(zone, ms);
    return Math.round((Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s) - Math.floor(ms / 1000) * 1000) / 60000);
  }
  /* 把 zone 里的墙上时间换成 UTC 时刻；夏令时跳过 → nonexistent，重复 → ambiguous（两个时刻） */
  function zonedToInstants(zone, y, mo, d, h, mi) {
    var t0 = Date.UTC(y, mo - 1, d, h, mi), seen = {}, out = [];
    [-36, -12, 0, 12, 36].forEach(function (dh) {
      var off = offsetMinutes(zone, t0 + dh * 3600000), inst = t0 - off * 60000;
      if (!seen[inst] && offsetMinutes(zone, inst) === off) { seen[inst] = 1; out.push(inst); }
    });
    out.sort(function (a, b) { return a - b; });
    return out;
  }
  function convertTime(fromZone, toZone, y, mo, d, h, mi) {
    try { new Intl.DateTimeFormat('en-US', { timeZone: fromZone }); new Intl.DateTimeFormat('en-US', { timeZone: toZone }); }
    catch (e) { return bad('未知时区'); }
    var inst = zonedToInstants(fromZone, y, mo, d, h, mi);
    if (!inst.length) return { status: 'invalid_input', error: '这个时刻因夏令时被跳过，不存在', nonexistent: true };
    return {
      status: 'ready', ambiguous: inst.length > 1,
      results: inst.map(function (ms) { return { ms: ms, at: parts(toZone, ms), fromOffset: offsetMinutes(fromZone, ms), toOffset: offsetMinutes(toZone, ms) }; })
    };
  }
  /* A 股连续竞价时段（北京时间）；节假日不在本函数内判断 */
  function ashareSession(ms) {
    var p = parts('Asia/Shanghai', ms), m = p.h * 60 + p.mi;
    if (p.wd === 'Sat' || p.wd === 'Sun') return { code: 'weekend', text: '周末休市' };
    if (m >= 555 && m < 565) return { code: 'auction', text: '集合竞价' };
    if (m >= 565 && m < 570) return { code: 'auction', text: '竞价结束，待开盘' };
    if (m >= 570 && m < 690) return { code: 'open', text: '上午交易中' };
    if (m >= 690 && m < 780) return { code: 'lunch', text: '午间休市' };
    if (m >= 780 && m < 900) return { code: 'open', text: '下午交易中' };
    return { code: 'closed', text: m < 555 ? '未开盘' : '已收盘' };
  }

  return {
    G_PER_OZT: G_PER_OZT, MASS: MASS, MASS_NAME: MASS_NAME,
    fx: fx, crossRate: crossRate, mass: mass, temperature: temperature, metal: metal, fxScenario: fxScenario,
    mortgage: mortgage, offsetMinutes: offsetMinutes, convertTime: convertTime, ashareSession: ashareSession, parts: parts
  };
});
