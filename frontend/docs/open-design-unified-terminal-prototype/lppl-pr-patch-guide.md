# CareyPang/LPPL 代码合入补丁说明（FCO 降噪 + 个股 as-of 锁定 + 全球四市场独立 PIT 回测与分时区每日定时更新）

> 适用基线：`CareyPang/LPPL` `main` 分支（PR `#181` 之后）。以下 6 处补丁全部复用仓库现有内置全球数据模块（`research/data/us_stock.py`、`research/data/external.py`、`research/pipeline/stock.py`），零第三方付费 API 依赖，可直接按文件合入仓库。

---

## 一、为什么「哈空调」等个股没有出现连续 `as-of` 不漂移锁定检验？

核查 `frontend/app/stock-view.js` 与 `frontend/app/alert-ledger.js` 源码后，发现有 **3 个直接原因**（其中第 2、3 点是代码缺口，不只是“近期没有”）：

1. **前置条件**：个股默认只跑当前分析，必须点击 **「生成 104 周回放」** 后 `lastHistory.frames` 才会有多周截面；若该股近期本身无合格顶部泡沫拟合（`no_qualified_fit`），也不会产生红柱簇。
2. **字段兼容 Bug（`alert-ledger.js` 第 195 行）**：
   当前 `episodes()` 强制要求 `frame.close != null && frame.w[scale]` 同时存在。但个股 104 周回放帧常常只带 `frame.scenarios` 或 `frame.clusters`，缺少 `frame.w['6-12m']` 或 `frame.close`，导致 `episodes()` 直接返回空数组 `[]`。
3. **缺少 UI 展示容器（`stock-view.js` & `stock.html`）**：
   `stock-view.js` 在 `rebuildFcoOverlay()` 中计算了 `lockedRanges`，但仅用于给红柱顶部画细线，**并未在 `stock.html` 渲染「连续 as-of 不漂移锁定检验」文字结论与明细表**，导致即使有数据也看不见。

---

## 二、补丁 1：`frontend/app/alert-ledger.js`（修复个股 `frames` 兼容）

在 `frameWindow(frame, scale)` 与 `episodes()` 中增加对 `frame.clusters[scale]` 和 `frame.scenarios` 的兜底读取，且不再因缺少 `frame.close` 而丢弃帧：

```js
// 替换 frontend/app/alert-ledger.js 中的 frameWindow()
function frameWindow(frame, scale) {
  var value = frame && frame.w && frame.w[scale];
  if (Array.isArray(value) && value.length >= 2) return [value[0], value[1]];
  var cls = frameClusters(frame, scale);
  if (cls && cls[0]) return [cls[0].q20_date, cls[0].q80_date];
  var sc = Array.isArray(frame && frame.scenarios) ? frame.scenarios[0] : null;
  if (sc && dateValue(sc.q20_date) !== null && dateValue(sc.q80_date) !== null) {
    return [sc.q20_date, sc.q80_date];
  }
  return null;
}

// 替换 episodes() 中的入栈判断（去掉 frame.close != null 强限制）
ordered.forEach(function (item) {
  var frame = item.frame, window = frameWindow(frame, scale);
  if (window) run.push({ frame: frame, window: window });
  else flush();
});
```

---

## 三、补丁 2：`frontend/app/scen-style.js`（FCO 红绿柱降噪分级统一规范）

确保所有指数与个股图共用同一套降噪阈值，并支持开关切换：

