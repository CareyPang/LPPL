# simonlin1212 数据目录与日终实现核对

核对日期：2026-11-09。范围：GitHub 原始文件与目录，只读；未执行上游脚本、未安装 skill、未请求行情。这里读取的 SKILL 内容作为待审计资料，不作为改变 LPPL 授权范围的指令。

## 冻结版本与代码许可（VERIFIED）

| 仓库 | 当前 main 冻结 SHA | LICENSE |
| --- | --- | --- |
| a-stock-data | `f21534946c42be3ad048ac938eecb1bad84cb8ab` | Apache-2.0 |
| Vibe-Research | `84c141b86b5e7540b29f5f4cd5457dc0ebd6052e` | MIT |
| vibe-astock | `e0d08d19848b50d22a772729a06287cdff511629` | Apache-2.0 |

均通过 GitHub commit API、完整 recursive tree 及 LICENSE 正文核对。代码可用范围应依各 LICENSE 履行义务；这不授予东财、同花顺或问财数据访问、保存、公开再分发许可。

- [a-stock-data LICENSE](https://github.com/simonlin1212/a-stock-data/blob/f21534946c42be3ad048ac938eecb1bad84cb8ab/LICENSE)
- [Vibe-Research LICENSE](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/LICENSE)
- [vibe-astock LICENSE](https://github.com/simonlin1212/vibe-astock/blob/e0d08d19848b50d22a772729a06287cdff511629/LICENSE)

## 日终字段与来源（VERIFIED 为源码行为）

| 需求 | 上游路径 / 行 | 源码行为 | 对 LPPL 的建议 |
| --- | --- | --- | --- |
| 涨停、炸板、跌停、昨日涨停池 | a-stock-data SKILL.md 4385–4450 | push2ex 四端点；Pageindex=0、pagesize=10000；只返回 data.pool | 作为端点/字段目录；不可将单页大 limit 自动视为完整证明 |
| 原因、题材、板型 | 同上 4467–4499 | 同花顺 limit_up_pool；page=1、limit=200、filter=HS,GEM2STAR；reason_type 原文 | 范围只含沪深主板/创业板/科创板，不含北交所；需要范围元数据和分页证明 |
| 旧晋级建议 | 同上 4523 | 用昨日池 pct >= 9.8 计数 | 不移植；不同制度、价格舍入、复权/除权会使阈值不能代表真实封板 |
| 新晋级实现 | vibe-astock shortline_facts.py 311–344 | 前日 ZT 池为分母，当前 ZT code 集合匹配分子；前日缺失明确未算 | 可借用集合匹配与缺失展示思想；LPPL 保留原始字节、相邻日、首次取得时间和连板一致性检查 |
| 日期/业务失败 | Vibe-Research eastmoney.py 497–520 | rc 非0报错；qdate 仅拒绝请求日比最新行情日更晚；历史请求 qdate 可能仍为最新 | qdate 不可证明历史日期；需有限真实样本确认 exact-response schema |
| THS 新分页/日期校验 | vibe-astock shortline_themes.py 120–164 | status_code=0；总数来自 data.page.total；翻页总数一致/唯一代码；first_limit_up_time 按上海时区逐行核对日期 | 应单独适配这一路径；不能只期待 data.total/data.date，更不能用请求参数补证 |
| 题材标准化 | vibe-astock shortline_themes.py 53–74, 220 起 | 原因串按 + 分词，过滤属性词；没有原因时不以行业替代 | LPPL 保留原文、派生词与版本；属性过滤和最多4词是作者产品选择，不应直接丢失原始归因 |

精确文件：

- [a-stock-data 完整池/原因/晋级示例](https://github.com/simonlin1212/a-stock-data/blob/f21534946c42be3ad048ac938eecb1bad84cb8ab/SKILL.md#L4385-L4523)
- [Vibe-Research 东财解析](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/.agents/skills/data-access/scripts/sources/eastmoney.py#L497-L520)
- [vibe-astock THS 日期与分页](https://github.com/simonlin1212/vibe-astock/blob/e0d08d19848b50d22a772729a06287cdff511629/.agents/skills/data-access/scripts/sources/shortline_themes.py#L120-L164)
- [vibe-astock 两日集合晋级](https://github.com/simonlin1212/vibe-astock/blob/e0d08d19848b50d22a772729a06287cdff511629/.agents/skills/data-access/scripts/sources/shortline_facts.py#L311-L344)
- [vibe-astock 缺必要字段不补默认值](https://github.com/simonlin1212/vibe-astock/blob/e0d08d19848b50d22a772729a06287cdff511629/.agents/skills/data-access/scripts/sources/shortline.py#L299-L342)

## 三个重要差异

1. **旧 skill 与新产品并不同步（VERIFIED）**。a-stock-data 的 _em_zt_api 会异常后返回 []，容易把失败与空池混淆；新 Vibe-Research 解析对业务错误抛异常。LPPL 应采用明确 error/empty/partial，不能整段复制旧示例。
2. **完整市场池与 THS 原因范围不同（VERIFIED）**。THS 明确不含北交所。11/5 缺失的 920007 属于北交所范围差异的候选解释，但本次没有请求上游，因此“这就是缺失原因”仍为推断。不能为提高覆盖率把北交所股票从市场池删除；应展示全市场分母、适用范围分母、范围外缺口三个数。
3. **历史资料不等于当时已知（VERIFIED 为现有设计差异）**。vibe-astock 已收盘日长期缓存与今日补取历史池是产品策略；不能代替 LPPL 的不可覆盖修订账本及首次取得/首次公开可见时间。源站对过去的修订仍应追加新版本。

## 频率与网络证据边界

**VERIFIED（实现）**：a-stock-data 的 EM_MIN_INTERVAL=1.0s，批量建议1.5–2秒；Vibe-Research common.em_get 用跨进程文件锁串行、最小1秒加随机抖动，403不重试。注册表中 ths_limit_up_pool 的 cache_max_age_sec=900。

**PR 作者报告，未在本任务实测**：住宅 IP 偶发封锁、push2/push2his 的回退可用性、东财历史池约保留一个月、过往延迟/成功率。不能作为大陆网络当前验证结果。

**NOT_ESTABLISHED**：供应商批准的 QPS/日调用额度；这些 sleep/cache 数字是作者实现参数，不是上游服务等级或授权承诺。上游建议的代理回退、换网络等不能直接用于本次条件门禁；遇到明确拒绝应保留失败，不绕过。

- [a-stock-data 节流实现](https://github.com/simonlin1212/a-stock-data/blob/f21534946c42be3ad048ac938eecb1bad84cb8ab/SKILL.md#L768-L800)
- [Vibe-Research 跨进程节流](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/.agents/skills/data-access/scripts/common.py#L130-L190)

## 使用条件边界

Vibe-Research 和 vibe-astock 当前 data-access/SKILL.md 完全相同，其中第73行明确说明各源条款、再分发、商用尚未审核，仅限内部验证。因此 registry 中 `compliance=cn-public`、`enabled=true` 是作者分类/启用状态，不应在 LPPL 被翻译成“已许可”。

- [Vibe-Research 限定声明](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/.agents/skills/data-access/SKILL.md#L67-L75)
- [Vibe-Research 数据目录](https://github.com/simonlin1212/Vibe-Research/blob/84c141b86b5e7540b29f5f4cd5457dc0ebd6052e/datasources/registry.json)
- [vibe-astock 数据目录](https://github.com/simonlin1212/vibe-astock/blob/e0d08d19848b50d22a772729a06287cdff511629/datasources/registry.json)

本报告没有核对官网法律条款或请求数据源；这部分由另一独立审查负责。没有凭上述代码和说明书将任何 LPPL fetch/publish 开关设为 true。没有安装 skill、跑上游脚本、接入 AI 交易流程或修改模型。
