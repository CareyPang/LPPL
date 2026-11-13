"""LPPLS_G3 / LPPLS_Q3 开关：关闭时列与数值与现行逐位相同；打开时只追加 g3_src、q3_p，q3_p 对未过 box 的窗口为 NaN。"""
import json
import os
import subprocess
import sys

import pytest

CODE = r"""
import json, sys, numpy as np
from research.features import lppls_scan as L
from research.lppls import core
core.ALLOW_INSIDE = True
rng = np.random.default_rng(1); n = 130; t = np.arange(n, dtype=float); dt = n - 1; tc0 = dt + 0.05 * dt
X = core.design(t, tc0, 0.5, 9.0, allow_inside=True); B = -0.6 / abs(tc0) ** 0.5
bub = X @ np.array([8.0, B, 0.1 * abs(B), 0.1 * abs(B)]) + rng.normal(0, 0.01, n)
gbm = np.cumsum(rng.normal(0, 0.02, n)) + 8
out = {"cols": L.COLS, "bub": list(map(str, L.fit_one(bub))), "gbm": list(map(str, L.fit_one(gbm)))}
print(json.dumps(out))
"""


def _run(**env):
    e = {**os.environ, "LPPLS_BOX": "v2", "LPPLS_WINDOWS": "lite", **env}
    e.pop("LPPLS_G3", None) if "LPPLS_G3" not in env else None
    e.pop("LPPLS_Q3", None) if "LPPLS_Q3" not in env else None
    p = subprocess.run([sys.executable, "-c", CODE], env=e, capture_output=True, text=True, check=True)
    return json.loads(p.stdout.strip().splitlines()[-1])


@pytest.mark.slow
def test_flags_off_identical_and_flags_on_append_only():
    off = _run()
    on = _run(LPPLS_G3="1", LPPLS_Q3="5")
    assert len(off["cols"]) == 18 and "q3_p" not in off["cols"]
    assert on["cols"] == off["cols"] + ["g3_src", "q3_p"]
    assert len(off["bub"]) == 17 and len(on["bub"]) == 19
    # 现行 tcgrid_lm 赢时前 17 项逐位相同；de_lbfgsb 赢时 SSE 必须更小
    for key in ("bub", "gbm"):
        src = on[key][17]
        assert src in ("tcgrid_lm", "de_lbfgsb")
        if src == "tcgrid_lm":
            assert on[key][:17] == off[key][:17]
        else:
            assert float(on[key][8]) < float(off[key][8])
    q_bub, q_gbm = float(on["bub"][18]), float(on["gbm"][18])
    assert 1 / 6 <= q_bub <= 1.0
    assert q_gbm != q_gbm or 1 / 6 <= q_gbm <= 1.0  # 未过 box → NaN
