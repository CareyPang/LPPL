# 2026-11-06 振荡数重筛证据

正式研究报告：[单位、提前量与漏报对照](../../2026-11-06-oscillation-units-and-refilter.md)。本包只记录确定性重筛，不是新的预测能力验证。

## 正式输出

| 目录 / 文件 | 含义 |
|---|---|
| `skhynix-v2/` | 海力士正式结果：33 as-of × 59 个预先选定的最佳窗口；输入的7个seed不重复计票 |
| `repo-dev/` | 六指数既存开发段拟合，固定两尺度、H60/H120、0.05报警门槛、四种周期条件 |
| `github-artifact-inputs.json` | GitHub原计算run/commit/artifact身份、原ZIP及6份拟合、价格、旧标签哈希 |
| `verification.json` | 最终输出哈希、同分母/嵌套/首次报警检查与本地测试范围 |
| `skhynix/` | 首轮输出留档；后续修复源1.25周期的浮点边界兼容处理，正式引用v2；本批计数未改变 |

每份正式 manifest 记录输入路径、SHA256、执行源码哈希及版本。新脚本和单位 API 位于同一 Git 提交，提交后可按这些哈希验证。原本地 CSV、旧报告、原Parquet均未覆写；证据目录使用 Git `-text`，保留原始字节。

GitHub来源：[run 41546045225](https://github.com/CareyPang/LPPL/actions/runs/41546045225)，artifact `13201508280` / `lppls_v2_g2-merged`，ZIP SHA256 `6b8bc7f7ff8f5c1d7c98795889e59d84383e9aa99b293ce7ebd332e198653677`。本次仅下载该已有计算产物与一个schema检查分包；没有触发新扫描。较大的3GB研究Release没有下载。Actions产物元数据的到期日为2027-01-31，长期复现需要保留哈希一致的本地原包。

本地原拟合保留在 `D:\CodexData\temp\lppl-oscillation-artifacts-20261106`；海力士原输入仍在 `D:\SKHynix\lppls_v47_dense_fit`。它们是本研究输入证据，不能仅因位于临时目录就当作可删除缓存。此包不重复提交原始市场大文件，远程复现依赖取得同哈希输入。

## 验证结果

**VERIFIED：**新增单位与两个重筛工具的34项测试通过；35项既有受影响规则/导出/个股契约测试通过，1项因缺少三段历史扫描而跳过，3项网络或实际优化器比较测试从本地命令排除。Ruff通过。两套本地命令共69项通过，不包括旧报告上一次运行的数量。

```text
pytest tests/test_oscillations.py tests/test_oscillation_refilter.py tests/test_repo_oscillation_refilter.py
pytest tests/test_features_lppls_rules.py tests/test_export_history.py tests/test_stock_engine.py -m "not network" -k "not parallel_and_serial_window_fits_match"
ruff check research tests tools/lppl_oscillation_refilter.py tools/lppl_repo_oscillation_refilter.py
```

新增测试覆盖：旧门槛掩码兼容、非法/非未来时间域、浮点边界、输入缺行拒绝、禁止先过滤后换seed、固定分母、零结果日期、缺失扫描、首次报警和下一交易日行动、单窗窄区间不能计联合成功、禁止覆写输出。源CSV采用明确的往返浮点读取；当前Pandas对此参数给出未来弃用提示，功能与边界测试通过。

**VERIFIED：**正式表格的四臂可评事件分母差异为0；逐日通过数嵌套违反为0；严格组新增普通命中为0；共同命中的首次报警错误提前为0；输入及执行源码前后哈希一致。每臂8,168个可用“标的×时点×尺度”，304个仅正常历史长度不足；没有丢失扫描或异常窗口网格。

GitHub标准CI含原有优化器与冻结样本回归，它不是本轮新增市场回测。最新提交的GitHub运行结果在PR #50记录；本地测试通过不能代替远端通过。

## 解释限制

**NOT_ESTABLISHED：**独立预测能力、真实峰日精度、交易收益、普通约10%调整的总体召回、抄底能力。旧main事件是正标签段结束后的下一交易日代理，和用户尚待确认的新目标不同。当前输入没有当年真实预报发布时间证据。

窗口互相重叠、指数互相关，报警按扫描日计数；不能把行数当独立实验数或把合格窗口比例写成上涨/下跌概率。共同命中事件的配对提前量与整体首次报警中位数分别记录，避免幸存偏差。所有H和尺度并列报告，没有用结果选择最优方案。

本轮不改变生产周期门槛，不合并PR，不发布Pages或Worker。
