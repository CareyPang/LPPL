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
