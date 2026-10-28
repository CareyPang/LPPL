# research/ — 临界点 2.0 研究层

| 目录 | 内容 |
|---|---|
| `data/` | `sources.py` 三个公开日线源（东方财富 → 腾讯 → 新浪），`cache.py` 本地 parquet 缓存 + Point-in-Time vintage |
| `lppls/` | `core.py` LPPLS 条件线性消元（lstsq）、代价函数、形态过滤（TOP_RULE 与 critical.js 一致；SORNETTE_RULE 为文献版） |
| `synth/` | `lppls_synth.py` 带已知真值的合成序列（iid / AR(1) / GARCH 噪声） |
| `optim/` | `optimizers.py` 四种优化器统一接口；`benchmark.py` 合成数据对比，输出到 `reports/` |

## 用法

```bash
pip install -e ".[dev]"
python -m research.data sh000001 000300 399006 600519   # 下载并缓存
python -m research.optim.benchmark --quick                # 优化器对比（快速版）
pytest
```

## Point-in-Time 规则

研究代码取数只能走 `research.data.cache.load(code, asof=...)`：
1. 选 **下载日期 ≤ asof** 的最新 vintage（防止未来的复权调整改写历史价格）；
2. 再按 `date ≤ asof` 截断（防止未来 K 线）。
3. asof 早于最早 vintage 时回退到最早 vintage，并打 `df.attrs["pit_approx"]=True`，报告中必须注明。

## 数据源已知问题（2026-10 实测）

- 东方财富 push2his / akshare `*_em` 接口在云端机器上连接被重置，本机可用；代码保留为首选源，失败自动换源。
- 腾讯个股 `qfq` 对长历史返回加法前复权（茅台 2016 年前价格为负），已被质量门拦截；个股源顺序改为 东方财富 → 新浪 → 腾讯。
- 腾讯指数数据无成交额字段（amount=NaN）。
