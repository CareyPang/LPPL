# 等待期六项工作结果汇总（2026-10-24；全部为开发段或工具层结果，不是样本外结论）

| # | 项目 | 状态 | 关键结果 | 来源文件 |
|---|---|---|---|---|
| 1 | D-TOP 决策层回测（主链 + 次要链） | 开发段完成；产品表达待 LPPLS 结果后定 | 6 组概率阈值规则在 2015 年以外仅减少事件后回撤 1–3 pp，≈ 安慰剂；无模型基线最强：波动率目标 22.8 pp、跟踪止损 20.1 pp（剔除 2015 后跟踪止损最好，+3.3 pp [下界 +1.6] 于波动率目标）；概率叠在波动率目标上（d3）剔除 2015 后 +1.7 pp [下界 +1.3]，相对跟踪止损不显著 | `reports/dtop_dev.md`、`reports/dtop_dev_point.md`、`docs/preregistration.md` §14.1/§14.4 |
| 2 | Q-DD "跌到哪"分位回归 | 完成 | 两组配置 Δpinball 均 ≈ +0.0020（区间含 0 偏正），覆盖 82.7%（目标 90%）——**不如无条件 90% 分位** | `reports/qdd_dev.md` |
| 3 | SPA / PBO / Deflated Sharpe 工具 | 代码 + 合成测试完成；已接入阶梯（`mt_report`），等完整顺序阶梯产出逐日损失矩阵 | — | `research/eval/multiple_testing.py`、`research/eval/mt_report.py`、`tests/test_multiple_testing.py` |
| 4 | R6 资金面数据准备 | 数据完成；特征与阶梯接入未做 | 沪、深融资日报各 3747 行，2010-03-31–2025-08-29，失败 0；市场级账户统计 2012-09 起；合并与 PIT 滞后 1 日的 `load_margin()` 已实现 | `reports/r6_fund_flow_data.md`、`research/data/margin.py` |
| 5 | 固定 Platt + 区间保形缩放 | 代码 + 合成测试完成；未碰校准段 | — | `research/eval/calibration.py`、`tests/test_calibration.py` |
| 6 | 底部三重障碍标签 | 代码 + 合成测试完成；未跑真实数据 | — | `research/labels/bottom.py`、`tests/test_labels_bottom.py` |

附加完成项：预登记 v1.4（§14.1–14.4）；`docs/bottom_and_price_layer_design.md`（底部/价格层/金融物理综述与 v1.5 草案）；无人值守流水线 `scripts/post_scan_pipeline.sh`（扫描结束 → §12.2 算力门 → 预登记顺序完整阶梯 → PBO/SPA → T-INT → D-TOP 重跑）。

扫描后（2026-10-24 晚）：指数 LPPLS 扫描完成；§12.2 算力门触发（`reports/ladder_dev_lppls.md`）；完整顺序稀疏阶梯主链 R0→R2、PBO 0.45、SPA p 0.44（`reports/ladder_dev_full.md`、`*_mt.md`）；T-INT 20 组全淘汰（`reports/tint_dev.md`）。
阶段 5 开发段（prereg §15/§15.1）：标签 `reports/bottom_label_events.md`；60 日阶梯 B0→B1→B2→B3（`reports/ladder_bottom_dev.md`）；快底 fast30 另保留 B7（`reports/ladder_bottom_dev_fast30.md`）；B5 融资子样本未保留（`reports/ladder_bottom_margin_dev.md`）；阶段二起涨确认仅宽度有效（`reports/thrust_stage2_dev.md`）；D-BOT 负面（`reports/dbot_dev.md`，失败记录 `dbot_dev_fixedbar.md`）。
未完成/待决定：个股开发段 LPPLS 扫描；校准段与最终测试段。

## v1.6 对抗性检验与证据等级（2026-10-24 夜，开发段，个股 LPPLS 扫描进行中）

| 检验 | 顶部 R1 / R2 / R7 | 顶部 R8 宽度聚合 | 底部 B1 / B2 / B3 |
|---|---|---|---|
| 剔除 2007–08 | ✗ / ✓ / ✓ | ✓ | ✓ / ✓ / ✗ |
| 剔除 2015 | ✗ / ✗ / ✗ | ✗ | ✓ / ✓ / ✗ |
| 剔除 2018 | ✓ / ✗ / ✗ | ✗ | ✓ / ✓ / ✗ |
| 只用指数 | ✗ / ✗ / ✗（保留链 = 基率） | — | ✓ / ✗ / ✗ |
| 只用个股 | ✗ / ✗ / ✓ | — | ✓ / ✗ / ✗ |
| 替代标签 PS / LT | 全部 ✗ | — | B1 ✗✗、B2 ✗✓、B3 ✗✗（替代底部标签事件极少，效力低） |

来源：`ladder_dev_loco.md`、`ladder_dev_r8_loco.md`、`ladder_dev_index.md`、`ladder_dev_stock.md`、`ladder_dev_alt_labels.md`、`ladder_bottom_dev_loco.md`、`ladder_bottom_dev_index.md`、`ladder_bottom_dev_stock.md`、`ladder_bottom_dev_alt_labels.md`。

其他 §15.2/§16 结果：T-INT-P 概率区间失败（IS 46 vs 基线 19，`tintp_dev.md`）；D-BOT 模型退出仍不胜基线（`dbot_dev.md`）；R8 主链保留但依赖 2015（`ladder_dev_r8.md`）。

### 证据等级（§16.5，当前）
| 产品输出 | 来源 | evidence | 备注 |
|---|---|---|---|
| 底部状态概率 | B1（回撤深度/跌幅/波动） | dev | 留出年、分层全部成立；替代标签下未成立 |
| 底部状态概率增量 | B2 量缩回升、B3 Omori | dev（弱） | B2 仅合并样本成立；B3 留出任一年均失效 |
| 起涨确认 | 阶段二宽度 | dev | 未做留出年检验 |
| 顶部风险概率 | R2/R7（+R8） | dev（依赖 2015） | 剔除 2015 后无增量；指数单独无增量；替代标签下失效 |
| 顶部时间区间 | 标签视窗 20 日 | 随顶部概率 | t_c 区间、概率区间、hazard 累计曲线（§16.7：hazard ΔBrier +0.0066 [+0.0015, +0.0141]，劣于二分类）均 none |
| 分批减仓 | 波动率目标 / 跟踪止损（无模型） | dev | 概率叠加增量仅 2015 外 +1.7pp |
| 下跌幅度 | — | none | Q-DD 不如无条件分位 |
| 底部进场规则 | — | none | D-BOT 各版本均不胜基线 |
| LPPLS t_c / 置信度 | — | none（指数）/ 待评估（个股） | 个股开发段扫描进行中 |
