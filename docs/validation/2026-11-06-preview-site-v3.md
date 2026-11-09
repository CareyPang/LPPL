# 海洋演示站第3版与本轮最终验收

日期：2026-11-06。[公开演示站](https://lppl-ocean-observatory-preview.groovy-cabin-8182.chatgpt.site)，沿用用户已授权的链接访问权限。

## 实际发布身份

- VERIFIED：Sites项目 `appgprj_6aedbc87f8808191b58788204795e049`，第3版部署 `appgdep_6aedf75518708191893fea3f4fe0dc48` 返回 `succeeded`。
- 保存版本：`appgprj_6aedbc87f8808191b58788204795e049~appgver_54cfbaa9a6e081918d9b1521ec83af43`。
- Sites源码：`ebd72a9ce5702a419e40f0d4188d03e41b8be0ae`；LPPL来源：`4f4fff52cd6cc6b868a2e264faf8b9c9ce160232`。
- 发布包SHA256：`8f6e5fd6b7ac43de6a83e539eb63909fe8ac40c963dd01c585214b4d4e19fe70`，53,442,560字节，862文件；构建清单内860个输出文件哈希逐一匹配。
- 第2版保留，部署 `appgdep_6aedf62e5fdc81919d97a7227f7edd37`；第3版追加修复首帧加载海报闪现。

## 用户可见改变

VERIFIED：已查回原对话及保留实现，左下hero“进入工作站”恢复太阳徽章与8秒高光；右上恢复普通深海半透明导航。青萍题句保留。每个解码来源先覆盖原天空再混合，Canvas回退也有天空绘制；动画状态清除原海报底图，避免加载和首帧淡入透出旧天空。静态/无JS阅读回退仍保留海面海报。

VERIFIED：本轮线上浏览器实际读取到 `stage painted`、动画背景 `none`、右上背景 `rgba(8,31,47,.7)`、hero动画 `badge-sun-pass`。点击左侧入口进入工作站，600519冻结K线与成交量可见，页面明确“交互演示、不运行模型”。默认演示不能因URL参数切换到生产接口。

VERIFIED：本地桌面下潜、水下、反向返回及正文接续已查看，采样画面未见旧天空漏出。实际390×844视口、内容宽375px，无水平溢出；动效关闭时扫光为none，重新开启恢复。最终加载修复实际验证动画背景为none、静态背景为poster。

NOT_INSPECTED：本次公开站390px覆盖未生效，实际读数仍为1215px，不能写成线上移动验收通过；本地390px记录单列。Canvas实机回退、全部素材帧逐帧、低端真机和大陆多运营商网络仍未验收。

## 代码与研究验证

- VERIFIED：离线Python全套422通过、2跳过、3网络测试排除；前端/Worker154通过。之后唯一代码变化是加载背景CSS，首页43项重新通过；未变研究及Worker实现。
- VERIFIED：Ruff、语法/空白检查通过。Git暂存字节与研究执行快照及哈希文件一致；新增证据路径明确关闭换行转换，并以 `core.autocrlf=true` 检出代表性研究快照和HTTP证据清单，字节一致。
- VERIFIED：研究独立复核69组相同91事件ID、18组逐资产同日同次数配对、54条旧E/TP/FN及全部输入/输出/代码哈希。结果见[提醒边界与单项对照](../research/2026-11-06-claim-boundary-ablation-results.md)。
- VERIFIED：新增浏览器本机首次可见账本与Worker持久首读回执通过代码和测试审查；真实接口两次GET均403。详见[真实链路与证据边界](2026-11-06-first-visible-chain.md)。

NOT_ESTABLISHED：真实计算链路成功、真实预测首次可见时间、模型实用性。历史重放、浏览器本机时间、Worker首读时间与可信首次公开发布不是同一证据。此轮仅发布独立静态演示站；没有合并PR、部署正式Pages/生产Worker或触发真实计算任务。
