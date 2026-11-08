# P1 有限上游复用：实现与验收

日期：2026-11-09。基线：PR #50 的 `3c2700c8f1d3fe62fac7ec2ea56d9b7d2d0abab1`。

## 本轮结果

**VERIFIED（代码与本地回归）**：已把 Vibe-Research 的目录/原始响应/哈希证据思路，以及 TradingAgents-astock 的字段解析思路落实为 LPPL 独立适配模块。未导入其框架、AI 角色、模型 SDK、Streamlit 或回测引擎，没有新增依赖。来源版本与许可边界见[来源记录](../product/upstream-adapter-provenance-2026-11-09.md)。

本轮交付是“可审计、可离线接入的 P1 数据层”，不是“新数据已经在网站上线”。

| 层 | 实现 | 边界 |
|---|---|---|
| 数据目录 | 8 项来源、固定参考版本、代码许可与数据许可分开 | 新目录 fetch/publish 均禁用；不改变旧抓取器的默认行为 |
| 解析器 | 资金流历史、龙虎榜、未来 90 自然日解禁 | 合成响应测试；未对这三个新增接口实时取数 |
| 封存 | 原始字节、响应哈希、解析器哈希、目录快照、独立 receipt | 本地归档不是公开发布记录，也不是供应商签名 |
| 时点 | 数据日、声明抓取时间、本地首次归档时间分开 | 历史日期不等于当时可获得，PIT 保持 NOT_ESTABLISHED |
| 接口 | `market-context.v1` 下 `p1.supplemental_sources` | 离线 `research_import`；不覆盖旧来源、旧晋级结果、模型输入 |
| 发布检查 | Python bundle/gate 与 Worker seed/refresh 拦截研究导入 | 线上未部署；现有两日真实快照仍可通过本地 seed 前验收 |

## 可执行入口

从仓库根目录运行，所有示例输出放在 D 盘。以下参数中的响应、证券与日期必须来自同一次真实取数；不要照抄示例日期为自己补造历史。

```powershell
. 'D:\CodexData\config\analysis-env.ps1'
$p1Python = 'D:\CodexData\envs\lppl-async-20261106\Scripts\python.exe'
& $p1Python -m scripts.import_p1_evidence catalog

# 只读取已经保存的响应，不进行网络请求。fetched-at 是声明值，不是可信发布时间。
& $p1Python -m scripts.import_p1_evidence import-response `
  --source eastmoney_fund_flow_history `
  --raw 'D:\CodexData\analysis\my-p1-evidence\response.json' `
  --archive 'D:\CodexData\analysis\my-p1-evidence\archive' `
  --asof '2026-11-06' --fetched-at '2026-11-06T10:30:00+00:00' `
  --source-url 'https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?secid=1.600519&fields2=f51,f52,f53,f54,f55,f56,f57' `
  --subject sh600519 --origin captured_response

# 用上一步实际返回的 receipt 路径；输出须使用新文件，不替换已封存日期。
& $p1Python -m scripts.import_p1_evidence build-context `
  --base-payload 'D:\CodexData\analysis\my-p1-evidence\market_2026-11-06.json' `
  --record 'D:\CodexData\analysis\my-p1-evidence\archive\records\<receipt-sha256>.json' `
  --out 'D:\CodexData\analysis\my-p1-evidence\research_context_v1.json'
