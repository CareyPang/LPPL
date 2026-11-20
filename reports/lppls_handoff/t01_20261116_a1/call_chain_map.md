# T01 调用链映射

## 旧 daily / scan 路径

`index_daily.yml` 与 `index_replay.yml` 通过 `LPPLS_BOX=v2 python -m research.pipeline.daily ...` 进入日更流水线（.github/workflows/index_daily.yml:49；.github/workflows/index_replay.yml:69）；`daily.run()` 按 BOX 设置全局 `_core.ALLOW_INSIDE=True`（research/pipeline/daily.py:62），未指定 `--windows` 时取 `full_windows(len(logp))`（research/pipeline/daily.py:69），再运行 `_derived()`、`rules()` 和 `build_record()`。执行数据加载默认先 `cache.refresh()`，除非显式 `--frozen`；workflow 未传该参数。

扫描器 `lppls_scan.fit_one()`（research/features/lppls_scan.py:121）按 v2 BOX 使用 m=[0.01,2]、ω=[1,50]、tc∈[t₂−0.2dt,t₂+0.2dt]，seed=0、n_random=10，并调用 `tcgrid_lm()`、`lin_fit()`。`allow_inside=None` 保持由 `core.ALLOW_INSIDE` 决定；v2 的内部点经 `abs(tc−t)` 设计矩阵计算。

## 新 future-only 路径

`LogPrice.from_price()` / `LogPrice.from_log_price()` 显式记录输入构造来源（research/lppls/future_contract.py:19）；`fit_window()`（research/lppls/future_contract.py:455）使用窗口内有效 bar 坐标 t1=0、t2=L−1，并调用 `SearchBounds.numeric_bounds()` 得到 tc∈[t₂+MIN_DT,t₂+0.2dt]。对每个 seed/retry 调用 `tcgrid_lm(..., allow_inside=False)`；`core.design`、`lin_fit` 和优化器均收到显式 False，不受进程级 `ALLOW_INSIDE` 污染。

每个 `WindowResult` 只汇总一个计划窗口，attempt 按 seed/retry 独立记录。拟合后按 `FilterBounds` 单独给出过滤结果；交易日映射把每个有效 bar 映到 session 索引，停牌缺口不压缩日历 session。eval_H 固定 63，label_confirmation_E 当前为 null。T01 只冻结契约并执行合成单元测试，不进行扫描或 B0 评价。

## 产品 headline 过滤证据

`grid_rules()` 的 `g_fco_standard` 规则是 B<0、0<m≤1、2≤ω≤25、D≥0.5、legacy osc≥2.5（research/features/lppls_rules.py:93；research/features/lppls_rules.py:94）。`_indicators()` 以该列的合格窗口数决定每尺度 signal（research/eval/export_contract.py:248；research/eval/export_contract.py:256）；`build_record()` 的 `top.signal_status` 再对 `SCALES_FCO` 尺度作 any 聚合（research/features/lppls_rules.py:63；research/eval/export_contract.py:450）。B0 因而沿用这一列作为 primary filter，在三个评价尺度应用同一规则。future 单位为 `cycles_full = omega/(2*pi)*ln((tc-t1)/(tc-t2))`；legacy `osc=(omega/2)*ln(|tc|/max(|tc-t2|,1e-3))`，换算为完整周期需除以 π，故旧 `osc>=2.5` 约等于 0.795775 周期。B0 下界 `tc=t2+MIN_DT` 且 `MIN_DT=1e-3`，因此该 legacy 分母保护不会改变 future 域的等价对数项。`g_fco_early`、`g_fco_end`、`g_fco_pure` 只进入每尺度置信度，不参与该 headline status。另一个字段 `top.lppls_confidence` 是 `_conf(d, rules(d), asof)` 的研究置信度摘要，并非此 headline status 的判定规则（research/eval/export_contract.py:452）。原 g_fco_standard 没有 R²、rel_err 或 horizon 限制；这些条件在 B0 中明确记录为 null，而不是补造阈值。
