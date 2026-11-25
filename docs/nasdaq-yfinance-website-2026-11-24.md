# IXIC / NDX 网站日线数据接入与验收

日期：2026-11-24。范围：改写用户提供的两个 yfinance 下载脚本，接入现有美股指数数据链路。保留原文件 `D:\IXIC\fetch_ixic_yfinance.py`、`D:\IXIC\fetch_ndx_yfinance.py` 及原数据。本次不运行 LPPL 拟合，不改模型、评分、前端设计，不部署、合并或发布。

## 交付结果

**VERIFIED：网站已经注册这两个美股指数，本次完善实际拉数链路，避免重复注册。**

| 网站 ID | 名称 | Yahoo 标识 | 分类 | 日历时区 |
|---|---|---|---|---|
| `US_IXIC` | 纳斯达克综合指数 | `^IXIC` | `us / index / USD` | America/New_York |
| `US_NDX` | 纳斯达克100 | `^NDX` | `us / index / USD` | America/New_York |

`frontend/app/lppl-data.js` 已有注册；`home.html` 的美股页签通过 `home-data.js` 加载美股卡片。卡片进入 `chart.html?code=US_IXIC&kind=index&from=home.html?market=us` 或对应 NDX 路由。搜索 `IXIC`、`NDX`、`^IXIC`、`^NDX` 均识别为美股指数，走全球数据入口，不走 A 股 Worker，不映射成沪深300。本次未修改上述前端文件。

## 原脚本到网站版本的差异

| 原脚本行为 | 网站版本 |
|---|---|
| 每次抓完整日线和60日15分钟线 | 网站日线单独更新，首次完整下载，后续重取末10个交易日起的日线；不绑定15分钟任务 |
| 固定本机输出目录 | `--root` 指定仓库外持久数据目录，兼容 Windows / Linux / 腾讯云进程 |
| 空下载可能写空CSV，异常后成功退出 | 校验后才更新最新指针；失败返回非零退出码、保留旧行情及逐次失败日志 |
| MultiIndex 列直接展平 | 支持两种列层级与单层列，拒绝混合/错误ticker、重复日期、无效价格和OHLC关系 |
| 未区分当天日线是否收盘 | 按现有 XNYS 交易日历、纽约时区、实际收盘后20分钟截取，覆盖提前收盘 |
| 自动 `repair=True` | 显式 `auto_adjust=False, repair=False`；不把供应商缺失OHLC/成交量编造成完整值 |
| 无可追溯的数据版本 | 原下载DataFrame JSON、Parquet、元数据及SHA256内容寻址保存，latest原子替换，旧版本保留 |

