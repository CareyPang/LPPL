# Choice / iFinD 正式 API 产品核验

核验日期：2026-11-09；项目基线 `c7ee81d`。仅核对官方公开目录、手册、FAQ 和协议，未安装 SDK、登录、申请试用、采集金融数据、购买、联系供应商或部署。本文的 **VERIFIED** 表示官方文档内容已核实，不表示账号已授权或实际数据已验收。

## 1. 决策结论

现在可以把两家列入正式数据源候选，但**尚不能据公开材料直接购买并启用完整 P1 复盘**。

候选不等于必须采购。a-stock-data 已提供直接取数代码；免费/公开来源若适用条件、完整性和运行能力满足目标用途，同样可采用。正式 API 询价用于补齐可比较的字段、授权、额度与价格证据，并不证明付费产品自动更完整或可公开展示。[两家可发送正文、共同询价表与选择说明](vendor-inquiries-2026-11-09/README.md) 已准备，尚未发送。

- Choice 的日终状态与历史概念字段已经找到明确指标，适合优先索要完整样本和覆盖承诺。
- iFinD 的 HTTP、额度和设备限制较清楚，适合验证腾讯后端的接口接入方式；P1 专用字段仍需具体命令。
- 两家原生完整四池、原因正文、历史事件题材，以及本网站的存储/衍生/展示授权均有未确认项。选择依据应是精确字段、样本和合同范围，不是产品名称或“全市场数据”宣传。

当前三个网页来源继续禁用。正式 Choice/iFinD 应作为新的独立来源登记，不能用正式产品权限给 `push2ex` 或 `data.10jqka` 网页接口放行。

## 2. 具体数据覆盖

| P1 需求 | Choice 正式 API | iFinD 正式 API | 项目判断 |
| --- | --- | --- | --- |
| 日线行情与股票目录 | **VERIFIED**：日行情指标和证券资料函数 | **VERIFIED**：`THS_HQ` 历史行情、HTTP 示例和 `THS_DR` 成分报表示例 | 通用函数存在；实际账号字段、历史全集和复权口径仍需样本 |
| 收盘涨停/跌停 | **VERIFIED**：`MAXUPORDOWN` 定义收盘状态；另有 `ISSURGEDLIMIT/ISDECLINELIMIT` | **NOT_ESTABLISHED**：未取得对应正式指标 ID/返回样例 | Choice 可作为构建派生池的候选，不能直接声称全市场完整池已提供 |
| 连板与涨跌停价 | **VERIFIED**：`HLIMITEDAYS/LLIMITEDDAYS`、`LIMITUPPRICE/LIMITDOWNPRICE` | **NOT_ESTABLISHED**：需精确指标和参数 | 特殊交易制度、ST、新股无限价日及北交所逐字段验收 |
| 完整 ZT/DT/YZT 池 | **NOT_ESTABLISHED**：直接报表未确认 | **NOT_ESTABLISHED**：数据池/专题功能存在，不等于本项目三池已确认 | 可在获准且完整的逐股数据上派生；历史证券全集和收盘最终性仍要证明 |
| 完整炸板池及开板次数 | **NOT_ESTABLISHED**：未确认专门报表、次数/首末封字段 | **NOT_ESTABLISHED**：未确认对应报表 | 日线只能研究“触及涨停价而收盘未封住”，不能还原开板次数和过程，也不宣称与供应商炸板池同义 |
| 涨停原因正文/摘要 | **NOT_ESTABLISHED** | **NOT_ESTABLISHED** | 不能以概念列表或生成文字代替来源的事件解释 |
| 概念及历史归属 | **VERIFIED**：`BLCONCEPTSORNOT`、`BLGAINIAN_HIS/BLGAINIANCODE_HIS`，有截止日参数 | **NOT_ESTABLISHED**：本次未取得具体字段及历史版本定义 | 概念成员关系与当天涨停题材/原因分别保存 |
| 次日晋级 | LPPL 可在获准的相邻两日完整池上计算 | 同左 | 是本项目派生统计，不冒充供应商已提供的结果；不用固定涨幅阈值 |

