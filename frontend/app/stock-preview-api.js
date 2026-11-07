/* Preview-only identity adapter. Network operations remain in the owned LPPL.stock adapter. */
(function (root) {
  'use strict';
  const aliases = new Map([
    ['sh000001', 'sh000001'], ['上证指数', 'sh000001'], ['上证', 'sh000001'], ['上证综指', 'sh000001'], ['沪指', 'sh000001'],
    ['sh600519', 'sh600519'], ['600519', 'sh600519'], ['贵州茅台', 'sh600519'], ['茅台', 'sh600519'],
  ]);
  function resolveCode(input) {
    const raw = String(input || '').trim().toLowerCase();
    if (raw === '000001') throw Error('000001也可指平安银行；上证指数请填写 sh000001 或“上证指数”。');
    const code = aliases.get(raw);
    if (!code) throw Error('本次真实预览支持上证指数 sh000001 与贵州茅台 600519。');
    return code;
  }
  function create(api) {
    const base = api.api();
    if (!/\/api\/preview\/?$/.test(base) || new URL(base, root.location.href).origin !== root.location.origin)
      throw Error('真实预览须使用本站隔离接口。');
    const transport = value => resolveCode(value).slice(2);
    return {
      isResearchPreview: true, historySupported: false, resolveCode, symbolFor: resolveCode,
      codes: ['sh000001', 'sh600519'],
      latest: async () => null, history: async () => null,
      market: code => api.market(transport(code)),
      request: (code, options) => {
        if (options?.mode === 'history') return Promise.reject(Error('当前预览只运行最新一期；历史回放尚未开放。'));
        return api.request(transport(code), { mode: 'current', historyWeeks: 0 });
      },
      status: (code, options) => api.status(transport(code), options),
      remote: (code, kind, options) => kind === 'history' ? Promise.resolve(null) : api.remote(transport(code), kind, options),
    };
  }
  root.StockPreviewApi = { create, resolveCode };
  if (typeof module === 'object' && module.exports) module.exports = root.StockPreviewApi;
})(typeof window === 'object' ? window : globalThis);
