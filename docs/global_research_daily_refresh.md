# 国际研究数据每日更新

本模块更新本机数据和当前截止日结果，不部署网站、不合并分支、不提交数据到GitHub。原始行情的公开再分发权限仍未建立，因此流程不上传行情、新闻或拟合结果为公共Actions artifacts。

## 执行入口

```text
python -m research.pipeline.global_daily --config <absolute-config.json>
python -m research.pipeline.global_daily --config <absolute-config.json> --dry-run
```

配置文件示例（路径须换成执行机器上的绝对路径，且均位于代码仓库之外）：

```json
{
  "source_root": "D:/CodexData/work/lppl/source",
  "jobs_root": "D:/CodexData/work/lppl/jobs",
  "state_root": "D:/CodexData/work/lppl/daily",
  "long_state_root": "D:/CodexData/work/lppl/daily-long",
  "fit_cache": "D:/CodexData/work/lppl/long-fit-cache",
  "seed_study_root": "D:/CodexData/work/lppl/frozen-52-period-study",
  "archive_root": null,
  "long_root": null,
  "symbols": ["US_IXIC", "US_NDX", "KR_KOSPI", "KR_KOSDAQ"],
  "long_assets": ["US_IXIC", "US_NDX", "KR_KOSPI", "KR_KOSDAQ"],
  "long_workers": 4,
  "minimum_rows": {"US_IXIC": 6700, "US_NDX": 6700, "KR_KOSPI": 6700, "KR_KOSDAQ": 6700},
  "long_window_rows": 6700
}
```

`minimum_rows` 是取得新源快照的最低真实观测数，逐标的设置。`long_window_rows` 是独立覆盖检查目标，不会补造数据。KOSDAQ的Yahoo序列曾只有6432日，之后核验到更长的独立Naver序列；源适配器记录明确来源，不把两套行情拼成一条。若后续某标的来源不足6700日，可明确降低其最低取数门槛，使 `global_refresh` 子入口保留真实短历史、继续短窗计算；长窗覆盖仍写 `insufficient_data`。`global_daily` 总入口此时不会激活新的完整长窗摘要，也不会返回完整更新成功。

每轮先全历史刷新并核对交易所时区下的最新完整日线。数据版本和计算代码指纹均未改变、已有结果仍通过身份核验时，跳过模型任务。这个状态只称“没有新完整交易日或修订”，不擅自认定交易所休市。数据修订即使截止日相同也会启动新的当前计算版本。

总入口 `global_daily` 先调用 `global_refresh` 更新行情和27窗当前分析，再调用冻结长窗研究的**单个最新截止日**入口。普通分析通过 `GlobalJobs.start({symbol, asof: null, refresh: false})` 按标的完成。长窗仍是900/925/950/6500/6600/6700日、两个seed和6600日固定tc检验，逐项复用精确输入检查点；**不会每天重跑52期研究或104周回放**。四个长窗标的的当前批次为48次自由拟合、248次固定tc检验，计数分别报告，复用与本次新增计算分开。

`seed_study_root` 指向已完成并封存的52期研究；没有可复用研究时可设为 `null`。历史只在方法版本、截止日前缀与摘要都核验一致时引用，不重新拟合、不改原文件。每日模块在 `long_state_root` 写独立版本与失败账本，所有配置长窗标的通过核验后才原子更新当前 `summary.json`；某标的失败保留上一批可用长窗结果。

`jobs_root` 的当前指针由既有统一入口读取；历史同日原档保持原版本，新版本有独立内容哈希。`state_root/assets/<symbol>.json` 保存成功状态和最近尝试，`state_root/runs/<run_id>.json` 保留每次审计，`latest.json` 指向本轮概况。刷新失败记录原因并保留 `last_good`，不会拿失败日期覆盖成功截止日。

长窗档案保留每个日期的首版和内容寻址的修订版本；summary携带 `snapshot_path/snapshot_version`。预览服务以 `--long-results <long_state_root>` 读取每日结果，只给输入前缀匹配的模型截止日附加研究卡。当前资讯单独按六小时缓存刷新，页面从最新缓存读取；不改不可变模型原档，不回填历史新闻。

OS文件锁防止同一 `long_state_root` 两次完整计划重叠，内部普通更新另锁 `state_root`；锁随进程释放，不依赖删除“过期锁”。退出码：0完成/未变化，1计算或资产更新失败，2配置错误，75已有同计划在运行。代码会等待已提交计算退出再释放锁。仅需要行情和27窗更新时，仍可显式使用 `global_refresh` 子入口；它不会被描述为完整长窗更新。

## 定时方式与当前边界

- 本机Codex自动任务可以按用户确认的时间调用上述入口。Windows运行前加载 `D:\CodexData\config\analysis-env.ps1`；机器、Codex与网络需要可用。自动任务的实际创建状态应以工具返回为准，这份文档本身不代表任务已启用。
- 仓库新增 `.github/workflows/global_research_refresh.yml`：PR只做离线测试和 `--dry-run`；手动运行要求预先配置带 `global-research` 标签的自托管runner及 `GLOBAL_RESEARCH_REFRESH_ENABLED=true`，配置文件与Python路径通过仓库变量传入。它不创建云资源，也不包含公开发布步骤。
- 每日08:30（UTC+8）对应的GitHub schedule仅为注释模板，**当前没有启用**。要使用GitHub定时，需另外完成runner部署与默认分支授权，并把schedule事件加入refresh job条件。仅将文件推到草稿PR不会使GitHub计划生效。
- 08:30是建议时间；该轮可取得前一美国交易日已收盘数据，以及韩国最近已完成交易日数据。若需要韩国收盘后当日更新，可另安排UTC+8 16:30，仍按输入指纹去重。

来源抓取使用`global-stock-data`对应的公开接口方法。长期数据下载与原始缓存本身不证明商业网站展示授权；本流程不改变来源许可状态。新闻六小时缓存和真实披露时间边界继续由资讯适配器维护，不能把今天抓到的标题塞进旧模型截止日。
