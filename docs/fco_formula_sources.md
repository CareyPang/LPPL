# "原站有但公式未公开"字段：公开代码与文献检索结果（2026-10-28）

检索范围：GitHub `lppls` 搜索前 15 个仓库（Boulder lppls 478★ 源码逐函数读、thebubbleindex、lppls-ci_tactical_asset_allocation 等）；文献全文：Zhang–Zhang–Sornette 2016 PLOS ONE（DS LPPLS Confidence/Trust 原始定义）、Gerlach–Demos–Sornette 2018 arXiv:1804.06261（情景聚类）、Filimonov–Demos–Sornette 2016 arXiv:1602.08258（t_c 区间）；FCO 官网首页 / FAQ / FBE 页；FCO Cockpit 2019 方法附录（已在 literature_review §16）。

## 结论一览
| 字段 | 公开出处 | 可按原文实现？ | 本项目处置 |
|---|---|---|---|
| DS Confidence（正/负） | PLOS 2016：满足条件 1 的窗口比例；Boulder `compute_indicators` 同（b<0 正泡沫、b>0 负泡沫） | 是，已实现 | 保持 |
| **DS Trust** | PLOS 2016：对每个窗口，把拟合残差 bootstrap 100 次加回拟合价生成合成序列，取满足**条件 2** 的比例，再对 126 个窗口取中位数 | 是（原站字段里没有 Trust，但原始论文有） | 可作"原版文献有、原站未显示"的补充；成本 ×100 拟合，先只对最新 as-of 算 |
| Confidence/Trust 的算术/几何均值 | PLOS 2016 第 3 点 | 是 | 同上 |
| **Combo(p)** 幂平均 | FCO 方法页：p=0 几何、1 算术、默认 0.1 | 是，已实现（3 尺度） | 扩六尺度；缺值规则原站未说→研究版规则（缺档剔除，分母按有值档） |
| **情景 probability** | Gerlach 2018：k-means 在 (dt, t_c−t_2) 平面聚类，k∈[2,10] 用 Silhouette 选；"把属于该簇的拟合比例解释为该情景概率的代理"（80%=101/126 拟合） | 是：簇内拟合数 / 合格拟合总数 | 实现并命名 `scenario.share`，页面写"情景占比（Gerlach 2018 口径），非崩盘概率"；原站 `ScenarioDto.probability` 是否同此口径未证实 |
| 情景数量/聚类空间 | 同上 | 是（我们现用的 (dt, t_c−t_2) k-means + Silhouette 与之一致） | 保持；补 k 上限 10 |
| **t_c 区间** | FDS 2016：修正剖面似然给 t_c 置信区间（含 m、ω、D 的区间） | 是，但每窗要算剖面似然，成本高 | 下一轮；本轮 t_c 区间仍为合格拟合 t_c 的经验分位（已标明） |
| **t_c 概率密度 PDF** | 未找到公开定义。FCO 官网只说"probability distribution of the critical time tc"；Gerlach 2018 只有直方图/簇 | 否 | 研究版：合格拟合 t_c 的加权 KDE（Scott 带宽，按尺度等权），标"经验分布，非校准概率" |
| **bubbleScore / bubbleMultiScaleScore** | 未找到。官网/FAQ/FBE 页只出现"daily bubble scores"字样；Cockpit 2019 附录无；Boulder/thebubbleindex 无同名量；原站前端 bundle 中 bubbleScore 与 combo10 并列用于排行（`refs_fco_frontend_notes.txt`） | 否 | 研究版 `score_rv = Combo(p=0.1)` 为主排序键，并列显示 `max 尺度置信度`（原站排行卡"分数+尺度"的最小可解释替代）；明确命名"研究版，非原站 bubbleScore" |
| **bubbleProgress** | 未找到公式。前端 bundle 显示它是 0–1 进度条 | 否 | 研究版：(t_2 − t_1)/(t_c − t_1)，t_1 为最长合格尺度 Lagrange 起点、t_c 为该尺度 tcMode；标研究版（我们当前 `top.bubble.progress` 已是这个定义） |
| **tcOffset / t1Offset / t2Offset** | 未找到单位说明 | 否 | 按"相对分析日 t_2 的交易日数"实现并注明 |
| **tcMode** | 未公开 | 否 | 研究版：合格拟合 t_c 直方图众数（5 日箱），已实现 |
| bubbleSize / bubbleDuration | FCO FAQ：起点到 t_c 处模型价幅度；起点到今天的时长 | 是，已实现 | 保持 |
| 月度体制带 | MONTHLY_REGIME_SPEC（交接包） | 是，已实现 | 保持 |
| Dragon-King Protection Protocol / Deep LPPLS 生产版 | 未公开 | 否 | 不做 |

## 两条有价值的新发现
1. **Trust 指标**是 Sornette 组自己定义、FCO 官网文字里没有但原始论文完整给出的量——"原版文献有"。它回答的是"这次拟合对噪声有多敏感"，与 Confidence（对窗口有多敏感）正交。可以作为"超越原站显示"的一项，但必须作为新模块走判据（先描述性）。
2. **情景概率的公开口径就是簇占比**（Gerlach 2018 原文），所以原站 `probability` 最可能也是这个；我们可以给出同口径数字，但必须写明"不是崩盘概率"。

## 不做的事
不把研究版评分叫作原站 bubbleScore；不把簇占比/KDE 当作校准预测概率；Trust、六尺度新增档、研究版评分一律先描述性显示，证据等级 `descriptive`/`research`，不进入本轮评价。
