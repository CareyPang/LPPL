# 在本机用真实行情测试「观时」

打开 `http://127.0.0.1:8797/guanshi.html?asset=sh600519`。页面先读取构建站点内的真实归档。点击「检查更新行情」时，浏览器向本机 8798 端口的 Worker 发起 `GET /market?code=600519`。本机运行相同的行情处理代码，读取腾讯上游。线上 Worker 的浏览器来源配置维持在正式站域名。

### 启动本地 Worker

在 Windows 的 PowerShell 7 终端中从仓库根目录执行以下命令。Wrangler 4.158.0、Node 24 已验证。示例将临时 Worker 源码、状态和包缓存放在本地分析环境。只复制源文件，在临时配置中指定本机来源并移除定时触发器，行情读取无需 GitHub 或 Cloudflare 凭据。

```powershell
. 'D:\CodexData\config\analysis-env.ps1'
$workerRoot = Join-Path $env:CODEX_ANALYSIS_WORK ("guanshi-worker-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $workerRoot | Out-Null
Copy-Item -LiteralPath workers/stock-query/src -Destination $workerRoot -Recurse
Get-Content -LiteralPath workers/stock-query/wrangler.toml |
    Where-Object { $_ -notmatch '^\[triggers\]$|^crons\s*=' } |
    ForEach-Object { $_ -replace '^ALLOWED_ORIGIN\s*=.*$', 'ALLOWED_ORIGIN = "http://127.0.0.1:8797"' } |
    Set-Content -LiteralPath (Join-Path $workerRoot 'wrangler.toml') -Encoding utf8NoBOM
Set-Location -LiteralPath $workerRoot
npx --yes wrangler@4.158.0 dev --local --config wrangler.toml --ip 127.0.0.1 --port 8798 --inspector-ip 127.0.0.1 --inspector-port 9298 --persist-to state
```

### 查看页面

在第二个终端的仓库根目录运行。传给 `--site` 的目录来自项目已有的 `bash scripts/build_site.sh`，包含 `guanshi.html` 和 `lab/mock/data/`。如要显示本次验收的模型记录，还需在构建该站点的检出目录内准备对应的 `stock-results` 本地分支。

```powershell
. 'D:\CodexData\config\analysis-env.ps1'
python tools/guanshi_preview.py --site _site
```

使用 `127.0.0.1` 访问。浏览器会将 `localhost` 识别为另一个来源。预览服务仅在返回「观时」HTML 时设置 `window.LPPL_QUERY_API`，其余页面和磁盘文件仍使用原本的内容。按 Ctrl+C 可分别结束两个服务。
