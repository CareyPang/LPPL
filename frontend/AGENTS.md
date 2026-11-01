# Open Design 前端协作规则

- 设计与页面改动仅提交到 `frontend/`；不得修改 Devin 所有的 `frontend/app/lppl-data.js`。
- 使用 `od/<topic>` 分支，并向 `main` 提交 PR。
- 所有业务数据只能通过 `frontend/app/lppl-data.js` 读取；它从静态 JSON `lab/mock/data/` 加载。禁止页面直接读取数据文件。
- 不在前端重算模型，不添加或恢复本地模型引擎及其回退逻辑。
- 字段含义以 `docs/od_field_mapping.md` 为准；证据显示遵守 `docs/frontend_contract.md` §3–4：
  - `none`、`fail*`、`dev_only`、`dev_failed` 不显示数值。
  - `descriptive` 必须显示样本数 `n` 和“历史分位，不是预测”。
  - `drawdown_price.value` 恒为 `null`，不得显示目标价。
  - 时间窗只显示为区间，不显示精确顶部日期。
- 禁止新增或显示 `bubbleScore`、`bubbleMultiScaleScore`、`bubbleProgress`、`tcOffset`、t_c 概率密度及趋势/动量指标。
- 本地预览：`bash scripts/build_site.sh && python -m http.server 8000 -d _site`。
