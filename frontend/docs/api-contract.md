> 已废弃：前端只读静态 JSON，见仓库 docs/frontend_contract.md 与 docs/od_field_mapping.md。

# 临界点 · 前后端接口约定 (contract v1)

前端只通过 `app/api.js` 的 `OD_API` 取数。后端按本文返回 JSON，前端无需再改页面。
本文字段全部来自现有引擎 `app/critical.js` 的实际输出（`CP.run`），后端的返回结构必须与之一致。

## 0. 约定

- Base：`{baseUrl}/api/v1`，所有响应 `Content-Type: application/json; charset=utf-8`。
- 每个成功响应都带 `"contract": 1`。版本不一致前端会报错并回退本地引擎。
- 鉴权（可选）：`Authorization: Bearer <token>`。
- 日期一律 `YYYY-MM-DD`。价格为前复权。
- **时间下标**：所有 `i`、`T`、`lo`、`hi`、`mid` 都是 `bars` 数组的下标，不是日期。窗口类字段（`scan.clusters` 等）用**相对 T 的偏移（交易日）**，见各字段说明。
- **NaN**：JSON 没有 NaN，用 `null`。前端会把 `recall/precision/randPrecision/medErr/topErr/dirUp` 的 null 还原为 NaN。
- **Point-in-Time**：`scan / rm / phase / chk` 只能用 `bars[0..T]` 计算。`replay` 与 `evalr` 是事后打分，可以用 T 之后的数据，但必须与预测部分分开。
- 前端不展示任何“收益保证”。`conf` 是窗口一致度，不是概率；后端不要把它命名为 probability。

## 1. 接口清单

| 方法 | 路径 | 用途 | 必需 |
|---|---|---|---|
| GET | `/analysis?code=&asof=` | 单标的分析 | 是 |
| GET | `/jobs/{id}` | 长任务轮询 | 分析超过数秒时 |
| GET | `/bench` | 三大指数全样本验证 | 否（缺省前端用本地快照） |
| GET | `/symbols?q=` | 代码或名称搜索 | 否 |
| GET | `/health` | 健康检查 | 否 |

### 1.1 `GET /analysis`

参数：

| 名称 | 说明 |
|---|---|
| `code` | 6 位 A 股代码（`600519`、`000001`，可带 `.SH/.SZ`），或 `上证指数 / 沪深300 / 创业板指`（前端传原文，后端自行识别；也可接受 `000001.SH` 等指数代码） |
| `asof` | 可选，`YYYY-MM-DD`。截止日，缺省为最新交易日。若不是交易日取其之前最近一日；`T<300` 时取第 300 根 |

响应 A（直接返回）：`{ "contract": 1, "result": <Analysis> }`

响应 B（任务模式）：`{ "contract": 1, "job": { "id", "status": "queued|running|done|failed", "progress": 0~1, "stage": "顶部引擎：第 3/21 个窗口", "result"?: <Analysis>, "errorCode"?, "message"? } }`
前端每 800ms 请求 `GET /jobs/{id}`，直到 `done`。

错误：HTTP 4xx/5xx，`{ "contract": 1, "error": { "code", "message" } }`

| code | 含义 |
|---|---|
| `BAD_INPUT` | 无法识别代码（前端不会回退本地，直接提示用户） |
| `DATA_UNAVAILABLE` | 数据源取不到 |
| `DATA_BAN` | 数据质量不达标，禁止分析 |
| `TOO_SHORT` | 有效日线少于 320 根 |
| `RATE_LIMIT` / `INTERNAL` | 限流 / 内部错误 |

### 1.2 `<Analysis>` 顶层

| 字段 | 类型 | 说明 |
|---|---|---|
| `sym` | Sym | 标的 |
| `data` | Data | 数据来源信息 |
| `bars` | Bar[] | 全部日线（升序），包含 T 之后的数据 |
| `T` | int | 截止日下标 |
| `asof` | string | `bars[T].date` |
| `latest` | bool | `T == bars.length-1` |
| `scan` | Scan | 截止日顶部多窗口扫描 |
| `rm` | Roadmap | 路线图（见顶窗口、回落、二波） |
| `phase` | Phase | 当前所处阶段 |
| `chk` | BottomCheck \| null | 底部 6 项检查 |
| `tape` | TapeEntry[] | 信号带：每 ~5 个交易日一条的历史扫描摘要 |
| `tapeSrc` | string | 信号带来源说明，原样展示 |
| `replay` | Replay \| null | `T >= N-3`（即最新）时为 null |
| `evalr` | Eval | 命中评估 |
| `backend` | string | 由前端写入，后端不用返回 |