```

测试样本必须用 `--origin fixture`，永远不会变成 `run_mode=live`。当前只支持三个新增适配器的离线导入；目录内其他来源登记不表示已有统一导入入口。

完整 URL 查询参数用于核对字段布局、资产、日线频率和报表类型；明确矛盾会拒绝。只保存了基础 URL、缺少查询参数时，不补造请求证据，解析状态降为 partial。无证券筛选的返回集合只叫 `observed_set`，不称全市场完整覆盖。

## 证据和时间约束

1. `raw_sha256` 对真实输入字节计算，换行和空白也参与；原始 JSON 不被重新序列化覆盖。拒绝重复键、NaN、Infinity、指数溢出、空响应及超限文件。
2. 独立 `record_sha256` 绑定元数据和解析结果；读取时重新校验哈希，并重新执行解析器核对结果。解析器哈希覆盖字段解析与请求/时间封装，源码统一 LF 后计算，避免 Windows/Linux 换行差异。
3. `observation_sha256` 区分来源、证券、asof、声明抓取时间、原始响应、解析器和目录版本。同一次观测再次导入复用首次本地 receipt，不把 `available_at` 推迟；数据或规则变化产生新 receipt，旧文件保留。
4. `fetched_at` 明确为 `caller_declared`。`available_at` 由归档程序生成，范围仅为 `local_archive_only_not_publication`；`public_first_published_at=null`，`pit_status=NOT_ESTABLISHED`。
5. 解禁的事件日可在未来，但解禁快照的 asof 必须等于声明抓取时间的北京时间日期，防止将今天的计划回填为过去已知。未核验单位的源字段保持原名/原值，不猜测“万股”或分母。
6. 若指定过去的可用时点，晚于截止点的补充数据隐藏。基础 market payload 本身没有可信历史可用回执，因此基础数据也按本次构建时点处理，不能仅遮挡补充卡却泄露后来补取的行情、题材或晋级结果。
7. 个股资金按来源与证券隔离，不作为全市场资金历史分位输入；龙虎榜分页不完整、源错误、缺失与“真实空集合”分开。
8. 研究结果明确 `run_mode=research_import`、`publication_eligible=false`。seed、refresh、两日计数、append-only bundle 都拒绝该结果；即使误改 run_mode 为 live，保留的导入/补充字段仍会阻断。

这些哈希验证完整性，不证明原始响应真实、不证明供应商授权、不证明历史发布时间。修改全部文件和哈希的人仍能伪造本地内容；正式数据需要受控采集与可信服务端记录。

## 实际验收

**VERIFIED**：本次离线检查结果：

- Python 全仓非网络回归：626 passed、2 skipped、3 deselected；6 条既有 pandas 弃用警告。之后补充解禁源字段保留与源码哈希换行兼容，最终相关组合回归再次通过。
- 本次目录/解析器/证据/持久化/gate 最终组合：142 passed（含新增的解禁原始字段测试），均为本地契约测试，不算真实市场观测。
- 前端、两个 Worker、独立 preview coordinator：235 passed。
- Ruff（research/tests 和本次 CLI/gate）：通过。
- `git diff --check`：通过。
- 两份既有真实快照 2026-11-05 / 2026-11-06：两日 gate 仍计 2 份，progression_ready=true；Worker 实际 seed validator 两份均 ok。只读验收，未调用线上 seed。

扩展 Node 验收时发现旧 preview 测试直接按 LF 切分 workflow，在 Windows CRLF checkout 失败。本轮只把该测试读取规范化为 LF，再完整重跑通过；未修改 workflow、权限或部署条件。

本地日志：`D:\CodexData\analysis\lppl-p1-adapter-20261109\python-regression.log`、`node-regression-final.log`。暂存和测试目录在 D 盘，旧原始数据、CSV、报告及真实两日快照未覆盖。

## 尚未建立的能力

- **NOT_ESTABLISHED**：新增源的实时可用性、逐源数据再分发许可、供应商可接受频率、大陆多运营商长期可达性。
- **NOT_ESTABLISHED**：新来源的真实采集、跨日自动持久化、线上历史复盘和前端轮询；没有运行新的网络抓取任务。
- **NOT_INSPECTED（本轮）**：新功能在正式桌面/390px 页面上的显示。本轮未修改产品页面，只改了一个既有测试的换行兼容。
- **NOT_ESTABLISHED**：顶部/底部预测、提前 5 个交易日、价格层或交易收益的任何新增提升。没有新回测或准确率结论。
- PR 保持 draft；没有合并、部署、购买资源、线上 seed 或发布。

下一步先补齐来源访问/再分发/频率/大陆网络证据，再选获准接口做小规模真实响应验收，之后才衔接每日持久化与网站展示。
