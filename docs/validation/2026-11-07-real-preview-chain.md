# 上证与茅台真实预览：工程验收和发布隔离

日期：2026-11-07。本交付只更新 PR #50 和既有独立海洋观测台预览；不合并 main，不部署正式 Worker，不触发正式 Pages。

## 已实现的闭环

首页进入工作站 → 输入上证指数/sh000001 或贵州茅台/600519 → 行情及成交量先显示 → 独立当前任务 → 真实 LPPLS 结果 → K 线未来区间或明确的无合格区间状态。

VERIFIED（本地）：两资产已通过真实 market/query/status/result 请求链。不是计时模拟；当前任务 history_weeks=0。既有演示适配器及旧结果仍保留，真实预览不进入该模拟分支。

VERIFIED（实现与自动检查）：

- 恢复暖象牙 #f3e8d3 至冷白 #eef5f3；变色完成后标题退场，保留海水、云与白金扫光。水下首区直接提供资产入口。
- 上证使用带市场前缀的 sh000001；裸000001不被工作站误认为上证。预览专用运输接口的六位映射与生产股票接口隔离。
- 前端网络请求仍通过原 LPPL.stock 适配器；没有修改 Devin 所属 lppl-data.js，也没有前端模型引擎。
- 当前分析和行情异步加载；历史任务在本轮未开放，既不读取也不恢复或启动104周计算。
- 预览存储使用 research-preview. 前缀，隔离生产与旧演示任务、浏览器首次可见记录。
- 实际K线使用未复权报价；个股模型仍用后复权，只共用时间轴，不混合价格轴。
- K线增加未来日期空间、截止线、候选区间及对应分析说明；不画虚构未来价格或成交量。
- 完整区间向外取整，不裁短以满足10日目标。单尺度或触边候选仍是观察，2027日期不会继承2026日历认证。
- 首次服务回执、浏览器首次可见与真实公开预测首发分开；public_first_published_at保持null。

## 独立托管架构

公开预览使用本网站同源 /api/preview；Sites Worker读取行情、协调任务并在D1保存任务与结果。真正SciPy计算由GitHub Actions在固定PR分支执行。它不是在Cloudflare网页进程中运行Python。

Worker只能派发 stock_query.yml 的 preview_only=true 路径，资产只限sh000001与sh600519，mode固定current、历史周数固定0。源码SHA由服务配置固定，客户无法提交任意仓库、分支、源码或历史任务。

原工作流prepare及publish均显式排除preview_only；preview job只有contents:read，只上传隔离artifact，不写stock-results也不调用pages.yml。上传Action固定在v4.6.2的源码SHA，ZIP读取校验中央目录、CRC、文件名及大小；GitHub令牌不转发给签名文件存储，也不进入浏览器或源文件。

公开演示每日（中国时区）最多两项新任务，跨资产共享额度；同资产/日期/源码去重。刷新和多人查看读取同一结果，不人为反复计算。已发生的派发即使响应超时也保留同一身份，不盲目重派。额度不能被视为正式产品容量设计。

结果验证job_id、symbol、requested_at、source_sha和实际Actions run身份，限制D1 bundle小于1.9MB。市场加载独立于任务；失败时保留已有真实缓存并明确其日期与失效状态。

## 验收记录

VERIFIED：429项Python测试通过，2项跳过、3项网络测试排除；定向研究测试及Ruff通过。前端、Worker和SQLite去重/额度/产物协议测试通过；最终具体总数见本次PR验证说明。

VERIFIED（本地浏览器）：首页进入工作站、上证入口、贵州茅台中文名称、两资产切换、刷新读取真实结果、未复权报价与未来候选区间已实际核验。

NOT_ESTABLISHED（此文提交时）：托管D1迁移、真实线上Actions派发、artifact读取与公开站点390px/桌面完整验收。后续上线验收应另保留部署ID、源码SHA、任务UUID、Actions run与服务回执，不回写成本地测试已证明。

## 运行与复现

本机先启动 tools/stock_real_preview.py（隔离目录在D:），再启动 tools/stock_preview_site.py，打开127.0.0.1:8792/home.html。真实网关仅监听loopback，默认最多两次当前拟合。

托管站使用frontend/demo-tools/prepare_real_site.py生成独立Sites构建，保留既有project_id与public访问范围。运行环境仅需要服务端PREVIEW_GITHUB_TOKEN、PREVIEW_SOURCE_SHA及固定PREVIEW_REF；令牌必须为secret，不写入构建。

详细模型方法、实测结果、修订与原始证据见[两资产研究报告](../research/2026-11-07-real-current-preview.md)。本交付建立工程闭环，不建立阶段顶预测准确率或逃顶收益。
