# legacy v2 到 future-only B0 契约差异

| 项目 | 分类 | legacy_main_v2 | candidate future-only B0 |
|---|---|---|---|
| inside 状态 | bug-fix（实现隔离） | v2 设置进程全局 `ALLOW_INSIDE=True`，同进程任务可能受其影响 | legacy 默认仍由全局控制；future-only 每次显式传 False |
| 搜索域与参数 | model-domain change | m=[0.01,2]、ω=[1,50]、tc∈[t₂−0.2dt,t₂+0.2dt]，设计可用 `abs(tc−t)`；tcgrid_lm 默认预算、seed=0、10 随机起点 | m、ω、solver、budget、seed、n_random 全部保留；仅将 tc 域修正为 [t₂+MIN_DT,t₂+0.2dt]，严格 future-only，不取 abs、不 clamp |
| headline 过滤 | 评分变化 | 产品 `top.signal_status` 使用各 SCALES_FCO 的 `g_fco_standard`；m/ω/D/方向如 frozen JSON，osc≥2.5 | 保留该过滤列的 m、ω、D 和缺省条件，交集 tc>t₂；振荡门槛改为完整周期≥1.5 |
| 单位解释 | 评分变化 | legacy `osc≥2.5` 按仓库公式约等于 0.795775 个完整周期 | 明确以 `cycles_full≥1.5` 计分 |
| 窗口 / attempts / 缓存 | bug-fix（可复现性与记录完整性） | 旧扫描输出不能表达每 seed attempt 的独立状态和时钟映射 | 一窗口一汇总，多 attempt 分列；缓存键绑定数据哈希、时钟映射、域、单位、边界、solver、版本与 seed |
| 日历映射 | bug-fix（evaluation clock 记录） | 扫描以有效 bars 拟合，原输出未携带逐 bar session 映射 | 仍以有效 bars 拟合，但保留真实 session 索引；evaluation H=63，确认期 E 暂为 null |

以上逐项归入 bug-fix、model-domain change 或 scoring change。新契约下未来重拟合的结果不是纯算法收益，不能与 legacy 结果作“只换算法”的归因。T01 不运行扫描、不生成 B0 成绩。
