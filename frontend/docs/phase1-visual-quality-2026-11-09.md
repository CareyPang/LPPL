# Phase 1 视觉质量报告：统一设计系统、首屏与动效

日期：2026-11-09  
基线：PR #50，`d3a7f3b52e2b49bba556bf17443de5a21c4931d7`  
范围：`home.html`、`stock.html`、`market.html` 的视觉桥接、首屏层级、动效预算和 390px/桌面验收。未修改行情、LPPLS、Worker 或 `frontend/app/lppl-data.js`。

## 结论

第一阶段已完成一个可回滚的视觉层：海洋入水叙事仍由首页负责，工作站和市场背景页开始共享同一套海水深色、象牙色、冷白色和香槟色语义。首屏只保留一个主行动“进入工作站”，海面标题、两句引语、边界文案和向下探索仍按原叙事顺序出现。

本阶段的“完成”指代码、可访问结构、响应式规则和本地预览均通过；它不等于获得 Awwwards、Webby 或 FWA 奖项，也不等于跨浏览器生产环境验收。

## 已实施

### 1. 共享设计 tokens

新增 `frontend/app/observatory-phase1.css`，使用 `--obs-*` 前缀避免覆盖旧页面和业务字段：

- 海水层级：`--obs-ocean-950/900/800`，仅保留安静底层和信息表面两种主要层级。
- 文字层级：`--obs-ivory`、`--obs-cold`、`--obs-muted`。
- 证据与状态：`--obs-cyan`（已核验）、`--obs-stale`（旧或待刷新）、`--obs-not-established`（未建立）、`--obs-error`（失败）。
- 交互尺寸：数据页按钮、筛选器和复盘切换统一至少 44px 高；可见焦点环统一为冷青色。
- 动效预算：控制 160ms、内容 360ms、章节 900ms；仅使用 transform/opacity 作为默认过渡，并保留 `prefers-reduced-motion` 关闭路径。

### 2. 首页首屏

- 保留“浪成于微澜之间。”和“启于青萍之末，满于狂澜之巅。”，不改变原有水线和水下章节逻辑。
- 降低首屏遮罩密度，让海面影像仍可见，同时保证象牙色标题在天空、海线和浪花上的对比度。
- 主 CTA 使用统一香槟色表面，移动端在 390px 宽度下占据可读宽度，箭头成为唯一的方向性微交互。
- 首屏标题启用平衡换行，边界文案限制行长，避免小屏横向挤压和文字重叠。
- 章节文字改用统一内容动效时长，水下叙事仍由滚动触发；系统减少动效或页面静态策略下不播放光带和章节过渡。

### 3. 个股工作站与市场背景页

- 两页通过 `body.observatory-page` 复用海水背景、半透明信息表面、12/18px 圆角和统一焦点环。
- 原有终端数据结构、来源字段、stale/error 文案和业务脚本保持不变；缺失市场快照仍显示原始失败边界，不伪造数据。
- 数据页导航、卡片、筛选器、复盘 tabs、题材阶梯和图表容器获得统一层级，但未把描述性数据升级为预测信号。

## 验收证据

| 项目 | 状态 | 证据 |
|---|---|---|
| 首页桌面首屏 | VERIFIED | 本地 HTTP 预览检查海面影像、标题、引语、CTA、导航和滚动提示；页面未出现文字重叠。 |
| 工作站桌面页 | VERIFIED | 本地预览检查海水表面、工作站入口、输入区和研究说明层级。 |
| 首页 390px | VERIFIED | 390px iframe 预览检查顶部导航、标题、引语、全宽 CTA 和边界文案。 |
| 工作站 390px | VERIFIED | 390px iframe 预览检查输入区、按钮、资产入口和下方研究卡片。 |
| 市场页 390px | VERIFIED | 390px iframe 预览检查导航、失败状态边界和窄屏信息层级；缺失 `market/market_latest.json` 是真实数据边界。 |
| CSS 响应式契约 | VERIFIED | `frontend/tests/observatory-design-system.test.cjs` 覆盖 390px 规则、44px 控件、首屏 CTA 和减少动效规则。 |
| 全量 Node/Worker 测试 | VERIFIED | 220 tests passed，0 failed。 |
| 真实手机、Safari、低带宽和屏幕阅读器 | NOT_INSPECTED | 当前仅完成本地 Chromium 预览和代码契约；需在目标设备与网络条件下补测。 |
| 奖项评分或获奖概率 | NOT_ESTABLISHED | Awwwards/Webby/FWA 标准用于设计自检，不构成评审结果。 |

## 自检标准

- Awwwards 的公开评估结构包含 Design、Usability、Creativity、Content；本阶段优先覆盖可用性、视觉系统、创意叙事和内容边界，未宣称达到任何分数。参考：[Awwwards Evaluation](https://www.awwwards.com/about-evaluation/)。
- Awwwards 移动指南强调 viewport、触控目标、可读字号、对比度、可见 CTA、首屏速度、懒加载和错误反馈；本阶段完成 viewport meta、44px 交互尺寸、焦点环、CTA 和失败状态，性能与真实网络仍待补测。参考：[Mobile Excellence Guidelines](https://www.awwwards.com/mobile-excellence-guidelines.pdf)。
- Webby 的公开标准覆盖 Content、Structure & Navigation、Visual Design、Functionality、Interactivity、Innovation 和 Overall Experience；本阶段把海洋叙事与数据页边界分工固定下来，未把描述性数据包装为预测。参考：[Webby Judging Criteria](https://www.webbyawards.com/judging-criteria/)。
- FWA 要求真实可访问项目和事实性项目说明；当前改动仍停留在 PR 预览，未发布，也未提交评奖。参考：[FWA Submit](https://thefwa.com/submit)。

## 下一阶段入口

1. 在真实 390px Android、Safari/iOS 和低带宽条件下记录首屏时间、视频降级、键盘焦点和滚动入水连续性。
2. 把工作站的顶部区间、数据截止日、来源和证据状态做成固定的首屏信息摘要，再进行个股流程验收。
3. 只有在 P1/P2 数据链路和 stale 证据稳定后，才继续加入热力图、全球宏观和预测市场概率卡片；这些卡片不得直接进入 LPPLS。

