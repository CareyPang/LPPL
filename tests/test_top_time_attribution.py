from tools.lppl_top_time_attribution import (
    classify,
    contract_qualified,
    later_qualified,
    primary_reason,
)


def forecast(left, right, action=80):
    return {"interval_start":left,"interval_end":right,"hypothetical_action_session":action,"session":action-1}


def test_no_claim_is_not_an_invented_negative_interval():
    result = classify(None, 100)
    assert result == {"interval_relation":"NO_FIRST_CLAIM","flags":["NO_FIRST_CLAIM"]}
    assert primary_reason(False,result["flags"]) == "NO_FIRST_CLAIM"


def test_position_and_width_are_independent_inclusive_contracts():
    result = classify(forecast(89,99),100)
    assert result["interval_relation"] == "BEFORE"
    assert result["width"] == 11
    assert result["event_lead"] == 20
    assert result["flags"] == ["INTERVAL_BEFORE_PEAK","WIDTH_EXCEEDED"]
    assert primary_reason(False,result["flags"]) == "INTERVAL_BEFORE_PEAK"
    assert classify(forecast(101,105),100)["interval_relation"] == "AFTER"


def test_window_lead_failure_exposed_even_when_other_reasons_already_fail():
    result = classify(forecast(96,110,97),100)
    assert result["flags"] == ["INVALID_OR_NONFUTURE","WIDTH_EXCEEDED","EVENT_LEAD_INSUFFICIENT","WINDOW_LEAD_INSUFFICIENT"]
    assert result["event_lead"] == 3 and result["window_lead"] == -1
    good = classify(forecast(100,109,95),100)
    assert good["flags"] == [] and good["width"] == 10
    assert primary_reason(True,good["flags"]) == "SUCCESS"


def test_oracle_keeps_original_target_and_later_time_without_repairing_score():
    def claim(name,event,pos,raw=True):
        return {"prediction_id":name,"target_event_id":event,"published_session":pos,
                "scope":"stage","diagnostic_contract_hit":raw,"strict_hit":False}
    first = claim("a","event-A",10,False)
    records = [first,claim("past","event-A",9),claim("other-peak","event-B",15),
               claim("too-wide","event-A",16,False),claim("correct-revision","event-A",17)]
    later = later_qualified(records,event_id="event-A",first=first)
    assert [r["prediction_id"] for r in later] == ["correct-revision"]
    assert not first["strict_hit"] and all(not r["strict_hit"] for r in records)
    assert len(later_qualified(records,event_id="event-A",first=None)) == 2


def test_reconstructed_contract_keeps_target_and_all_gates_except_duplicate():
    claim={"scope":"stage","status":"event","pending":False,"boundary_excluded":False,
           "target_session":100,"target_event_id":"peak-100","action_session":95,"published_session":94,
           "failure_reasons":["duplicate_event_claim"],"strict_hit":False}
    assert contract_qualified(claim,forecast(100,109,95))
    assert not claim["strict_hit"]
    assert not contract_qualified({**claim,"failure_reasons":["duplicate_event_claim","late_publication"]},forecast(100,109,95))
    assert not contract_qualified({**claim,"pending":True},forecast(100,109,95))
    assert not contract_qualified(claim,forecast(100,110,95))


def test_independent_hand_cases_for_oracle_do_not_turn_revisions_into_tp():
    base={"scope":"stage","status":"event","pending":False,"boundary_excluded":False,
          "target_session":100,"target_event_id":"peak-100","action_session":95,"published_session":94,
          "failure_reasons":[],"strict_evidence_failures":["actionability_not_verified"],"strict_hit":False}
    # Expected values are hand-derived for peak=100, action=95, inclusive max=10.
    cases=[
        ("same episode revision",{"is_revision":True},100,109,True),
        ("new episode duplicate",{"duplicate_event":True,"failure_reasons":["duplicate_event_claim"]},100,109,True),
        ("late publication",{"strict_evidence_failures":["late_publication"]},100,109,False),
        ("eleven dates",{},100,110,False),
        ("unknown anchor",{"pending":True,"status":"pending_labels"},100,109,False),
        ("outside scored range",{"boundary_excluded":True},100,109,False),
        ("other layer",{"scope":"short"},100,109,False),
        ("window starts only four days ahead",{},99,105,False),
        ("window already started",{},94,100,False),
        ("wrong side of peak",{},101,109,False),
        ("outside H63",{},100,159,False),
        ("timestamp ledger mismatch",{"published_session":93},100,109,False),
    ]
    for name,change,left,right,expected in cases:
        claim={**base,**change}
        assert contract_qualified(claim,forecast(left,right,95)) is expected,name
        assert claim["strict_hit"] is False,name
    assert not contract_qualified({**base,"action_session":96,"published_session":95},forecast(100,105,96))
