"""命令行用法：refresh/freeze 子命令与兼容旧的 refresh 参数。"""
from __future__ import annotations

import argparse
import logging
import sys

from .cache import freeze, load, quality_check, refresh


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m research.data")
    subcommands = parser.add_subparsers(dest="command", required=True)
    refresh_parser = subcommands.add_parser("refresh", help="下载并缓存日线数据")
    refresh_parser.add_argument("codes", nargs="+")
    refresh_parser.add_argument("--adjust", default="qfq")
    freeze_parser = subcommands.add_parser("freeze", help="创建冻结数据版本")
    freeze_parser.add_argument("--name", required=True)
    freeze_parser.add_argument("codes", nargs="*")
    freeze_parser.add_argument("--adjust", default="qfq")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"refresh", "freeze"}:
        args.insert(0, "refresh")
    parsed = _parser().parse_args(args)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if parsed.command == "freeze":
        records = freeze(parsed.name, parsed.codes or None, parsed.adjust)
        for record in records:
            print(
                record["symbol"],
                record["source"],
                f"rows={record['rows']}",
                f"last={record['last_date']}",
            )
        return
    for code in parsed.codes:
        vintage = refresh(code, parsed.adjust)
        print(code, vintage.source, quality_check(load(code, adjust=parsed.adjust)))


if __name__ == "__main__":
    main()
