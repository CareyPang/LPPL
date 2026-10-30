// 原站 F13 主题设置：深色（默认）/ 浅色，localStorage 记忆；只改 CSS 变量，不改任何内容。
(function(){
  const KEY = 'lppl-theme';
  const css = `html[data-theme=light]{--bg:#f6f8fa;--panel:#ffffff;--line:#d0d7de;--fg:#1f2328;--mute:#57606a;--none:#8c959f}
  html[data-theme=light] .bar{background:#e6e9ee}html[data-theme=light] select,html[data-theme=light] input,html[data-theme=light] button{background:#fff!important;color:#1f2328!important;border-color:#d0d7de}
  .themebtn{position:fixed;right:14px;bottom:14px;z-index:9;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:16px;padding:4px 12px;font-size:12px;cursor:pointer;opacity:.85}`;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  const apply = t => { document.documentElement.dataset.theme = t; localStorage.setItem(KEY, t); const b = document.getElementById('themebtn'); if (b) b.textContent = t === 'light' ? '深色主题' : '浅色主题'; };
  const init = localStorage.getItem(KEY) || 'dark';
  document.documentElement.dataset.theme = init;
  document.addEventListener('DOMContentLoaded', () => { const b = document.createElement('button'); b.id = 'themebtn'; b.className = 'themebtn'; b.title = '原站 F13 主题设置'; b.onclick = () => apply(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'); document.body.appendChild(b); apply(init); });
})();
