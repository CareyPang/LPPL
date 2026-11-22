/* 临界点 · 统一证据等级徽章（EvidenceBadge）
   把全站零散重复的防御性免责长段落收敛为右上角极简徽章（点击/悬停展开检验细节）与页脚单行声明。
   只做展示，不做任何模型计算。 */
(function (G) {
  'use strict';

  const META = {
    passed:      { label: '样本外通过', tone: 'ok',   tip: '该指标在样本外测试段通过了预设检验标准。' },
    oos_passed:  { label: '样本外通过', tone: 'ok',   tip: '该指标在样本外测试段通过了预设检验标准。' },
    dev:         { label: '开发段验证', tone: 'info', tip: '开发段通过，仍处于样本外持续观察阶段。' },
    dev_only:    { label: '开发段观测', tone: 'info', tip: '仅在开发段完成回测，尚未进入独立测试段定论。' },
    candidate:   { label: '研究候选',   tone: 'info', tip: '按统一 LPPLS 拟合口径生成的个股研究观测值。' },
    descriptive: { label: '历史统计',   tone: 'mute', tip: '基于历史同类样本的经验分位统计，供结构参照。' },
    dev_failed:  { label: '未过样本外', tone: 'warn', tip: '开发/测试段未通过预设统计阈值，保留观测值供复盘对照。' },
    fail:        { label: '未过样本外', tone: 'warn', tip: '该规则在测试段未通过统计检验，保留原样数据供复盘。' },
    none:        { label: '观测态',     tone: 'mute', tip: '暂无独立样本外结论，仅呈现客观物理拟合结构。' },
  };

  function norm(level) {
    const raw = String(level || 'none').toLowerCase().trim();
    if (META[raw]) return raw;
    if (raw.startsWith('fail')) return 'fail';
    if (raw.startsWith('pass')) return 'passed';
    if (raw.includes('desc')) return 'descriptive';
    if (raw.includes('cand')) return 'candidate';
    if (raw.includes('dev')) return 'dev_only';
    return 'none';
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function injectStyle() {
    if (typeof document === 'undefined' || document.getElementById('cp-evb-style')) return;
    const st = document.createElement('style');
    st.id = 'cp-evb-style';
    st.textContent = [
      '.cp-evb{position:relative;display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;font:600 11px/1.4 "Inter","PingFang SC","Microsoft YaHei",system-ui,sans-serif;letter-spacing:.02em;border:1px solid #d5dce8;background:#f4f7fc;color:#4c525e;cursor:help;vertical-align:middle;white-space:nowrap}',
      '.cp-evb::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.85}',
      '.cp-evb[data-tone="ok"]{border-color:#bfd6fb;background:#eaf2ff;color:#1f5fd6}',
      '.cp-evb[data-tone="info"]{border-color:#c8d8f5;background:#f0f5ff;color:#2753a7}',
      '.cp-evb[data-tone="warn"]{border-color:#f0d8a8;background:#fff8eb;color:#9a5b00}',
      '.cp-evb[data-tone="mute"]{border-color:#dde2ec;background:#f6f8fb;color:#5f6776}',
      '.cp-evb-pop{position:absolute;right:0;top:calc(100% + 6px);z-index:80;width:248px;padding:10px 12px;border-radius:10px;border:1px solid #d8dfeb;background:#fff;color:#131722;box-shadow:0 12px 32px -12px rgba(19,23,34,.24);font:400 12px/1.55 "Inter","PingFang SC","Microsoft YaHei",system-ui,sans-serif;white-space:normal;text-align:left;opacity:0;pointer-events:none;transform:translateY(-2px);transition:opacity .14s ease,transform .14s ease}',
      '.cp-evb:hover .cp-evb-pop,.cp-evb:focus-within .cp-evb-pop,.cp-evb[data-open="1"] .cp-evb-pop{opacity:1;pointer-events:auto;transform:translateY(0)}',
      '.cp-evb-pop b{display:block;margin-bottom:3px;font-size:12px;color:#131722}',
      '.cp-evb-pop span{display:block;color:#4c525e}',
      '.cp-evb-pop em{display:block;margin-top:5px;font-style:normal;font-family:"JetBrains Mono",Consolas,monospace;font-size:11px;color:#6a6d78}',
      '.cp-footer-note{font-size:12px;color:#6a7180;padding:10px 16px;border-top:1px solid #e3e7ee;background:#fff;text-align:center}'
    ].join('');
    document.head.appendChild(st);
  }

  function renderHtml(level, opts) {
    injectStyle();
    const key = norm(level);
    const meta = META[key] || META.none;
    const o = opts || {};
    const label = o.label || meta.label;
    const tip = o.detail || meta.tip;
    const nText = (o.n != null && Number.isFinite(Number(o.n))) ? ('样本 n = ' + Number(o.n)) : '';
    const extra = o.extra ? String(o.extra) : '';
    const metaLine = [nText, extra].filter(Boolean).join(' · ');
    return '<span class="cp-evb" tabindex="0" data-level="' + esc(key) + '" data-tone="' + esc(meta.tone) + '" aria-label="' + esc(label + '：' + tip) + '">' +
      esc(label) +
      '<span class="cp-evb-pop" role="tooltip"><b>' + esc(label) + '</b><span>' + esc(tip) + '</span>' +
      (metaLine ? '<em>' + esc(metaLine) + '</em>' : '') +
      '</span></span>';
  }

  function bindAuto() {
    injectStyle();
    if (typeof document === 'undefined') return;
    document.querySelectorAll('[data-evidence-badge]').forEach(function (el) {
      const lvl = el.getAttribute('data-evidence-badge');
      const n = el.getAttribute('data-evidence-n');
      const detail = el.getAttribute('data-evidence-detail');
      const label = el.getAttribute('data-evidence-label');
      el.innerHTML = renderHtml(lvl, { n: n ? Number(n) : null, detail: detail || '', label: label || '' });
    });
    document.addEventListener('click', function (ev) {
      const badge = ev.target && ev.target.closest ? ev.target.closest('.cp-evb') : null;
      document.querySelectorAll('.cp-evb[data-open="1"]').forEach(function (b) {
        if (b !== badge) b.removeAttribute('data-open');
      });
      if (badge) {
        if (badge.getAttribute('data-open') === '1') badge.removeAttribute('data-open');
        else badge.setAttribute('data-open', '1');
      }
    });
  }

  G.CPEvidenceBadge = {
    norm: norm,
    meta: function (lvl) { return META[norm(lvl)] || META.none; },
    html: renderHtml,
    bind: bindAuto,
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bindAuto);
    else bindAuto();
  }
})(typeof window !== 'undefined' ? window : globalThis);