```js
// frontend/app/scen-style.js
const TOP_HIGH_THRESHOLD = 0.40;
const BOT_HIGH_THRESHOLD = 0.50;

function drawFcoBar(ctx, { x, w, bottom, maxH, intensity, hot, locked, denoise = true }) {
  const high = intensity >= TOP_HIGH_THRESHOLD || locked;
  const hScale = (denoise && !high) ? 0.35 : 1.0;
  const alpha  = (denoise && !high) ? 0.24 : (hot ? 0.92 : 0.76);
  const h = Math.max(3, intensity * maxH * hScale);
  ctx.save();
  ctx.fillStyle = `rgba(207, 34, 46, ${alpha})`;
  ctx.fillRect(x - w / 2, bottom - h, w, h);
  if (locked) {
    ctx.fillStyle = '#cf222e';
    ctx.fillRect(x - w / 2, bottom - h - 2, w, 2.5); // 高危锁定顶线锚记
  }
  ctx.restore();
}

function drawFcoBottomBar(ctx, { x, w, bottom, maxH, intensity, hot, denoise = true }) {
  const high = intensity >= BOT_HIGH_THRESHOLD;
  const hScale = (denoise && !high) ? 0.38 : 1.0;
  const alpha  = (denoise && !high) ? 0.22 : (hot ? 0.90 : 0.72);
  const h = Math.max(3, intensity * maxH * hScale);
  ctx.save();
  ctx.fillStyle = `rgba(26, 127, 55, ${alpha})`;
  ctx.fillRect(x - w / 2, bottom - h, w, h);
  ctx.restore();
}
```

---

## 四、补丁 3：`frontend/stock.html` & `frontend/app/stock-view.js`（渲染个股 `as-of` 锁定检验卡）

1. 在 `frontend/stock.html` 的 `#stock-action-card` 下方新增容器：
   ```html
   <section id="stock-asof-convergence" class="card" hidden>
     <h3>连续 as-of 顶部聚类不漂移检验</h3>
     <p id="stock-asof-summary"></p>
   </section>
   ```
2. 在 `frontend/app/stock-view.js` 的 `rebuildFcoOverlay()` 末尾调用 `CPAlertLedger.latestConvergence()` 并更新文案：
   ```js
   const box = $('stock-asof-convergence');
   const txt = $('stock-asof-summary');
   if (box && txt && root.CPAlertLedger) {
     box.hidden = false;
     if (!frames.length) {
       txt.textContent = '尚未生成 104 周历史回放，请先点击「生成104周回放」以运行连续 as-of 不漂移检验。';
     } else {
       const conv = root.CPAlertLedger.latestConvergence(frames, lastHistory?.tops || [], selectedScale || '6-12m');
       if (!conv.latest) {
         txt.textContent = '近 104 周回放内无合格 LPPLS 顶部泡沫拟合（no_qualified_fit），顶部风险安全。';
       } else {
         const c = conv.latest.convergence;
         txt.textContent = `最近顶部聚类中心 ${c.median_date} · 状态：${c.label} · drift_ratio=${c.drift_ratio ?? '—'}（累计锁定 ${conv.lockedCount} 轮）。`;
       }
     }
   }
   ```

---

## 五、补丁 4：扩充仓库内置 `research/data/external.py` 与 `us_watchlist.py`（补齐 `^SOX` / `TSM` 及韩日数据层）

仓库已内置两套成熟的全球行情模块：
1. **美股个股（`research/data/us_stock.py` + `us_watchlist.py`）**：新浪美股日线 + 拆股现金分红乘性前复权，已由 `.github/workflows/us_nightly.yml` 每日 `30 22 * * 1-5` 产出 `stock/US_*.json`。将 **`TSM`（台积电）、`AVGO`（博通）、`ASML`（阿斯麦）、`AMD`**、`MRVL`、`MU`、`SNDK` 补入 `US_WATCHLIST` 即可自动随每晚 6 分片任务生成完整的 `physics_price.py` 指标（`well_F`, `vwap_gap`, `obv_div`, `amihud_ratio`）与 104 周 `as-of` OHLC K 线回放。
2. **全球指数与韩股双雄（`research/data/external.py`）**：仓库 `data/frozen/ext_v20261029/` 已内置 Yahoo Finance v8 管线并冻结了 `SPX.parquet` (`^GSPC`)、`NDX.parquet` (`^NDX`)、`N225.parquet` (`^N225`，11,513 根日线)。在 `EXTERNAL_TARGETS` 中补齐纳指综合、道指、**费城半导体指数（`^SOX`）**、韩国 KOSPI 与 SK 海力士 / 三星电子：

