# 顶部标签审阅证据包

日期：2026-11-06。状态：`CASEBOOK_ONLY_NOT_EVALUATOR_NOT_BACKTEST`。

主报告：[标签例集](../../2026-11-06-top-time-label-casebook.md)。评分：[21例手工真值](../../2026-11-06-top-time-scoring-review.md)。

- `synthetic_cases.json`：6条手工构造曲线、指定峰点与预期邻域关系；无资产或模型含义。
- `synthetic_prices.csv`：181个抽象交易日×6条曲线。
- `core_examples.png`、`boundary_examples.png`：合成示意；只标指定审阅点。
- `selected_real_cases.json`：独立审阅的7个行情案例、源哈希、邻域/谷/闭合日期、旧新谷规则、右21/42对照。不是预测成绩。
- `real_case_spec.json`：4个明确指定的作图案例。
- `real_example_prices.csv`：四幅图展示的价格片段，可有不同case重复日期；保留case_id。
- `real_example_checks.json`：4例指定点的独立算术核对。
- `real_examples.png`、`stage_semantics_comparison.png`：真实快照图；后者阴影/虚线是事后标签范围，不是预测带。
- `render_examples.py`：图表/证据生成器，只核对指定点，不实现通用评价器，不读拟合或预测，不访问网络。
- `manifest.json`：输入身份、指定点检查与本包文件哈希；没有用本地mtime证明历史提前预测。

复现从仓库根运行已有Python环境下的`python docs/research/evidence/top-time-label-review-20261106/render_examples.py`。Windows分析环境先加载`D:\CodexData\config\analysis-env.ps1`，字体为系统微软雅黑；不安装新依赖。作图缓存位于D盘。

两份输入来自已有`data/frozen/v20261104`，不是新下载。qfq口径、历史公司行动、当时可得时间与独立交易所日历尚未验证。观测行差不自动构成已核验可交易日差。当前例集是已消费的语义材料，不是独立性能样本。

生成器输出是研究文档附件；未修改任何生产模型、原评分器、前端或发布链路。真实模型性能和顶部判级能力仍为`NOT_ESTABLISHED`。
