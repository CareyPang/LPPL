# 第二阶段后端升级与 JSON 导出规范（Devin Fusion 任务清单）

> 前端已完成第 0 步契约松绑与第一阶段重构（分支 `od/lppl-workbench-v2`），并预留了以下标准字段接口。后端 `research/` 按本清单完成后，前端即可自动无缝点亮更精细的 FCO 泡沫强度柱、Episode 事件级回测指标与冷却期状态。

## 1. 优化器架构：固定种子 DE + TRF/LM 混合加速
- **离线全量扫描与历史回测**：保留固定随机种子（Deterministic Seed）的 **Differential Evolution（DE）** 全局搜索，确保多盆地（主簇 + 次级簇）完备检出且结果可复现无抖动。
- **精修器替换**：将 DE 之后的局部精修器由 `L-BFGS-B` 替换为专为非线性最小二乘设计的 **`TRF / Levenberg-Marquardt`**（利用解析或半解析雅可比矩阵，提升收敛速度与边界稳定性）。
- **每日实盘增量更新**：以「昨日全盆地解 + 确定性 $t_c$ 网格」作为热启动（Warm-start）运行多起点 TRF/LM，实现单标的 2 秒内增量更新；每周做一次全量 DE 复核。

## 2. 历史回测 JSON 新增 FCO 泡沫强度字段
前端 `backtest.html` 已优先读取每帧上的 `fco_intensity` 字段（范围 `[0, 1]`）；若缺失则暂由多尺度聚类活跃度与主簇占比合成。

请在 `*_history.json` 的 `frames[]` 中为每个周度截止日新增：
```json
{
  "asof": "2015-05-29",
  "close": 4611.74,
  "fco_intensity": 0.86,
  "fco_scales_active": 3,
  "first_alert_flag": true
}
```
- `fco_intensity`（float, `0..1`）：类似 ETH Zurich FCO 的正向泡沫综合强度（由多尺度合格拟合占比 + 顶部聚类集中度合成），用于绘制主图底部红色柱状图。
- `first_alert_flag`（bool, 可选）：该截止日是否为本轮泡沫预警段（Episode）的严格 `as-of` 首次预警日。

## 3. Episode 事件级回测指标（替代逐日 Brier 误判）
- LPPLS 置信度是**相变序参量**而非校准概率，不应仅用逐日 Brier 评判。
- 请在回测评估模块新增 **Episode 事件级回测报告**，输出：
  1. 每轮预警段的 `first_asof`（严格 `as-of` 首次出现顶部聚类的日期）、持续周数、首次主簇区间 `[q20_date, q80_date]`；
  2. 事后确认顶日期、提前天数（`days_to_top`）、事后最大回撤 `max_dd`；
  3. 事件级命中率（顶落在主簇区间或缓冲窗内的比例）与**同等报警频率随机置放基线（Null Permutation Baseline）**的对比。

## 4. 逃顶后防“过早回补”冷却期（Cooling-Off）状态字段
为解决 LPPLS 只预测时间不预测跌幅导致的“逃顶后抄底过早回吐”，请在单标的 latest JSON 中导出 `cooling_state`：
```json
{
  "cooling_state": {
    "phase": "cooling_after_top",
    "top_conf_cleared": false,
    "omori_aftershock_active": true,
    "drawdown_bucket": "q20-q50",
    "reentry_ready": false,
    "note": "6-12m 顶部置信度尚未归零，处于破裂余震冷却期"
  }
}
```
- 三道防线：① 顶部聚类置信度归零 + Omori 余震（高频大阴线/跌停潮）衰减；② 价格进入同类泡沫历史耗散区间或筹码势能阱；③ Lunde–Timmermann 熊市结束右侧确认或市场宽度修复，支持 30%→30%→40% 分批回补回测。

## 5. JSON 文案去防御化规范
- 请勿在 JSON 的 `note` / `rule` 字段中重复拼接“历史分位，不是预测”、“不构成投资建议”等防御性长尾句；前端已通过统一证据徽章（`frontend/app/evidence-badge.js`）与页脚单行声明统一承载。
- 保留硬红线：严格 Point-in-Time、只输出时间区间（不输出精确顶部日期）、`drawdown_price.value` 恒为 `null`（不输出目标价）。