```python
# research/data/external.py 扩充 EXTERNAL_TARGETS
EXTERNAL_TARGETS = {
    # 已有内置标的
    "HSI":  {"yahoo": "^HSI",      "market": "hk", "kind": "index", "tz": "Asia/Hong_Kong", "close_hm": (16, 10)},
    "SPX":  {"yahoo": "^GSPC",     "market": "us", "kind": "index", "tz": "America/New_York", "close_hm": (16, 15)},
    "NDX":  {"yahoo": "^NDX",      "market": "us", "kind": "index", "tz": "America/New_York", "close_hm": (16, 15)},
    "N225": {"yahoo": "^N225",     "market": "jp", "kind": "index", "tz": "Asia/Tokyo",       "close_hm": (15, 35)},
    # 新增美股宽基/费城半导体 + 韩股 KOSPI 与半导体双雄（使用 Yahoo adjclose 乘性前复权）
    "IXIC":      {"yahoo": "^IXIC",     "market": "us", "kind": "index", "tz": "America/New_York", "close_hm": (16, 15)},
    "SOX":       {"yahoo": "^SOX",      "market": "us", "kind": "index", "tz": "America/New_York", "close_hm": (16, 15)},
    "DJI":       {"yahoo": "^DJI",      "market": "us", "kind": "index", "tz": "America/New_York", "close_hm": (16, 15)},
    "KR_KOSPI":  {"yahoo": "^KS11",     "market": "kr", "kind": "index", "tz": "Asia/Seoul",       "close_hm": (15, 35)},
    "KR_000660": {"yahoo": "000660.KS", "market": "kr", "kind": "stock", "tz": "Asia/Seoul",       "close_hm": (15, 35)},
    "KR_005930": {"yahoo": "005930.KS", "market": "kr", "kind": "stock", "tz": "Asia/Seoul",       "close_hm": (15, 35)},
}
```

> **PIT 收盘截点防泄漏（Strict Point-in-Time）**：不再粗糙剔除 UTC 当日，而是将最新 bar 时间戳转换至标的所属交易所本地时区 `tz`；若抓取时刻早于当地 `close_hm`，自动丢弃最后一根盘中残缺 K 线，确保四市场回测 100% 零前视偏差。

---

## 六、补丁 5：A 股 / 日股 / 韩股 / 美股分开回测与分时区每日定时更新（GitHub Actions）

因四个市场涨跌停制度（A股 ±10%/20%、韩股 ±30%、日股弹性限幅、美股无涨跌停）与宏观锚不同，**严禁跨市场混池归一化**，按各自收盘后 15~90 分钟拆分为 4 条独立定时流水线，统一推送到 `stock-results` 分支：

| 市场独立回测池 | 当地收盘时间 | GitHub Actions Cron (UTC) | 工作流文件 | 产出 JSON（写入 `stock-results`） |
| :--- | :--- | :--- | :--- | :--- |
| **[JP] 日股**（日经 225 `^N225`） | 15:30 JST | `45 6 * * 1-5` | `.github/workflows/jp_nightly.yml`（新增） | `index/JP_N225_latest.json`、`overview_jp_latest.json` |
| **[KR] 韩股**（`^KS11` + 海力士 `000660.KS` + 三星 `005930.KS`） | 15:30 KST | `10 7 * * 1-5` | `.github/workflows/kr_nightly.yml`（新增） | `index/KR_KOSPI_latest.json`、`stock/KR_000660.json`、`stock/KR_005930.json`、`overview_kr_latest.json` |
| **[CN] A 股**（7 大宽基 + 全 A 个股） | 15:00 CST | `45 7 * * 1-5` | `.github/workflows/index_daily.yml`（已有） | `index/sh*_latest.json`、`stock/300843.json`、`overview_latest.json` |
| **[US] 美股**（4 大指数 + `US_WATCHLIST` 个股） | 16:00 EST | `30 22 * * 1-5` | `.github/workflows/us_nightly.yml`（已有，扩充指数） | `index/US_*_latest.json`、`stock/US_*.json`、`overview_us_latest.json` |

新增 `.github/workflows/kr_nightly.yml` 与 `.github/workflows/jp_nightly.yml` 独立工作流模板（按时区彻底解耦重试与快照，直接复用 `us_nightly.yml` 的无锁并发提交与 SHA256 哈希封存）：