### 1.3 子结构

**Sym**：`{ key, label, code, secid, isIndex, limit, market }`
`limit` 涨跌停幅度（0.1 / 0.2）；`market` 为 `SH|SZ`；指数 `isIndex=true`。

**Data**：`{ name, source, snapshot?: bool, synthetic?: bool, truncated?: int, fetchError?: string }`

**Bar**：`{ date, open, high, low, close, volume }`（`volume` 单位：股）。可选 `amount`。

**Scan**（顶部引擎，窗口数通常 ~21）
```
{ T, total, nq, conf, clusters: Cluster[], fits: Fit[], anchors: int[] }
```
- `total` 拟合窗口数；`nq` 通过形态过滤的窗口数；`conf = nq/total`。
- `Fit`：`{ n, ahead, m, w, D, O, R2, q }` — `n` 窗口长度（交易日），`ahead` t_c 距 T 的交易日数（可为小数），`m` 幂指数，`w` 角频率 ω，`D` 阻尼，`O` 振荡次数，`R2`，`q` 是否通过过滤。
- `Cluster`（t_c 聚类，按一致度降序）：`{ lo, hi, mid, n, conf, wins }`，**`lo/hi/mid` 是相对 T 的偏移（交易日）**；`n` 成员窗口数；`conf` = n/total；`wins` 成员窗口长度数组。
- 前端 `rm` 里会把偏移换算成绝对下标，所以后端只需给 `Scan` 的偏移，并保证 `rm` 已换算。

**Roadmap（rm）**
```
{ T, date, close, sigma, scan, topW, altW, conf, level, topPx, crash, stats, wellsBelow, hi60, hi60I }
```
- `sigma` 近 60 日日对数收益标准差；`hi60/hi60I` 近 60 日最高收盘价及下标。
- `level`：`none|low|mid|high`（`conf≥0.15` 为 mid，`≥0.3` 为 high）。
- `topW` / `altW`：`null` 或 `{ lo, hi, mid, n, conf, loDate, hiDate, midDate, wins }`，**这里的 lo/hi/mid 是绝对下标**。入选条件：成员窗口 ≥4 且 `conf ≥ 0.06`。
- `topPx`：`null` 或 `[低, 高]`，到达窗口中点时的 1σ 价格区间（不是目标价）。
- `crash`：`null`（需要 `topW` 且历史回撤样本 ≥3）或
  `{ depth:[q25,q50,q75], days:[…], rebound:[…], n, botLo, botHi, botLoDate, botHiDate, pxHi, pxLo, pxMid, ref, wave2 }`
  `pxHi/pxLo` 是回落区价格上下沿，`wave2` 二波参考价。
- `stats`：`{ thr, n, legs:[{top,bot,depth,days,rebound}], depth:[3], days:[3], rebound:[3] }`
- `wellsBelow`：现价下方最多 2 个价格井 `{ g, x, price, F, mass, depth, lo, hi }`。

**Phase**：`{ k: "acc|accel|crit|crash|base|wave2", chk?: BottomCheck }`

**BottomCheck**
```
{ items: [{ k, name, need, ok, detail }], score, max, pass, dd, ddNow, lowI, peakI, sigma, well }
```
`items.k` 取值：`depth` `time` `panic` `turn` `well` `anti`。`pass = 必要项全满足 且 score≥4`。`detail` 为给用户看的中文说明，后端直接生成。

**TapeEntry**（紧凑数组，节省体积）
`[T, total, nq, c0, c1]`，`c0/c1` 为 `null` 或 `[lo, hi, mid, n]`（相对 T 的偏移，最多两个聚类）。

**Replay**（事后打分）
```
{ T, end, peak:{i,date,px,gain}, bottom:{i,date,px,dd}, wave2:{i,date,px,gain},
  topHit?, topErr?, botTimeHit?, botPxHit?,
  firstSig?:{ i, date, conf, lead },
  sim: Sim }
```
**Sim**：`{ from, to, eq:number[], bh:number[], phase:string[], acts:Act[], ret, bhRet, mdd, bhMdd, dates:string[], state, pos }`
`eq/bh` 为从 `from` 到 `to` 的净值（起点 1.0），`Act`：`{ i, date, px, from, to, why }`（仓位 0~1 变动）。

