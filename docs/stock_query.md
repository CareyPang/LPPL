# 个股 LPPLS 查询

## 发起查询

在 GitHub 仓库打开 **Actions → stock_query → Run workflow**，填写六位 A 股代码；可选 `stk_lite` / `stk_full`，并设置历史周数（0–156，默认 104）。也可使用 GitHub CLI：

```sh
gh workflow run stock_query.yml -f code=600519
```

任务完成后，最新记录可在以下地址查看：

`https://careypang.github.io/LPPL/lab/mock/data/stock/<code>.json`

如果请求了历史，周度记录位于：

`https://careypang.github.io/LPPL/lab/mock/data/stock/<code>_history.json`

结果写入独立的 `stock-results` 分支，不写入 `main`；Pages 构建时将该分支合并到站点文件。工作流失败时也会发布 `<code>_error.json`，其中包含错误摘要和本次运行链接。

## 口径与限制

- 个股结果证据等级为 `research_candidate`，尚未经过样本外检验；不可视为指数证据、预测或投资建议。
- `stk_lite` 加 104 周历史在四核 runner 上，冷缓存预计约 4–15 分钟；`stk_full` 通常更久。
- 行情使用腾讯未复权日线与新浪后复权因子。GitHub 海外 runner 对腾讯/新浪接口的连通性尚未验证，首次运行前不能保证可达。
