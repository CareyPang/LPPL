import json
from pathlib import Path

import pytest

from research.pipeline import daily


@pytest.mark.skipif(not Path("data/frozen/v20261024").exists(), reason="需要冻结数据")
def test_daily_frozen_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("LPPLS_BOX", "v2")
    p = daily.run("sh000001", frozen=True, asof="2015-06-12", windows=(130, 200, 300), out=tmp_path, trust_boot=2)
    rec = json.loads(p.read_text())
    conf = rec["top"]["lppls_confidence"]
    assert set(["1-3m", "6-12m", "12-24m"]) <= set(conf)
    assert rec["top"]["p20"]["evidence"] == "fail_i_iii"
    assert rec["top"]["bubble"]["evidence"] == "descriptive"
    assert rec["data_version"].startswith("frozen_")