**Eval**
```
{ thr, events:[{i,type:"top",p,hit}], episodes:[{start,lo,hi,n,conf,drop,good}],
  recall, precision, randPrecision, medErr, nEv, nEp }
```

**交易规则（写死，前后端一致）**：T+1、涨跌停不可成交、佣金、印花税、滑点，参数见 `CP.RULES`（`alertConf, alertLead, firstCut, trail, crashK, falseAlarmDays, comm, stamp, slip`）。后端改动规则时必须升级 `contract`。

### 1.4 `GET /bench`
`{ contract:1, result:[{ key, label, ev:Eval, s16, s19, s24, end, start }] }`
`s16/s19/s24 = { ret, bh, mdd, bhMdd }`（2016/2019/2024 年起按计划与持有对比）。目前页面直接用本地快照，此接口接入后再切换。

### 1.5 `GET /symbols?q=`
`{ contract:1, result:[{ code, name, market, isIndex }] }`，最多 20 条。

### 1.6 `GET /health`
`{ contract:1, status:"ok", engine:"python-0.1", dataThrough:"YYYY-MM-DD" }`

## 2. 后端必须守住的约束
1. `scan/rm/phase/chk/tape` 只用 `bars[0..T]`；`tape` 中每条 `T'` 也只用 `bars[0..T']`。
2. 拟合价格口径一致（同一次拟合只用前复权）。
3. 失败与无信号的案例保留，`topW=null` 就返回 null，不要凑一个窗口。
4. `conf` 不得改名或解释为概率；概率类字段若新增，必须带 `calibrated: bool` 并说明样本外状态。
5. 响应体积：`bars` 全量约 1MB 以内可接受；超过 5MB 时与前端商量改为分页或压缩（gzip 必开）。

## 3. 前端如何切换
```html
<!-- 方式一：网址参数 -->
tv.html?api=http://127.0.0.1:8000

<!-- 方式二：页面加载前配置 -->
<script>window.OD_API_CONFIG = { mode:'remote', baseUrl:'https://api.example.com', token:'…', fallback:true };</script>
```
- `fallback:true`：后端失败（网络、超时、版本不符）时自动回退浏览器引擎，页面会拿到 `R.backend='local'` 与 `R.backendError`。`BAD_INPUT` 不回退。
- 打包 APK（Capacitor）时 `baseUrl` 必须是 https 地址，并在后端开启 CORS：允许 `Authorization`、`Accept` 头与 `GET`。
- 联调检查：控制台执行 `await OD_API.ping()`。

## 4. 最小示例（节选）
```json
{
  "contract": 1,
  "result": {
    "sym": {"key":"1.000001","label":"上证指数","code":"上证指数","secid":"1.000001","isIndex":true,"limit":0.1,"market":"SH"},
    "data": {"name":"上证指数","source":"AkShare 前复权日线","snapshot":false},
    "bars": [{"date":"2026-02-27","open":4100.1,"high":4120.3,"low":4090.0,"close":4110.5,"volume":412345678}],
    "T": 2370, "asof": "2026-02-27", "latest": false,
    "scan": {"T":2370,"total":21,"nq":5,"conf":0.238,"clusters":[{"lo":2,"hi":11,"mid":6,"n":5,"conf":0.238,"wins":[60,90,120,160,225]}],"fits":[],"anchors":[]},
    "rm": {"topW":{"lo":2372,"hi":2381,"mid":2376,"n":5,"conf":0.238,"loDate":"2026-03-02","hiDate":"2026-03-13","midDate":"2026-03-06","wins":[]},"crash":null,"level":"mid"},
    "phase": {"k":"crit"},
    "chk": null,
    "tape": [[2000,21,0,null,null]],
    "tapeSrc": "后端预计算，截至 2026-10-23",
    "replay": null,
    "evalr": {"events":[],"episodes":[],"recall":null,"precision":null,"randPrecision":0.2,"medErr":null,"nEv":0,"nEp":0}
  }
}
```
（示例数值仅为说明字段格式。）
