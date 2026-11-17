/* 临界点 · 标的目录（Open Design 维护）
   数据来源只有 LPPL.catalog()（317 个标准标的）与 LPPL.stock.index()（已发布个股结果的代码表），
   本文件不读其他 JSON，不计算任何模型值。纯逻辑部分（normalize/filter/sort）可在 node 下测试。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(globalThis);
  else root.StockCatalog = factory(root);
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';
  var STATE_KEY = 'lppl.catalog.v1';
  var TYPE_LABEL = { index: '宽基', industry: '行业', stock: '个股' };
  var BOARD_SHORT = { '沪市主板': '沪主', '深市主板': '深主', '创业板': '创业', '科创板': '科创' };
  var MEMBER_LABEL = { sh000300: '沪深300', sh000016: '上证50', sh000905: '中证500' };
  var DEFAULT_STATE = { q: '', type: 'all', board: 'all', member: 'all', published: 'all', sort: 'code', dir: 'asc', dense: false };
  var TYPES = new Set(['all', 'index', 'industry', 'stock']);
  var BOARDS = new Set(['all', '沪市主板', '深市主板', '创业板', '科创板']);
  var MEMBERS = new Set(['all', 'sh000300', 'sh000016', 'sh000905']);
  var PUBLISHED = new Set(['all', 'yes', 'no']);
  var SORTS = new Set(['code', 'name', 'type', 'board', 'member', 'published']);

  function cleanState(value) {
    var source = value && typeof value === 'object' ? value : {};
    return {
      q: typeof source.q === 'string' ? source.q : '',
      type: TYPES.has(source.type) ? source.type : DEFAULT_STATE.type,
      board: BOARDS.has(source.board) ? source.board : DEFAULT_STATE.board,
      member: MEMBERS.has(source.member) ? source.member : DEFAULT_STATE.member,
      published: PUBLISHED.has(source.published) ? source.published : DEFAULT_STATE.published,
      sort: SORTS.has(source.sort) ? source.sort : DEFAULT_STATE.sort,
      dir: source.dir === 'desc' ? 'desc' : DEFAULT_STATE.dir,
      dense: typeof source.dense === 'boolean' ? source.dense : DEFAULT_STATE.dense,
    };
  }

  function serializeState(value, scrollY) {
    var y = Number(scrollY);
    return JSON.stringify(Object.assign(cleanState(value), {
      scrollY: Number.isFinite(y) && y > 0 ? Math.floor(y) : 0,
    }));
  }

  function parseState(value, query) {
    var source = value;
    if (typeof source === 'string') {
      try { source = JSON.parse(source); } catch (e) { source = {}; }
    }
    var state = cleanState(source);
    if (query !== undefined && query !== null) state.q = String(query);
    var y = Number(source && source.scrollY);
    return { state: state, scrollY: Number.isFinite(y) && y > 0 ? Math.floor(y) : 0 };
  }

  function normalize(catalog, published) {
    var rows = catalog && Array.isArray(catalog.rows) ? catalog.rows : Array.isArray(catalog) ? catalog : [];
    var names = (catalog && catalog.index_names) || {};
    var pub = published instanceof Set ? published : new Set(Array.isArray(published) ? published : Object.keys(published || {}));
    return rows.map(function (r) {
      var type = r.type === 'index' || r.type === 'industry' || r.type === 'stock' ? r.type : 'stock';
      var members = Array.isArray(r.member_of) ? r.member_of : [];
      var isPub = type === 'index' ? !!r.dashboard : type === 'stock' ? pub.has(r.code) : false;
      return {
        symbol: r.symbol || '', code: r.code || '', name: r.name || r.code || '', type: type, typeLabel: TYPE_LABEL[type],
        board: r.board || '', boardShort: BOARD_SHORT[r.board] || '', exchange: r.exchange || '',
        memberOf: members, memberNames: members.map(function (m) { return names[m] || MEMBER_LABEL[m] || m; }),
        published: isPub,
        href: type === 'index' ? 'index.html?code=' + encodeURIComponent(r.symbol || r.code) : type === 'stock' ? 'stock.html?code=' + encodeURIComponent(r.code) : '',
        watchKey: type === 'index' ? r.symbol : type === 'stock' ? r.code : '',
      };
    });
  }
  /* f = { q, type: all|index|industry|stock, board: all|<板块>, member: all|<sym>, published: all|yes|no } */
  function filter(rows, f) {
    var q = String((f && f.q) || '').trim().toLowerCase();
    return rows.filter(function (r) {
      if (f.type && f.type !== 'all' && r.type !== f.type) return false;
      if (f.board && f.board !== 'all' && r.board !== f.board) return false;
      if (f.member && f.member !== 'all' && r.memberOf.indexOf(f.member) < 0) return false;
      if (f.published === 'yes' && !r.published) return false;
      if (f.published === 'no' && r.published) return false;
      if (q && r.name.toLowerCase().indexOf(q) < 0 && r.code.indexOf(q) < 0 && r.symbol.toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
  }
  var TYPE_ORDER = { index: 0, industry: 1, stock: 2 };
  function sort(rows, key, dir) {
    var d = dir === 'desc' ? -1 : 1, k = key || 'code';
    var val = function (r) {
      if (k === 'type') return TYPE_ORDER[r.type];
      if (k === 'published') return r.published ? 0 : 1;
      if (k === 'board') return r.board || '\uffff';
      if (k === 'member') return r.memberNames.join(',') || '\uffff';
      return String(r[k] == null ? '' : r[k]);
    };
    return rows.slice().sort(function (a, b) {
      var x = val(a), y = val(b);
      if (x < y) return -d; if (x > y) return d;
      return a.code < b.code ? -1 : a.code > b.code ? 1 : 0;
    });
  }
  function counts(rows) {
    var c = { index: 0, industry: 0, stock: 0, published: 0 };
    rows.forEach(function (r) { c[r.type]++; if (r.published) c.published++; });
    return c;
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  /* mount({ el, catalog, published, watch: { has(row), toggle(row) }, onOpen(row) }) */
  function mount(o) {
    var el = o.el, all = normalize(o.catalog, o.published), total = all.length;
    var win = o.window || root, storage = o.storage, saved;
    if (storage === undefined) {
      try { storage = win.sessionStorage; } catch (e) { storage = null; }
    }
    try { saved = storage && storage.getItem(STATE_KEY); } catch (e) { saved = null; }
    var restored = parseState(saved, o.query);
    var state = restored.state, ready = false, scrollTimer = null, navigating = false;
    var COLS = [['code', '代码'], ['name', '名称'], ['type', '类型'], ['board', '板块'], ['member', '所属指数'], ['published', '结果']];
    function persist() {
      try { if (storage) storage.setItem(STATE_KEY, serializeState(state, win.scrollY)); } catch (e) { /* storage may be unavailable */ }
    }
    function chips(name, items) {
      return '<div class="cat-f" role="group" aria-label="' + esc(name) + '">' + items.map(function (it) {
        return '<button type="button" data-f="' + esc(it[0]) + '" data-v="' + esc(it[1]) + '" aria-pressed="' + (state[it[0]] === it[1]) + '">' + esc(it[2]) + '</button>';
      }).join('') + '</div>';
    }
    function draw() {
      var rows = sort(filter(all, state), state.sort, state.dir), c = counts(rows);
      el.innerHTML =
        '<div class="cat-top"><h2>标的目录</h2><span class="cat-n m">匹配 ' + rows.length + ' / ' + total + '</span>' +
        '<span class="cat-sub">宽基 ' + c.index + ' · 行业 ' + c.industry + ' · 个股 ' + c.stock + ' · 已发布 ' + c.published + '</span>' +
        '<button type="button" class="cat-dense" aria-pressed="' + state.dense + '" title="切换行高">' + (state.dense ? '舒适' : '紧凑') + '</button></div>' +
        '<div class="cat-fs">' +
        '<input class="cat-q" type="search" placeholder="在目录内筛选：名称 / 代码" value="' + esc(state.q) + '" aria-label="目录内筛选">' +
        chips('类型', [['type', 'all', '全部'], ['type', 'index', '宽基'], ['type', 'industry', '行业'], ['type', 'stock', '个股']]) +
        chips('板块', [['board', 'all', '全部板块'], ['board', '沪市主板', '沪主'], ['board', '深市主板', '深主'], ['board', '创业板', '创业'], ['board', '科创板', '科创']]) +
        chips('所属指数', [['member', 'all', '全部指数'], ['member', 'sh000300', '沪深300'], ['member', 'sh000016', '上证50'], ['member', 'sh000905', '中证500']]) +
        chips('结果', [['published', 'all', '全部'], ['published', 'yes', '已发布'], ['published', 'no', '未发布']]) +
        '</div>' +
        '<div class="cat-tw"><table class="cat-t' + (state.dense ? ' dense' : '') + '"><thead><tr>' + COLS.map(function (col) {
          var on = state.sort === col[0];
          return '<th scope="col" aria-sort="' + (on ? (state.dir === 'asc' ? 'ascending' : 'descending') : 'none') + '"><button type="button" data-sort="' + col[0] + '">' + col[1] + (on ? (state.dir === 'asc' ? ' ↑' : ' ↓') : '') + '</button></th>';
        }).join('') + '<th scope="col"><span class="vh">自选</span>☆</th></tr></thead><tbody>' +
        (rows.length ? rows.map(function (r, i) {
          var watched = o.watch && r.watchKey ? !!o.watch.has(r) : false;
          var nameCell = r.href ? '<a href="' + esc(r.href) + '" data-i="' + i + '">' + esc(r.name) + '</a>' : '<span class="cat-dis" title="行业指数暂无详情页">' + esc(r.name) + '</span>';
          return '<tr data-i="' + i + '"><td class="m">' + esc(r.code) + '</td><td>' + nameCell + '</td><td><i class="tag t-' + r.type + '">' + esc(r.typeLabel) + '</i></td>' +
            '<td>' + (r.boardShort ? '<i class="tag">' + esc(r.boardShort) + '</i>' : '—') + '</td><td class="cat-mem">' + (r.memberNames.length ? esc(r.memberNames.join(' · ')) : '—') + '</td>' +
            '<td>' + (r.published ? '<i class="tag pub">已发布</i>' : '<span class="cat-dim">—</span>') + '</td>' +
            '<td>' + (r.watchKey ? '<button type="button" class="cat-w" data-w="' + i + '" aria-pressed="' + watched + '" aria-label="' + (watched ? '移出自选 ' : '加入自选 ') + esc(r.name) + '">' + (watched ? '★' : '☆') + '</button>' : '') + '</td></tr>';
        }).join('') : '<tr><td colspan="7" class="cat-empty">没有匹配的标的。清空筛选或换个关键词。</td></tr>') +
        '</tbody></table></div>' +
        '<p class="cat-note">目录 = 7 个宽基指数 + 10 个中证行业指数 + 300 个沪深300 成分股；“已发布”指后端已有计算结果。目录外的 A 股可在上方输入 6 位代码发起查询。</p>';
      el.__rows = rows;
      if (ready) persist();
    }
    el.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-f]');
      if (b) { state[b.dataset.f] = b.dataset.v; draw(); return; }
      var s = e.target.closest('button[data-sort]');
      if (s) { if (state.sort === s.dataset.sort) state.dir = state.dir === 'asc' ? 'desc' : 'asc'; else { state.sort = s.dataset.sort; state.dir = 'asc'; } draw(); return; }
      var w = e.target.closest('button[data-w]');
      if (w) { var r = el.__rows[Number(w.dataset.w)]; if (o.watch && r) { o.watch.toggle(r); draw(); } return; }
      var dn = e.target.closest('.cat-dense');
      if (dn) { state.dense = !state.dense; draw(); return; }
      var a = e.target.closest('a[data-i]');
      if (a) {
        var linkRow = el.__rows[Number(a.dataset.i)];
        persist();
        if (linkRow && linkRow.type === 'index' && e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) {
          navigating = true;
          if (scrollTimer) { clearTimeout(scrollTimer); scrollTimer = null; }
        }
      }
      if (a && o.onOpen) { var row = el.__rows[Number(a.dataset.i)]; if (row && row.type === 'stock') { e.preventDefault(); o.onOpen(row); } }
    });
    function applyQuery(t) {
      var input = typeof t === 'string' ? null : t;
      var pos = input && input.selectionStart;
      state.q = String(input ? input.value : t || '');
      draw();
      if (input) {
        var q = el.querySelector('.cat-q');
        if (q) { q.focus(); try { q.setSelectionRange(pos, pos); } catch (err) { /* ignore */ } }
      }
    }
    el.addEventListener('input', function (e) {
      if (!e.target.classList.contains('cat-q') || e.isComposing) return; /* 中文输入法合成中不重绘，否则候选被打断 */
      applyQuery(e.target);
    });
    el.addEventListener('compositionend', function (e) {
      if (e.target.classList.contains('cat-q')) applyQuery(e.target);
    });
    if (win && win.addEventListener) {
      win.addEventListener('scroll', function () {
        if (navigating) return;
        if (scrollTimer) return;
        scrollTimer = setTimeout(function () { scrollTimer = null; persist(); }, 120);
      }, { passive: true });
    }
    if (o.query !== undefined && o.query !== null) applyQuery(String(o.query));
    else draw();
    ready = true;
    var restoreScroll = function () {
      if (restored.scrollY && win && typeof win.scrollTo === 'function') win.scrollTo(0, restored.scrollY);
      persist();
    };
    if (restored.scrollY) {
      if (win && typeof win.requestAnimationFrame === 'function') win.requestAnimationFrame(restoreScroll);
      else setTimeout(restoreScroll, 0);
    } else persist();
    return { redraw: draw, state: state, rows: all };
  }

  return {
    STATE_KEY: STATE_KEY, TYPE_LABEL: TYPE_LABEL, BOARD_SHORT: BOARD_SHORT,
    serializeState: serializeState, parseState: parseState,
    normalize: normalize, filter: filter, sort: sort, counts: counts, mount: mount,
  };
});
