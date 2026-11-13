# Phase 3b 底部时间：B9 候选（阴跌/恐慌代理、新低广度、Omori 稳定性、−lnP LPPLS）加入底部保留链（开发段，CPCV；2026-11-12）

> 代码 `research/eval/ladder_bottom_b9.py`；表 `reports/ladder_bottom_b9{,_point,_sub,_sub_point}.{md,csv}`。保留链 R0→B1(dd_nodur_z)→B2(amt_only_z)→B3(omori25) 用 `force_keep` 固定（§16.6 已选配置），B9 与 B3 配对 ΔBrier（80 日块 bootstrap 90% 区间）；主链 ci、次要链 point。
> 候选（全部 as-of 可知）：regime = fall_speed（dd60/dd250）+ days_since_max250；newlow = 成分股 60 日新低比例及 20 日均值；omori_stab = omori_p_25 的 20 日滚动标准差；regime_newlow；子集 106 标的（6 指数 + 100 成分股，有 −lnP 扫描）另加 neglppls（STANDARD 12–24m 置信度，as-of 前向填充）、neg_x_slow（置信度 × fall_speed）。

## 结论：**全部未通过**（主链与次要链）
| 样本 | B3 Brier | B9 最优 | B9 Brier | ΔBrier vs B3 | 90% 区间 | 主链 | 次要链 |
|---|--:|---|--:|--:|---|:--:|:--:|
| 306 标的（n=470,305） | 0.06051 | newlow（C=0.1） | 0.06055 | +0.00004 | [−0.00030, +0.00033] | 未达 | 未达 |
| 106 标的子集（n=168,396） | 0.05962 | newlow（C=0.1） | 0.05971 | +0.00009 | [−0.00007, +0.00025] | 未达 | 未达 |

子集中 neglppls Brier 0.05976、neg_x_slow 0.06021（均劣于 B3 0.05962）；regime 0.06016–0.06094、omori_stab 0.05997–0.06086，全部不优于 B3。PR-AUC 最高 omori_stab 0.129 vs B3 0.126，无实质差别。

## 解读
- Phase 3a 的分层信号（阴跌底召回 0.58–0.77）在 CPCV ΔBrier 框架下没有转化为增量：三重障碍标签在 20 日窗内的日频概率，B1 的回撤/收益/波动特征已经吸收了"跌了多久、跌了多少"的信息，fall_speed 与 −lnP 置信度是它们的函数。
- 事件级（底前 120 日是否有报警）与日频概率（每日 Brier）是两个口径；3a 的召回优势说明 −lnP LPPLS 可作**阴跌体制下的描述性事件标记**，但不能作为概率模型的特征进入保留链。
- 恐慌底仍无工具：newlow / omori_stab 也没有增量。

## 对 3c 与产品的含义
- 抄底时间：保留链维持 R0→B1→B2→B3；LPPLS −lnP 只作描述字段并标注"仅阴跌型下跌有历史召回"（as-of 代理 fall_speed 低于 0.5 时显示），不进判据。
- 3c 底部价格：在既有估值地板带之外不再新增模型；谷价条件分位已由 Q-DD2（§21.5）负面覆盖。
