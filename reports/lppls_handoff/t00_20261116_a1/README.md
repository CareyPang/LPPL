# T00 冻结基线与旧结果保护

本目录是 `t00_20261116_a1` 的只读研究登记；仅做文档/清单，无模型改动、重拟合、workflow dispatch、生产版本变更或合并。

## 版本关系

- 当前执行时 `origin/main`：`4a5e1375e6dbd9a5b442d16c876b69ccaff7d0b5`；PR #100 文档 pinned main：`5d5fc7959e24b8eebaa34e3882c7b2ce069daeb0`。
- 两者全路径差异只有 8 个 frontend/worker 文件；`research/`、`scripts/`、`data/frozen/`、`docs/preregistration*.md` 差异为空。
- 只读研究 refs：PR #50 `7f7fe930ab4065295718dfcfe89b87cedcaaf1fb`；PR #99 `4986455cb9d8871bb7fda25a221db5a5a11ad009`；PR #100 任务文档源 `3f2de2e541c519e962d010055da8715733101e20`。

完整 bounds、精确窗口列表与 SHA-256、依赖、冻结数据清单及调用链见 `baseline_manifest.json`；旧资料逐文件哈希见 `preserved_legacy_sha256.json`；样本消费见 `sample_consumption_register.json`。

## 生产调用链摘要

`index_daily.yml` 和 `index_replay.yml` 实际都执行 `LPPLS_BOX=v2 python -m research.pipeline.daily`。daily 入口按 BOX 将 `_core.ALLOW_INSIDE` 设为 `True`，默认取 `full_windows(len(logp))`，经 `_derived` / `rules()` 并由 `build_record()` 加 `grid_rules()` 构建记录。workflow 不传 `--frozen`：行情从运行时 cache refresh，精确 vintage 随运行变化；T00 未 dispatch。扫描 CLI 的 `LPPLS_PROCS=8` 实为进程池，不是线程参数；daily 路径不使用该进程池。

## 三个不同基线

| 注册名 | 参数/时间域 | 评分 | 数据 |
|---|---|---|---|
| `legacy_main_v2` | m=[0.01,2]、ω=[1,50]、tc=t2±0.2dt；允许窗内 tc，设计用绝对 τ；10 个随机起点 | 历史 `original_standard` A1/A2，不等于 PR #50 重放分数 | 指数 v20261024 qfq；个股 stocks_v20261024 close_hfq |
| `legacy_pr50_replay` | 九组保存的区间 + `calendar_fixed_10`；不拟合 | hypothetical diagnostic；首条区间需覆盖阶段峰、行动提前≥5、含端点宽度≤10、整窗提前；91 个事件仅 0–3 TP | 六指数 v20261024 qfq，最后原拟合日 2018-12-26、映射预测/评价至 2018-12-28、账本截止 2018-12-31；价格读至 2019-12-31 仅成熟标签 |
| `candidate_future_fullcycles_1p5` | 规格：tc>t2、future-only、完整周期 ω/(2π)·ln((tc−t1)/(tc−t2))≥1.5；其他参数留给 T01 | 未运行；评分契约需先冻结 | 未选数据版本；不构成结果 |

**单位核对**：`Fit.n_osc=ω/(2π)·ln((tc−t0)/(tc−t_end))` 是完整周期；`TOP_RULE` 门槛为 1.5。`lppls_rules._derived` 的 `osc=(ω/2)·ln(|tc|/max(|tc−t2|,1e−3))` 且 `n_osc=osc/π`，含 `abs()` 内域语义。`lit1/lit2` 的 `osc≥2.5` 等价于代码口径 `n_osc≥2.5/π≈0.795775` 周期；`p_ds/p_strict` 是 `n_osc≥2.5`；`p_top` 是 `n_osc≥1.5`。PR #50 的单位文档同时指出公开 Zhang 表格的分母与仓库公式不同，故官方/商业实现等价性 **NOT_ESTABLISHED**。

## 旧结果、样本与保护

- `preserved_legacy_sha256.json` 流式 SHA-256 固定 main 上 prereg 文档、被引用报告、全部 `data/frozen/**`、可识别的 tracked research results、PR #50 相关 replay/unit evidence、PR #99 F1–F4 报告/日志/生成器，以及 `/home/ubuntu/repos/LPPL/data/features/lppls_*` 本机扫描。
- PR #99 中 F2/F3/F4 仍为 **FAILED**。三项均保留首轮 `run_r1.log` 与更正生成器后的 `run.log`；F4 两日志 hash 相同。合成生成器有 SHA-256，但无明确版本常量。
- 本机扫描实测 10 个目录、323 个文件、367,492,055 字节（350.47 MiB）。先前约 1.4 GB 来自 `du data/features`，统计整个目录，包含 `bottom_v1`、`daily_v1`、`thrust_v1`、`wells_v1` 等；`du -c data/features/lppls_*` 为 352M，与本次 `lppls_*` 流式哈希统计相符。这些文件仅哈希，没有复制进仓库。
- PR #50 的 91 个阶段顶是已消费开发诊断，不是新 holdout。原拟合最后日是 2018-12-26，输入映射的预测/评价结束日是 2018-12-28，账本边界为 2018-12-31；2019 数据只用于标签成熟。没有找到独立的“2016–2025 新留出集”登记。
- 仍有符合既有登记、尚未用于模型评价的确认样本候选：`a90s_v20261104` 的 1990 年代两指数（深证回算段单列）及 `ext_v20261029` 的 HSI/N225/NDX/SPX。T00 只读其说明/manifest 并哈希，未扫描或评价；按 Round 2/预登记授权继续保持关闭。

## NOT_ESTABLISHED

1. `ext_v20261029` 的调整方式：README/MANIFEST 未声明 adjusted/unadjusted。
2. PR #50 原始拟合 parquet：原清单指向 Windows `D:\CodexData`；本机仅有保存报告、清单和哈希。
3. PR #50 的历史真实发布时间、原始 scope 与可行动性：旧回放明确是假想诊断，不是原预测证明。
4. PR #99 合成生成器的显式版本标签：未发现版本常量，只能以源文件哈希固定内容。
5. 独立 2016–2025 样本身份；2025-09 至 2025-12 是否被单独注册/消费；校准/测试段个股具体扫描覆盖。
6. 当前 production daily 的未来运行 vintage：workflow 会刷新行情，T00 没有 dispatch。
7. stocks_v20261024 的 `data/cache/stocks/*.parquet` 在当前 worktree 中不存在；只保留 frozen manifest 中的逐股 hashes。
8. Zhang–Zhang–Sornette 公布公式的作者意图以及其与商业 FCO 服务器规则的等价性。
9. 当前 main 的 `research/` 下没有符合已记录结果文件后缀筛选的 tracked result 文件；因此该类别没有可哈希对象。

新 run 目录一旦存在，生成器拒绝覆盖；后续重算须使用新的 run_id。失败尝试亦应另建新目录，不复用本目录。