Choice 字段来自官方 [日行情目录](https://quantapi.eastmoney.com/AIGuide/GetMarkdownContent?nodeId=101001005001&pnodeId=101001005) 与 [证券资料目录](https://quantapi.eastmoney.com/AIGuide/GetMarkdownContent?nodeId=101001001001&pnodeId=101001001)。日行情参数为 `TradeDate`，历史概念/ST 等使用相应日期参数。`MAXUPORDOWN` 的收盘含义明确；另外两个“是否涨跌停”字段的触及/收盘语义还需供应商解释。

Choice 父目录标为沪深京，也有 ST/*ST 指标；这只证明目录考虑了这些类别，不证明每项字段对全部市场、所有历史日期均完整。已检查的 [135 项公开股票专题目录](https://quantapi.eastmoney.com/AIGuide/GetAllLeafNodes?nodeId=0001&pageSize=200&pageIndex=1) 未确认原生四池和原因表；**检索未命中不等于产品不提供**。

iFinD [FAQ](https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center/faq.html) 表明具体命令通过“超级命令”查看，未提供独立指标字典。本次匿名公开材料未建立上述专用 report/indicator ID；未借登录账号或第三方网页端点补证。

iFinD [官方示例](https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/example.html) 确有 A 股成分和历史行情用法。但 Python 成分例使用 `p03291`，HTTP 例有 `p03425` 与 `p03291_f...` 字段混用；应让供应商给出当前账号生成的完整命令，不拼接示例当作已验证请求。

## 3. 调用限制：次数、数据量和账号权限分开

### Choice

**VERIFIED（正式手册）**：CSS、CSD 各不超过 700 次/分钟，单次最多 64 个指标；这个规则不是所有接口统一的 QPS，也不能据此推导瞬时突发并发。账户流量周期、阈值与剩余额度可用 `datastatistics` 查询，当前具体套餐额度、CTR 限制、费用和试用范围均 **NOT_ESTABLISHED**。

手册为 V2.7.9.0、2026-10-30，新增 API KEY 登录；支持 Linux SDK。默认账号多 IP/多进程有约束，多点服务需单独确认。[正式 Python 手册](https://quantapi.eastmoney.com/Upload/EMQuantAPI_Python.html?_=639297839052435895)。纯 REST 接口及腾讯具体实例兼容性本次未建立证据。

### iFinD

**VERIFIED（公开权限表，取 LPPL 相关部分）**：免费档历史行情 100 万单元格/月，基础/日期序列/专题报表分别 60 万/月；试用与正式档公布的行情合计 1.5 亿/周、基础三类合计 500 万/周。条数按数据单元格计，不是请求次数。免费/试用的日历史通常最近 5 年，正式档列证券上市以来；具体字段仍可能有自身覆盖限制。[权限说明](https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center/permission.html)

**VERIFIED（FAQ）**：单函数 QPS 10，EDB 为 5，账号合计 20；SDK 同时单设备，累计可绑定 8 台。免费档资格的公开说法存在差异：权限页写已有 iFinD 账号即可，FAQ 将其解释为终端购买者的附带接口；因此不能承诺新注册即可取得免费额度。该页同时列 A 股日行情约 15:07、一般行情收盘后 1–2 小时入库，不能据此给原因/题材完整池设定确定的 ready 时间。[FAQ](https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center/faq.html)

HTTP 的 20 个 IP 限制按单个 access_token 绑定说明理解，不是账户终身只准 20 个 IP；后台应按实际合同与令牌规则管理出口。[部署说明](https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center/deploy.html)

额度不等于网站展示许可；免费、试用或正式档都要单独核对使用主体和用途。费用尚未取得可适用于本项目的明确报价。

### 本项目预算示例（推算，不是供应商报价）

假设 6,000 个证券、每天 6 个数据值、22 个交易日，约 79.2 万单元格/月；一次为 100 个证券补 1,000 日、6 列历史，约 60 万单元格。这里的证券数是容量情景，不是当前市场数量。两项还未计补抓、其他字段和失败计费，不能据此宣布某免费档够用。共享缓存与按需补历史可降低重复提取；应以账户计量规则核算。

## 4. 保存、衍生与网站展示

| 用途 | 本轮结论 | 仍需确认的范围 |
| --- | --- | --- |
| 正式 API 自动取数 | **VERIFIED**：两家产品均提供编程取数；本项目账号权限 **NOT_ESTABLISHED** | 主体、套餐、端点/字段、服务器与用途 |
| 保存原始响应/长期缓存 | **NOT_ESTABLISHED** | 保存时长、历史修订、备份、合同终止后的保留/删除 |
| 晋级率、题材热度等派生统计 | **NOT_ESTABLISHED**：产品研究定位不自动覆盖对外发布 | 内部研究与公开/付费展示分别约定，是否需署名、审查或额外费用 |
| 对外网页显示行情/原因/题材 | **NOT_ESTABLISHED** | 原始/延迟数据、图表、文字、下载导出、访问人数、是否允许付费用户 |

不得把官网一般声明、终端个人协议或 API 的技术“权限说明”当成已经签订的机构数据服务合同。现有公开页面没有使本项目取得上述缺失权利；这不等于认定供应商永远不提供相应授权。

具体边界：Choice [API 注册页](https://quantapi.eastmoney.com/Account/Register) 关联的 [上海奇思协议](https://choice.eastmoney.com/Html/userprotocol/userprotocol12.html) 含个人/移动设备表述，同时承认其他服务可能另有条款。因此不能把它直接当作机构 API 合同并断言 Linux 云部署禁止。iFinD [隐私协议](https://ft.10jqka.com.cn/thsft/iFindService/CellPhone/information/agreement?protocol=privacy&status=1) 的专项约定优先规则属于隐私范围，不能扩大成 API 数据转供授权。两家具体订单、专项数据许可及其优先顺序本轮均未取得。

## 5. 腾讯后端连接方案

**设计推断**：用户只访问 LPPL，后台通过获准 API 统一采集和缓存；原始响应留在私有存储，只把合同允许的字段投影到网页。不要把供应商账号、cookie、API key/access token 放进浏览器，也不要每个页面访问都登录供应商。

- Choice：优先验证单个 Linux SDK 采集进程，固定运行环境；多实例与故障切换须核对账号授权，不默认容器可以无限横向扩展。
- iFinD：优先验证后端 HTTP 适配，SDK 也有 Linux 方案；按 IP 和账号限制设计固定出口、共享限流与缓存。HTTP 不需要 SDK 环境初始化见 [部署手册](https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center/deploy.html)。
- 两者的腾讯实际网络、延迟、兼容性和 SLA 均 **NOT_INSPECTED**；本次只是文档核验，没有进行 API 数据调用或云部署。

## 6. 供应商确认清单与小样本验收

采购前要求对方逐项提供可执行命令/字段字典及合同范围，先确认下列内容：

1. ZT/ZB/DT/YZT 原生报表 ID、总数和分页；若不提供，哪些正式字段可供派生，如何取得历史有效证券全集。
2. 沪深北、ST/*ST、退市、换码、新股无涨跌幅限制日的覆盖；至少给北交所和普通沪深证券的对应样例。
3. 原因文本与事件题材的确切字段、内容来源、最早历史日、发布时间、修订记录；概念归属另列。
4. 日终最终更新时间、错误与空池的区别、补数据和修订机制；前一日是否仍能取得同一版本。
5. 调用次数、每次数据上限、数据单元格/流量计费、周期、超额处理、试用与正式差异及服务器/IP授权。
6. 原始留存、规范化保存、备份、派生统计、免费与付费网站展示、图表/文字/导出各自是否允许；给可留档的条款或书面确认。

确认后才准备有限样本：两个相邻已收盘交易日，预先固定市场范围和请求预算；保存 raw/来源时间/分页/总数，验证原因覆盖、完整池、次日晋级和修订。历史补取标注实际取得时间，不计当时已知，更不计真实提前预测。

**本轮操作结果**：研究报告更新 PR #50，采集开关、模型、旧结果和线上状态不变；没有把任何未知权利改成 verified。

## 7. 文档证据与验收边界

[官方文档索引与 hash](../validation/evidence/formal-api-review-20261109/public-document-index.json) 记录本次核对的公开资料。原始手册保留在 `D:\CodexData\analysis\lppl-formal-api-review-20261109`，未把整本手册、账户资料或供应商市场数据上传仓库。本地索引只绑定所读文档，不是供应商授权证明。

本轮只修改报告和规划链接，核对相对链接、JSON 及本地文档 hash。没有模型/采集代码变化，不以先前代码测试数冒充新的数据采集验收。
