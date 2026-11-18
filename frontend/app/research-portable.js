(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    const Core = window.ResearchPortableCore;
    if (!Core) return;
    let storage; try { storage = window.localStorage; } catch { /* Show errors on action. */ }
    const names = ['指数自选', '股票自选', '研究分组、笔记与本机摘要', '已读状态与手动持仓'];
    const mount = document.createElement('section');
    mount.className = 'panel portable-panel'; mount.id = 'research-portable';
    mount.innerHTML = '<div class="section-head"><div><span class="section-kicker">TAKE YOUR RESEARCH WITH YOU</span><h2>把研究带走。</h2></div><span class="local-label">手动文件迁移</span></div><p class="section-description">导出到自己的设备，或在另一台设备导入。备份含私人笔记和持仓；不会上传，尚未接通账户云同步。</p><div class="portable-actions"><button type="button" class="button button-quiet" id="export-private">导出私人备份</button><label class="button button-quiet" for="import-private">选择备份文件</label><input id="import-private" class="sr-only" type="file" accept=".json,application/json"></div><p id="portable-status" role="status" class="record-caption"></p><div id="portable-preview" hidden><h3>先核对，再导入</h3><p class="record-caption">默认保留本机数据。研究记录会合并，保留两边笔记版本；自选与持仓分区按你的选择替换。导入的本机摘要不代表首次公开预测。</p><div id="portable-sections"></div><button type="button" class="button button-primary" id="apply-private">备份当前数据并确认导入</button></div>';
    document.querySelector('.workspace-footer').before(mount);
    const $ = id => document.getElementById(id);
    let pending = null, baseline = null;
    const tell = text => { $('portable-status').textContent = text; };
    const download = (object, name) => {
      const blob = new Blob([JSON.stringify(object, null, 2)], { type: 'application/json;charset=utf-8' });
      const url = URL.createObjectURL(blob), anchor = document.createElement('a');
      anchor.href = url; anchor.download = name; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
    };
    const fileName = prefix => prefix + '-' + new Date().toISOString().slice(0, 19).replaceAll(':', '-') + '.json';
    $('export-private').addEventListener('click', () => {
      try { download(Core.create(storage, null, window.ResearchPersonalCore), fileName('lppl-private-backup')); tell('已发起备份下载，请确认文件已保存。文件包含私人资料，请勿作为公开研究卡分享。未保存草稿不在备份内。'); }
      catch (error) { tell('导出失败：' + error.message); }
    });
    $('import-private').addEventListener('change', async event => {
      pending = null; $('portable-preview').hidden = true;
      const file = event.target.files?.[0]; if (!file) return;
      try {
        if (file.size > Core.MAX_BYTES) throw new Error('文件超过 6 MB');
        pending = Core.parse(await file.text(), window.ResearchPersonalCore);
        baseline = Core.snapshot(storage);
        $('portable-sections').replaceChildren();
        for (const key of Object.keys(pending.sections)) {
          const label = document.createElement('label'); label.className = 'portable-choice';
          const input = document.createElement('input'); input.type = 'checkbox'; input.dataset.key = key;
          const text = document.createElement('span');
          const value = pending.sections[key];
          const count = Array.isArray(value) ? value.length + ' 个标的' : key === Core.KEYS[2] ? value.notes.length + ' 个笔记版本 · ' + Object.keys(value.observations).length + ' 个标的摘要' : '私人记录';
          text.textContent = names[Core.KEYS.indexOf(key)] + ' · ' + count + (baseline[key] !== null ? ' · 本机已有数据' : ' · 本机为空');
          label.append(input, text); $('portable-sections').append(label);
        }
        $('portable-preview').hidden = false; tell('备份生成于 ' + pending.exportedAt + '。请选择要导入的分区。');
      } catch (error) { pending = null; tell('未导入：' + error.message); }
      event.target.value = '';
    });
    $('apply-private').addEventListener('click', () => {
      if (!pending) return;
      try {
        const selected = [...$('portable-sections').querySelectorAll('input:checked')].map(input => input.dataset.key);
        if (!selected.length) throw new Error('尚未选择分区');
        if (window.ResearchWorkspaceActions?.hasUnsaved()) throw new Error('还有未保存的笔记或持仓草稿，请先保存或复制草稿后再导入');
        // Validate every mutation against a staging storage before downloading or writing.
        const map = new Map(Object.entries(Core.snapshot(storage)));
        const stage = { getItem: key => map.get(key) ?? null, setItem: (key, v) => map.set(key, v), removeItem: key => map.delete(key) };
        Core.apply(stage, baseline, pending, selected, window.ResearchPersonalCore);
        const hadRecords = Core.KEYS.some(key => baseline[key] !== null);
        if (hadRecords) download(Core.create(storage, null, window.ResearchPersonalCore), fileName('lppl-before-import-private'));
        const count = Core.apply(storage, baseline, pending, selected, window.ResearchPersonalCore);
        pending = null; $('portable-preview').hidden = true;
        window.dispatchEvent(new Event('workspace-imported'));
        tell('已导入 ' + count + ' 个分区。' + (hadRecords ? '已发起导入前备份下载，请确认文件已保存。' : '原本机记录为空，无需另行备份。'));
      } catch (error) { tell('未完成导入：' + error.message); }
    });
  });
})();