官方文档说明 `download` 有复权、修复、时区和超时选项，且日线与盘中历史范围不同，因此这里逐项显式设置，不依赖默认值。[yfinance 下载接口](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)。缓存通过 `set_tz_cache_location` 定向到数据根目录的 `.cache/yfinance`，避免写入默认用户目录。[yfinance 缓存文档](https://ranaroussi.github.io/yfinance/advanced/caching.html)。

## 数据流和更新规则

```text
scripts/fetch_{ixic,ndx}_yfinance.py（单资产兼容入口）
  → research.pipeline.nasdaq_data（只拉数据，不拟合）
  → research.data.global_terminal.fetch_snapshot(provider='yfinance')
  → research.data.nasdaq_yfinance.download_nasdaq
  → root/source/{US_IXIC,US_NDX}/immutable snapshots + latest.json

现有 global_daily / research.pipeline.global_terminal
  → 同一 fetch_snapshot（两纳指强制full_history且至少6600条真实日线）
  → 原有拟合、global JSON导出、既有LPPLData入口和Lightweight Charts
```

1. 第一次取 `period=max`，后续只有 provider、normalizer、身份与经过哈希核验的快照匹配时才增量合并。切换来源或规范化版本时独立全量重取，不拼接不同供应商。
2. 增量重取末10行起的全部已收盘交易日，修订仅替换该尾段；旧前缀保留。记录重叠修订行数、字段、样本和前一版本哈希。更早供应商修订不由10日重叠发现，元数据明确这一边界。
3. 最终整段按交易日历检查首日到截止日有无缺日；最少6600行只是数量门槛，不代替缺口检查。不填充假行情，也不拿ETF代理补指数历史。
4. 下载失败、数据滞后、缺日、异常OHLC或历史倒退时拒绝新快照，保留旧latest。独立CLI写 `fetch-audit/*.json` 和 `nasdaq_fetch_latest.json`，展示失败原因与可用旧截止日，成功资产仍可完成。
5. `fetched_at`、数据截止日、原始/标准化哈希、provider、normalizer版本、增量模式、交易日完整性及历史版本血缘都保留。这里的原始JSON是观察到的 yfinance DataFrame，不冒称原始Yahoo HTTP字节。
6. 源历史是今天重建的历史数据，`history_vintage=current_download_reconstruction`；不把它当作当年已发布的预测证据。真实首次可见预测账本保持原逻辑。

## 使用方法

安装项目依赖：`python -m pip install -e .`。本次新增 yfinance 依赖；不在应用运行中自动安装包。

```powershell
. 'D:\CodexData\config\analysis-env.ps1'
# 数据根目录应在代码仓库之外，生产时固定为持久目录。
python -m research.pipeline.nasdaq_data --root D:\CodexData\data\lppl-global --assets US_IXIC,US_NDX
python scripts/fetch_ixic_yfinance.py --root D:\CodexData\data\lppl-global
python scripts/fetch_ndx_yfinance.py --root D:\CodexData\data\lppl-global
# 兼容原参数：--symbol '^NDX'。只检查已保存数据、不联网：
python -m research.pipeline.nasdaq_data --root D:\CodexData\data\lppl-global --cache-only
```

Linux / 腾讯云使用同一入口，将 `--root` 指向持久卷，例如 `/srv/lppl-data/global`；应由一个作业串行写同一数据根目录。浏览器复用已有全球行情JSON，不能直接运行Python或取得后端文件系统访问权。本次没有购买、配置或启动云资源。

单独运行该数据CLI不会改变线上网页。要更新网站研究结果，仍需走既有 `research.pipeline.global_terminal --refresh` 的拟合和导出链路；这一执行并未在本轮触发。

## 每日任务

**VERIFIED（代码静态核对）：** `.github/workflows/global_daily.yml` 已有 `22:30 UTC` 工作日全市场更新，换算 UTC+8 为次日06:30；`07:30 UTC`任务针对日/韩市场。本次不新增重复定时器。

本次补上两纳指 `source` 目录的 Actions 缓存，后续作业恢复旧历史后 `--refresh` 拉取新尾段；显式刷新防止恢复缓存后停留在旧日期。缓存丢失时重新拉全量，不影响数据真实性。公开GitHub缓存中不放凭证；源目录沿用既有数据权限边界。

**NOT_RUN：** 草稿PR没有激活这项修改；未手动触发Actions、stock-results写入或Pages发布。将来进入main后仍受现有全市场任务预算和整批成功门控约束：其他资产失败或拟合未完成可能阻止整批发布。本轮不把下载成功等同于当天必定上线，也不重构这一既有门控。

## 真实验收（2026-11-24）

| 数据 | IXIC | NDX |
|---|---:|---:|
| 实际首日 | 1971-02-05 | 1985-10-01 |
| 最后已收盘交易日 | 2026-11-23 | 2026-11-23 |
| 日线行数 | 14,068 | 10,367 |
| 第二次下载行数 | 10 | 10 |
| 保留旧前缀行数 | 14,058 | 10,357 |
| 首日之后日历缺口 | 0 | 0 |
| 第二次重叠价格/成交量修订 | 0 | 0 |

真实网络全量和增量均成功。证据包含请求参数、时点、来源、哈希、版本血缘和交易日完整性：[机器可读验收](evidence/nasdaq-yfinance-2026-11-24.json)。本次仅提交代码和验收元数据，不把整包行情文件上传到代码分支。

离线测试覆盖：两ticker/三种列布局、正常及提前收盘、错误ticker、无效OHLC、完整历史不足、全段缺口、增量缺口、历史倒退、换源、空返回、失败旧快照不变和CLI退出码。已有全球数据/刷新/长历史测试及前端分类、搜索、历史截止日、数据入口回归一并执行。最终测试计数见PR交接评论。

## 证据边界与Devin交接

- **VERIFIED：** 两指数真实下载、增量复用、源历史6600+、既有美股指数注册、现有K线数据入口及离线合同测试。
- **NOT_RUN：** 本轮LPPL回测、当前预警重新计算、线上日更执行与发布；不存在本轮新顶部/底部结论。
- **NOT_ESTABLISHED：** 因数据更长而预测更准、数据从指数诞生首日即完整、供应商长期稳定性和免费数据的公开商业再分发许可。沿用原元数据 `public_redistribution=NOT_ESTABLISHED`，没有将开源Python许可当作行情授权。
- **NOT_INSPECTED：** 本轮未做桌面/390px视觉重验；没有前端页面改动。已有路由及分类通过自动化合同测试。
- `WINDOWS`日更拟合配置未改；取得6600+日历史不等于本轮已运行6600日拟合。已有超长期研究附件/回放保持原样。
- Devin接续应复用本次数据入口，避免再增加一份IXIC/NDX卡片或绕过 `lppl-data.js`。将来如需独立刷新行情而不等待整批拟合/发布，应另做任务状态与发布粒度设计，并保留源截止日与模型截止日的区别。
