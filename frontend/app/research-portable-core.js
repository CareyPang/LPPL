/* Local-file transport only. No account, network, publication or model writes. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./research-workspace-core.js'));
  else root.ResearchPortableCore = factory(root.ResearchWorkspaceCore);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Workspace) {
  'use strict';
  const FORMAT = 'lppl-personal-backup', MAX_BYTES = 6 * 1024 * 1024;
  const KEYS = ['lppl.watchlist.idx.v1', 'lppl.watchlist.v1', Workspace.KEY, 'lppl.research-personal.v1'];
  const INDEX = new Set(['sh000001', 'sh000016', 'sh000300', 'sh000905', 'sh000688', 'sz399001', 'sz399006']);
  const plain = v => !!v && typeof v === 'object' && !Array.isArray(v);
  function safeTree(v, depth) {
    if ((depth || 0) > 24) throw new Error('备份结构过深');
    if (typeof v === 'number' && !Number.isFinite(v)) throw new Error('含无效数字');
    if (!v || typeof v !== 'object') return;
    for (const key of Object.keys(v)) {
      if (['__proto__', 'constructor', 'prototype'].includes(key)) throw new Error('含不支持的字段');
      safeTree(v[key], (depth || 0) + 1);
    }
  }
  function section(key, value, Personal) {
    safeTree(value);
    if (key === KEYS[0] || key === KEYS[1]) {
      const index = key === KEYS[0];
      if (!Array.isArray(value) || value.length > (index ? 7 : 50) || value.some(c => typeof c !== 'string' || !(index ? INDEX.has(c) : /^(?:60|68|00|30|43|83|87|92)\d{4}$/.test(c))) || new Set(value).size !== value.length) throw new Error('自选清单格式不正确');
      return value;
    }
    if (!plain(value) || value.version !== 1) throw new Error('不支持的数据版本');
    if (key === Workspace.KEY) {
      const normalized = Workspace.normalize(value);
      if (value.storageIssue || !Array.isArray(value.notes) || value.notes.length !== normalized.notes.length || !Array.isArray(value.groups) || value.groups.length !== normalized.groups.length) throw new Error('笔记或分组不完整，未导入');
      for (const note of value.notes) if (note.asof != null && Workspace.date(note.asof) !== note.asof) throw new Error('笔记绑定日期不正确，未导入');
      for (const [id, entries] of Object.entries(value.observations || {})) {
        if (!Array.isArray(entries) || normalized.observations[id]?.length !== entries.length) throw new Error('历史摘要校验失败，未导入');
      }
      return normalized;
    }
    if (key === KEYS[3] && Personal?.normalize) {
      if (!Array.isArray(value.holdings) || !Array.isArray(value.readChanges)) throw new Error('个人记录缺少持仓或已读清单');
      const normalized = Personal.normalize(value);
      if (!normalized || normalized.storageIssue) throw new Error('个人记录格式不正确');
      // A normalizer must not silently drop positions during a restore.
      if (normalized.holdings?.length !== value.holdings.length || normalized.readChanges?.length !== value.readChanges.length) throw new Error('持仓或已读记录未通过校验');
      return normalized;
    }
    throw new Error('不支持的数据分区');
  }
  function snapshot(storage) {
    if (!storage) throw new Error('浏览器存储不可用');
    return Object.fromEntries(KEYS.map(key => [key, storage.getItem(key)]));
  }
  function create(storage, now, Personal) {
    const raw = snapshot(storage), sections = {};
    for (const key of KEYS) if (raw[key] !== null) sections[key] = section(key, JSON.parse(raw[key]), Personal);
    if (!Object.keys(sections).length) throw new Error('本机还没有可备份的记录');
    return { format: FORMAT, version: 1, exportedAt: new Date(now || Date.now()).toISOString(), privacy: 'PRIVATE_BACKUP', observations: 'local retrieval records; not first public predictions', sections };
  }
  function parse(text, Personal) {
    if (typeof text !== 'string' || new TextEncoder().encode(text).length > MAX_BYTES) throw new Error('文件超过 6 MB 或不是文本');
    const bundle = JSON.parse(text); safeTree(bundle);
    if (!plain(bundle) || bundle.format !== FORMAT || bundle.version !== 1 || bundle.privacy !== 'PRIVATE_BACKUP' || !plain(bundle.sections) || !Number.isFinite(Date.parse(bundle.exportedAt))) throw new Error('不是受支持的研究备份');
    const sections = {};
    for (const [key, value] of Object.entries(bundle.sections)) {
      if (!KEYS.includes(key)) throw new Error('备份包含未知分区');
      sections[key] = section(key, value, Personal);
    }
    if (!Object.keys(sections).length) throw new Error('备份为空');
    return { ...bundle, sections };
  }
  function mergeWorkspace(local, incoming) {
    const current = Workspace.normalize(local), imported = Workspace.normalize(incoming);
    const out = { ...imported, ...current };
    const recentByKey = new Map();
    for (const recent of current.recent.concat(imported.recent)) {
      const key = JSON.stringify([recent.assetId, recent.asof, recent.predictionId, recent.modelVersion]);
      const previous = recentByKey.get(key);
      if (!previous || recent.visitedAt > previous.visitedAt) recentByKey.set(key, recent);
    }
    out.recent = [...recentByKey.values()].sort((a, b) => b.visitedAt.localeCompare(a.visitedAt)).slice(0, 10);
    out.groups = [...new Set(current.groups.concat(imported.groups))];
    if (out.groups.length > 12) throw new Error('合并后分组超过 12 个，请先整理；未丢弃分组');
    out.meta = { ...imported.meta, ...current.meta };
    out.notes = current.notes.slice();
    for (const note of imported.notes) {
      const content = n => JSON.stringify([n.assetId, n.asof, n.predictionId, n.modelVersion, n.text, n.createdAt]);
      if (out.notes.some(n => content(n) === content(note))) continue;
      const next = { ...note, imported: true };
      if (out.notes.some(n => n.id === next.id)) next.id = 'imported-' + out.notes.length + '-' + note.id.slice(-60);
      out.notes.push(next);
    }
    if (out.notes.length > 200) throw new Error('合并后笔记超过 200 个版本，请保留备份后整理；未丢弃笔记');
    const localIds = new Set(current.notes.map(n => n.id));
    out.notes.sort((a, b) => a.createdAt.localeCompare(b.createdAt) || Number(localIds.has(a.id)) - Number(localIds.has(b.id)));
    out.observations = {};
    for (const id of new Set(Object.keys(current.observations).concat(Object.keys(imported.observations)))) {
      const rows = (current.observations[id] || []).slice();
      for (const row of imported.observations[id] || []) {
        if (rows.some(r => Workspace.signature(r) === Workspace.signature(row) && r.observedAt === row.observedAt)) continue;
        rows.push({ ...row, id: rows.some(r => r.id === row.id) ? 'imported-' + rows.length + '-' + row.id.slice(-60) : row.id });
      }
      if (rows.length > 40) throw new Error('合并后某标的摘要超过 40 条，请保留两份备份；未丢弃记录');
      rows.sort((a, b) => a.asof.localeCompare(b.asof) || String(a.generatedAt || '').localeCompare(String(b.generatedAt || '')) || a.observedAt.localeCompare(b.observedAt));
      out.observations[id] = rows;
    }
    if (Object.keys(out.observations).length > 100 || Object.keys(out.meta).length > 100) throw new Error('合并后资产数超过上限，未丢弃记录');
    out.observationSeq = Math.max(current.observationSeq, imported.observationSeq);
    return Workspace.normalize(out);
  }
  function apply(storage, baseline, bundle, selectedKeys, Personal) {
    const selected = [...new Set(selectedKeys)];
    if (!selected.length) throw new Error('请选择要导入的分区');
    for (const key of KEYS) if (storage.getItem(key) !== baseline[key]) throw new Error('预览后本机数据发生变化，请重新预览；未覆盖任何记录');
    const changes = selected.map(key => {
      if (!KEYS.includes(key) || !Object.hasOwn(bundle.sections, key)) throw new Error('无效的导入分区');
      if (baseline[key] !== null) section(key, JSON.parse(baseline[key]), Personal);
      let value = section(key, bundle.sections[key], Personal);
      if (key === Workspace.KEY && baseline[key] !== null) value = mergeWorkspace(JSON.parse(baseline[key]), value);
      if (key === Workspace.KEY || key === KEYS[3]) {
        const current = baseline[key] ? JSON.parse(baseline[key]) : {};
        value.revision = Math.max(Number.isSafeInteger(current.revision) ? current.revision : 0, value.revision || 0) + 1;
      }
      return [key, JSON.stringify(value)];
    });
    const done = [];
    try {
      for (const [key, value] of changes) { storage.setItem(key, value); done.push([key, value]); }
    } catch {
      let rollback = true;
      for (const [key, value] of done.reverse()) {
        try {
          if (storage.getItem(key) !== value) { rollback = false; continue; }
          if (baseline[key] === null) storage.removeItem(key); else storage.setItem(key, baseline[key]);
        } catch { rollback = false; }
      }
      throw new Error(rollback ? '写入失败，已恢复原记录' : '写入失败，部分记录未能自动恢复，请使用导入前备份；暂勿继续保存');
    }
    return selected.length;
  }
  return { FORMAT, MAX_BYTES, KEYS, snapshot, create, parse, apply, mergeWorkspace };
});
