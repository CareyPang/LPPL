# 个股公开查询 Worker

Worker 为 GitHub Pages 个股页提供公开排队入口、运行状态和已发布结果读取。Worker 不执行模型；计算仍由仓库的 `stock_query.yml` 工作流完成。

## 部署

1. 注册 Cloudflare 账号并启用 Workers。
2. 在本地安装 Node.js/npm，然后进入 `workers/stock-query/`，登录：
   ```sh
   npx wrangler login
   ```
3. 创建限流 KV namespace：
   ```sh
   npx wrangler kv namespace create RL
   ```
   将命令输出的 namespace ID 填入 `wrangler.toml` 的示例绑定，并取消 `[[kv_namespaces]]` 三行的注释。没有 KV 绑定时仍可用，但响应会带 `ratelimit: "disabled"`。
4. 创建仅限 `CareyPang/LPPL` 的 fine-grained personal access token，并设置 Worker secret：
   ```sh
   npx wrangler secret put GH_TOKEN
   ```
   只选择 `CareyPang/LPPL` 仓库，并授权 **Contents: Read and write** 与 **Actions: Read**。Contents 读权限用于从 `stock-results` 读取结果，写权限用于创建 `repository_dispatch` 事件；Actions 读权限用于读取 `stock_query.yml` 的运行状态。不要将 token 写入源码或 `wrangler.toml`。
5. 部署：
   ```sh
   npx wrangler deploy
   ```

默认允许的浏览器来源是 `https://careypang.github.io`，默认仓库是 `CareyPang/LPPL`。可在 `wrangler.toml` 的 `[vars]` 中调整 `ALLOWED_ORIGIN` 和 `REPO`。

## API

- `POST /query`，JSON `{"code":"600519"}`：成功排队返回 HTTP 202。绑定 KV 时，每 IP 10 分钟最多 5 次，同一代码 15 分钟内只派发一次。
- `GET /status?code=600519`：返回匹配的最新工作流状态。
- `GET /result?code=600519&kind=latest|history|error`：读取 `stock-results` 分支中的对应 JSON；缺失时保留 HTTP 404。
