# 临界点 2.0 —— Web 应用总规划、当前进度与交接（2026-11-01）

> 本文件是总指挥文档：换电脑继续做时先读这里。数字均来自仓库内脚本与报告，标注了出处。

## 0. 一句话现状
6 个 A 股指数的完整产品已上线（[主页](https://careypang.github.io/LPPL/) / [终端](https://careypang.github.io/LPPL/index.html) / [回测](https://careypang.github.io/LPPL/backtest.html) / 旧研究站 `/lab/`）。"输入任意 A 股代码 → 取数 → 当前预测 + 历史参考"尚未产品化：`frontend/stock.html` 只把个股映射到所属指数；`research/pipeline/universe.py` 能对单只个股算当前信号，但结果只进工作台排行。

## 1. 已完成（按层）
| 层 | 状态 | 关键文件 |
|---|---|---|
| 研究层 | LPPLS 核心、六尺度置信度、Trust、开发/校准/测试三段、前瞻日志与季度复盘 | `research/lppls/`、`research/eval/`、`research/pipeline/forward_log.py` |
| 数据层 | PIT 冻结：A 股 6 指数 + 外部 4 指数；两融、PE、FINRA 缓存；腾讯→新浪/东财备用链 | `research/data/` |
| 价格层 | P1 回撤情景表 + 估值地板；B 卡（便宜层 + LT 确认状态）；W 卡（收复比例等 4 列） | `research/price_layer/`、PR #16 #21 |
| 前端 | Open Design 主页、终端、回测页；共享情景区间绘图 | `frontend/`、PR #17 #19 #20 |
| 文献 | 价格层四问综述、回撤条件变量核实（排序更正为 涨幅/加速度 > 估值 ≈ 两融） | `docs/literature_price_layer.md` |

## 2. 证据的实话（产品边界）
顶部模型 `validation`（`web/mock/data/sh000001_latest.json`）：
- 开发段 2000–2018：长尺度置信度 ≥5% 时，顶被提前报警 50%；报警后 120 日内未见顶 70%。
- 校准段 2019–2021：`fail_i` / `cal_fragile`；最终测试 2022-01–2025-08：`fail`。三段合并 **`dev_only`**。
- t_c 聚类紧是否让顶部时间更准：**否**（`reports/tc_cluster_dev.md`：聚类≤10 日顶区 ±5 日命中 11.1% vs 随机 10.0%；约六成紧聚类之后 250 日内无顶）。
- 底部：没有模型在独立样本外提前给出底部日期或价格；LT 15% 是滞后确认。

**因此产品只承诺**：风险区间 + 历史频率 + 虚警率 + 事后确认 + 描述性价格分位（带 n）。**不写**目标价、精确顶/底日期、"误差一周"。

## 3. 目标产品（终态）
用户输入 6 位代码 →
1. **当前预测**（秒级）：六尺度置信度、t_c 情景区间（只显示起止）、Trust、B/W 卡（指数）或个股简版卡；顶部固定一行证据等级。
2. **历史参考**（后台）：近 2 年周度截止日的情景区间回放 + 事后确认顶 + 该标的自己的命中/虚警（n 不足不显示数字）。
3. **市场基础信息**（描述性，不进模型）：行业资金流热力图、北向、两融、估值热力图、市场宽度。

## 4. 计算量（实测，`贵州茅台`，6 年日线，8 核 VM，2026-11-01）
| 步骤 | 耗时 |
|---|---|
| 取数（腾讯 + 新浪复权因子） | 6.7 秒 |
| 当前预测，轻量 16 窗口 | 8 核 1.2 秒 / 单核 9 秒 |
| 当前预测，全套 189 窗口 | 8 核 12 秒 / 单核约 100 秒 |
| `universe.one` 端到端 | 11 秒 |
| 近 2 年周度历史参考（104 个截止日） | 轻量约 2 分钟 / 全套约 21 分钟（8 核） |
| Trust（100 次 bootstrap） | 未计入；放后台 |

Trust 的作用：把拟合残差重采样 100 次加回拟合价格，重新拟合并检查原文 Table 3 条件 2，通过比例的中位数即 Trust（Zhang–Zhang–Sornette 2016）。衡量"这个泡沫结构对噪声是否敏感"，与置信度（对窗口长度的敏感性）正交；证据等级 descriptive。

## 5. 三条主线的执行方案
### 5.1 个股引擎
- 新模块 `research/pipeline/stock.py`：`predict(code, variant)`（当前预测）与 `history(code, weeks, variant)`（周度回放）。复用 `daily.fit_asof` / `_derived` / `rules` / `build_record`。
- 变体：`stk_lite`（`universe.WINDOWS`，16 窗）、`stk_full`（日更同款窗口集合）。变体写进 `model_version`，成绩单不得混算。
- 复权：**后复权**（新浪 hfq 因子 × 腾讯不复权），不受未来分红改写历史；因子日期 ≤ 交易日。
- 个股规则：上市满 500 个交易日；剔除上市首 60 日；停牌不插值；窗口内一字板（|涨跌|≥9.8% 且 high==low）比例 >20% 标 `degenerate`；ST 与市值后 10% 允许查询但标"不入统计"。
- 缓存键：`(code, asof, variant, data_version, code_version)` → `data/stock/{code}/{variant}/fits.parquet`（追加，已有键永不重算）；JSON 输出 `web/mock/data/stock/{code}.json`。
- 证据：个股一律 `research_candidate`，不继承指数证据；置信度数值按 `dev_only` 规则不显示。
- 测试：PIT（截断数据重算 = 回放结果）、确定性、缓存命中不重算、复权因子方向、规则边界。

### 5.2 后端（不备案方案：拉取式）
| | 拉取式（推荐首期） | 直连 API |
|---|---|---|
| 备案 | 不需要 | 大陆机绑域名需要（1–3 周） |
| 安全 | 计算机不开端口 | 暴露公网，需限流/防护 |
| 速度 | 排队 + 计算 + 推回，约 1–3 分钟 | 秒级 |
| 结果 | 推回仓库，可复现可审计 | 服务器磁盘，需备份 |

拉取式实现分两期：
1. **GitHub Actions 版（零服务器）**：`workflow_dispatch` 输入代码 → Actions 跑 `stock.predict` → 提交 JSON → Pages 自动发布。GitHub 托管机在境外，腾讯/新浪接口需实测可达性。
2. **腾讯云 worker 版**：大陆机定时拉取队列（Cloudflare Worker + KV，或 GitHub Issues 标签）→ 计算 → 推回仓库/COS。公网入口由 Cloudflare Worker 承担（HTTPS、限流、代码格式校验）。

缓存分层：浏览器内存（单页会话）→ Pages/CDN 静态 JSON → 计算机磁盘 parquet（拟合结果）+ SQLite（任务与元数据）。缓存键含数据版本与模型版本，历史结果不被当天覆盖。

### 5.3 个股证据分级
- 初始：指数维持现有；行业指数、个股为 `research_candidate`。
- 升级必须：单独预登记 → 开发/校准/测试三段 → A1/A2 对随机 → Holm 校正 → 事件簇（按月）block bootstrap 置信区间；只报整体与预定分组（市值三档 × 行业），不展示"最好的股票"；n 不足不显示数字。
- 禁止：借用指数证据；个股表现差后改窗口或阈值"修"信号。

## 6. 市场基础信息（描述性）
| 图 | 接口（a-stock-data skill） | 历史 | 注意 |
|---|---|---|---|
| 行业/概念/地域资金流热力图 | `board_fund_flow(类型, 今日/5日/10日)` | 无长历史，上线日起每日落盘 | "主力"=按单笔金额分档，不是机构流向 |
| 个股资金流 | `stock_fund_flow_120d(code)` | 120 日 | 同上 |
| 北向资金 | HKEX 日度官方统计 | 2014 起 | 2024-08 起盘中不披露 |
| 两融 | 已有缓存 | 2010 起 | 滞后 1 日；对回撤无样本外预测力，只作对照 |
| 行业估值热力图 | 中证/国证指数估值 | 约 10 年 | 发布滞后约 1 个月 |
| 市场宽度 | 涨停池/炸板率、通达信盘后包 | — | 趋势/宽度类只作对照基线，不进模型 |

## 7. 14 小时长程计划（2026-11-01 起，每阶段一个 PR，合并需用户说"合并"）
| 序 | 时长 | 内容 | 验收 |
|---|---|---|---|
| A | 1h | 本文件 + t_c 聚类探索入库 | PR |
| B | 4h | 个股引擎 `stock.py`（§5.1）+ 测试 + 10 只沪深300 成分测速报告 | `python -m research.pipeline.stock 600519` 出 JSON；CI 绿；测速表 |
| C | 3h | 市场基础信息数据层：行业资金流/北向/两融/估值/宽度日更落盘 `web/mock/data/market/` + `/lab/` 简版卡 | 一次真实落盘；CI 绿 |
| D | 2h | GitHub Actions 按需计算（§5.2 第 1 期）：`workflow_dispatch(code)` → JSON 提交；境外可达性实测与备用链 | 手动触发一次成功或记录失败原因 |
| E | 2h | 沪深300 成分当前预测预算库（`stk_lite`）+ 历史参考 2 年；`/lab/` 代码查询页 | 300 只 JSON；失败清单 |
| F | 1h | 个股/行业预登记草案（只写判据不跑）+ Open Design 前端 prompt（个股页、市场页） | 文档 |
| G | 1h | 本文件进度更新、交接 | PR |

## 8. 待用户决定
1. 腾讯云：是否开机（2 核 4G 起，大陆）；拉取式不需要备案。
2. 是否接受"区间 + 频率 + 虚警率"的表达，不写日期和目标价。

## 9. 换电脑继续
```
git clone https://github.com/CareyPang/LPPL && cd LPPL
pip install -e ".[dev]"
pytest -m "not network"          # 离线自检
python -m research.pipeline.universe --help
bash scripts/build_site.sh && python -m http.server 8000 -d _site
```
入库的只有 `data/frozen/`（PIT 冻结价格）和 `data/universe/`。`data/features/`（LPPLS 扫描，研究脚本如 `tc_stability_eval`/`tc_cluster_dev` 依赖它）、`data/labels/`、`data/cache/`、`data/oof/` 体积约 3.8 GB，作为 GitHub Release [`research-data-v20261101`](https://github.com/CareyPang/LPPL/releases/tag/research-data-v20261101) 附件发布（zstd 分 2 卷，2.9 GB，带 SHA256）。新电脑在仓库根目录执行：
```
pip install zstandard
python scripts/fetch_research_data.py
```
日更、个股预测与前端不依赖它们。Open Design 规则见 `frontend/AGENTS.md`。进度以本文件 §7 表格与 PR 列表为准。
