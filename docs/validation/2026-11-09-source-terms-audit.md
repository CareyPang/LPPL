# 日终源访问与频率独立核验

核验日：2026-11-09。范围只读官方网页及 a-stock-data 文档；没有请求行情池、创建账户、购买、联系服务商或修改 LPPL 仓库。网页工具取得成功只证明该工具可读，不证明大陆实测。

## 来源结论

| LPPL 来源 | 官方条款证据 | 当前可以确认 | 尚不能确认 |
|---|---|---|---|
| eastmoney_limit_pools：getTopicZTPool / getTopicZBPool / getTopicDTPool | https://about.eastmoney.com/home/legal 第四、八、十节；https://about.eastmoney.com/home/protocol 首部、协议范围、服务内容 | VERIFIED：网站限制不合理高负载；内容复制、传播、演示等涉及书面许可，行情另提交易所许可。服务协议包含 WEB 端与行情服务，特定服务可能另有协议 | NOT_ESTABLISHED：这些网页内部端点是否另有可供本项目研究采集/原始响应保存的许可、公开展示范围、端点数值限频、完整性与稳定性 |
| eastmoney_yesterday_zt_pool：getYesterdayZTPool | 同上，不能借昨日数据名义绕开同一供应商条款 | VERIFIED：相同供应商网站条款是相关证据 | NOT_ESTABLISHED：端点具体许可、供应商认可的频率、实际数据定义/日期覆盖 |
| ths_limit_up_pool：data.10jqka.com.cn/dataapi/limit_up/limit_up_pool | https://news.10jqka.com.cn/clientinfo/protocol.html 第 1–3 节 | VERIFIED：明确免费产品的自用非商业下载使用有条件许可；复制/分发受限，商业复制分发须书面授权，未明示权利保留 | NOT_ESTABLISHED：该 dataapi 端点是否属于此项免费产品许可、自动访问与 raw 留存范围、原因题材对外展示权、端点数值频率 |

这里的门禁结论是“尚不能标为研究访问审核通过”，不是对所有私人查看或数据使用作违法判断；条款适用范围与任何额外合同均需按具体端点确认。搜索没有找到许可，不等于存在全面禁止；同样，HTTP 200、零 Key 或 GitHub 示例不能替代许可。

## 不可混用的证据

- a-stock-data 当前 LICENSE 为 Apache-2.0：https://github.com/simonlin1212/a-stock-data/blob/main/LICENSE 。其代码/文档授权不自动授权东方财富、同花顺的行情及解释文本。
- 该 SKILL.md 的“不封 IP”“免费无 key”“实测”等是作者技术报告；其退避或请求间隔是客户端做法，不是供应商承诺的限频或 SLA。不能据此把 policy 的研究权限、频率和大陆路径改为 verified。
- 同花顺 iFinD 的公开权限说明属于另一个产品：https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center.html 。其条数/账户配额不可用于上述 dataapi 网页端点。
- 在同花顺社区域名搜到“每秒 5 次”等文章，不是该日终端点的合同或 API 手册；本轮不采用。另有问财/同顺号专属协议，也不直接套作 limit_up_pool 的唯一适用协议。
- 机器人文件与 HTTP 响应均不能独自授予内容再分发权；没有拿到供应商限频，不应通过压力试探寻找封禁阈值。

## 可执行的下一步

1. 许可记录拆成 automated_access、raw_storage、derived_statistics、public_display 四种用途，并记录端点、主体、期限、条款/书面确认及核验人。不能一个 verified 同时放行所有用途。
2. 频率分成 provider_limit（未公布则空）和 local_budget（计划值）。有限研究建议只作为待审核预算：单并发、同源间隔至少 5 秒、最多 5 个核心请求/日、不重试 403/429、遇验证码即停；这些不是已获准额度。
3. 网络验证独立：DNS/TCP/TLS 或条款页成功可记录技术可达；若走代理、出口或地理位置未核实，不能标大陆直连通过。API 字段与完整池仍需通过许可后的真实响应核验。
4. 获取真实样本前，先明确是私人研究原始存储还是未来网站展示；前者获准不自动放行后者。对于当前代码三来源，保持 fetch_enabled=false，直到端点适用依据补齐。
5. 官方产品替代通道可进一步询价/核对（不在本轮主动购买或联系）：Choice 官方 API https://quantapi.eastmoney.com/ 提供试用、文档和流量查询；iFinD 官方 API https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/ 提供试用及权限说明。是否包含全量日终池/原因/题材、可再分发及价格仍未成立。

## 证据边界

VERIFIED：上述官方页面的条款存在、来源 URL、a-stock-data 的代码许可证类型。

NOT_ESTABLISHED：三来源通过本项目许可门禁、端点供应商限频、大陆直连、真实日终样本、次日晋级成功、公开再分发。

用户本轮确认目前没有相关授权。没有读取私人合同、账号权限或凭证；不能假定存在额外端点许可。
