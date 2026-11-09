"""Boundary tests for explicit provenance and immutable evaluator outputs."""
import json
from datetime import date, timedelta

import numpy as np
import pytest

from research.eval.top_time.cli import load_bundle, run_bundle
from research.eval.top_time.contracts import VERSION, Protocol


def _bundle():
    sessions = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(351)]
    return {
        "schema_version": VERSION, "symbol": "SYNTHETIC", "sessions": sessions,
        "prices": np.interp(range(351), [0, 100, 160, 220, 280, 350],
                             [120, 105, 90, 140, 110, 115]).round(2).tolist(),
        "price_basis": "synthetic units", "calendar_status": "SYNTHETIC",
        "price_basis_status": "SYNTHETIC", "publication_status": "SYNTHETIC",
        "input_status": "SYNTHETIC", "mode": "fixture", "protocol": {},
        "runs": [{"run_id": "r1", "symbol": "SYNTHETIC", "cutoff_session": 200,
                  "status": "ON_TIME_INTERVAL"}],
        "forecasts": [{"prediction_id": "p1", "episode_id": "e1", "symbol": "SYNTHETIC",
                       "scope": "stage", "interval_start": 215, "interval_end": 224,
                       "data_cutoff_session": 200, "published_session": 200,
                       "published_at": sessions[200] + "T16:00:00+08:00",
                       "action_session": 201, "actionability": "verified", "run_id": "r1"}],
    }


def _input(tmp_path, bundle):
    p = tmp_path / "input.json"
    p.write_text(json.dumps(bundle), encoding="utf-8")
    return p


def test_fixture_end_to_end_is_not_model_skill_and_cannot_overwrite(tmp_path):
    p = _input(tmp_path, _bundle())
    original = p.read_bytes()
    result = run_bundle(p, tmp_path / "output")
    assert result["metrics"]["stage"]["TP"] == 1
    assert result["evidence_status"] == "SYNTHETIC_IMPLEMENTATION_CHECK_NOT_MODEL_SKILL"
    assert p.read_bytes() == original
    with pytest.raises(FileExistsError):
        run_bundle(p, tmp_path / "output")


def test_unverified_calendar_cannot_silently_enter_strict_mode(tmp_path):
    bundle = _bundle()
    bundle.update(mode="strict", input_status="ARCHIVED")
    p = _input(tmp_path, bundle)
    with pytest.raises(ValueError, match="calendar_status"):
        run_bundle(p, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_strict_requires_data_availability_and_fixture_rejects_real_data(tmp_path):
    bundle = _bundle()
    bundle.update(mode="strict", input_status="ARCHIVED", calendar_status="VERIFIED",
                  price_basis_status="VERIFIED", publication_status="VERIFIED")
    with pytest.raises(ValueError, match="availability"):
        load_bundle(_input(tmp_path, bundle))
    bundle["mode"] = "fixture"
    with pytest.raises(ValueError, match="synthetic"):
        load_bundle(_input(tmp_path, bundle))


@pytest.mark.parametrize("change", [{"unexpected": 1}, {"sessions": []}, {"runs": None},
                                    {"input_status": None}, {"publication_status": ""}])
def test_malformed_ledger_rejected(tmp_path, change):
    bundle = _bundle()
    bundle.update(change)
    with pytest.raises(ValueError):
        load_bundle(_input(tmp_path, bundle))


def test_parameter_defaults_are_explicit_and_invalid_types_fail():
    config = Protocol()
    assert config.stage_right == 42
    assert config.minimum_lead == 5
    assert config.to_dict()["parameter_status"] == "RESEARCH_DEFAULT_NOT_FROZEN"
    for overrides in ({"stage_right": 5}, {"short_left": True},
                      {"require_entire_window_lead": "false"}, {"price_field": "auto"}):
        with pytest.raises(ValueError):
            Protocol(**overrides)


@pytest.mark.parametrize("status", ["UNVERIFIED", "FROZEN_QFQ_NOT_HISTORICAL_PIT", "ARCHIVED"])
def test_strict_rejects_conflicting_input_provenance(tmp_path, status):
    bundle = _bundle()
    bundle.update(mode="strict", input_status=status, calendar_status="VERIFIED",
                  price_basis_status="VERIFIED", publication_status="VERIFIED",
                  available_sessions=list(range(len(bundle["sessions"]))))
    with pytest.raises(ValueError, match="VERIFIED_LEDGER"):
        load_bundle(_input(tmp_path, bundle))
    bundle["input_status"] = "VERIFIED_LEDGER"
    # Declaration consistency only, not independent attestation of this test data.
    assert load_bundle(_input(tmp_path, bundle))["input_status"] == "VERIFIED_LEDGER"
