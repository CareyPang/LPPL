# 临界点 LPPLS 研究项目

A 股 LPPLS 浏览器原型与 Python 研究层，包含冻结行情数据、拟合优化和验证工具。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `web/` | 浏览器原型与静态资源 |
| `research/` | Python 研究层 |
| `tests/` | 自动化测试 |
| `data/frozen/` | 冻结数据版本 |
| `reports/` | 研究报告与基准结果 |
| `docs/` | 研究框架文档 |

## 运行

```bash
pip install -e ".[dev]"
pytest
python -m research.data refresh sh000001 600519
python -m research.data freeze --name v20261024
```
