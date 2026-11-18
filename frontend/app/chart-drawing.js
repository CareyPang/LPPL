(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ChartDrawing = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  var TYPES = ['trend-line', 'horizontal-line', 'rectangle', 'text', 'fib-retracement'];
  var TOOL_LABELS = {
    'trend-line': '趋势线',
    'horizontal-line': '水平线',
    rectangle: '矩形',
    text: '文字',
    'fib-retracement': '斐波那契回撤',
  };
  var SAVE_ERROR = '画线保存失败（浏览器存储不可用）';
  var CAPTION = '画线仅保存在此浏览器，是你自己的标注，不是模型结果';

  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    var parts = value.split('-').map(Number);
    var date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    return date.getUTCFullYear() === parts[0] && date.getUTCMonth() === parts[1] - 1 &&
      date.getUTCDate() === parts[2];
  }

  function shanghaiDate(value) {
    var date = value instanceof Date ? value : new Date(value == null ? Date.now() : value);
    var parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(date);
    var fields = {};
    parts.forEach(function (part) { if (part.type !== 'literal') fields[part.type] = part.value; });
    return fields.year + '-' + fields.month + '-' + fields.day;
  }

  function filterDrawings(drawings) {
    return (Array.isArray(drawings) ? drawings : []).filter(function (drawing) {
      return drawing && TYPES.indexOf(drawing.kind) >= 0;
    });
  }

  function wrapStorage(items, today) {
    var created = validDate(today) ? today : shanghaiDate();
    return {
      v: 1,
      items: (Array.isArray(items) ? items : []).reduce(function (result, item) {
        var drawing = item && item.drawing ? item.drawing : item;
        if (!drawing || TYPES.indexOf(drawing.kind) < 0) return result;
        var createdAt = item && item.drawing && validDate(item.createdAt) ? item.createdAt : created;
        result.push({ createdAt: createdAt, drawing: drawing });
        return result;
      }, []),
    };
  }

  function unwrapStorage(value) {
    var parsed = value;
    try { if (typeof parsed === 'string') parsed = JSON.parse(parsed); } catch (_) { return []; }
    if (!parsed || parsed.v !== 1 || !Array.isArray(parsed.items)) return [];
    return parsed.items.filter(function (item) {
      return item && validDate(item.createdAt) && item.drawing &&
        TYPES.indexOf(item.drawing.kind) >= 0;
    }).map(function (item) {
      return { createdAt: item.createdAt, drawing: item.drawing };
    });
  }

  function historyVisibility(asof) {
    return !validDate(asof);
  }

  function lateDrawingDates(items, asof) {
    if (!validDate(asof)) return [];
    return Array.from(new Set((Array.isArray(items) ? items : [])
      .filter(function (item) { return item && validDate(item.createdAt) && item.createdAt > asof; })
      .map(function (item) { return item.createdAt; }))).sort();
  }

  function pushUndo(stack, snapshot, limit) {
    var next = Array.isArray(stack) ? stack.slice() : [];
    var cap = Number.isInteger(limit) && limit > 0 ? limit : 50;
    if (typeof snapshot !== 'string' || next[next.length - 1] === snapshot) return next;
    next.push(snapshot);
    return next.length > cap ? next.slice(next.length - cap) : next;
  }

  function mergeRecords(current, stored, deletedIds, changedIds) {
    var merged = new Map();
    var deleted = deletedIds instanceof Set ? deletedIds : new Set(deletedIds || []);
    var changed = changedIds instanceof Set ? changedIds : new Set(changedIds || []);
    var local = new Map();
    (Array.isArray(stored) ? stored : []).forEach(function (item) {
      var id = item && item.drawing && item.drawing.id;
      if (id) merged.set(id, item);
    });
    (Array.isArray(current) ? current : []).forEach(function (item) {
      var id = item && item.drawing && item.drawing.id;
      if (id) local.set(id, item);
    });
    changed.forEach(function (id) {
      var item = local.get(id);
      if (item && !deleted.has(id)) merged.set(id, item);
    });
    deleted.forEach(function (id) { merged.delete(id); });
    return Array.from(merged.values());
  }

  function closeEditorIfDeleted(editing, selectedIds, pendingIds, close) {
    var id = editing && editing.drawing && editing.drawing.id;
    var selected = selectedIds instanceof Set ? selectedIds : new Set(selectedIds || []);
    if (!id || !selected.has(id)) return false;
    if (pendingIds) pendingIds.delete(id);
    if (typeof close === 'function') close();
    return true;
  }

  function sameRecords(left, right) {
    var leftById = new Map();
    var rightById = new Map();
    (Array.isArray(left) ? left : []).forEach(function (item) {
      var id = item && item.drawing && item.drawing.id;
      if (id) leftById.set(id, item);
    });
    (Array.isArray(right) ? right : []).forEach(function (item) {
      var id = item && item.drawing && item.drawing.id;
      if (id) rightById.set(id, item);
    });
    if (leftById.size !== rightById.size) return false;
    return Array.from(leftById.entries()).every(function (entry) {
      return JSON.stringify(entry[1]) === JSON.stringify(rightById.get(entry[0]));
    });
  }

  function isImeCompositionKey(event) {
    return !!(event && (event.isComposing || event.keyCode === 229));
  }

  function hasTextContent(text) {
    return typeof text === 'string' && text.trim().length > 0;
  }

  function attach(chartApi, initialContext) {
    var target = chartApi.drawingTarget();
    var chart = target.chart;
    var host = document.getElementById('chart-host');
    var card = document.getElementById('chart-card');
    var toolbar = document.getElementById('drawing-toolbar');
    if (!host || !card || !toolbar) throw new Error('图表画线工具未就绪');
    function addButton(parent, label, attribute, value) {
      var button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.setAttribute(attribute, value);
      parent.appendChild(button);
      return button;
    }
    if (!toolbar.querySelector('[data-drawing-tool]')) {
      toolbar.classList.add('chart-drawing-toolbar');
      var group = document.createElement('div');
      group.className = 'chart-drawing-tools';
      group.setAttribute('role', 'group');
      group.setAttribute('aria-label', '画线工具');
      TYPES.forEach(function (kind) { addButton(group, TOOL_LABELS[kind], 'data-drawing-tool', kind); });
      addButton(group, '撤销', 'data-drawing-undo', '');
      addButton(group, '删除选中', 'data-drawing-delete', '');
      addButton(group, '清空', 'data-drawing-clear', '');
      addButton(group, '全部隐藏', 'data-drawing-visibility', '');
      toolbar.appendChild(group);
      var caption = document.createElement('p');
      caption.className = 'chart-drawing-caption';
      caption.textContent = CAPTION;
      toolbar.appendChild(caption);
      var history = document.createElement('p');
      history.className = 'chart-drawing-history';
      history.setAttribute('data-drawing-history', '');
      history.setAttribute('role', 'status');
      history.hidden = true;
      toolbar.appendChild(history);
      var dateList = document.createElement('div');
      dateList.className = 'chart-drawing-date-list';
      dateList.setAttribute('data-drawing-dates', '');
      dateList.setAttribute('aria-label', '画线创建日期');
      dateList.hidden = true;
      toolbar.appendChild(dateList);
      var message = document.createElement('p');
      message.className = 'chart-drawing-status';
      message.setAttribute('data-drawing-status', '');
      message.setAttribute('role', 'status');
      message.setAttribute('aria-live', 'polite');
      toolbar.appendChild(message);
    }
    var buttons = Array.prototype.slice.call(toolbar.querySelectorAll('[data-drawing-tool]'));
    var undoButton = toolbar.querySelector('[data-drawing-undo]');
    var deleteButton = toolbar.querySelector('[data-drawing-delete]');
    var clearButton = toolbar.querySelector('[data-drawing-clear]');
    var visibilityButton = toolbar.querySelector('[data-drawing-visibility]');
    var status = toolbar.querySelector('[data-drawing-status]');
    var historyCaption = toolbar.querySelector('[data-drawing-history]');
    var dateList = toolbar.querySelector('[data-drawing-dates]');
    var Drawing = root.LPPLLwc && root.LPPLLwc.Drawing;
    if (!Drawing || !Drawing.DrawingManager) throw new Error('画线库未加载');

    var context = { symbol: '', asof: null };
    var key = '';
    var records = [];
    var manager = null;
    var currentSeries = target.series;
    var visible = true;
    var undoStack = [];
    var committedSnapshot = '[]';
    var managerOff = [];
    var domOff = [];
    var temporarilyHidden = new Set();
    var offSeries = null;
    var editing = null;
    var pendingTextIds = new Set();
    var changedDrawingIds = new Set();
    var deletedDrawingIds = new Set();
    var storageSyncPending = false;
    var pointerActive = false;
    var textInput = document.createElement('input');
    var detached = false;

    textInput.type = 'text';
    textInput.className = 'chart-drawing-text-editor';
    textInput.setAttribute('aria-label', '画线文字');
    textInput.autocomplete = 'off';
    textInput.maxLength = 240;
    textInput.hidden = true;
    host.appendChild(textInput);
    toolbar.dataset.aiExclude = 'true';

    function setStatus(message) { status.textContent = message || ''; }

    function symbolKey(symbol) {
      var normalized = String(symbol || '').trim().toLowerCase();
      return normalized ? 'lppl.drawings.v1:' + normalized : '';
    }

    function readRecords(nextKey) {
      try {
        if (!root.localStorage || !nextKey) return [];
        return unwrapStorage(root.localStorage.getItem(nextKey));
      } catch (_) {
        setStatus(SAVE_ERROR);
        return [];
      }
    }

    function themed(drawing) {
      if (!drawing || TYPES.indexOf(drawing.kind) < 0) return drawing;
      var color = drawing.kind === 'rectangle' || drawing.kind === 'fib-retracement'
        ? '#8745a5' : '#d56a13';
      var style = Object.assign({}, drawing.style || {}, { color: color, textColor: color });
      if (drawing.kind === 'rectangle') {
        style.fillBackground = true;
        style.backgroundColor = color;
        style.transparency = 78;
      }
      if (drawing.kind === 'fib-retracement' && Array.isArray(style.levels)) {
        style.levels = style.levels.map(function (level) {
          return Object.assign({}, level, { color: color });
        });
      }
      return Object.assign({}, drawing, { style: style });
    }

    function managerDrawings() {
      if (!manager) return [];
      var drawings;
      try { drawings = JSON.parse(manager.exportJSON()); } catch (_) { drawings = []; }
      var prior = new Map(records.map(function (item) { return [item.drawing.id, item]; }));
      return filterDrawings(drawings).filter(function (drawing) {
        return !pendingTextIds.has(drawing.id);
      }).map(function (drawing) {
        var old = prior.get(drawing.id);
        if (old && temporarilyHidden.has(drawing.id)) {
          drawing = Object.assign({}, drawing, { hidden: old.drawing.hidden });
        }
        return {
          createdAt: old && validDate(old.createdAt) ? old.createdAt : shanghaiDate(),
          drawing: themed(drawing),
        };
      });
    }

    function writeRecords(items) {
      try {
        if (!root.localStorage || !key) throw new Error('storage unavailable');
        var current = wrapStorage(items).items;
        var merged = wrapStorage(mergeRecords(
          items, readRecords(key), deletedDrawingIds, changedDrawingIds,
        )).items;
        root.localStorage.setItem(key, JSON.stringify(wrapStorage(merged)));
        if (!sameRecords(merged, current)) storageSyncPending = true;
        changedDrawingIds.clear();
        deletedDrawingIds.clear();
        setStatus(merged.length ? '已保存 ' + merged.length + ' 条画线' : '画线已清空并保存');
        return true;
      } catch (_) {
        setStatus(SAVE_ERROR);
        return false;
      }
    }

    function render() {
      var count = manager ? manager.drawings().length : records.length;
      toolbar.dataset.drawingCount = String(count);
      undoButton.disabled = undoStack.length === 0;
      deleteButton.disabled = !manager || manager.selection().length === 0;
      var currentTool = manager && manager.tool();
      buttons.forEach(function (button) {
        button.setAttribute('aria-pressed', String(button.dataset.drawingTool === currentTool));
      });
      visibilityButton.textContent = visible ? '全部隐藏' : '显示我的画线';
      visibilityButton.setAttribute('aria-pressed', String(visible));
      var dates = lateDrawingDates(records, context.asof);
      historyCaption.hidden = !context.asof || !visible || dates.length === 0;
      historyCaption.textContent = historyCaption.hidden ? '' :
        '这些画线创建于 ' + dates.join('、') + '，晚于当前截止日 ' + context.asof;
      dateList.replaceChildren();
      records.forEach(function (item) {
        var label = document.createElement('span');
        label.textContent = (TOOL_LABELS[item.drawing.kind] || item.drawing.kind) + ' · 创建于 ' + item.createdAt;
        dateList.appendChild(label);
      });
      dateList.hidden = !visible || records.length === 0;
    }

    function snapshot() { return JSON.stringify(records); }

    function trackRecordChanges(previous, next) {
      var previousById = new Map();
      var nextById = new Map();
      previous.forEach(function (item) { previousById.set(item.drawing.id, item); });
      next.forEach(function (item) { nextById.set(item.drawing.id, item); });
      previousById.forEach(function (item, id) {
        if (!nextById.has(id)) {
          deletedDrawingIds.add(id);
          changedDrawingIds.delete(id);
        }
      });
      nextById.forEach(function (item, id) {
        var prior = previousById.get(id);
        if (!prior || JSON.stringify(prior) !== JSON.stringify(item)) {
          changedDrawingIds.add(id);
          deletedDrawingIds.delete(id);
        }
      });
    }

    function commitMutation() {
      var previousRecords = records;
      var nextRecords = managerDrawings();
      trackRecordChanges(previousRecords, nextRecords);
      records = nextRecords;
      var next = snapshot();
      if (next !== committedSnapshot) {
        undoStack = pushUndo(undoStack, committedSnapshot, 50);
        committedSnapshot = next;
        writeRecords(records);
      }
      render();
    }

    function importRecords(items) {
      records = wrapStorage(items).items;
      changedDrawingIds.clear();
      deletedDrawingIds.clear();
      if (manager) {
        manager.importJSON(JSON.stringify(records.map(function (item) { return item.drawing; })));
        manager.setDrawingsVisible(visible);
      }
      committedSnapshot = snapshot();
      render();
    }

    function flushStorageSync() {
      if (!storageSyncPending || editing || pointerActive || (manager && manager.tool())) return;
      storageSyncPending = false;
      var stored = readRecords(key);
      var storedIds = new Set(stored.map(function (item) { return item.drawing.id; }));
      deletedDrawingIds.forEach(function (id) {
        if (!storedIds.has(id)) deletedDrawingIds.delete(id);
      });
      importRecords(mergeRecords([], stored, deletedDrawingIds));
      undoStack = [];
      render();
    }

    function bindManager(series, preserveVisibility) {
      var priorVisibility = preserveVisibility ? visible : historyVisibility(context.asof);
      if (manager) manager.destroy();
      managerOff.forEach(function (off) { off(); });
      managerOff = [];
      currentSeries = series;
      manager = new Drawing.DrawingManager(chart, series, {
        keyboard: false,
        fontFamily: '"Microsoft YaHei", "Noto Sans SC", sans-serif',
        timeInfo: function () { return { timeZone: 'Asia/Shanghai', intraday: false }; },
        formatLabel: function (label) {
          return label.id === 'caption' && label.text === 'Add text' ? '输入文字' : undefined;
        },
      });
      manager.importJSON(JSON.stringify(records.map(function (item) { return item.drawing; })));
      temporarilyHidden.forEach(function (id) {
        if (manager.get(id)) manager.setHidden(id, true);
      });
      visible = priorVisibility;
      manager.setDrawingsVisible(priorVisibility);
      managerOff.push(manager.on('add', function (drawing) {
        var next = themed(drawing);
        if (JSON.stringify(next) !== JSON.stringify(drawing)) manager.update(next);
        if (drawing.kind === 'text') {
          pendingTextIds.add(drawing.id);
          return;
        }
        commitMutation();
      }));
      managerOff.push(manager.on('remove', commitMutation));
      managerOff.push(manager.on('gestureEnd', function () {
        commitMutation();
        flushStorageSync();
      }));
      managerOff.push(manager.on('selection', render));
      managerOff.push(manager.on('tool', function () {
        render();
        flushStorageSync();
      }));
      managerOff.push(manager.on('visibility', render));
      managerOff.push(manager.on('textEdit', openTextEditor));
      render();
    }

    function openTextEditor(drawing, point) {
      editing = { drawing: drawing, original: drawing.text || '' };
      var pane = currentSeries && currentSeries.getPane && currentSeries.getPane();
      var paneElement = pane && pane.getHTMLElement && pane.getHTMLElement();
      var paneRect = paneElement ? paneElement.getBoundingClientRect() : host.getBoundingClientRect();
      var hostRect = host.getBoundingClientRect();
      textInput.style.left = Math.max(0, point.x + paneRect.left - hostRect.left) + 'px';
      textInput.style.top = Math.max(0, point.y + paneRect.top - hostRect.top) + 'px';
      textInput.value = editing.original;
      textInput.hidden = false;
      textInput.focus();
      textInput.select();
    }

    function closeTextEditor() {
      editing = null;
      textInput.hidden = true;
      textInput.value = '';
      host.focus({ preventScroll: true });
    }

    function saveTextEditor() {
      if (!editing || !manager) return;
      var drawing = manager.get(editing.drawing.id);
      if (!drawing) {
        pendingTextIds.delete(editing.drawing.id);
        closeTextEditor();
        return;
      }
      var text = textInput.value;
      var pending = pendingTextIds.has(drawing.id);
      if (!hasTextContent(text)) {
        if (pending || !editing.original) {
          pendingTextIds.delete(drawing.id);
          manager.remove(drawing.id);
        } else {
          manager.update(Object.assign({}, drawing, { text: editing.original }));
        }
        closeTextEditor();
        flushStorageSync();
        return;
      }
      pendingTextIds.delete(drawing.id);
      manager.update(Object.assign({}, drawing, { text: text }));
      commitMutation();
      closeTextEditor();
      flushStorageSync();
    }

    function cancelTextEditor() {
      if (!editing || !manager) return;
      var drawing = manager.get(editing.drawing.id);
      if (!drawing) {
        pendingTextIds.delete(editing.drawing.id);
        closeTextEditor();
        return;
      }
      if (pendingTextIds.delete(drawing.id) || !editing.original) manager.remove(drawing.id);
      else manager.update(Object.assign({}, drawing, { text: editing.original }));
      closeTextEditor();
      flushStorageSync();
    }

    function activateTool(kind) {
      if (!manager) return;
      if (context.asof && !manager.drawingsVisible()) {
        records.forEach(function (item) {
          var drawing = manager.get(item.drawing.id);
          if (drawing && !drawing.hidden) {
            temporarilyHidden.add(drawing.id);
            manager.setHidden(drawing.id, true);
          }
        });
      }
      manager.setTool(manager.tool() === kind ? null : kind);
    }

    function listen(element, name, handler) {
      element.addEventListener(name, handler);
      domOff.push(function () { element.removeEventListener(name, handler); });
    }

    function onStorage(event) {
      if (event.key !== key && event.key !== null) return;
      storageSyncPending = true;
      flushStorageSync();
    }
    function onPointerDown(event) {
      if (card.contains(event.target)) pointerActive = true;
    }
    function onPointerEnd() {
      if (!pointerActive) return;
      pointerActive = false;
      flushStorageSync();
    }
    root.addEventListener('storage', onStorage);
    document.addEventListener('pointerdown', onPointerDown, true);
    root.addEventListener('pointerup', onPointerEnd);
    root.addEventListener('pointercancel', onPointerEnd);
    domOff.push(function () { root.removeEventListener('storage', onStorage); });
    domOff.push(function () { document.removeEventListener('pointerdown', onPointerDown, true); });
    domOff.push(function () { root.removeEventListener('pointerup', onPointerEnd); });
    domOff.push(function () { root.removeEventListener('pointercancel', onPointerEnd); });

    buttons.forEach(function (button) {
      listen(button, 'click', function () { activateTool(button.dataset.drawingTool); });
    });
    listen(undoButton, 'click', function () { undo(); });
    listen(deleteButton, 'click', function () { removeSelected(); });
    listen(clearButton, 'click', function () {
      if (editing) cancelTextEditor();
      if (!manager) return;
      var stored = readRecords(key);
      if (!manager.drawings().length && !stored.length) return;
      if (!root.confirm('确定清空此标的的全部画线吗？')) return;
      stored.forEach(function (item) { deletedDrawingIds.add(item.drawing.id); });
      manager.clear();
      commitMutation();
      if (stored.length) writeRecords(records);
      flushStorageSync();
    });
    listen(visibilityButton, 'click', function () {
      if (!manager) return;
      var show = !visible;
      if (show) {
        temporarilyHidden.forEach(function (id) {
          var item = records.find(function (record) { return record.drawing.id === id; });
          if (item && manager.get(id)) manager.setHidden(id, !!item.drawing.hidden);
        });
        temporarilyHidden.clear();
      }
      visible = show;
      manager.setDrawingsVisible(show);
      render();
    });

    function undo() {
      if (!manager || !undoStack.length) return;
      if (editing) cancelTextEditor();
      var previous = undoStack.pop();
      var restored;
      try { restored = unwrapStorage({ v: 1, items: JSON.parse(previous) }); } catch (_) { return; }
      trackRecordChanges(records, restored);
      records = restored;
      manager.importJSON(JSON.stringify(records.map(function (item) { return item.drawing; })));
      manager.setDrawingsVisible(visible);
      committedSnapshot = snapshot();
      writeRecords(records);
      render();
      flushStorageSync();
    }

    function removeSelected() {
      if (!manager) return;
      var selected = manager.selection().slice();
      closeEditorIfDeleted(editing, selected, pendingTextIds, closeTextEditor);
      selected.forEach(function (id) { manager.remove(id); });
      render();
      flushStorageSync();
    }

    function onCardKeydown(event) {
      if (!card.contains(event.target) || !card.contains(document.activeElement)) return;
      if (event.target === textInput) return;
      if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        undo();
        return;
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && manager && manager.selection().length) {
        event.preventDefault();
        removeSelected();
      } else if (event.key === 'Escape' && manager) {
        manager.cancelPending();
        manager.setTool(null);
        manager.select([]);
        render();
      }
    }

    function onTextKeydown(event) {
      if (event.key !== 'Enter' && event.key !== 'Escape') return;
      event.stopPropagation();
      if (isImeCompositionKey(event)) return;
      if (event.key === 'Enter') {
        event.preventDefault();
        saveTextEditor();
      } else {
        event.preventDefault();
        cancelTextEditor();
      }
    }

    listen(card, 'keydown', onCardKeydown);
    listen(textInput, 'keydown', onTextKeydown);
    listen(host, 'pointerdown', function () { host.focus({ preventScroll: true }); });

    function setContext(next) {
      next = next || {};
      var nextSymbol = String(next.symbol || '').toLowerCase();
      var nextKey = symbolKey(nextSymbol);
      var nextAsof = validDate(next.asof) ? next.asof : null;
      var symbolChanged = nextKey !== key;
      var asofChanged = nextAsof !== context.asof;
      context = { symbol: nextSymbol, asof: nextAsof };
      if (symbolChanged) {
        key = nextKey;
        records = readRecords(key);
        undoStack = [];
        changedDrawingIds.clear();
        deletedDrawingIds.clear();
        storageSyncPending = false;
        temporarilyHidden.clear();
        visible = historyVisibility(context.asof);
        if (manager) {
          manager.importJSON(JSON.stringify(records.map(function (item) { return item.drawing; })));
          manager.setDrawingsVisible(visible);
        }
        committedSnapshot = snapshot();
      } else if (asofChanged && manager) {
        visible = historyVisibility(context.asof);
        if (!context.asof) {
          temporarilyHidden.forEach(function (id) {
            var item = records.find(function (record) { return record.drawing.id === id; });
            if (item && manager.get(id)) manager.setHidden(id, !!item.drawing.hidden);
          });
          temporarilyHidden.clear();
        }
        manager.setDrawingsVisible(visible);
      }
      render();
    }

    setContext(initialContext);
    bindManager(target.series, false);
    if (chartApi.on) {
      offSeries = chartApi.on('priceSeries', function (series) {
        if (manager) records = managerDrawings();
        bindManager(series, true);
      });
    }

    function detach() {
      if (detached) return;
      detached = true;
      if (offSeries) offSeries();
      managerOff.forEach(function (off) { off(); });
      managerOff = [];
      if (manager) manager.destroy();
      manager = null;
      domOff.forEach(function (off) { off(); });
      domOff = [];
      textInput.remove();
      records = [];
    }

    return {
      setContext: setContext,
      setVisibleForScreenshot: function (value) {
        if (manager) manager.setDrawingsVisible(!!value);
      },
      composeScreenshot: function (canvas) {
        if (!canvas || !currentSeries) return canvas;
        var pane = currentSeries.getPane();
        var paneElement = pane && pane.getHTMLElement();
        var host = root.document.getElementById('chart-host');
        if (!paneElement || !host) return canvas;
        var hostRect = host.getBoundingClientRect();
        if (!hostRect.width || !hostRect.height) return canvas;
        var scaleX = canvas.width / hostRect.width;
        var scaleY = canvas.height / hostRect.height;
        var context = canvas.getContext('2d');
        Array.prototype.forEach.call(paneElement.querySelectorAll('canvas'), function (layer) {
          if (Number(root.getComputedStyle(layer).zIndex) < 2) return;
          var rect = layer.getBoundingClientRect();
          context.drawImage(layer, (rect.left - hostRect.left) * scaleX,
            (rect.top - hostRect.top) * scaleY, rect.width * scaleX, rect.height * scaleY);
        });
        return canvas;
      },
      setDrawingsVisible: function (value) {
        if (manager) manager.setDrawingsVisible(!!value);
      },
      drawingsVisible: function () { return !!manager && manager.drawingsVisible(); },
      detach: detach,
    };
  }

  return {
    TYPES: TYPES.slice(),
    SAVE_ERROR: SAVE_ERROR,
    CAPTION: CAPTION,
    filterDrawings: filterDrawings,
    shanghaiDate: shanghaiDate,
    wrapStorage: wrapStorage,
    unwrapStorage: unwrapStorage,
    historyVisibility: historyVisibility,
    lateDrawingDates: lateDrawingDates,
    pushUndo: pushUndo,
    mergeRecords: mergeRecords,
    closeEditorIfDeleted: closeEditorIfDeleted,
    isImeCompositionKey: isImeCompositionKey,
    hasTextContent: hasTextContent,
    storageKey: function (symbol) {
      var normalized = String(symbol || '').trim().toLowerCase();
      return normalized ? 'lppl.drawings.v1:' + normalized : '';
    },
    attach: attach,
  };
});
