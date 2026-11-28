from research.eval.bottom_score_pbn import CONFIGS, is_green


def _frame(erp, pbn, dd, valuation):
    return {"bottom_detail": {"erp_pct": erp, "pbn_pct": pbn, "dd_52w": dd, "valuation": valuation}}


def test_candidates_follow_registration():
    # 2026-11-26 上证读数：破净分位 0.888、ERP 分位 0.442、回撤 -16.8%，V2 估值 0.22
    live = _frame(0.442, 0.888, -0.168, 0.22)
    assert not is_green(live, CONFIGS["B0"])
    assert is_green(live, CONFIGS["P1_v0.3_t50"])  # 0.6*0.96 = 57.6
    assert not is_green(live, CONFIGS["P1_v0.3_t60"])
    assert is_green(live, CONFIGS["P3_t90"])
    assert is_green(live, CONFIGS["P2_v0.7_t50"])
    assert not is_green(_frame(None, None, -0.5, None), CONFIGS["P2_v0.3_t50"])
    assert not is_green(_frame(0.95, None, -0.5, 1.0), CONFIGS["P1_v0.3_t50"])
    assert len(CONFIGS) == 11
