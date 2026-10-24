"""用法: python -m research.data sh000001 000300 600519 [--adjust qfq]"""
import argparse
import logging

from .cache import load, quality_check, refresh

p = argparse.ArgumentParser()
p.add_argument("codes", nargs="+")
p.add_argument("--adjust", default="qfq")
a = p.parse_args()
logging.basicConfig(level=logging.INFO, format="%(message)s")
for c in a.codes:
    v = refresh(c, a.adjust)
    print(c, v.source, quality_check(load(c, adjust=a.adjust)))