```yaml
# .github/workflows/jp_nightly.yml — 日股独立 PIT 回测（15:30 JST 收盘 → 15:45 JST 执行）
name: JP Market Daily PIT Pipeline
on:
  schedule:
    - cron: "45 6 * * 1-5"
  workflow_dispatch:

jobs:
  run-jp-pit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - name: Run JP isolated PIT backtest (N225.parquet + external.py incremental)
        run: python -m research.pipeline.apac_nightly --market jp --strict-pit
      - name: Publish JP artifacts to stock-results branch
        run: ./scripts/publish_stock_results.sh --prefix index/JP_,overview_jp
```

```yaml
# .github/workflows/kr_nightly.yml — 韩股独立 PIT 回测（15:30 KST 收盘 → 16:10 KST 执行）
name: KR Market Daily PIT Pipeline
on:
  schedule:
    - cron: "10 7 * * 1-5"
  workflow_dispatch:

jobs:
  run-kr-pit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - name: Run KR isolated PIT backtest (^KS11 / 000660.KS / 005930.KS)
        run: python -m research.pipeline.apac_nightly --market kr --strict-pit
      - name: Publish KR artifacts to stock-results branch
        run: ./scripts/publish_stock_results.sh --prefix index/KR_,stock/KR_,overview_kr
```

---

## 七、补丁 6：跨市场个股统一输出「完整专属物理指标面板 + 余震三定律 (Omori · Båth · Productivity)」

无论是 A 股（`300843`）、美股半导体/宽基（`^SOX`, `US_TSM`, `US_NVDA`, `US_AVGO`, `US_ASML`, `US_AMD`, `US_MU`, `US_MRVL`, `US_SNDK`）、韩股个股（`000660.KS`, `005930.KS`）还是日经 225（`^N225`），`research/pipeline/stock.py` 统一调用 `physics_price.py` 与 `bottom_dashboard.py` 输出对等字段，前端 `stock-view.js` 与统一终端 `index.html` 100% 对齐渲染：
1. **价格层 4 大物理指标**：自由能筹码势阱 `well_F`（`>= 1.25` 出清真空区，样本外 `IC +0.174`）、250 日 VWAP 折价 `vwap_gap`、OBV 20 日量价底背离 `obv_div`、Amihud 非流动性枯竭比 `amihud_ratio`。
2. **多维底分公式 × 外生环境三层交叉验证**：
   - 指数四维公式：`Score = 100 × (0.35·Valuation + 0.30·Clearing + 0.20·Stabilize + 0.15·RightSide)`（存在 6–12m 顶部红柱或回撤 `> -12%` 归 0）；
   - 个股防死猫跳乘数：`StockScore = 100 × Clearing × (0.48 + 0.34·Stabilize + 0.18·RightSide)`（回撤未达 `-15%` 归 0；余震红灯硬封顶 `<= 46` 分）；
   - 外生交叉验证：融资余额去杠杆（T+1 严格 PIT）、股债性价比 ERP 与破净率、头部宽基 ETF 申赎、市场宽度 `p20/p60` 及汇率/10Y 美债锚（剔除季度滞后的股东户数与已停披的日频北向资金）。
3. **地震统计物理余震三定律硬闸门（ETAS 框架） + 市场专属正交宏观锚**：
   - **第 1 定律 Omori–Utsu 衰减律**：`λ(t) = K / (t + c)^p`，要求 `λ(t)/λ₀ <= 1.25×` 且近 15 日超阈值冲击 `< 2` 次；
   - **第 2 定律 Båth's Law 震级差定律**：`ΔM = M₀ - M₁`，要求二次恐慌释放落入 `[0.72, 1.45]`（`< 0.72` 次生主震，`> 1.45` 欠释放）；
   - **第 3 定律 Utsu–Seki Productivity 生产力律**：`N_exp(M₀) = k · 10^(α(M₀ - M_c))`，核验实测累计余震 `N_obs` 与 `N_exp` 之比 `<= 1.35×` 且 ETAS 分支比 `n < 0.90`（排除去杠杆连环强平的超临界传染簇）。
