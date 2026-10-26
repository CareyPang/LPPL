# 老版前端（web/app，原型 engine.js / critical.js / ui.js）模块证据审计（D1，2026-10-26）

目的：产品化时，老版页面上每一个输出都必须对应研究层的证据等级；没有证据的模块改为"无证据"显示或下线。证据等级来源 `docs/dev_freeze.md` §2 与 `reports/lppls_v2_summary.md`。

| 老版模块（函数） | 老版输出 | 研究层对应 | 证据等级 | 处置 |
|---|---|---|---|---|
| `scanAt` / `fitWindow` / `qualifyTop`（DS 置信度） | 多窗口合格比例 | T-B LPPLS 置信度（E7 搜索域 + box 规则，产品尺度 6–12 / 12–24 月） | dev（原版 FBE 口径；精度集中泡沫年） | 保留，改为 FCO 两主档 + 1–3 月描述性，带 badge |
| `clusterTc` | 临界时间簇、"一致的临界时间" | T-C t_c 情景（簇内 20/80 分位，不跨簇） | dev（覆盖率 1–4%，不作峰值日） | 保留为展示，文案改"情景"，禁止"一致临界时间"措辞 |
| `lagrangeBest` | Lagrange 选窗 | §17.4-5 M3/E4 | dev | 保留为内部选窗，不单独展示 |
| `logitFit` + 阈值（p20） | 见顶概率 | T-A 阶梯概率（保留链 R0→R2 GSADF；R4 LPPLS 未通过） | dev，待校准 | 来源待用户裁决（R2 vs R4）；校准前标 dev |
| `governor`（Signal Governor） | "临界区：准备逃顶 / 平稳期：无临界结构" | T-D 顶部区间与失效规则 | rule（规则，非预测） | 保留，badge=rule |
| `kdeLandscape` / `findWells`（EFE 自由能、支撑阱） | "预计回落区（价格）" | 开发段 B7well：未进入保留链 | none | 改为"无有效预测 + 历史无条件回撤分位（描述性）" |
| `dfaAt` / `permEntAt` / `ar`（临界慢化、DFA、置换熵） | 相变指标 | R7 统计物理：阶梯未保留（ΔBrier 区间含 0） | none | 下线或折叠到"研究中"，不参与结论 |
| 首达概率（`solveBeta`/`gauss` 相关） | "回落时间" | 无对应登记模块 | none | 改为"无有效预测" |
| 反泡沫（critical.js 底部结构） | "进场抄底" | §17.12/17.13 负泡沫/反泡沫：0 稳健 | none | 底部卡片只显示描述性状态；LPPLS 底部标"无证据" |
| 二波（"二波参考 / 二波目标 / 二波高点 / 二波：持有"） | 二波目标与退出 | 无登记模块 | none | 下线；契约 `second_wave.value=null, evidence=none` |
| `tape-snapshot.js` 预算信号带 | 历史信号缓存 | 由契约 JSON（`research/pipeline/daily.py` 输出）替代 | — | 替换 |
| `data-snapshot.js` | 行情快照 | PIT 缓存 `research/data/cache.py` | — | 替换 |

处置原则：顶部为第一优先输出且定位不变；凡标 none 的模块不删除研究代码，只在产品层停止给出结论；校准段/最终测试段出结果后按 `dev_freeze.md` §4 升降 badge。
